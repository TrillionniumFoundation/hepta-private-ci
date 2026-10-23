"""Recount the genuinely retained LoCoMo A/D-like evidence, without relabeling it.

The physical source-retrieval experiment is already in PR #3125. This program
audits its frozen journal identities and emits a gap census; it does not rerun
a Reader, train a Head, or claim a complete prospective A-I experiment.
"""
import json
from pathlib import Path

from memory_nine_arm_gate import ARMS, Refused, require, sha

EVIDENCE_DIR = Path(__file__).parent / "evidence" / "20261022-locomo-memory-retrieval"
CODE_DIR = Path(__file__).parent


def recount(directory=EVIDENCE_DIR, code_dir=CODE_DIR):
    directory, code_dir = Path(directory), Path(code_dir)
    raw = {name: (directory / name).read_bytes()
           for name in ("plan.json", "selection.json", "report.json")}
    p, s, r = (json.loads(raw[name])
               for name in ("plan.json", "selection.json", "report.json"))
    require(p["schema"] == "hepta.locomo-source-retrieval-plan.v1"
            and p["source_sha256"]
            == "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4",
            "wrong original LoCoMo task")
    require(p["arms"] == ["bm25_turn", "bm25_turn_session",
                         "episodic_context", "episodic_meta"],
            "not original four-arm retrieval")
    require(sha(raw["plan.json"]) == s["plan_sha256"] == r["plan_sha256"],
            "original source-first plan hash drift")
    require(sha(raw["selection.json"]) == r["selection_sha256"],
            "original selected configuration hash drift")
    require(p["created_unix_ns"] < s["frozen_unix_ns"]
            and s["evaluation_rows_read_for_selection"] == 0,
            "original development/calibration chronology failed")
    for name, original_digest in p["code_sha256"].items():
        require(name in {"memory_retrieval_probe.py", "memory_retrieval_data.py",
                         "memory_retrieval_scoring.py"}, "unknown producer script")
        require(sha((code_dir / name).read_bytes()) == original_digest,
                "original producer source modified")
    require(len(p["partitions"]["evaluation"]) == 6 and p["questions"] == 1986,
            "original source family/question census drift")
    require(r["boundaries"]["memory_task"] is True
            and r["boundaries"]["answer_correctness_measured"] is False
            and r["boundaries"]["semantic_citation_entailment_measured"] is False
            and r["boundaries"]["fresh_future_calendar_windows"] is False
            and r["boundaries"]["source_independence_authenticated"] is False
            and r["boundaries"]["superiority_established"] is False
            and r["boundaries"]["production_activation_allowed"] is False
            and r["boundaries"]["llm_calls"] == 0
            and r["boundaries"]["gradient_updates"] == 0
            and r["boundaries"]["authority"] == "DENY_ALL",
            "retrieval-only evidence relabeled as memory QA")
    results = r["results"]["evaluation"]
    lexical = results["bm25_turn_session"]["overall"]
    typed = results["episodic_context"]["overall"]
    for x in (lexical, typed):
        require(x["planned_questions"] == 1331
                and x["scorable_support_questions"] == 1022
                and x["adversarial_questions"] == 299
                and x["unresolved_or_missing_questions"] == 10,
                "original negative/unknown census altered")
        require(x["answerability_balanced_accuracy"] == .5,
                "adversarial failure silently repaired")
    pair = r["paired_evaluation"]["episodic_minus_strong_sparse"]
    delta = typed["group_macro_all_support"] - lexical["group_macro_all_support"]
    require(abs(delta - pair["group_macro_difference"]) < 1e-12
            and pair["groups"] == 6 and pair["low_power"] is True
            and pair["multiple_comparison_adjusted"] is False
            and pair["population_independence_authenticated"] is False
            and pair["superiority_established"] is False,
            "original paired low-power result changed")
    lexical_hop = results["bm25_turn_session"]["by_category"]["1"]["overall"]
    typed_hop = results["episodic_context"]["by_category"]["1"]["overall"]
    multi_hop_delta = (typed_hop["all_support_recalled"]
                       - lexical_hop["all_support_recalled"])
    require(multi_hop_delta < 0, "original multi-hop regression hidden")
    return {
        "schema": "hepta.memory.a-i.original-evidence-crosswalk.v1",
        "original_plan_sha256": sha(raw["plan.json"]),
        "original_report_sha256": sha(raw["report.json"]),
        "original_source_sha256": p["source_sha256"],
        "evidence_scope": "six historical LoCoMo dialogues; support retrieval only",
        "observed_subset": {
            "A": {"implementation": "BM25 turn+session lexical (stronger A control)",
                  "group_macro_all_support": lexical["group_macro_all_support"]},
            "D": {"implementation": "untrained episodic typed organization",
                  "group_macro_all_support": typed["group_macro_all_support"]},
        },
        "A_to_D_group_macro_support_delta": delta,
        "multi_hop_all_support_regression": multi_hop_delta,
        "adversarial_questions_accepted": 299,
        "other_arms": {arm: "NOT_RUN_ON_SAME_MEMORY_COHORT"
                       for arm in ARMS if arm not in ("A", "D")},
        "reader_answers_generated": 0,
        "nine_arm_original_answer_census_closed": False,
        "prospective_future_windows": 0,
        "authenticated_independent_source_families": 0,
        "production_accepted": False,
        "superiority_established": False,
        "status": "HOLD_NO_GO",
    }


if __name__ == "__main__":
    print(json.dumps(recount(), sort_keys=True, indent=2))
