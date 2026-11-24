"""Streaming gateway for the synthetic campus-ticket comparison."""

import json
import math
from http.client import HTTPException
from threading import Lock
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from src.llm_client import MAX_RESPONSE_BYTES, ModelError, RejectRedirects, parse_json


def stream_events(response, deadline):
    received = 0
    lines = []
    while True:
        if monotonic() >= deadline:
            raise TimeoutError
        line = response.readline(MAX_RESPONSE_BYTES - received + 1)
        if monotonic() >= deadline:
            raise TimeoutError
        received += len(line)
        if received > MAX_RESPONSE_BYTES:
            raise ModelError("Streaming response exceeded the size limit.")
        if not line or not line.rstrip(b"\r\n"):
            if lines:
                yield b"\n".join(lines)
                lines.clear()
            if not line:
                break
        elif line.startswith(b"data:"):
            lines.append(line[5:].removeprefix(b" ").rstrip(b"\r\n"))


def token_usage(usage):
    counts = {
        key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        if type(usage.get(key)) is int and usage[key] >= 0
    }
    details = usage.get("completion_tokens_details")
    if isinstance(details, dict):
        reasoning = details.get("reasoning_tokens")
        if type(reasoning) is int and reasoning >= 0:
            counts["reasoning_tokens"] = reasoning
    return counts


def read_completion(response, deadline, call):
    content = []
    try:
        for data in stream_events(response, deadline):
            if data.strip() == b"[DONE]":
                break
            frame = parse_json(data)
            if not isinstance(frame, dict) or "error" in frame:
                raise ModelError("The gateway reported a streaming error.")
            if isinstance(frame.get("usage"), dict):
                call["usage"] = token_usage(frame["usage"])
            for choice in frame.get("choices", []):
                if choice.get("index", 0) != 0:
                    continue
                delta = choice.get("delta") or {}
                piece = delta.get("content")
                if isinstance(piece, str):
                    content.append(piece)
                finish = choice.get("finish_reason")
                if isinstance(finish, str):
                    call["finish_reason"] = finish if finish in (
                        "stop", "length", "content_filter", "tool_calls", "function_call",
                    ) else "unknown"
        else:
            raise ModelError("The stream ended before completion.")
    except (ValueError, AttributeError, TypeError, RecursionError):
        raise ModelError("The gateway returned an invalid streaming data frame.") from None

    finish = call.get("finish_reason")
    if finish != "stop":
        message = "The stream reached its output cap." if finish == "length" else "The stream did not finish normally."
        raise ModelError(message)
    usage = call["usage"]
    if not {"prompt_tokens", "completion_tokens", "total_tokens"} <= usage.keys():
        raise ModelError("The gateway did not report complete Token use.")
    if usage["completion_tokens"] > call["max_output_tokens_requested"] or usage.get("reasoning_tokens", 0) > 0:
        raise ModelError("The gateway did not respect the requested output budget.")

    text = "".join(content).strip()
    lines = text.splitlines()
    fence = chr(96) * 3
    if len(lines) > 1 and lines[0].strip().lower() in (fence, f"{fence}json") and lines[-1].strip() == fence:
        text = "\n".join(lines[1:-1])
    try:
        result = parse_json(text)
    except (ValueError, RecursionError):
        raise ModelError("The model message is not a JSON object.") from None
    if not isinstance(result, dict):
        raise ModelError("The model message is not a JSON object.")
    return result


class PersonalStreamClient:
    def __init__(self, config, *, max_requests, initial_cap=96, review_cap=160, opener_factory=None):
        if urlsplit(config.endpoint).scheme.lower() != "https":
            raise ValueError("Use an HTTPS endpoint for the personal gateway.")
        if type(max_requests) is not int or max_requests < 0:
            raise ValueError("The model request budget must be a nonnegative integer.")
        if any(type(cap) is not int or cap <= 0 for cap in (initial_cap, review_cap)):
            raise ValueError("Output caps must be positive integers.")
        self._config = config
        self._opener_factory = opener_factory or build_opener
        self._lock = Lock()
        self._output_caps = {"initial": initial_cap, "review": review_cap}
        self._max_requests = max_requests
        self.endpoint = config.endpoint
        self.model = config.model
        self.timeout = config.timeout
        self.use_json_schema = False
        self.calls = []

    @property
    def profile(self):
        return {
            "stream": True, "thinking_requested": False,
            "output_token_caps": self._output_caps.copy(), "max_requests": self._max_requests,
            "review_text_style": "short_phrases",
        }

    def complete(self, stage, instructions, data, schema, *, budget=None):
        if stage not in self._output_caps:
            raise ModelError("Unsupported civilian experiment stage.")
        if budget is not None and (not math.isfinite(budget) or budget <= 0):
            raise ModelError("Model-call time budget exhausted.")
        timeout = self.timeout if budget is None else min(self.timeout, budget)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ModelError("Model-call time budget exhausted.")
        limit = self._output_caps[stage]
        if stage == "review":
            instructions += " Keep each text field to one short phrase."
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": f"{instructions}\nReturn only JSON matching this schema: "
                    + json.dumps(schema, ensure_ascii=False),
                },
                {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
            ],
            "stream": True,
            "stream_options": {"include_usage": True},
            "enable_thinking": False,
            "max_tokens": limit,
        }
        request = Request(
            self.endpoint, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._config.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            method="POST",
        )
        call = {"stage": stage, "case_id": data["case"]["id"], "round": data.get("round", 0),
                "max_output_tokens_requested": limit, "usage": {}}
        with self._lock:
            if len(self.calls) >= self._max_requests:
                raise ModelError("Model request budget exhausted.")
            self.calls.append(call)
        deadline = monotonic() + timeout
        try:
            return self._request_stream(request, timeout, deadline, call)
        except ModelError as error:
            call["error"] = str(error)
            raise

    def _request_stream(self, request, timeout, deadline, call):
        try:
            with self._opener_factory(RejectRedirects()).open(request, timeout=timeout) as response:
                status = getattr(response, "status", None)
                if type(status) is int:
                    call["http_status"] = status
                content_type = response.headers.get("Content-Type", "").partition(";")[0].strip().lower()
                if content_type != "text/event-stream":
                    raise ModelError("The gateway did not return an event stream.")
                return read_completion(response, deadline, call)
        except HTTPError as error:
            call["http_status"] = error.code
            error.close()
            raise ModelError(f"Model gateway returned HTTP {error.code}.") from None
        except URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise ModelError("Model gateway request timed out.") from None
            raise ModelError("Could not complete the model gateway request.") from None
        except TimeoutError:
            raise ModelError("Model gateway request timed out.") from None
        except (OSError, HTTPException, ValueError):
            raise ModelError("Could not complete the model gateway request.") from None
