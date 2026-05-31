from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Any
from urllib import parse

from codex_switch.models import (
    ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI,
    ROUTE_PROXY_PROTOCOL_OPENAI_CHAT_TO_RESPONSES,
    ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT,
)
from codex_switch.proxy.translator import (
    anthropic_to_openai_request,
    iter_openai_chat_sse_to_responses,
    iter_openai_sse_to_anthropic,
    iter_responses_sse_to_openai_chat,
    openai_chat_to_responses_response,
    openai_chat_to_responses_request,
    openai_responses_to_chat_request,
    openai_to_anthropic_response,
    responses_to_openai_chat_response,
)


PayloadTranslator = Callable[[dict[str, Any], str], dict[str, Any]]
StreamTranslator = Callable[[Iterable[bytes], str], Iterator[bytes]]


@dataclass(frozen=True)
class ProtocolTranslation:
    protocol: str
    client_endpoint: str
    upstream_endpoint: str
    request: PayloadTranslator
    response: PayloadTranslator
    stream: StreamTranslator

    def matches(self, protocol: str, request_path: str) -> bool:
        return self.protocol == protocol and parse.urlparse(request_path).path == self.client_endpoint


PROTOCOL_TRANSLATIONS: tuple[ProtocolTranslation, ...] = (
    ProtocolTranslation(
        protocol=ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI,
        client_endpoint="/v1/messages",
        upstream_endpoint="/v1/chat/completions",
        request=anthropic_to_openai_request,
        response=openai_to_anthropic_response,
        stream=iter_openai_sse_to_anthropic,
    ),
    ProtocolTranslation(
        protocol=ROUTE_PROXY_PROTOCOL_OPENAI_CHAT_TO_RESPONSES,
        client_endpoint="/v1/chat/completions",
        upstream_endpoint="/v1/responses",
        request=openai_chat_to_responses_request,
        response=responses_to_openai_chat_response,
        stream=iter_responses_sse_to_openai_chat,
    ),
    ProtocolTranslation(
        protocol=ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT,
        client_endpoint="/v1/responses",
        upstream_endpoint="/v1/chat/completions",
        request=openai_responses_to_chat_request,
        response=openai_chat_to_responses_response,
        stream=iter_openai_chat_sse_to_responses,
    ),
)


def translation_for_protocol(protocol: str, request_path: str) -> ProtocolTranslation | None:
    for translation in PROTOCOL_TRANSLATIONS:
        if translation.matches(protocol, request_path):
            return translation
    return None
