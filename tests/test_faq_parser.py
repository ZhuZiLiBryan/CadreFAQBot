"""M3: the FAQ parser builds FAQ Entries and a URL allowlist, or fails with a line."""

import re

import pytest

from backend.faq import Faq, FaqParseError, load_faq, parse_faq

VALID_FAQ = """\
# Test FAQ

## Section one

### 1. What is one?
Body of one.

Sources: [Page A](https://cadre.ai/a)

### 2. What is two?
Body of two.

Sources: [Page B](https://cadre.ai/b), [Page C](https://cadre.ai/c)
"""


def build_faq(lines: list[str]) -> str:
    return "\n".join(lines) + "\n"


def line_of(lines: list[str], needle: str) -> int:
    """1-based line number of the first line that equals or starts with needle."""
    for index, line in enumerate(lines, start=1):
        if line == needle or line.startswith(needle):
            return index
    raise AssertionError(f"{needle!r} not found in test FAQ")


def reported_lines(error: BaseException) -> set[int]:
    """Every number that follows the word 'line' in the error message."""
    return {
        int(n) for n in re.findall(r"line\s+(\d+)", str(error), flags=re.IGNORECASE)
    }


def assert_names_a_line_in(error: BaseException, allowed: range | set[int]) -> None:
    found = reported_lines(error)
    assert found, f"error message does not name a line number: {error!s}"
    assert found & set(allowed), (
        f"error names {sorted(found)}, expected one of {sorted(allowed)}: {error!s}"
    )


# --- the real FAQ ---


def test_real_faq_parses_to_52_entries():
    faq = load_faq()

    assert isinstance(faq, Faq)
    assert len(faq.entries) == 52


def test_real_faq_entries_are_keyed_by_number_in_ascending_order():
    faq = load_faq()

    assert list(faq.entries) == list(range(1, 53))
    for number, entry in faq.entries.items():
        assert entry.number == number


def test_real_faq_entry_one_has_its_question_and_source():
    entry = load_faq().entries[1]

    assert entry.question == "What does Cadre AI do?"
    assert [(s.title, s.url) for s in entry.sources] == [
        ("Cadre homepage", "https://cadre.ai/")
    ]
    assert entry.body.strip() != ""


def test_real_faq_entry_three_has_two_sources_in_order():
    entry = load_faq().entries[3]

    assert [s.title for s in entry.sources] == ["Cadre homepage", "AI Engineering"]
    assert entry.sources[1].url == "https://cadre.ai/ai-engineering"


def test_real_faq_allowlist_contains_normalized_source_urls_only_as_https():
    faq = load_faq()

    assert isinstance(faq.allowlist, frozenset)
    assert "https://cadre.ai/ai-maturity-index" in faq.allowlist
    assert "https://cadre.ai/strategy" in faq.allowlist
    assert all(url.startswith("https://") for url in faq.allowlist)
    assert all(not url.endswith("/") for url in faq.allowlist)


def test_real_faq_allowlist_covers_every_source_of_every_entry():
    faq = load_faq()

    for entry in faq.entries.values():
        for source in entry.sources:
            normalized = source.url.rstrip("/").lower().replace("://www.", "://")
            assert normalized in faq.allowlist


# --- a minimal valid FAQ ---


def test_minimal_valid_faq_parses():
    faq = parse_faq(VALID_FAQ)

    assert list(faq.entries) == [1, 2]
    assert faq.entries[1].number == 1
    assert faq.entries[1].question == "What is one?"
    assert "Body of one." in faq.entries[1].body
    assert [(s.title, s.url) for s in faq.entries[1].sources] == [
        ("Page A", "https://cadre.ai/a")
    ]
    assert [(s.title, s.url) for s in faq.entries[2].sources] == [
        ("Page B", "https://cadre.ai/b"),
        ("Page C", "https://cadre.ai/c"),
    ]


def test_entry_body_does_not_include_the_sources_line():
    faq = parse_faq(VALID_FAQ)

    assert "Sources:" not in faq.entries[1].body


def test_a_single_entry_faq_parses():
    faq = parse_faq("### 1. Only?\nOnly body.\n\nSources: [A](https://cadre.ai/a)\n")

    assert list(faq.entries) == [1]


def test_multi_line_body_is_kept():
    faq = parse_faq(
        "### 1. Q?\nFirst body line.\nSecond body line.\n\nSources: [A](https://cadre.ai/a)\n"
    )

    assert "First body line." in faq.entries[1].body
    assert "Second body line." in faq.entries[1].body


def test_title_and_section_headings_are_ignored():
    faq = parse_faq(VALID_FAQ)

    assert len(faq.entries) == 2
    for entry in faq.entries.values():
        assert "Test FAQ" not in entry.question
        assert "Section one" not in entry.body
        assert "Section one" not in entry.question


def test_section_heading_between_entries_does_not_leak_into_the_previous_body():
    text = build_faq(
        [
            "# Title",
            "## Section A",
            "### 1. Q one?",
            "Body one.",
            "",
            "Sources: [A](https://cadre.ai/a)",
            "",
            "## Section B",
            "",
            "### 2. Q two?",
            "Body two.",
            "",
            "Sources: [B](https://cadre.ai/b)",
        ]
    )

    faq = parse_faq(text)

    assert list(faq.entries) == [1, 2]
    assert "Section B" not in faq.entries[1].body


def test_entries_may_skip_numbers_if_strictly_ascending():
    text = build_faq(
        [
            "### 1. Q?",
            "Body.",
            "Sources: [A](https://cadre.ai/a)",
            "### 5. Q?",
            "Body.",
            "Sources: [A](https://cadre.ai/a)",
        ]
    )

    assert list(parse_faq(text).entries) == [1, 5]


# --- URL allowlist normalization ---


def test_allowlist_strips_trailing_slash():
    faq = parse_faq("### 1. Q?\nBody.\n\nSources: [Home](https://cadre.ai/)\n")

    assert "https://cadre.ai" in faq.allowlist


def test_allowlist_strips_www_prefix():
    faq = parse_faq("### 1. Q?\nBody.\n\nSources: [A](https://www.cadre.ai/strategy)\n")

    assert "https://cadre.ai/strategy" in faq.allowlist
    assert "https://www.cadre.ai/strategy" not in faq.allowlist


def test_allowlist_lowercases_the_host():
    faq = parse_faq("### 1. Q?\nBody.\n\nSources: [A](https://CADRE.AI/strategy)\n")

    assert "https://cadre.ai/strategy" in faq.allowlist
    assert "https://CADRE.AI/strategy" not in faq.allowlist


def test_allowlist_applies_all_normalizations_together():
    faq = parse_faq(
        "### 1. Q?\nBody.\n\nSources: [A](https://WWW.Cadre.AI/strategy/)\n"
    )

    assert faq.allowlist == frozenset({"https://cadre.ai/strategy"})


def test_allowlist_includes_inline_body_links_as_well_as_sources():
    text = (
        "### 1. Q?\n"
        "See [the pricing page](https://www.Example.com/pricing/) for details.\n"
        "\n"
        "Sources: [A](https://cadre.ai/a)\n"
    )

    faq = parse_faq(text)

    assert faq.allowlist == frozenset(
        {"https://example.com/pricing", "https://cadre.ai/a"}
    )


def test_allowlist_collects_urls_from_every_entry_without_duplicates():
    faq = parse_faq(
        VALID_FAQ
        + "\n### 3. What is three?\nBody.\n\nSources: [Again](https://cadre.ai/a/)\n"
    )

    assert faq.allowlist == frozenset(
        {"https://cadre.ai/a", "https://cadre.ai/b", "https://cadre.ai/c"}
    )


def test_allowlist_does_not_contain_non_faq_urls():
    faq = parse_faq(VALID_FAQ)

    assert "https://evil.example.com" not in faq.allowlist


# --- malformed FAQs raise FaqParseError naming a line ---


def test_faq_parse_error_is_a_value_error():
    assert issubclass(FaqParseError, ValueError)


def test_missing_sources_line_raises_with_line_number():
    lines = [
        "# Title",
        "",
        "### 1. Q one?",
        "Body one.",
        "",
        "### 2. Q two?",
        "Body two.",
        "",
        "Sources: [B](https://cadre.ai/b)",
    ]

    with pytest.raises(FaqParseError) as excinfo:
        parse_faq(build_faq(lines))

    # Entry 1 spans the heading line up to the line before entry 2's heading.
    assert_names_a_line_in(
        excinfo.value, range(line_of(lines, "### 1."), line_of(lines, "### 2.") + 1)
    )


def test_missing_sources_on_the_last_entry_raises_with_line_number():
    lines = [
        "### 1. Q one?",
        "Body one.",
        "",
        "Sources: [A](https://cadre.ai/a)",
        "",
        "### 2. Q two?",
        "Body two.",
    ]

    with pytest.raises(FaqParseError) as excinfo:
        parse_faq(build_faq(lines))

    assert_names_a_line_in(
        excinfo.value, range(line_of(lines, "### 2."), len(lines) + 2)
    )


def test_duplicate_entry_number_raises_with_the_line_of_the_duplicate():
    lines = [
        "### 1. Q one?",
        "Body one.",
        "Sources: [A](https://cadre.ai/a)",
        "",
        "### 1. Q one again?",
        "Body again.",
        "Sources: [A](https://cadre.ai/a)",
    ]

    with pytest.raises(FaqParseError) as excinfo:
        parse_faq(build_faq(lines))

    assert_names_a_line_in(excinfo.value, {line_of(lines, "### 1. Q one again?")})


def test_out_of_order_entry_number_raises_with_the_line_of_the_offender():
    lines = [
        "### 1. Q one?",
        "Body one.",
        "Sources: [A](https://cadre.ai/a)",
        "",
        "### 3. Q three?",
        "Body three.",
        "Sources: [A](https://cadre.ai/a)",
        "",
        "### 2. Q two?",
        "Body two.",
        "Sources: [A](https://cadre.ai/a)",
    ]

    with pytest.raises(FaqParseError) as excinfo:
        parse_faq(build_faq(lines))

    assert_names_a_line_in(excinfo.value, {line_of(lines, "### 2. Q two?")})


def test_entry_number_zero_is_rejected():
    # N is "a positive integer, unique, strictly ascending"; zero is not positive.
    lines = [
        "### 0. Q zero?",
        "Body.",
        "Sources: [A](https://cadre.ai/a)",
    ]

    with pytest.raises(FaqParseError) as excinfo:
        parse_faq(build_faq(lines))

    assert_names_a_line_in(excinfo.value, range(1, len(lines) + 2))


def test_http_source_url_raises_with_the_line_of_the_url():
    lines = [
        "# Title",
        "",
        "### 1. Q one?",
        "Body one.",
        "",
        "Sources: [A](http://cadre.ai/a)",
    ]

    with pytest.raises(FaqParseError) as excinfo:
        parse_faq(build_faq(lines))

    assert_names_a_line_in(excinfo.value, {line_of(lines, "Sources:")})


def test_http_url_in_a_later_entry_reports_that_entrys_line():
    lines = [
        "### 1. Q one?",
        "Body one.",
        "Sources: [A](https://cadre.ai/a)",
        "",
        "### 2. Q two?",
        "Body two.",
        "Sources: [B](http://cadre.ai/b)",
    ]

    with pytest.raises(FaqParseError) as excinfo:
        parse_faq(build_faq(lines))

    assert_names_a_line_in(excinfo.value, {line_of(lines, "Sources: [B]")})


def test_empty_body_raises_with_line_number():
    lines = [
        "# Title",
        "",
        "### 1. Q one?",
        "",
        "Sources: [A](https://cadre.ai/a)",
    ]

    with pytest.raises(FaqParseError) as excinfo:
        parse_faq(build_faq(lines))

    assert_names_a_line_in(
        excinfo.value, range(line_of(lines, "### 1."), len(lines) + 1)
    )


def test_heading_directly_followed_by_sources_has_an_empty_body():
    lines = [
        "### 1. Q one?",
        "Sources: [A](https://cadre.ai/a)",
    ]

    with pytest.raises(FaqParseError) as excinfo:
        parse_faq(build_faq(lines))

    assert_names_a_line_in(excinfo.value, {1, 2})


def test_sources_line_with_a_non_link_raises():
    lines = [
        "### 1. Q one?",
        "Body one.",
        "Sources: just some words",
    ]

    with pytest.raises(FaqParseError) as excinfo:
        parse_faq(build_faq(lines))

    assert_names_a_line_in(excinfo.value, {1, 2, 3, 4})


def test_error_message_mentions_the_word_line():
    with pytest.raises(FaqParseError, match=r"(?i)line\s+\d+"):
        parse_faq("### 1. Q one?\nBody one.\n")


# --- Sources scheme and heading URLs ---


@pytest.mark.parametrize(
    "url",
    ["ftp://cadre.ai/a", "javascript:alert(1)", "mailto:a@b.co", "cadre.ai/a"],
)
def test_non_https_source_link_raises_with_the_sources_line(url):
    lines = [
        "# Title",
        "",
        "### 1. Q one?",
        "Body one.",
        "",
        f"Sources: [A]({url})",
    ]

    with pytest.raises(FaqParseError) as excinfo:
        parse_faq(build_faq(lines))

    assert_names_a_line_in(excinfo.value, {line_of(lines, "Sources:")})


def test_https_url_in_a_heading_is_in_the_normalized_allowlist():
    text = (
        "### 1. What is [the AI page](https://www.Example.com/ai/)?\n"
        "Body.\n"
        "\n"
        "Sources: [A](https://cadre.ai/a)\n"
    )

    faq = parse_faq(text)

    assert "https://example.com/ai" in faq.allowlist
    assert "https://cadre.ai/a" in faq.allowlist


def test_http_url_in_a_heading_raises_with_the_heading_line():
    lines = [
        "# Title",
        "",
        "### 1. Q one?",
        "Body one.",
        "",
        "Sources: [A](https://cadre.ai/a)",
        "",
        "### 2. What is [this](http://example.com/x)?",
        "Body two.",
        "",
        "Sources: [B](https://cadre.ai/b)",
    ]

    with pytest.raises(FaqParseError) as excinfo:
        parse_faq(build_faq(lines))

    assert_names_a_line_in(excinfo.value, {line_of(lines, "### 2.")})
