"""Explicit remote provider: JSON object on wire, strict Pydantic locally.

No provider retries, local tokenizer assumptions, raw error bodies or tool calls.
The shared LocalStructuredModel builds the same prompts and evidence payloads.
"""
import json
import os

import httpx
from langchain_openai import ChatOpenAI
from openai import APIConnectionError, APIStatusError, APITimeoutError, LengthFinishReasonError
from pydantic import ValidationError

from .local_llm import LocalStructuredModel, ProviderFailure


class DeepSeekStructuredModel(LocalStructuredModel):
    def __init__(self, settings, *, http_client=None):
        settings.validate()
        if settings.model_backend != "deepseek":
            raise ValueError("DEEPSEEK_BACKEND_REQUIRED")
        if any(os.getenv(k, "").lower() in {"true", "1"}
               for k in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2")):
            raise ValueError("REMOTE_TRACING_MUST_BE_DISABLED")
        self.settings = settings
        self.identity = {"provider": "deepseek", "model": settings.model_name,
                         "base_url": settings.model_base_url.rstrip("/"),
                         "identity_kind": "provider_alias_not_pinned_weights"}
        self.client = ChatOpenAI(model=settings.model_name, api_key=settings.model_api_key,
            base_url=settings.model_base_url, max_retries=0, timeout=20, temperature=0,
            http_client=http_client or httpx.Client(trust_env=False, follow_redirects=False))

    def preflight(self, timeout):
        # No /api/tags, model download or extra billable identity request.
        pass

    def input_size(self, system, content):
        # A deliberately conservative application byte bound, NOT a DeepSeek tokenizer.
        # The common guard adds 128 more for framing and reserves the output budget.
        return len((system + content).encode("utf-8"))

    def request(self, schema, provider_schema, messages, timeout):
        usage = {"provider": "deepseek", "requested_model": self.settings.model_name,
                 "response_model": None, "finish_reason": None}
        try:
            raw = self.client.bind(response_format={"type": "json_object"}, timeout=timeout,
                extra_body={"max_tokens": self.settings.model_output_tokens,
                            "thinking": {"type": "disabled"}}).invoke(messages)
        except LengthFinishReasonError as exc:
            # SDK parse() raises before ChatOpenAI returns an AIMessage.
            completion = exc.completion
            tokens = completion.usage
            if tokens:
                usage.update(input_tokens=tokens.prompt_tokens, output_tokens=tokens.completion_tokens,
                             total_tokens=tokens.total_tokens)
            usage["finish_reason"] = "length"
            if completion.model.startswith("deepseek-"):
                usage["response_model"] = completion.model[:120]
            raise ProviderFailure("MODEL_OUTPUT_TRUNCATED", usage) from None
        except APITimeoutError:
            raise ProviderFailure("MODEL_TIMEOUT", usage) from None
        except APIConnectionError:
            raise ProviderFailure("MODEL_CONNECTION_ERROR", usage) from None
        except APIStatusError as exc:
            code = {401: "MODEL_AUTHENTICATION_FAILED", 403: "MODEL_PERMISSION_DENIED",
                    429: "MODEL_RATE_LIMITED"}.get(exc.status_code,
                        "MODEL_SERVER_ERROR" if exc.status_code >= 500 else "MODEL_HTTP_ERROR")
            raise ProviderFailure(code, usage) from None
        except Exception:  # noqa: BLE001 -- sanitize malformed SDK responses at provider boundary
            # SDK/parser exceptions may contain response text; never propagate them.
            raise ProviderFailure("MODEL_RESPONSE_INVALID", usage) from None
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            value = (raw.usage_metadata or {}).get(key)
            if isinstance(value, int) and value >= 0:
                usage[key] = value
        # The provider's response model is useful evidence, not a pinned weight identity.
        response_model = raw.response_metadata.get("model_name")
        if isinstance(response_model, str) and response_model.startswith("deepseek-"):
            usage["response_model"] = response_model[:120]
        reason = raw.response_metadata.get("finish_reason")
        usage["finish_reason"] = reason if reason in {"stop", "length", "content_filter", "tool_calls"} else "unknown"
        if reason == "length":
            raise ProviderFailure("MODEL_OUTPUT_TRUNCATED", usage)
        if reason != "stop" or raw.tool_calls or raw.invalid_tool_calls:
            raise ProviderFailure("MODEL_RESPONSE_INVALID", usage)
        if not isinstance(raw.content, str) or not raw.content.strip():
            raise ProviderFailure("MODEL_EMPTY_RESPONSE", usage)
        try:
            value = json.loads(raw.content)
            parsed = schema.model_validate(value, strict=True).model_dump()
        except (ValueError, TypeError, ValidationError):
            raise ProviderFailure("MODEL_JSON_SCHEMA_INVALID", usage) from None
        # Pass only whitelisted metadata back to the common accounting path.
        raw.response_metadata["model_name"] = usage["response_model"]
        return raw, parsed
