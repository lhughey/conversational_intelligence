"""The turn-decision dataset and its evaluation."""

import pytest

from convint.bench import gate_eval
from convint.dataset.build import build, load
from convint.dataset.schema import Item, Label
from convint.domain.enums import Action


def test_build_produces_one_item_per_user_turn():
    items, labels = build()
    assert len(items) == len(labels) >= 90
    assert all(i.item_id == l.item_id for i, l in zip(items, labels))


def test_items_carry_the_state_the_gate_needs():
    items, _ = build()
    probe = items[0]
    for field in ("followups_used", "floor", "ceiling", "specificity", "ownership", "signal"):
        assert hasattr(probe, field)


def test_every_label_is_marked_weak():
    """No number from this set may be quoted as an accuracy without adjudication."""
    _, labels = build()
    assert {l.source for l in labels} == {"weak"}


def test_committed_dataset_matches_a_fresh_build():
    """Regenerating must be deterministic, or the committed file is a fiction."""
    built_items, built_labels = build()
    loaded_items, loaded_labels = load()
    assert [i.item_id for i in built_items] == [i.item_id for i in loaded_items]
    assert [l.action for l in built_labels] == [l.action for l in loaded_labels]


def test_labels_cover_every_action_kind():
    _, labels = build()
    assert {l.action for l in labels} >= {
        Action.FOLLOW_UP, Action.ADVANCE, Action.SYNTHESIZE, Action.REFUSE_AND_CONTINUE
    }


def test_acceptable_set_scoring():
    label = Label(item_id="x", action=Action.FOLLOW_UP, acceptable=[Action.ADVANCE])
    assert label.is_correct(Action.FOLLOW_UP)
    assert label.is_correct(Action.ADVANCE)
    assert not label.is_correct(Action.SYNTHESIZE)


def test_text_prefix_guards_against_fixture_drift():
    items, _ = build()
    assert all(i.text.startswith(i.text_prefix) for i in items)


# --- gate evaluation -------------------------------------------------------

def test_gate_eval_reports_both_failure_directions():
    result = gate_eval.run("corpus")
    for name, metrics in result.items():
        assert metrics["premature_advance_rate"] is not None, name
        assert metrics["stall_rate"] is not None, name


def test_degenerate_policies_are_exposed_by_the_metric_pair():
    """Neither failure rate means anything alone; together they catch both
    ways of gaming the benchmark."""
    result = gate_eval.run("corpus")
    assert result["always_follow_up"]["premature_advance_rate"] == 0.0
    assert result["always_follow_up"]["stall_rate"] == 1.0
    assert result["always_advance"]["premature_advance_rate"] == 1.0
    assert result["always_advance"]["stall_rate"] == 0.0


def test_gate_is_not_a_degenerate_policy_on_the_realistic_split():
    """On the weakly-labelled corpus the gate must sit between the extremes
    rather than collapsing onto one of them."""
    gate = gate_eval.run("corpus")["gate"]
    assert 0.0 < gate["premature_advance_rate"] < 1.0
    assert 0.0 < gate["stall_rate"] < 1.0
    assert gate["accuracy_acceptable"] > 0.8


def test_gate_conforms_exactly_on_the_spec_labelled_split():
    """Different split, different claim: on spec labels this is a CONFORMANCE
    check, and 100% is the expected result rather than evidence of quality."""
    gate = gate_eval.run("synth")["gate"]
    assert gate["accuracy_strict"] == 1.0
    assert gate["premature_advance_rate"] == 0.0
    assert gate["stall_rate"] == 0.0


def test_denominators_are_reported_so_small_n_is_visible():
    result = gate_eval.run("corpus")["gate"]
    assert result["premature_advance_n"] > 0
    assert result["stall_n"] > 0


# --- confidence intervals and end-to-end mode ------------------------------

def test_oracle_synth_numbers_are_unchanged():
    """Pinned to the pre-CI values: adding intervals must not move a rate."""
    result = gate_eval.run("synth")
    assert result["gate"]["accuracy_strict"] == 1.0
    assert result["gate"]["minimal_pair_accuracy"] == 1.0
    assert result["budget_only"]["accuracy_strict"] == pytest.approx(46 / 52)
    assert result["budget_only"]["stall_rate"] == pytest.approx(6 / 19)
    assert result["budget_only"]["minimal_pair_accuracy"] == 0.0
    assert result["length_threshold"]["premature_advance_rate"] == pytest.approx(10 / 33)
    assert result["gate"]["premature_advance_n"] == 33
    assert result["gate"]["stall_n"] == 19
    assert result["gate"]["minimal_pair_n"] == 12


def test_every_rate_carries_a_ci_a_denominator_and_a_cluster_count():
    for split in ("synth", "corpus"):
        for name, m in gate_eval.run(split).items():
            for metric in ("accuracy_strict", "accuracy_acceptable",
                           "premature_advance_rate", "stall_rate", "minimal_pair_accuracy"):
                assert f"{metric}_n" in m and f"{metric}_k" in m, (split, name, metric)
                ci = m[f"{metric}_ci"]
                if m[metric] is None:
                    assert ci is None
                elif ci is not None:
                    assert ci[0] <= m[metric] <= ci[1], (split, name, metric)


def test_cluster_keys_keep_minimal_pairs_together_and_corpus_by_transcript():
    from convint.dataset.synth import build_from_banks, minimal_pairs

    items, labels = build_from_banks()
    by_id = {i.item_id: i for i in items}
    for a, b in minimal_pairs(items, labels):
        assert gate_eval.cluster_key(by_id[a]) == gate_eval.cluster_key(by_id[b])
    assert len({gate_eval.cluster_key(i) for i in items}) > 1

    corpus_items, _ = build()
    assert {gate_eval.cluster_key(i) for i in corpus_items} == {i.transcript for i in corpus_items}
    assert gate_eval.run("corpus")["gate"]["clusters"] == len({i.transcript for i in corpus_items})


def test_e2e_mode_adds_a_row_beside_the_oracle_and_leaves_the_rest_alone():
    from convint.adapters.assessor_deterministic import DeterministicAssessor

    oracle = gate_eval.run("synth")
    both = gate_eval.run("synth", e2e_assessor=DeterministicAssessor())
    e2e = gate_eval.e2e_key("deterministic")
    assert e2e in both and "gate" in both
    assert set(both) == set(oracle) | {e2e}
    for name in oracle:
        assert both[name] == oracle[name], name
    row = both[e2e]
    assert row["n"] == oracle["gate"]["n"]
    assert 0.0 <= row["accuracy_strict"] <= 1.0
    assert 0.0 <= row["assessor_specificity_agreement"] <= 1.0


def test_e2e_policy_uses_the_assessor_not_the_authored_inputs():
    """An assessor that always says 'rich, owned episode' must make the gate
    advance once the floor is met, whatever the item was authored as."""
    from convint.domain.enums import Ownership, Specificity
    from convint.domain.sufficiency import Assessment

    class Generous:
        name = "generous"

        def assess(self, text, prior):
            return Assessment(specificity=Specificity.S3, ownership=Ownership.O2)

    item = Item(item_id="x", transcript="bank:t", turn_index=0, text="meh",
                followups_used=1, specificity=Specificity.S0, ownership=Ownership.O0)
    assert gate_eval.gate_policy(item) is Action.FOLLOW_UP
    assert gate_eval.E2EGatePolicy(Generous())(item) is Action.ADVANCE


def test_e2e_is_refused_off_the_synth_split():
    from convint.adapters.assessor_deterministic import DeterministicAssessor

    with pytest.raises(ValueError):
        gate_eval.run("corpus", e2e_assessor=DeterministicAssessor())


def test_make_assessor_parses_specs_without_calling_anything():
    assert gate_eval.make_assessor("deterministic").name == "deterministic"
    for bad in ("", "llm", "llm:", "gpt:haiku-4-5"):
        with pytest.raises(ValueError):
            gate_eval.make_assessor(bad)


def test_bench_gate_e2e_cli_prints_both_rows(capsys):
    from convint.api.cli import main as cli_main

    assert cli_main(["bench", "--gate", "--split", "synth", "--e2e"]) == 0
    out = capsys.readouterr().out
    assert "gate (oracle inputs)" in out
    assert "gate (e2e: deterministic)" in out
    assert "k=4 topics" in out
    with pytest.raises(SystemExit):
        cli_main(["bench", "--gate", "--split", "corpus", "--e2e"])
