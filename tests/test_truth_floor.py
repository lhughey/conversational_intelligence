"""Mechanical truth-floor checks: quotes in any quote style, and stated numbers."""

import pytest

from convint.domain.truth_floor import (
    check_truth_floor, extract_quotes, number_mentions, unsupported_numbers,
    unsupported_quotes,
)

MAYA = (
    "I remember one woman, furious about a dress. It was her daughter’s "
    "graduation and she was terrified of looking poor. I told my mom that. "
    "She comped the cleaning and the woman cried.\n"
    "Billing and clinical blamed each other for months — the standoff "
    "dissolved in one session. Later, on a twelve-state care initiative, I "
    "flagged three of those gaps. That was back in 2019, and it cut wait "
    "times by 30 percent, saving about $2M."
)


def _spans(issues):
    return [i.span for i in issues]


# --- quotes: every quote style ---------------------------------------------

@pytest.mark.parametrize("text", [
    "You said “I ran the entire division”.",           # curly double
    "You said ‘I ran the entire division’.",           # curly single
    "You said 'I ran the entire division'.",                     # straight single
    "You said «I ran the entire division».",           # guillemets
    'You said "I ran the entire division".',                     # straight double
])
def test_fabricated_quote_is_caught_in_any_quote_style(text):
    assert _spans(unsupported_quotes({"a": text}, MAYA)) == ["I ran the entire division"]


@pytest.mark.parametrize("text", [
    "You said “I told my mom that”.",
    "You said ‘I told my mom that.’",
    "You said 'she comped the cleaning'.",
    # curly apostrophe in the Read, curly in the source: normalised both sides
    "You noticed “her daughter’s graduation” mattered.",
    # straight apostrophe in the Read, curly in the source
    "You noticed \"her daughter's graduation\" mattered.",
    # em dash in the source, spaced hyphen in the Read
    '"blamed each other for months - the standoff dissolved"',
    # ellipsis elides; each fragment must still be theirs
    '"I told my mom that… the woman cried"',
])
def test_real_quotes_pass_in_any_style(text):
    assert unsupported_quotes({"a": text}, MAYA) == []


def test_ellipsis_does_not_launder_an_invented_fragment():
    issues = unsupported_quotes({"a": '"I told my mom that... and she promoted me"'}, MAYA)
    assert len(issues) == 1


@pytest.mark.parametrize("text", [
    "You don't wait to be asked, and you didn't then.",
    "Your parents' shop taught you the customers' real needs.",
    "In the '90s you weren't the one they'd call.",
    "You'd sit with 'em until it was clear.",
    "Rock 'n' roll was never your parents' thing, 'cause it's loud.",
    "It's your kids' school and your neighbours' garden.",
])
def test_apostrophes_are_not_mistaken_for_quotes(text):
    assert extract_quotes(text) == []


def test_text_between_two_short_quotes_is_not_a_quote():
    """Quotes pair left to right: the gap between "done" and "fine" is not a
    quoted span, even when it is long enough to look like one."""
    assert extract_quotes('You called it "done" and then later "fine".') == []


def test_short_scare_quotes_are_not_checked():
    assert extract_quotes("You were the 'fixer' and the “glue”.") == []


def test_nested_quotes_are_checked_once():
    text = 'You said "she comped the cleaning, \'no charge\'" to me.'
    assert extract_quotes(text) == ["she comped the cleaning, 'no charge'"]


def test_quotes_in_nested_fields_are_checked_with_their_path():
    art = {"items": [{"text": "ok"}, {"text": '"I scaled a 400-person org"'}]}
    issues = unsupported_quotes(art, MAYA)
    assert [(i.field, i.span) for i in issues] == [("items[1].text", "I scaled a 400-person org")]


# --- numbers -----------------------------------------------------------------

@pytest.mark.parametrize("text, invented", [
    ("You increased revenue by 300%.", "300%"),
    ("You led a team of 200.", "200"),
    ("Back in 2017 you saw it.", "2017"),
    ("You saved $5 million.", "$5 million"),
    ("You flagged four of those gaps.", "four"),
    ("Across fourteen states.", "fourteen"),
    ("A hundred teams trusted you.", "A hundred"),
    ("Two dozen teams trusted you.", "Two dozen"),
    ("Wait times fell by 40 percent.", "40 percent"),
])
def test_invented_number_is_caught(text, invented):
    assert _spans(unsupported_numbers({"a": text}, MAYA)) == [invented]


@pytest.mark.parametrize("text", [
    "You flagged three of those gaps.",            # same word
    "You flagged 3 of those gaps.",                # word in source, digit in Read
    "Across 12 states.",                           # "twelve-state" in source
    "Across twelve states.",
    "In 2019 you cut wait times.",                 # year
    "You cut wait times by 30%.",                  # "30 percent" in source
    "You cut wait times by thirty percent.",
    "You saved roughly 2 million dollars.",        # "$2M" in source
    "You saved $2,000,000.",
    "You saved $2M.",
])
def test_number_the_user_stated_passes_in_any_form(text):
    assert unsupported_numbers({"a": text}, MAYA) == []


def test_a_percentage_must_be_backed_by_a_percentage():
    """"30" was only ever a percentage, but "flagged three" does not make 3%
    the user's claim."""
    assert _spans(unsupported_numbers({"a": "a 3% gain"}, MAYA)) == ["3%"]


def test_a_bare_number_may_echo_a_percentage():
    assert unsupported_numbers({"a": "about 30 of every 100"}, "30 percent of 100 calls") == []


@pytest.mark.parametrize("text", [
    "No one else saw it; you were the one who did.",
    "A word meaning two different things.",       # from a real cached Read
    "You hold two worlds together, one room at a time.",
    "First you listen, then you name it. A third of it is patience.",
    "1. You see the real need.\n2) You act on it.",  # list markers are layout
])
def test_low_risk_number_language_is_not_flagged(text):
    assert unsupported_numbers({"a": text}, MAYA) == []


def test_compound_and_adjacent_number_words():
    assert [m.value for m in number_mentions("twenty-five people")] == [25]
    assert [m.value for m in number_mentions("two three-hour sessions")] == [2, 3]
    assert [m.value for m in number_mentions("two hundred")] == [200]
    assert [m.value for m in number_mentions("2 million")] == [2_000_000]


def test_check_truth_floor_returns_structured_issues():
    art = {"headline": "You “ran the whole division”", "brings": "a 300% lift"}
    issues = check_truth_floor(art, MAYA)
    assert [(i.kind, i.field, i.span) for i in issues] == [
        ("quote", "headline", "ran the whole division"),
        ("number", "brings", "300%"),
    ]


# --- golden transcripts: the user's own words always pass --------------------

def test_every_golden_user_turn_passes_its_own_truth_floor(goldens):
    """Sanity pass over the replay fixtures: a Read made only of the user's own
    words, in every quote style and number form they used, must never be
    withheld. Catches a normaliser that reads the same text two ways."""
    checked = 0
    for name, transcript in goldens.items():
        turns = transcript["userTurns"]
        source = "\n".join(turns)
        for i, turn in enumerate(turns):
            art = {"plain": turn, "quoted": f"You said “{turn}”"}
            issues = check_truth_floor(art, source)
            assert issues == [], f"{name} turn {i}: {issues}"
            checked += 1
    assert checked > 50
