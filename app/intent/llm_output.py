import json
from typing import Any


def response_to_payload(response: Any) -> dict:
    content = getattr(response, "content", response)
    if isinstance(content, list):
        content = "".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in content
        )
    if not isinstance(content, str):
        raise TypeError("LLM结构化意图输出必须是JSON文本")
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:].lstrip()
    return json.loads(content)
