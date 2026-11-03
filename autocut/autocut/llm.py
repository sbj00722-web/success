"""Claude API 호출 공통부."""
import json
import os

import anthropic

_client = None


class LLMError(RuntimeError):
    pass


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 또는 `ant auth login` 프로필 사용
    return _client


def ask(model: str, system: str, content, effort: str = "high", schema: dict = None,
        max_tokens: int = 32000) -> str:
    """응답 텍스트를 돌려줌. schema 를 주면 JSON 형식이 보장됨."""
    output_config = {"effort": effort}
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    # 긴 대본/SVG 를 다루므로 스트리밍으로 받음 (HTTP 타임아웃 방지).
    # 안전 분류기가 거절하면 서버가 다른 모델로 자동 재시도하도록 fallbacks 사용.
    try:
        with client().beta.messages.stream(
            model=model,
            max_tokens=max_tokens,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=system,
            output_config=output_config,
            messages=[{"role": "user", "content": content}],
        ) as stream:
            msg = stream.get_final_message()
    except anthropic.APIStatusError as e:
        if "credit balance" in str(e):
            raise LLMError("Claude 크레딧이 부족해요 (console.anthropic.com → Plans & Billing 에서 충전)") from e
        if e.status_code == 401:
            raise LLMError("Claude API 키가 맞지 않아요 (.env 의 ANTHROPIC_API_KEY 확인)") from e
        raise LLMError(f"Claude API 오류 {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise LLMError("Claude 서버에 연결하지 못했어요 (인터넷 연결 확인)") from e

    if msg.stop_reason == "refusal":
        raise LLMError("Claude 가 요청을 거절했습니다")
    if msg.stop_reason == "max_tokens":
        raise LLMError("응답이 max_tokens 에서 잘렸습니다")
    return "".join(b.text for b in msg.content if b.type == "text")


def ask_json(model: str, system: str, content, schema: dict, effort: str = "high", **kw):
    return json.loads(ask(model, system, content, effort=effort, schema=schema, **kw))


def ask_json_any(settings, system: str, text: str, schema: dict):
    """Claude 로 먼저, 안 되면(키·크레딧 없음) OpenAI 로. (결과, 사용한 곳) 을 돌려줌."""
    problems = []
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return ask_json(settings.claude_model, system, text, schema, effort=settings.claude_effort), "Claude"
        except LLMError as e:
            problems.append(str(e))
    if os.environ.get("OPENAI_API_KEY"):
        import openai
        try:
            r = openai.OpenAI().chat.completions.create(
                model=settings.openai_text_model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": text}],
                response_format={"type": "json_schema",
                                 "json_schema": {"name": "result", "strict": True, "schema": schema}},
            )
            return json.loads(r.choices[0].message.content), "OpenAI"
        except openai.APIStatusError as e:
            msg = str(e).lower()
            if e.status_code == 429 and ("credit" in msg or "quota" in msg):
                problems.append("OpenAI 크레딧이 부족해요 (platform.openai.com → Billing 에서 충전)")
            elif e.status_code == 401:
                problems.append("OpenAI API 키가 맞지 않아요 (.env 의 OPENAI_API_KEY 확인)")
            else:
                problems.append(f"OpenAI API 오류 {e.status_code}")
        except openai.APIConnectionError:
            problems.append("OpenAI 서버에 연결하지 못했어요 (인터넷 연결 확인)")
    raise LLMError(" / ".join(problems) or "API 키가 없어요")
