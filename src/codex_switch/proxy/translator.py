from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any
import json
import time
import uuid


class TranslationError(ValueError):
    pass


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        raise TranslationError("Unsupported content payload.")
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            raise TranslationError("Unsupported content block.")
        block_type = block.get("type")
        if block_type == "text":
            parts.append(str(block.get("text") or ""))
        else:
            raise TranslationError(f"Unsupported content block for conversion: {block_type}")
    return "\n".join(part for part in parts if part)


def _tool_result_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            elif isinstance(block, str):
                parts.append(block)
            else:
                parts.append(json.dumps(block, ensure_ascii=False))
        return "\n".join(parts)
    return json.dumps(content, ensure_ascii=False)


def _anthropic_tool_choice_to_openai(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    choice_type = value.get("type")
    if choice_type == "auto":
        return "auto"
    if choice_type == "any":
        return "required"
    if choice_type == "tool":
        name = value.get("name")
        if name:
            return {"type": "function", "function": {"name": name}}
    return "auto"


def _openai_arguments_to_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _chat_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                block_type = block.get("type")
                if block_type in {"text", "input_text", "output_text"}:
                    parts.append(str(block.get("text") or ""))
                else:
                    parts.append(json.dumps(block, ensure_ascii=False))
            else:
                parts.append(str(block))
        return "\n".join(part for part in parts if part)
    if content is None:
        return ""
    return str(content)


def anthropic_to_openai_request(payload: dict[str, Any], upstream_model: str) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    system = payload.get("system")
    if system:
        if isinstance(system, list):
            system_text = _content_to_text(system)
        else:
            system_text = str(system)
        if system_text:
            messages.append({"role": "system", "content": system_text})

    for message in payload.get("messages", []):
        if not isinstance(message, dict):
            raise TranslationError("Anthropic message must be an object.")
        role = str(message.get("role") or "")
        content = message.get("content", "")
        if isinstance(content, str):
            messages.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            raise TranslationError("Unsupported Anthropic message content.")

        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        tool_messages: list[dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict):
                raise TranslationError("Anthropic content block must be an object.")
            block_type = block.get("type")
            if block_type == "text":
                text_parts.append(str(block.get("text") or ""))
            elif block_type == "tool_use" and role == "assistant":
                tool_calls.append(
                    {
                        "id": str(block.get("id") or f"call_{uuid.uuid4().hex[:12]}"),
                        "type": "function",
                        "function": {
                            "name": str(block.get("name") or ""),
                            "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                        },
                    }
                )
            elif block_type == "tool_result" and role == "user":
                tool_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(block.get("tool_use_id") or ""),
                        "content": _tool_result_to_text(block.get("content", "")),
                    }
                )
            else:
                raise TranslationError(f"Unsupported content block for conversion: {block_type}")

        if role == "assistant" and tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": "\n".join(part for part in text_parts if part) or None,
                    "tool_calls": tool_calls,
                }
            )
        elif text_parts:
            messages.append({"role": role, "content": "\n".join(part for part in text_parts if part)})
        messages.extend(tool_messages)

    rendered: dict[str, Any] = {
        "model": upstream_model or str(payload.get("model") or ""),
        "messages": messages,
    }
    for source, target in (
        ("temperature", "temperature"),
        ("top_p", "top_p"),
        ("max_tokens", "max_tokens"),
        ("stream", "stream"),
    ):
        if source in payload:
            rendered[target] = payload[source]
    if "stop_sequences" in payload:
        rendered["stop"] = payload["stop_sequences"]

    tools = payload.get("tools")
    if isinstance(tools, list) and tools:
        rendered["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": str(tool.get("name") or ""),
                    "description": str(tool.get("description") or ""),
                    "parameters": tool.get("input_schema") or {},
                },
            }
            for tool in tools
            if isinstance(tool, dict)
        ]
    if "tool_choice" in payload:
        rendered["tool_choice"] = _anthropic_tool_choice_to_openai(payload["tool_choice"])
    return rendered


def openai_chat_to_responses_request(payload: dict[str, Any], upstream_model: str) -> dict[str, Any]:
    instructions: list[str] = []
    input_items: list[dict[str, Any]] = []
    for message in payload.get("messages") or []:
        if not isinstance(message, dict):
            raise TranslationError("OpenAI chat message must be an object.")
        role = str(message.get("role") or "user")
        content_text = _chat_content_to_text(message.get("content", ""))
        if role in {"system", "developer"}:
            if content_text:
                instructions.append(content_text)
            continue
        if role == "tool":
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": str(message.get("tool_call_id") or ""),
                    "output": content_text,
                }
            )
            continue
        input_items.append({"role": role, "content": content_text})
        for tool_call in message.get("tool_calls") or []:
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function") or {}
            input_items.append(
                {
                    "type": "function_call",
                    "call_id": str(tool_call.get("id") or f"call_{uuid.uuid4().hex[:12]}"),
                    "name": str(function.get("name") or ""),
                    "arguments": str(function.get("arguments") or "{}"),
                }
            )

    rendered: dict[str, Any] = {
        "model": upstream_model or str(payload.get("model") or ""),
        "input": input_items or "",
    }
    if instructions:
        rendered["instructions"] = "\n".join(instructions)
    for source, target in (
        ("temperature", "temperature"),
        ("top_p", "top_p"),
        ("stream", "stream"),
    ):
        if source in payload:
            rendered[target] = payload[source]
    if "max_tokens" in payload:
        rendered["max_output_tokens"] = payload["max_tokens"]
    if "stop" in payload:
        rendered["stop"] = payload["stop"]

    tools = payload.get("tools")
    if isinstance(tools, list) and tools:
        rendered["tools"] = [
            {
                "type": "function",
                "name": str((tool.get("function") or {}).get("name") or ""),
                "description": str((tool.get("function") or {}).get("description") or ""),
                "parameters": (tool.get("function") or {}).get("parameters") or {},
            }
            for tool in tools
            if isinstance(tool, dict) and tool.get("type") == "function"
        ]
    if "tool_choice" in payload:
        rendered["tool_choice"] = payload["tool_choice"]
    return rendered


def openai_to_anthropic_response(payload: dict[str, Any], model: str) -> dict[str, Any]:
    choice = (payload.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content: list[dict[str, Any]] = []
    text = message.get("content")
    if text:
        content.append({"type": "text", "text": str(text)})
    for tool_call in message.get("tool_calls") or []:
        function = tool_call.get("function") or {}
        content.append(
            {
                "type": "tool_use",
                "id": str(tool_call.get("id") or f"call_{uuid.uuid4().hex[:12]}"),
                "name": str(function.get("name") or ""),
                "input": _openai_arguments_to_dict(function.get("arguments")),
            }
        )
    finish_reason = choice.get("finish_reason")
    stop_reason = {
        "stop": "end_turn",
        "length": "max_tokens",
        "tool_calls": "tool_use",
    }.get(str(finish_reason or ""), "end_turn")
    usage = payload.get("usage") or {}
    return {
        "id": str(payload.get("id") or f"msg_{uuid.uuid4().hex[:24]}"),
        "type": "message",
        "role": "assistant",
        "model": model or str(payload.get("model") or ""),
        "content": content or [{"type": "text", "text": ""}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": int(usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("completion_tokens") or 0),
        },
    }


def responses_to_openai_chat_response(payload: dict[str, Any], model: str) -> dict[str, Any]:
    text = str(payload.get("output_text") or "")
    collect_output_text = not text
    tool_calls: list[dict[str, Any]] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "message":
            for block in item.get("content") or []:
                if collect_output_text and isinstance(block, dict) and block.get("type") in {"output_text", "text"}:
                    text += str(block.get("text") or "")
        elif item_type == "function_call":
            tool_calls.append(
                {
                    "id": str(item.get("call_id") or item.get("id") or f"call_{uuid.uuid4().hex[:12]}"),
                    "type": "function",
                    "function": {
                        "name": str(item.get("name") or ""),
                        "arguments": str(item.get("arguments") or "{}"),
                    },
                }
            )
    message: dict[str, Any] = {"role": "assistant", "content": text or None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    usage = payload.get("usage") or {}
    prompt_tokens = int(usage.get("input_tokens") or 0)
    completion_tokens = int(usage.get("output_tokens") or 0)
    return {
        "id": str(payload.get("id") or f"chatcmpl_{uuid.uuid4().hex[:24]}"),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model or str(payload.get("model") or ""),
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": int(usage.get("total_tokens") or prompt_tokens + completion_tokens),
        },
    }


def iter_openai_sse_to_anthropic(lines: Iterable[bytes], model: str) -> Iterator[bytes]:
    message_id = f"msg_{uuid.uuid4().hex[:24]}"
    yielded_message = False
    text_block_started = False
    tool_blocks: dict[int, dict[str, Any]] = {}
    output_tokens = 0

    def event(name: str, data: dict[str, Any]) -> bytes:
        return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")

    for raw_line in lines:
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        if line.startswith("data:"):
            line = line[5:].strip()
        if line == "[DONE]":
            break
        try:
            chunk = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not yielded_message:
            yielded_message = True
            yield event(
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": message_id,
                        "type": "message",
                        "role": "assistant",
                        "model": model,
                        "content": [],
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": {"input_tokens": 0, "output_tokens": 0},
                    },
                },
            )

        choice = (chunk.get("choices") or [{}])[0]
        delta = choice.get("delta") or {}
        if delta.get("content"):
            if not text_block_started:
                text_block_started = True
                yield event("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
            text = str(delta.get("content") or "")
            output_tokens += 1
            yield event("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}})

        for tool_call in delta.get("tool_calls") or []:
            index = int(tool_call.get("index") or 0) + 1
            state = tool_blocks.setdefault(index, {"id": "", "name": "", "arguments": ""})
            if tool_call.get("id"):
                state["id"] = str(tool_call.get("id"))
            function = tool_call.get("function") or {}
            if function.get("name"):
                state["name"] = str(function.get("name"))
            if "started" not in state and state["id"] and state["name"]:
                state["started"] = True
                yield event(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": index,
                        "content_block": {"type": "tool_use", "id": state["id"], "name": state["name"], "input": {}},
                    },
                )
            if function.get("arguments"):
                state["arguments"] += str(function.get("arguments"))
                yield event(
                    "content_block_delta",
                    {"type": "content_block_delta", "index": index, "delta": {"type": "input_json_delta", "partial_json": str(function.get("arguments"))}},
                )

    if not yielded_message:
        yield event(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": message_id,
                    "type": "message",
                    "role": "assistant",
                    "model": model,
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            },
        )
    if text_block_started:
        yield event("content_block_stop", {"type": "content_block_stop", "index": 0})
    for index, state in sorted(tool_blocks.items()):
        if state.get("started"):
            yield event("content_block_stop", {"type": "content_block_stop", "index": index})
    stop_reason = "tool_use" if tool_blocks else "end_turn"
    yield event("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop_reason, "stop_sequence": None}, "usage": {"output_tokens": output_tokens}})
    yield event("message_stop", {"type": "message_stop"})


def iter_responses_sse_to_openai_chat(lines: Iterable[bytes], model: str) -> Iterator[bytes]:
    chunk_id = f"chatcmpl_{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    def chunk(delta: dict[str, Any], finish_reason: str | None = None) -> bytes:
        payload = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")

    yield chunk({"role": "assistant"})
    for raw_line in lines:
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line or not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            continue
        event_type = str(event.get("type") or "")
        if event_type == "response.output_text.delta" and event.get("delta"):
            yield chunk({"content": str(event.get("delta") or "")})
        elif event_type == "response.function_call_arguments.delta":
            yield chunk(
                {
                    "tool_calls": [
                        {
                            "index": int(event.get("output_index") or 0),
                            "function": {"arguments": str(event.get("delta") or "")},
                        }
                    ]
                }
            )
    yield chunk({}, "stop")
    yield b"data: [DONE]\n\n"
