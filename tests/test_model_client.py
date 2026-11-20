"""M4: the real ModelClient (OpenRouter through the openai SDK), against a mocked SDK.

The SDK class ``backend.model_client.AsyncOpenAI`` is replaced with a recording
fake, so nothing here touches the network.
"""

import asyncio
import json
from types import SimpleNamespace

import httpx
import openai
import pytest
from fastapi.testclient import TestClient

from backend import model_client
from backend.faq import FAQ_PATH
from backend.main import app
from backend.model_client import (
    ModelResult,
    OpenRouterClient,
    UpstreamError,
    get_model_client,
)
from backend.prompts import load_prompt

OUTCOMES = {"answered", "partial", "unanswered", "smalltalk"}
REQUEST = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")


def http_response(status: int) -> httpx.Response:
    return httpx.Response(status, request=REQUEST)


# --- fake SDK ---


@pytest.fixture
def sdk(monkeypatch):
    """Replace AsyncOpenAI. ``sdk.script`` is a list of responses or exceptions,
    consumed in order, one per ``chat.completions.create`` call."""
    state = SimpleNamespace(script=[], calls=[], init_kwargs=[], init_args=[])

    async def create(**kwargs):
        state.calls.append(kwargs)
        assert state.script, "SDK called more times than the test scripted"
        item = state.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    class FakeAsyncOpenAI:
        def __init__(self, *args, **kwargs):
            state.init_args.append(args)
            state.init_kwargs.append(kwargs)
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    monkeypatch.setattr(model_client, "AsyncOpenAI", FakeAsyncOpenAI)
    return state


def reply_json(outcome="answered", answer="An answer.", citations=(1, 4)) -> str:
    return json.dumps(
        {"outcome": outcome, "answer": answer, "citations": list(citations)}
    )


def sdk_response(
    content,
    model="served/model-x",
    prompt_tokens=11,
    completion_tokens=7,
    include_model=True,
):
    fields = {
        "choices": [SimpleNamespace(message=SimpleNamespace(content=content))],
        "usage": SimpleNamespace(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        ),
    }
    if include_model:
        fields["model"] = model
    return SimpleNamespace(**fields)


def make_client(model="configured/model") -> OpenRouterClient:
    return OpenRouterClient(api_key="k-123", model=model)


def run_complete(client, system_prompt="SYS", history=None, message="Hi?"):
    return asyncio.run(
        client.complete(system_prompt, [] if history is None else history, message)
    )


# --- how the SDK is constructed ---


def test_sdk_is_built_with_the_openrouter_base_url(sdk):
    make_client()

    assert len(sdk.init_kwargs) == 1
    assert sdk.init_kwargs[0]["base_url"] == "https://openrouter.ai/api/v1"


def test_sdk_is_built_with_the_api_key(sdk):
    OpenRouterClient(api_key="the-secret-key", model="m")

    assert sdk.init_kwargs[0]["api_key"] == "the-secret-key"


def test_sdk_own_retries_are_disabled(sdk):
    make_client()

    assert sdk.init_kwargs[0]["max_retries"] == 0


# --- the request ---


def test_request_uses_the_configured_model(sdk):
    sdk.script = [sdk_response(reply_json())]

    run_complete(make_client(model="vendor/some-model"))

    assert sdk.calls[0]["model"] == "vendor/some-model"


def test_request_is_not_streamed(sdk):
    sdk.script = [sdk_response(reply_json())]

    run_complete(make_client())

    assert not sdk.calls[0].get("stream")


def test_request_asks_for_strict_json_schema_output(sdk):
    sdk.script = [sdk_response(reply_json())]

    run_complete(make_client())

    response_format = sdk.calls[0]["response_format"]
    assert response_format["type"] == "json_schema"
    json_schema = response_format["json_schema"]
    assert json_schema["strict"] is True
    assert isinstance(json_schema["name"], str) and json_schema["name"]


def test_json_schema_describes_the_model_reply_schema(sdk):
    sdk.script = [sdk_response(reply_json())]

    run_complete(make_client())

    schema = sdk.calls[0]["response_format"]["json_schema"]["schema"]
    assert schema["type"] == "object"
    assert set(schema["properties"]) == {"outcome", "answer", "citations"}
    assert set(schema["required"]) == {"outcome", "answer", "citations"}
    assert schema.get("additionalProperties") is False
    assert set(schema["properties"]["outcome"]["enum"]) == OUTCOMES
    assert schema["properties"]["answer"]["type"] == "string"
    citations = schema["properties"]["citations"]
    assert citations["type"] == "array"
    assert citations["items"]["type"] == "integer"


def test_request_requires_provider_parameter_support(sdk):
    sdk.script = [sdk_response(reply_json())]

    run_complete(make_client())

    assert sdk.calls[0]["extra_body"] == {"provider": {"require_parameters": True}}


def test_messages_are_system_then_history_in_order_then_the_new_message(sdk):
    sdk.script = [sdk_response(reply_json())]
    history = [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "second question"},
    ]

    run_complete(
        make_client(), system_prompt="THE SYSTEM", history=history, message="new one"
    )

    assert sdk.calls[0]["messages"] == [
        {"role": "system", "content": "THE SYSTEM"},
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "second question"},
        {"role": "user", "content": "new one"},
    ]


def test_messages_with_no_history_are_system_then_message(sdk):
    sdk.script = [sdk_response(reply_json())]

    run_complete(make_client(), system_prompt="SYS", history=[], message="hello")

    assert sdk.calls[0]["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "hello"},
    ]


def test_the_real_system_prompt_with_the_faq_is_sent_as_the_system_message(sdk):
    sdk.script = [sdk_response(reply_json())]
    system_prompt = load_prompt()

    run_complete(make_client(), system_prompt=system_prompt)

    system_message = sdk.calls[0]["messages"][0]
    assert system_message["role"] == "system"
    assert system_message["content"] == system_prompt
    assert FAQ_PATH.read_text(encoding="utf-8").strip() in system_message["content"]


# --- the returned ModelResult ---


def test_valid_output_becomes_a_model_result(sdk):
    sdk.script = [
        sdk_response(
            reply_json("partial", "Half of it.", [5, 23]),
            model="served/actual-model",
            prompt_tokens=123,
            completion_tokens=45,
        )
    ]

    result = run_complete(make_client())

    assert isinstance(result, ModelResult)
    assert result.outcome == "partial"
    assert result.answer == "Half of it."
    assert list(result.citations) == [5, 23]
    assert result.served_model == "served/actual-model"
    assert result.tokens_in == 123
    assert result.tokens_out == 45


@pytest.mark.parametrize("outcome", sorted(OUTCOMES))
def test_every_outcome_is_accepted(sdk, outcome):
    sdk.script = [sdk_response(reply_json(outcome, "x", []))]

    result = run_complete(make_client())

    assert result.outcome == outcome


def test_served_model_is_unknown_when_the_response_has_no_model(sdk):
    sdk.script = [sdk_response(reply_json(), include_model=False)]

    result = run_complete(make_client())

    assert result.served_model == "unknown"


def test_served_model_is_unknown_when_the_response_model_is_none(sdk):
    sdk.script = [sdk_response(reply_json(), model=None)]

    result = run_complete(make_client())

    assert result.served_model == "unknown"


def test_a_valid_first_attempt_makes_exactly_one_call(sdk):
    sdk.script = [sdk_response(reply_json())]

    run_complete(make_client())

    assert len(sdk.calls) == 1


# --- invalid model output: retried once ---

INVALID_OUTPUTS = [
    pytest.param("this is not json", id="non-json"),
    pytest.param("", id="empty-string"),
    pytest.param(None, id="null-content"),
    pytest.param('{"outcome": "answered", "answer": "cut off', id="truncated-json"),
    pytest.param("[1, 2, 3]", id="json-but-not-an-object"),
    pytest.param(reply_json(outcome="maybe"), id="bad-outcome"),
    pytest.param(reply_json(outcome="Answered"), id="outcome-wrong-case"),
    pytest.param(
        json.dumps({"outcome": "answered", "citations": [1]}), id="missing-answer"
    ),
    pytest.param(
        json.dumps({"outcome": "answered", "answer": "x"}), id="missing-citations"
    ),
    pytest.param(json.dumps({"answer": "x", "citations": []}), id="missing-outcome"),
    pytest.param(
        json.dumps({"outcome": "answered", "answer": "x", "citations": ["one"]}),
        id="citations-wrong-type",
    ),
    pytest.param(
        json.dumps({"outcome": "answered", "answer": 5, "citations": []}),
        id="answer-wrong-type",
    ),
]


@pytest.mark.parametrize("bad", INVALID_OUTPUTS)
def test_invalid_output_is_retried_once_and_a_valid_second_attempt_succeeds(sdk, bad):
    sdk.script = [
        sdk_response(bad),
        sdk_response(reply_json("answered", "Second time lucky.", [2])),
    ]

    result = run_complete(make_client())

    assert len(sdk.calls) == 2
    assert result.answer == "Second time lucky."
    assert list(result.citations) == [2]


@pytest.mark.parametrize("bad", INVALID_OUTPUTS)
def test_two_invalid_outputs_raise_upstream_error_after_exactly_two_calls(sdk, bad):
    sdk.script = [sdk_response(bad), sdk_response(bad)]

    with pytest.raises(UpstreamError):
        run_complete(make_client())

    assert len(sdk.calls) == 2


def test_the_retry_sends_the_same_request(sdk):
    sdk.script = [sdk_response("garbage"), sdk_response(reply_json())]

    run_complete(
        make_client(), system_prompt="S", history=[{"role": "user", "content": "h"}]
    )

    assert sdk.calls[0] == sdk.calls[1]


def test_a_third_attempt_is_never_made(sdk):
    sdk.script = [sdk_response("a"), sdk_response("b"), sdk_response(reply_json())]

    with pytest.raises(UpstreamError):
        run_complete(make_client())

    assert len(sdk.calls) == 2


# --- SDK exceptions are wrapped as UpstreamError ---

SDK_ERRORS = [
    pytest.param(openai.APIConnectionError(request=REQUEST), id="connection"),
    pytest.param(openai.APITimeoutError(request=REQUEST), id="timeout"),
    pytest.param(
        openai.BadRequestError("bad", response=http_response(400), body=None),
        id="400",
    ),
    pytest.param(
        openai.AuthenticationError("auth", response=http_response(401), body=None),
        id="401",
    ),
    pytest.param(
        openai.PermissionDeniedError("denied", response=http_response(403), body=None),
        id="403",
    ),
    pytest.param(
        openai.NotFoundError("nf", response=http_response(404), body=None), id="404"
    ),
    pytest.param(
        openai.RateLimitError("slow down", response=http_response(429), body=None),
        id="429",
    ),
    pytest.param(
        openai.InternalServerError("boom", response=http_response(500), body=None),
        id="500",
    ),
    pytest.param(openai.OpenAIError("generic sdk failure"), id="generic"),
]


@pytest.mark.parametrize("error", SDK_ERRORS)
def test_sdk_exceptions_are_wrapped_as_upstream_error(sdk, error):
    sdk.script = [error]

    with pytest.raises(UpstreamError):
        run_complete(make_client())


@pytest.mark.parametrize("error", SDK_ERRORS)
def test_sdk_exceptions_are_not_retried_here(sdk, error):
    # Retrying transport errors is M9's job; M4 makes one call.
    sdk.script = [error, sdk_response(reply_json())]

    with pytest.raises(UpstreamError):
        run_complete(make_client())

    assert len(sdk.calls) == 1


def test_sdk_error_on_the_retry_attempt_is_also_upstream_error(sdk):
    sdk.script = [
        sdk_response("not json"),
        openai.APIConnectionError(request=REQUEST),
    ]

    with pytest.raises(UpstreamError):
        run_complete(make_client())

    assert len(sdk.calls) == 2


# --- the default dependency builds the client from the environment ---


def test_default_dependency_uses_the_model_and_key_from_the_environment(
    sdk, monkeypatch
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-key-1")
    monkeypatch.setenv("OPENROUTER_MODEL", "env/model-1")
    getattr(get_model_client, "cache_clear", lambda: None)()
    sdk.script = [sdk_response(reply_json())]

    try:
        client = get_model_client()
        run_complete(client)
    finally:
        getattr(get_model_client, "cache_clear", lambda: None)()

    assert sdk.init_kwargs[-1]["api_key"] == "env-key-1"
    assert sdk.init_kwargs[-1]["base_url"] == "https://openrouter.ai/api/v1"
    assert sdk.calls[0]["model"] == "env/model-1"


# --- through the API ---


@pytest.fixture
def api(sdk):
    app.dependency_overrides.clear()
    app.dependency_overrides[get_model_client] = make_client
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_api_returns_the_reply_built_from_the_sdk_output(sdk, api):
    sdk.script = [sdk_response(reply_json("answered", "Cadre is a consultancy.", [1]))]

    response = api.post("/api/chat", json={"message": "What is Cadre?"})

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "answered"
    assert body["answer"] == "Cadre is a consultancy."
    assert [c["faq_id"] for c in body["citations"]] == [1]


def test_api_sends_the_real_system_prompt_history_and_message_to_the_sdk(sdk, api):
    sdk.script = [sdk_response(reply_json("smalltalk", "Hi!", []))]
    history = [
        {"role": "user", "content": "earlier"},
        {"role": "assistant", "content": "earlier reply"},
    ]

    api.post("/api/chat", json={"message": "  now  ", "history": history})

    messages = sdk.calls[0]["messages"]
    assert messages[0] == {"role": "system", "content": load_prompt()}
    assert messages[1:] == [*history, {"role": "user", "content": "now"}]


def test_api_retries_invalid_output_once_then_succeeds(sdk, api):
    sdk.script = [
        sdk_response("garbage"),
        sdk_response(reply_json("smalltalk", "Hi!", [])),
    ]

    response = api.post("/api/chat", json={"message": "Hello"})

    assert response.status_code == 200
    assert response.json()["outcome"] == "smalltalk"
    assert len(sdk.calls) == 2


def test_api_returns_503_after_two_invalid_outputs(sdk, api):
    sdk.script = [sdk_response("garbage"), sdk_response('{"outcome": "nope"}')]

    response = api.post("/api/chat", json={"message": "Hello"})

    assert response.status_code == 503
    body = response.json()
    assert body["error"] == "upstream_unavailable"
    assert set(body) == {"error", "message", "contact"}
    assert len(sdk.calls) == 2


def test_api_returns_503_on_an_sdk_exception_without_leaking_its_text(sdk, api):
    sdk.script = [
        openai.AuthenticationError(
            "secret-key-detail-xyz", response=http_response(401), body=None
        )
    ]

    response = api.post("/api/chat", json={"message": "Hello"})

    assert response.status_code == 503
    assert response.json()["error"] == "upstream_unavailable"
    assert "secret-key-detail-xyz" not in response.text


def test_api_returns_503_on_a_connection_error(sdk, api):
    sdk.script = [openai.APIConnectionError(request=REQUEST)]

    response = api.post("/api/chat", json={"message": "Hello"})

    assert response.status_code == 503
    assert response.json()["error"] == "upstream_unavailable"
