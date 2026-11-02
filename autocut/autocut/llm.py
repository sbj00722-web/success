"""Claude API 호출 공통부."""
import json

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

    if msg.stop_reason == "refusal":
        raise LLMError("Claude 가 요청을 거절했습니다")
    if msg.stop_reason == "max_tokens":
        raise LLMError("응답이 max_tokens 에서 잘렸습니다")
    return "".join(b.text for b in msg.content if b.type == "text")


def ask_json(model: str, system: str, content, schema: dict, effort: str = "high", **kw):
    return json.loads(ask(model, system, content, effort=effort, schema=schema, **kw))
