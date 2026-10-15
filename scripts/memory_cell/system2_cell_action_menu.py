"""Post-seal ceiling for one frozen Qwen action menu on exact synthetic sources.

No neural calls. Every archived Reader attempt was paid in its original run.
A hindsight oracle is diagnostic only; it may NOT be used to choose actions
online or sold as a trained Cell. A closed-grammar symbolic parser is a control.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import time

from system2_cell_support_gate import (
    ABSTAIN,
    EVAL_POSITIONS,
    PINS,
    prepare,
    sha,
    write,
)

SCHEMA = "hepta.system2.cell-menu-ceiling.v1"
VIEWS = ("e_label", "neutral_alias", "unlabeled")
SUPPORTED_ARMS = ("target_decoy_first", "target_decoy_last")
NEGATIVE_ARMS = ("decoy_only", "no_evidence")
READER_POSITIONS = 200
QUESTION_IDS = 20
SUPPORTED_POSITIONS = 120
NEGATIVE_POSITIONS = 80


def visible(row):
    """Construct the online-visible state WITHOUT target, Reader output or cost."""
    if (row["arm"], row["view"]) not in EVAL_POSITIONS:
        raise ValueError("unregistered original action menu")
    facts = row["matched_facts"]
    if not isinstance(facts, list) or any(
        not isinstance(f, (tuple, list))
        or len(f) != 2
        or not all(isinstance(x, str) for x in f)
        for f in facts
    ):
        raise ValueError("bad exact source relations")
    return dict(
        qid=row["qid"],
        arm=row["arm"],
        view=row["view"],
        question_device=row["question_device"],
        matched_facts=tuple(tuple(f) for f in facts),
        sources=row["sources"],
    )


def static_action(state):
    """Frozen parse, NOT a learned general-language inference or online oracle."""
    if set(state) != {
        "qid",
        "arm",
        "view",
        "question_device",
        "matched_facts",
        "sources",
    }:
        raise ValueError("privileged or incomplete online observation")
    hits = [
        token
        for device, token in state["matched_facts"]
        if device == state["question_device"]
    ]
    if len(hits) > 1:
        raise ValueError("ambiguous factual support")
    return dict(
        qid=state["qid"],
        arm=state["arm"],
        view=state["view"],
        frozen_source_match=bool(hits),
        closed_grammar_response=hits[0] if hits else ABSTAIN,
        choice_frozen_before_scoring=True,
    )


def _index(rows):
    result = {}
    for r in rows:
        key = r["qid"], r["arm"], r["view"]
        if key in result:
            raise ValueError("duplicate archived question/arm/view")
        result[key] = r
    if (
        len(result) != READER_POSITIONS
        or len({k[0] for k in result}) != QUESTION_IDS
        or {k[1:] for k in result} != set(EVAL_POSITIONS)
    ):
        raise ValueError("unexpected immutable evaluation census")
    ids = {key[0] for key in result}
    if set(result) != {(qid, arm, view) for qid in ids for arm, view in EVAL_POSITIONS}:
        raise ValueError("missing registered view or task")
    if sum(bool(r["support"]) for r in rows) != SUPPORTED_POSITIONS:
        raise ValueError("unexpected support census")
    return result


def review(rows, actions):
    """Every best action here is a POST-SEAL perfect-information diagnostic."""
    by_key = _index(rows)
    action_index = {}
    for action in actions:
        key = action["qid"], action["arm"], action["view"]
        if key in action_index:
            raise ValueError("duplicated frozen action")
        if key not in by_key or action != static_action(visible(by_key[key])):
            raise ValueError("changed or privileged frozen action")
        action_index[key] = action
    if len(actions) != READER_POSITIONS or set(action_index) != set(by_key):
        raise ValueError("incomplete frozen action census")
    actual_call = always_call = always_stop = fixed = oracle = symbolic = 0
    costs_all = costs_gate = 0
    per_position = []
    for key, row in by_key.items():
        act = action_index[key]
        support = bool(row["support"])
        if support != act["frozen_source_match"]:
            raise ValueError("disagreement in exact source support")
        answer = row["reader_answer"].strip()
        if not answer:
            raise ValueError("blank archived neural output")
        cpu = row["reader_cost_ns"]
        if not isinstance(cpu, int) or isinstance(cpu, bool) or cpu < 0:
            raise ValueError("unknown original paid decoder work")
        correct_call = answer == (row["target"] if support else ABSTAIN)
        correct_stop = not support
        frozen_score = correct_call if act["frozen_source_match"] else correct_stop
        oracle_score = correct_call or correct_stop
        symbolic_score = act["closed_grammar_response"] == (
            row["target"] if support else ABSTAIN
        )
        actual_call += int(act["frozen_source_match"])
        always_call += int(correct_call)
        always_stop += int(correct_stop)
        fixed += int(frozen_score)
        oracle += int(oracle_score)
        symbolic += int(symbolic_score)
        costs_all += cpu
        costs_gate += cpu if act["frozen_source_match"] else 0
        per_position.append(
            dict(
                qid=key[0],
                arm=key[1],
                view=key[2],
                paid_cpu_ns=cpu,
                original_neural_exact=correct_call,
                externally_abstain_correct=correct_stop,
                frozen_call_or_abstain_correct=frozen_score,
                hindsight_best_call_or_abstain=oracle_score,
                closed_grammar_symbolic_correct=symbolic_score,
            )
        )
    if fixed != oracle:
        raise ValueError("unsupported incremental call/stop headroom claim")
    if actual_call != SUPPORTED_POSITIONS or always_stop != NEGATIVE_POSITIONS:
        raise ValueError("unexpected callable source census")
    by_qid_arm = {}
    for key, row in by_key.items():
        qid, arm, view = key
        if arm in SUPPORTED_ARMS:
            by_qid_arm.setdefault((qid, arm), {})[view] = row
    if len(by_qid_arm) != QUESTION_IDS * len(SUPPORTED_ARMS):
        raise ValueError("missing positive order cases")
    view_cases = []
    for (qid, arm), options in sorted(by_qid_arm.items()):
        if set(options) != set(VIEWS):
            raise ValueError("incomplete three-view menu")
        targets = {row["target"] for row in options.values()}
        if len(targets) != 1 or not all(row["support"] for row in options.values()):
            raise ValueError("changed source fact or target across renderings")
        target = next(iter(targets))
        hit = {view: options[view]["reader_answer"].strip() == target for view in VIEWS}
        fixed_view = hit["unlabeled"]
        hindsight_any = any(hit.values())
        view_cases.append(
            dict(
                qid=qid,
                arm=arm,
                views_exact=hit,
                unlabeled_correct=fixed_view,
                hindsight_any_view_correct=hindsight_any,
                hindsight_complements_unlabeled=hindsight_any and not fixed_view,
                unlabeled_historical_decoder_cpu_ns=options["unlabeled"][
                    "reader_cost_ns"
                ],
                all_three_views_historical_decoder_cpu_ns=sum(
                    options[v]["reader_cost_ns"] for v in VIEWS
                ),
            )
        )
    frozen_view_correct = sum(c["unlabeled_correct"] for c in view_cases)
    hindsight_view_correct = sum(c["hindsight_any_view_correct"] for c in view_cases)
    menu_headroom = hindsight_view_correct - frozen_view_correct
    if menu_headroom < 0 or menu_headroom > len(view_cases) - frozen_view_correct:
        raise ValueError("invalid perfect-information view ceiling")
    return dict(
        schema=SCHEMA,
        original_paid_inference_calls=READER_POSITIONS,
        original_archived_decoder_cpu_ns=costs_all,
        reader_calls_simulated_by_frozen_gate=actual_call,
        posthoc_gate_selected_archived_cpu_ns=costs_gate,
        hypothetical_avoided_decoder_cpu_ns=costs_all - costs_gate,
        actually_saved_decoder_cpu_ns=0,
        always_call_correct=always_call,
        always_abstain_correct=always_stop,
        frozen_source_match_correct=fixed,
        perfect_information_call_stop_ceiling=oracle,
        learned_gate_action_menu_headroom=oracle - fixed,
        closed_grammar_symbolic_correct=symbolic,
        closed_grammar_symbolic_uses_no_reader=True,
        positive_order_cases=len(view_cases),
        fixed_unlabeled_positive_correct=frozen_view_correct,
        postseal_any_of_three_views_correct=hindsight_view_correct,
        postseal_view_menu_headroom=menu_headroom,
        positive_view_extractions=view_cases,
        source_action_receipts=per_position,
        postseal_view_oracle_was_never_an_online_action=True,
        all_historical_view_inferences_paid=True,
        source_tasks_are_exposed_correlated_synthetic=True,
        independent_human_semantic_evidence=False,
        production_accepted=False,
        general_ndu_fbsde_gain=False,
    )


def run(archives, output, *, source_commit):
    if not re.fullmatch("[0-9a-f]{40}", source_commit or ""):
        raise ValueError("generating Git commit required")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write(
        output / "plan.json",
        dict(
            schema=SCHEMA,
            source_commit=source_commit,
            source_archive_sha256={k: p["sha"] for k, p in PINS.items()},
            registered_positions=READER_POSITIONS,
            distinct_questions=QUESTION_IDS,
            offline_oracle_used_only_after_prediction_seal=True,
            cost_is_original_paid_archived_decoder_cpu=True,
            reader_calls_this_run=0,
            source_is_synthetic=True,
            production_accepted=False,
        ),
    )
    started = time.process_time_ns()
    try:
        snapshots, train, held = prepare(archives)
        if len(train) != 180 or len(held) != READER_POSITIONS:
            raise ValueError("source training/evaluation census drift")
        _index(held)
        actions = [static_action(visible(row)) for row in held]
        with (output / "frozen-actions.jsonl").open("x", encoding="utf8") as stream:
            for action in actions:
                stream.write(json.dumps(action, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        raw = (output / "frozen-actions.jsonl").read_bytes()
        seal = dict(sha256=sha(raw), rows=len(actions), scoring_started=False)
        write(output / "action-seal.json", seal)
        result = review(held, actions)
        if sha((output / "frozen-actions.jsonl").read_bytes()) != seal["sha256"]:
            raise ValueError("scoring changed original frozen actions")
        result.update(
            source_commit=source_commit,
            completed_archives={
                k: dict(sha256=x["sha"], verified_manifest_files=x["files"])
                for k, x in snapshots.items()
            },
            frozen_actions_sha256=seal["sha256"],
            training_contexts_reused=len(train),
            true_new_model_calls=0,
            original_archived_reader_answers_reused=len(held),
            processing_cpu_ns=time.process_time_ns() - started,
            candidate_disposition="stop_binary_head_no_action_menu_headroom",
        )
        write(output / "summary.json", result)
        return result
    except BaseException as error:
        write(
            output / "failure.json",
            dict(
                error_type=type(error).__name__,
                error=str(error)[:512],
                incomplete=True,
                unknown_work_not_free=True,
            ),
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lexical_320", type=Path)
    parser.add_argument("tag_180", type=Path)
    parser.add_argument("equal_token_200", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = run(
        dict(
            train_lexical=args.lexical_320,
            train_label=args.tag_180,
            eval_placebo=args.equal_token_200,
        ),
        args.output,
        source_commit=os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", ""),
    )
    print(
        json.dumps(
            dict(
                source=result["source_commit"],
                binary_action_menu_ceiling=result[
                    "perfect_information_call_stop_ceiling"
                ],
                binary_frozen_correct=result["frozen_source_match_correct"],
                view_menu_headroom=result["postseal_view_menu_headroom"],
                closed_grammar_symbolic_correct=result[
                    "closed_grammar_symbolic_correct"
                ],
                original_model_calls=result["original_paid_inference_calls"],
                actual_new_model_calls=result["true_new_model_calls"],
            ),
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
