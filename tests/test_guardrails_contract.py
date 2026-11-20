"""M6: guardrails seen through the /api/chat contract (mocked ModelClient)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.model_client import ModelResult, get_model_client

FORM_URL = "https://cadre.ai/contact"
EMAIL = "hello@gocadre.ai"


class FakeClient:
    def __init__(self, result: ModelResult):
        self.result = result

    async def complete(self, system_prompt, history, message) -> ModelResult:
        return self.result


def make_result(outcome, answer, citations) -> ModelResult:
    return ModelResult(
        outcome=outcome,
        answer=answer,
        citations=citations,
        served_model="fake/model",
        tokens_in=10,
        tokens_out=5,
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides.clear()
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def chat(client: TestClient, result: ModelResult) -> dict:
    app.dependency_overrides[get_model_client] = lambda: FakeClient(result)
    response = client.post("/api/chat", json={"message": "Q?"})
    assert response.status_code == 200
    return response.json()


def fallback_answer(client: TestClient) -> str:
    return chat(client, make_result("unanswered", "ignored", []))["answer"]


def test_answered_reply_citing_only_unknown_ids_becomes_unanswered_fallback(client):
    fallback = fallback_answer(client)

    body = chat(client, make_result("answered", "Confident claim.", [9999, 0]))

    assert body["outcome"] == "unanswered"
    assert body["answer"] == fallback
    assert "Confident claim." not in body["answer"]
    assert body["citations"] == []
    assert body["contact"]["form_url"] == FORM_URL
    assert body["contact"]["email"] == EMAIL
    assert body["contact"]["text"].strip() != ""


def test_partial_reply_with_no_citations_becomes_unanswered(client):
    body = chat(client, make_result("partial", "Half claim.", []))

    assert body["outcome"] == "unanswered"
    assert body["citations"] == []
    assert body["contact"] is not None


def test_answered_reply_with_a_valid_citation_is_unaffected(client):
    body = chat(client, make_result("answered", "Fine answer.", [23]))

    assert body["outcome"] == "answered"
    assert body["answer"] == "Fine answer."
    assert body["contact"] is None


def test_non_allowlisted_link_and_email_never_reach_the_visitor(client):
    answer = "See [here](https://evil.example/p) or mail bad@evil.example."

    body = chat(client, make_result("answered", answer, [23]))

    assert "evil.example" not in body["answer"]
    assert "here" in body["answer"]


def test_smalltalk_with_a_url_is_replaced_and_has_no_citations(client):
    body = chat(client, make_result("smalltalk", "Go to https://evil.example", [1]))

    assert body["outcome"] == "smalltalk"
    assert "evil.example" not in body["answer"]
    assert body["citations"] == []
    assert body["contact"] is None
