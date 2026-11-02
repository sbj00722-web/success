"""Claude 가 그린 SVG 로 '플랫 벡터 + 핸드드로잉 카툰' 설명 그림 만들기."""
import base64
import re

from . import llm

STYLE = """You are an illustrator for Korean YouTube explainer videos. You draw in SVG.

Style (always):
- Flat vector illustration mixed with a hand-drawn cartoon look.
- Warm cream paper background is added for you; do NOT draw a full-canvas background rectangle.
- Limited palette of 4-6 flat colors, e.g. coral #FF7A6B, sunny yellow #FFC94D, mint #5CC9A7, sky blue #6BB6FF, lavender #B39DDB, with charcoal #2B2B2B outlines.
- Thick charcoal outlines (stroke-width 6-9), stroke-linecap and stroke-linejoin "round".
- Shapes are slightly imperfect and organic, like drawn with a marker: prefer paths with gentle curves over perfect rectangles/circles.
- Simple cute characters (round heads, dot eyes) and objects; chunky hand-drawn arrows; a few small doodle accents (sparkles, motion lines).
- No gradients, no photorealism, no drop shadows except a flat offset shadow shape if useful.
- Bold and readable from far away: few large elements, generous empty space, main subject fills about 70% of the canvas.

Text:
- Minimal. Only the given label (if any), once, large (font-size 90-130 for 1920 width), font-family "{font}", font-weight bold, fill #2B2B2B.
- No other words, numbers only if essential to the idea.

Technical:
- Return ONE complete <svg> element with xmlns="http://www.w3.org/2000/svg" and viewBox="0 0 {w} {h}".
- Plain SVG only: no <image>, <foreignObject>, <script>, external references, CSS @import, or filters (a sketch filter is applied afterwards).
- Keep everything inside the viewBox with at least 80px margin."""

REVIEW = """You review an SVG illustration rendered to PNG (attached) for a YouTube explainer.
Check: text cut off or overlapping, elements outside the canvas, clutter, more text than the label,
unreadable/tiny elements, broken shapes, scene not matching the intent.
If it is good, set ok=true and svg="". Otherwise set ok=false and return the complete corrected <svg> in svg,
keeping the same style rules:
""" + STYLE

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "problems": {"type": "string"}, "svg": {"type": "string"}},
    "required": ["ok", "problems", "svg"],
    "additionalProperties": False,
}

# 마커로 그린 듯한 떨림 + 종이 질감. Claude 가 그린 내용 전체에 씌움.
_WRAP = """<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
<defs>
  <filter id="hand" x="-5%" y="-5%" width="110%" height="110%">
    <feTurbulence type="fractalNoise" baseFrequency="0.018" numOctaves="2" seed="7" result="n"/>
    <feDisplacementMap in="SourceGraphic" in2="n" scale="5" xChannelSelector="R" yChannelSelector="G"/>
  </filter>
  <filter id="paper">
    <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="2" result="g"/>
    <feColorMatrix in="g" type="matrix" values="0 0 0 0 0.45  0 0 0 0 0.38  0 0 0 0 0.28  0 0 0 0.06 0"/>
  </filter>
</defs>
<rect width="{w}" height="{h}" fill="#FFF7E8"/>
<rect width="{w}" height="{h}" filter="url(#paper)"/>
<g filter="url(#hand)">
<svg viewBox="{vb}" width="{w}" height="{h}" preserveAspectRatio="xMidYMid meet">
{inner}
</svg>
</g>
</svg>"""


def _extract_svg(text: str) -> str:
    m = re.search(r"<svg[\s\S]*</svg>", text)
    if not m:
        raise llm.LLMError("SVG 를 찾을 수 없습니다")
    return m.group(0)


def _wrap(svg: str, w: int, h: int) -> str:
    vb = re.search(r'viewBox="([^"]+)"', svg)
    open_end = svg.index(">") + 1
    inner = svg[open_end: svg.rindex("</svg>")]
    return _WRAP.format(w=w, h=h, vb=vb.group(1) if vb else f"0 0 {w} {h}", inner=inner)


def render_png(svg: str, out_path: str, font_dirs=None):
    import resvg_py
    # 시스템 글꼴(맑은 고딕 등)은 기본으로 불러옴
    data = resvg_py.svg_to_bytes(svg_string=svg, font_dirs=font_dirs)
    if isinstance(data, str):  # 구버전 resvg_py 는 base64 문자열을 돌려줌
        data = base64.b64decode(data)
    elif isinstance(data, list):
        data = bytes(data)
    with open(out_path, "wb") as f:
        f.write(data)


def make(item: dict, w: int, h: int, out_png: str, settings, log) -> str:
    """item: planner 의 illustrations 항목. 최종 SVG 문자열을 돌려줌."""
    system = STYLE.replace("{font}", settings.font_family).replace("{w}", str(w)).replace("{h}", str(h))
    prompt = (f"Canvas: {w}x{h}.\nConcept being explained (Korean): {item['concept']}\n"
              f"Scene: {item['scene']}\n"
              f"Label text: {item['label'] or '(none - no text at all)'}")
    svg = _extract_svg(llm.ask(settings.model, system, prompt, effort=settings.effort))

    for attempt in range(2):
        final = _wrap(svg, w, h)
        try:
            render_png(final, out_png)
        except Exception as e:
            if attempt:
                raise
            log(f"    SVG 렌더링 오류, 다시 그립니다: {e}")
            svg = _extract_svg(llm.ask(settings.model, system,
                                       prompt + f"\n\nYour previous SVG failed to render: {e}\nReturn a simpler valid SVG.",
                                       effort=settings.effort))
            continue
        break

    if settings.illustration_review:
        with open(out_png, "rb") as f:
            png_b64 = base64.standard_b64encode(f.read()).decode()
        review_sys = REVIEW.replace("{font}", settings.font_family).replace("{w}", str(w)).replace("{h}", str(h))
        res = llm.ask_json(settings.model, review_sys, [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": png_b64}},
            {"type": "text", "text": f"Intent:\n{prompt}\n\nSVG:\n{svg}"},
        ], REVIEW_SCHEMA, effort=settings.effort)
        if not res["ok"] and "<svg" in res["svg"]:
            log(f"    검토 후 수정: {res['problems']}")
            try:
                final = _wrap(_extract_svg(res["svg"]), w, h)
                render_png(final, out_png)
            except Exception as e:  # 수정본이 깨지면 원래 그림 유지
                log(f"    수정본 렌더링 실패, 원래 그림을 씁니다: {e}")
                final = _wrap(svg, w, h)
                render_png(final, out_png)
    return final
