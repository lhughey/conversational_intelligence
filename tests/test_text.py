from convint.domain.text import (
    content_tokens, ends_with_question, grounding_overlap, question_count, quoted_span, tokens,
)

USER = "Made flashcards. Read things out loud different ways until something clicked for her."


def test_stopwords_and_short_words_are_dropped():
    assert "the" not in content_tokens("the flashcards")
    assert "flashcards" in content_tokens("the flashcards")


def test_grounding_finds_words_lifted_from_the_user():
    assert "flashcards" in grounding_overlap("What made you reach for flashcards?", USER)


def test_grounding_gives_no_credit_for_echoing_the_interviewer():
    """Otherwise a model scores 'grounded' by repeating its own prior turn."""
    assert grounding_overlap("Tell me about the flashcards.", USER, exclude="flashcards") == []


def test_grounding_is_deduplicated_and_ordered():
    assert grounding_overlap("flashcards flashcards clicked", USER) == ["flashcards", "clicked"]


def test_quoted_span_detects_a_carried_phrase():
    assert quoted_span("you made flashcards for her", USER) == "made flashcards"


def test_quoted_span_requires_consecutive_words():
    assert quoted_span("what happened next", USER) is None


def test_quoted_span_does_not_stem():
    """Strict by design: 'reading' is not 'read'."""
    assert quoted_span("reading things", USER) is None


def test_tokenizer_lowercases_and_strips_punctuation():
    assert tokens("Billing, and CLINICAL?") == ["billing", "and", "clinical"]


def test_tokenizer_keeps_hyphenated_compounds_intact():
    """`care-coordination` is one term, not two - grounding depends on it."""
    assert tokens("care-coordination work") == ["care-coordination", "work"]


def test_tokenizer_keeps_contractions():
    assert tokens("don't") == ["don't"]


def test_question_helpers():
    assert question_count("a? b?") == 2
    assert ends_with_question("really?  ")
    assert not ends_with_question("really")
