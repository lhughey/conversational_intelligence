from convint.domain import Ownership, Specificity, assess_turn, extract_components
from convint.domain.sufficiency import SufficiencyComponents

DRESS = (
    "I remember one woman, furious about a dress. My mom was apologizing about the "
    "stain but I could see it wasn't about the dress — it was her daughter's "
    "graduation and she was terrified of looking poor in front of the other families. "
    "I told my mom that. She comped the cleaning and added a small alteration for "
    "free. The woman cried."
)


def test_canonical_episode_scores_s3_with_all_four_components():
    a = assess_turn(DRESS)
    assert a.specificity is Specificity.S3
    c = a.components
    assert (c.scene, c.stakes, c.action, c.outcome) == (True, True, True, True)
    assert set(c.evidence) >= {"scene", "stakes", "action", "outcome"}


def test_deflection_scores_s0():
    a = assess_turn("I don't really remember childhood. Normal I guess. Nothing weird.")
    assert a.specificity is Specificity.S0


def test_generalization_without_instance_scores_s1_not_higher():
    a = assess_turn("I'm good at what I do but I can never explain it to anyone.")
    assert a.specificity is Specificity.S1


def test_self_label_is_ownership_o1_not_o2():
    """A pre-existing label the user brought with them is not discovered insight."""
    a = assess_turn("I know my pattern — I'm a connector. I see what's missing and build the bridge.")
    assert a.ownership is Ownership.O1


def test_own_derivation_is_o2():
    a = assess_turn("I think I've always been able to see the real thing under what people say.")
    assert a.ownership is Ownership.O2


def test_specificity_and_ownership_are_independent():
    """A confident self-description with no instance: high ownership, low specificity."""
    a = assess_turn("I'm a connector. That's just who I am.")
    assert a.specificity.rank <= Specificity.S1.rank
    assert a.ownership.rank >= Ownership.O1.rank


def test_components_merge_accumulates_across_turns():
    """Two partial turns on one topic can together clear a bar neither clears alone."""
    first = SufficiencyComponents(scene=True, stakes=True, evidence={"scene": "x"})
    second = SufficiencyComponents(action=True, outcome=True, evidence={"action": "y"})
    merged = first.merge(second)
    assert merged.narrative_count == 4
    assert merged.evidence == {"scene": "x", "action": "y"}


def test_merge_is_non_destructive():
    a = SufficiencyComponents(scene=True)
    b = SufficiencyComponents(action=True)
    a.merge(b)
    assert a.action is False and b.scene is False


def test_extraction_records_why():
    c = extract_components(DRESS)
    assert "cried" in c.evidence["outcome"]
