from convint.app.moves import select_move
from convint.domain.enums import Action, MoveType, SubAction
from convint.domain.gate import Decision
from convint.domain.sufficiency import SufficiencyComponents


def _d(action=Action.FOLLOW_UP, sub=SubAction.DEEPEN):
    return Decision(action=action, sub_action=sub, rule_fired="r", rationale="r")


def test_no_move_when_not_following_up():
    assert select_move(_d(Action.ADVANCE, SubAction.HANDOFF), SufficiencyComponents()) is None
    assert select_move(_d(Action.SYNTHESIZE, SubAction.HANDOFF), SufficiencyComponents()) is None


def test_move_targets_the_missing_component():
    assert select_move(_d(), SufficiencyComponents()) is MoveType.ASK_FOR_SCENE
    assert select_move(_d(), SufficiencyComponents(scene=True)) is MoveType.ASK_WHAT_WAS_AT_STAKE
    assert select_move(
        _d(), SufficiencyComponents(scene=True, stakes=True)
    ) is MoveType.ASK_WHAT_THEY_DID
    assert select_move(
        _d(), SufficiencyComponents(scene=True, stakes=True, action=True)
    ) is MoveType.ASK_WHAT_SURPRISED


def test_complete_episode_moves_to_reflection():
    full = SufficiencyComponents(scene=True, stakes=True, action=True, outcome=True)
    assert select_move(_d(), full) is MoveType.REFLECT_AND_CHECK


def test_redirect_asks_smaller_not_bigger():
    """A thin answer gets a concrete access point, never an abstract reframe."""
    assert select_move(_d(sub=SubAction.REDIRECT), SufficiencyComponents()) is MoveType.ASK_FOR_SCENE


def test_hold_reflects_rather_than_probing():
    assert select_move(_d(sub=SubAction.HOLD), SufficiencyComponents()) is MoveType.REFLECT_AND_CHECK


def test_exclusion_avoids_repeating_a_move():
    m = select_move(_d(), SufficiencyComponents(), exclude={MoveType.ASK_FOR_SCENE})
    assert m is not MoveType.ASK_FOR_SCENE


def test_cross_domain_move_offered_when_earlier_material_exists():
    full = SufficiencyComponents(scene=True, stakes=True, action=True, outcome=True, reflection=True)
    assert select_move(
        _d(), full, has_earlier_material=True, exclude={MoveType.REFLECT_AND_CHECK}
    ) is MoveType.CONTRAST_WITH_EARLIER


def test_always_returns_a_move_for_a_followup():
    full = SufficiencyComponents(scene=True, stakes=True, action=True, outcome=True, reflection=True)
    assert select_move(_d(), full) is not None
