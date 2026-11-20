"""M6: output guardrails, unit-tested against small FAQs built with parse_faq."""

import pytest

from backend.faq import parse_faq
from backend.guardrails import MAX_ANSWER_CHARS, SMALLTALK_GREETING, apply_guardrails
from backend.model_client import ModelResult

FAQ_TEXT = """# Test FAQ

## General

### 1. What does Cadre do?
Cadre helps with AI strategy. Email hello@gocadre.ai or call +1 (555) 010-2030.
See [the index](https://www.Example.com/Guide/) for more.
Sources: [Home](https://cadre.ai/), [AI Maturity Index](https://cadre.ai/ai-maturity-index)

### 2. How do I start?
Use the form.
Sources: [Contact](https://cadre.ai/contact)
"""

FAQ = parse_faq(FAQ_TEXT)


def make(outcome="answered", answer="Plain answer.", citations=None) -> ModelResult:
    return ModelResult(
        outcome=outcome,
        answer=answer,
        citations=[1] if citations is None else citations,
        served_model="fake/model",
        tokens_in=10,
        tokens_out=5,
    )


def run(answer, outcome="answered", citations=None):
    return apply_guardrails(make(outcome, answer, citations), FAQ)


# --- clean replies ---


def test_clean_answered_reply_is_unchanged_with_no_reasons():
    original = make("answered", "Cadre helps with AI strategy.", [1, 2])

    result, reasons = apply_guardrails(original, FAQ)

    assert reasons == []
    assert result == original


def test_clean_partial_reply_is_unchanged_with_no_reasons():
    original = make("partial", "Only part is covered.", [2])

    result, reasons = apply_guardrails(original, FAQ)

    assert reasons == []
    assert result == original


def test_unanswered_reply_gets_no_reasons():
    result, reasons = run("Nothing here.", "unanswered", [])

    assert reasons == []
    assert result.outcome == "unanswered"


def test_other_result_fields_are_preserved_when_modified():
    result, _ = run("See [x](https://evil.example/y).")

    assert result.served_model == "fake/model"
    assert result.tokens_in == 10
    assert result.tokens_out == 5


# --- no_valid_citations ---


@pytest.mark.parametrize("outcome", ["answered", "partial"])
def test_zero_citations_becomes_unanswered(outcome):
    result, reasons = run("Claim.", outcome, [])

    assert result.outcome == "unanswered"
    assert reasons == ["no_valid_citations"]


@pytest.mark.parametrize("outcome", ["answered", "partial"])
def test_only_unknown_citations_becomes_unanswered(outcome):
    result, reasons = run("Claim.", outcome, [999, 0, -1])

    assert result.outcome == "unanswered"
    assert "no_valid_citations" in reasons


def test_one_valid_among_unknown_citations_stays_answered():
    result, reasons = run("Claim.", "answered", [999, 2])

    assert result.outcome == "answered"
    assert "no_valid_citations" not in reasons


# --- links ---


def test_allowlisted_markdown_link_is_kept():
    answer = "See [the form](https://cadre.ai/contact) now."

    result, reasons = run(answer)

    assert result.answer == answer
    assert reasons == []


def test_inline_body_link_url_is_on_the_allowlist():
    answer = "See [guide](https://example.com/Guide) now."

    result, reasons = run(answer)

    assert result.answer == answer
    assert reasons == []


@pytest.mark.parametrize(
    "url",
    [
        "https://www.cadre.ai/contact",
        "https://cadre.ai/contact/",
        "https://CADRE.AI/contact",
        "https://WWW.Cadre.AI/contact/",
    ],
)
def test_allowlist_normalization_www_trailing_slash_and_host_case(url):
    answer = f"See [the form]({url}) now."

    result, reasons = run(answer)

    assert result.answer == answer
    assert "link_not_allowed" not in reasons


def test_non_allowlisted_markdown_link_is_replaced_by_its_text():
    result, reasons = run("Go to [our site](https://evil.example/phish) today.")

    assert result.answer == "Go to our site today."
    assert reasons == ["link_not_allowed"]


def test_lookalike_domain_link_is_rejected():
    result, reasons = run("Go to [Cadre](https://cadre.ai.evil.com/x) today.")

    assert "evil.com" not in result.answer
    assert "Cadre" in result.answer
    assert "link_not_allowed" in reasons


def test_lookalike_prefix_domain_link_is_rejected():
    result, reasons = run("Go to [Cadre](https://evilcadre.ai/contact) today.")

    assert "evilcadre.ai" not in result.answer
    assert "link_not_allowed" in reasons


def test_non_https_markdown_link_is_not_kept():
    result, reasons = run("Go to [Cadre](http://cadre.ai/contact) today.")

    assert "http://cadre.ai/contact" not in result.answer
    assert "link_not_allowed" in reasons


def test_allowlisted_and_bad_links_in_one_answer():
    answer = "[ok](https://cadre.ai/contact) and [bad](https://evil.example/z)"

    result, reasons = run(answer)

    assert result.answer == "[ok](https://cadre.ai/contact) and bad"
    assert reasons == ["link_not_allowed"]


# --- bare URLs ---


def test_bare_non_allowlisted_url_is_removed():
    result, reasons = run("Visit https://evil.example/phish now.")

    assert "evil.example" not in result.answer
    assert "Visit" in result.answer
    assert "now." in result.answer
    assert "url_not_allowed" in reasons


def test_bare_http_url_is_removed():
    result, reasons = run("Visit http://cadre.ai/contact now.")

    assert "http://" not in result.answer
    assert "url_not_allowed" in reasons


def test_bare_lookalike_url_is_removed():
    result, reasons = run("Visit https://cadre.ai.evil.com/x now.")

    assert "evil.com" not in result.answer
    assert "url_not_allowed" in reasons


def test_bare_allowlisted_url_is_kept():
    answer = "Visit https://cadre.ai/contact now."

    result, reasons = run(answer)

    assert result.answer == answer
    assert reasons == []


# --- emails and phones ---


def test_email_not_in_faq_is_removed():
    result, reasons = run("Write to attacker@evil.example please.")

    assert "attacker@evil.example" not in result.answer
    assert "please." in result.answer
    assert "contact_not_allowed" in reasons


def test_email_present_in_faq_is_kept():
    answer = "Write to hello@gocadre.ai please."

    result, reasons = run(answer)

    assert result.answer == answer
    assert reasons == []


def test_phone_not_in_faq_is_removed():
    result, reasons = run("Call +1 (555) 999-8888 today.")

    assert "999-8888" not in result.answer
    assert "contact_not_allowed" in reasons


def test_phone_present_in_faq_is_kept():
    answer = "Call +1 (555) 010-2030 today."

    result, reasons = run(answer)

    assert result.answer == answer
    assert reasons == []


def test_mixed_allowed_and_disallowed_contacts():
    result, reasons = run("Email hello@gocadre.ai or bad@evil.example.")

    assert "hello@gocadre.ai" in result.answer
    assert "bad@evil.example" not in result.answer
    assert reasons == ["contact_not_allowed"]


# --- truncation ---


def test_answer_at_the_limit_is_not_truncated():
    answer = ("word " * 400)[:MAX_ANSWER_CHARS]

    result, reasons = run(answer)

    assert result.answer == answer
    assert "answer_truncated" not in reasons


def test_long_answer_is_truncated_with_an_ellipsis_within_the_limit():
    answer = "alpha " * 400

    result, reasons = run(answer)

    assert MAX_ANSWER_CHARS == 1200
    assert len(result.answer) <= MAX_ANSWER_CHARS
    assert result.answer.endswith("…")
    assert reasons == ["answer_truncated"]


def test_truncation_cuts_at_a_word_boundary():
    answer = "abcdefghi " * 200

    result, _ = run(answer)

    body = result.answer[:-1]
    assert body.split() and all(w == "abcdefghi" for w in body.split())
    assert answer.startswith(body)


def test_truncation_applies_to_partial_replies_too():
    result, reasons = run("alpha " * 400, "partial", [1])

    assert result.outcome == "partial"
    assert reasons == ["answer_truncated"]


# --- reasons list ---


def test_reasons_have_no_duplicates():
    answer = "[a](https://evil.example/1) and [b](https://evil.example/2)"

    _, reasons = run(answer)

    assert reasons == ["link_not_allowed"]


def test_multiple_reasons_are_all_reported():
    answer = "[a](https://evil.example/1) https://evil.example/2 bad@evil.example"

    _, reasons = run(answer)

    assert set(reasons) == {
        "link_not_allowed",
        "url_not_allowed",
        "contact_not_allowed",
    }
    assert len(reasons) == len(set(reasons))


# --- smalltalk ---


def test_plain_greeting_smalltalk_is_kept():
    result, reasons = run("Hello! Ask me about Cadre.", "smalltalk", [])

    assert result.outcome == "smalltalk"
    assert result.answer == "Hello! Ask me about Cadre."
    assert reasons == []


def test_greeting_constant_matches_the_plan():
    assert SMALLTALK_GREETING == (
        "Hi! I can answer questions about Cadre AI's services, the AI Maturity "
        "Index, industries, and how to get in touch. What would you like to know?"
    )


@pytest.mark.parametrize(
    "text",
    [
        "Hello " + "there " * 60,
        "See https://cadre.ai/contact for more.",
        "Mail hello@gocadre.ai for more.",
        "Call 555-010-2030 for more.",
        "We have 3 services.",
        "It costs $five.",
    ],
)
def test_smalltalk_with_risky_content_is_replaced_by_the_greeting(text):
    result, reasons = run(text, "smalltalk", [])

    assert result.outcome == "smalltalk"
    assert result.answer == SMALLTALK_GREETING
    assert "smalltalk_replaced" in reasons


def test_smalltalk_of_exactly_300_chars_is_kept():
    text = ("a" * 299) + "."
    assert len(text) == 300

    result, reasons = run(text, "smalltalk", [])

    assert result.answer == text
    assert "smalltalk_replaced" not in reasons


def test_smalltalk_over_300_chars_is_replaced():
    result, reasons = run("a" * 301, "smalltalk", [])

    assert result.answer == SMALLTALK_GREETING
    assert "smalltalk_replaced" in reasons


def test_smalltalk_citations_are_cleared_even_for_a_plain_greeting():
    result, _ = run("Hi there!", "smalltalk", [1, 2])

    assert result.citations == []


def test_smalltalk_citations_are_cleared_when_replaced():
    result, _ = run("Call 555-010-2030.", "smalltalk", [1])

    assert result.citations == []
    assert result.answer == SMALLTALK_GREETING
