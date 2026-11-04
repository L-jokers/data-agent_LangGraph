import json
import re
from typing import Any


class LLMOutputParseError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def response_to_payload(response: Any) -> dict:
    if isinstance(response, dict) and "status" in response:
        return response
    if isinstance(response, dict) and "parsed" in response:
        if response.get("parsing_error") is not None:
            raise LLMOutputParseError("STRUCTURED_OUTPUT_PARSE_FAILED")
        content = response["parsed"]
        if hasattr(content, "model_dump"):
            content = content.model_dump()
        if isinstance(content, dict):
            return content
        raise LLMOutputParseError("INVALID_STRUCTURED_OUTPUT_TYPE")
    content = getattr(response, "content", response)
    if hasattr(content, "model_dump"):
        content = content.model_dump()
        if isinstance(content, dict):
            return content
        raise LLMOutputParseError("INVALID_STRUCTURED_OUTPUT_TYPE")
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            else:
                raise LLMOutputParseError("INVALID_CONTENT_BLOCK")
        content = "".join(parts)
    if not isinstance(content, str):
        raise LLMOutputParseError("INVALID_CONTENT_TYPE")
    content = content.strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", content, re.IGNORECASE | re.DOTALL)
    if fence:
        content = fence.group(1)
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMOutputParseError("INVALID_JSON") from exc
    if not isinstance(payload, dict):
        raise LLMOutputParseError("INVALID_ROOT_TYPE")
    return payload
