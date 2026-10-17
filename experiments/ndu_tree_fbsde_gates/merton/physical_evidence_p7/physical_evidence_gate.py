"""Independent P7 P5-original physical evidence check; research-only DENY_ALL.

Runs without importing original Qwen worker, P1 optimizer, P5 reviewer, P6
planner, or model weights. It can recompute what original trace metadata proves,
not authenticate GitHub hosts, infer unseen counterfactuals or certify causality.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from collections import Counter
from fractions import Fraction
from pathlib import Path

RUN_ID = 39000773484
ORIGINAL_SHA = "ded66a28c186a8963c7781df3f091968758791e3"
POSTURE = "RESEARCH_ONLY_DENY_ALL"
SCHEMA = "hepta.ndu-merton.p7.original-physical-raw-voi-gate.v1"
BASE = "hepta.ndu-merton.p5.original-balanced-and-declared-parser.v1"
SOURCE_SCHEMA = "hepta.ndu-merton.p5.class-balanced-agnews-source.v1"
WEIGHTS_SHA256 = "f47f71177f32bcd101b7573ec9171e6a57f4f4d31148d38e382306f42996874b"
TOKENIZER_SHA256 = "aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4"
POLICIES = ("direct", "fixed_reason", "greedy", "neutral", "fixed_risk", "ndu_discrete", "ordinary_same_profile")
ACTIONS = ("direct", "reason", "verify")

# SHA-256 of the *uncompressed* immutable files, distinct from ZIP hashes.
PINNED_SHA256 = {
    "train-public.json": "580d078fc173fd9e3d7c35bca0a8eec874586f2a53b7a901838ff3362a92d3ab",
    "held-public.json": "9b6da146af00c54c607277cfccd452e9bc2e04a912638c1954f2f9452c6ddc55",
    "held-private-labels.json": "4e126e349252fe8bb04506006d32e2c89db8677058881ac4b718ca6863c02202",
    "completed-original.json": "666f95832f8338d8c44e012bdf85a0c08b811ad250df7bfa037e8ba0e0017c15",
    "frozen-plan.json": "0b7fd6635a802d643d48d8174301d8cbfe1ebbb83c588c7a37e4353dd9f88245",
    "original-starts-and-dones.jsonl": "5fde8256c696cab3b73e480279f7a6243ea1f3afb858ea4f22abfcbebbcf0862",
    "hepta-p5-sanitized-review.json": "45d5ac14634250763249e884adbb17762804d90dc444a153a746538ba5df6c26",
}
REQUIRED = tuple(PINNED_SHA256)
RE_ANSWER = re.compile(r"\s*(?:FINAL\s*[:=]\s*)?(?:([0-3])|<([0-3])>)\s*", re.I | re.ASCII)
RE_SHA = re.compile(r"[a-f0-9]{64}\Z")


class EvidenceError(ValueError):
    pass


def insist(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(obj) -> bytes:
    try:
        return json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise EvidenceError("nonfinite or non-JSON evidence") from exc


def digest(obj) -> str:
    return sha(canonical(obj))


def unique(pairs):
    result = {}
    for key, val in pairs:
        insist(key not in result, "duplicate JSON property")
        result[key] = val
    return result


def decode(raw: bytes):
    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                      parse_constant=lambda k: (_ for _ in ()).throw(EvidenceError("nonfinite " + k)))


def parse_answer(answer: str):
    insist(isinstance(answer, str), "answer must be text")
    match = RE_ANSWER.fullmatch(answer)
    return int(match.group(1) or match.group(2)) if match else None


def read_evidence(paths: dict[str, Path], expected: dict[str, str] = PINNED_SHA256):
    insist(set(paths) == set(REQUIRED), "missing or unexpected evidence file")
    insist(set(expected) == set(REQUIRED), "incomplete source digests")
    documents = {}
    for name in REQUIRED:
        raw = paths[name].read_bytes()
        insist(sha(raw) == expected[name], "original file digest mismatch: " + name)
        if name.endswith(".jsonl"):
            insist(raw.endswith(b"\n"), "journal truncated")
            documents[name] = [decode(row) for row in raw.splitlines()]
        else:
            documents[name] = decode(raw)
    return documents


def validate_source(train: dict, held: dict, gold: dict):
    for name, obj, schema in (("train", train, SOURCE_SCHEMA + ".train"),
                              ("held", held, SOURCE_SCHEMA + ".held-public"),
                              ("gold", gold, SOURCE_SCHEMA + ".held-private-labels")):
        insist(type(obj) is dict and obj.get("schema") == schema, "wrong source schema: " + name)
        insist(type(obj.get("rows")) is list and len(obj["rows"]) == 16, "wrong source census: " + name)
        insist(obj.get("source") == train.get("source"), "source provenance mismatch")
    source = train["source"]
    insist(source["publisher_future_window"] is False and source["independent_source_families"] is False,
           "unjustified prospective or family independence claim")
    insist(source["split_rule"] == "first-per-original-publisher-class-bucket-index-parity", "source policy drift")
    insist(source["bucket_rule"] == "short_if_unicode_length_le_180", "length bucket drift")
    insist(source["repo"] == "szhuggingface/ag_news" and len(source["revision"]) == 40, "publisher drift")

    def keyed(obj, split, text):
        result = {}
        for row in obj["rows"]:
            insist(type(row) is dict and type(row.get("task_id")) is str,
                   "invalid source row")
            task_id = row["task_id"]
            insist(bool(re.fullmatch(fr"{split}-[0-9]{{5}}", task_id)) and task_id not in result,
                   "duplicate or malformed source identity")
            assert_sha(row.get("text_sha256"))
            if text:
                insist(type(row.get("text")) is str and len(row["text"]) > 0,
                       "missing original source text")
                insist(sha(row["text"].encode("utf-8")) == row["text_sha256"], "text source identity drift")
                insist(row.get("bucket") == ("short" if len(row["text"]) <= 180 else "long"),
                       "incorrect original observable length bucket")
                insist(row.get("group") == split + "-row-parity-" + str(int(task_id[-5:]) % 2),
                       "original index parity mismatch")
            else:
                insist("text" not in row and "bucket" not in row and "group" not in row,
                       "secret labels or source fields misplaced")
            result[task_id] = row
        return result

    t, h, g = keyed(train, "train", True), keyed(held, "held", True), keyed(gold, "held", False)
    insist(set(h) == set(g) and set(t).isdisjoint(h), "split or label mismatch")
    insist({x["text_sha256"] for x in t.values()}.isdisjoint({x["text_sha256"] for x in h.values()}),
           "train/held text overlap")
    for ident in h:
        insist("label" not in h[ident], "held labels leaked into public features")
        insist(g[ident]["text_sha256"] == h[ident]["text_sha256"], "gold-source mismatch")
    for r in (*t.values(), *g.values()):
        insist(type(r.get("label")) is int and r["label"] in range(4), "invalid original publisher label")
    insist(Counter(row["label"] for row in t.values()) == Counter({0:4,1:4,2:4,3:4}),
           "unbalanced train publisher labels")
    insist(Counter(row["label"] for row in g.values()) == Counter({0:4,1:4,2:4,3:4}),
           "unbalanced held publisher labels")
    return t, h, g


def assert_sha(value):
    insist(type(value) is str and RE_SHA.fullmatch(value) is not None, "invalid sha256")


def validate_model_row(row, eligible_ids, stage, expected_action=None, expected_policy=None):
    insist(type(row) is dict and row.get("source_kind") == "original_physical", "not original model evidence")
    for name in ("answer_sha256", "output_token_ids_sha256", "input_token_ids_sha256", "prompt_sha256"):
        assert_sha(row.get(name))
    insist(row.get("task_id") in eligible_ids, "out of population original invocation")
    action, policy = row.get("action"), row.get("policy")
    insist(action in (*ACTIONS, "reason_equalcap") and type(policy) is str, "unregistered model action")
    if expected_action is not None:
        insist(action == expected_action, "sealed original action was replaced")
    if expected_policy is not None:
        insist(policy == expected_policy, "sealed original policy was replaced")
    if stage == "train":
        insist(action in ACTIONS and policy == "train", "train policy mismatch")
    if stage == "held":
        insist(policy in POLICIES and action in ACTIONS, "held policy mismatch")
    if stage == "contrast":
        insist(policy == "equal_cap" and action in ("reason", "reason_equalcap"), "contrast policy mismatch")
    insist(type(row.get("input_tokens")) is int and 0 < row["input_tokens"] <= 50000,
           "invalid measured input-token count")
    insist(type(row.get("output_tokens")) is int and 0 < row["output_tokens"] <= 96,
           "invalid measured output-token count")
    insist(type(row.get("sampling_seed")) is int and row["sampling_seed"] >= 0,
           "invalid original seed")
    for axis in ("measured_cpu_seconds", "measured_wall_seconds"):
        metric = row.get(axis)
        insist(type(metric) in (int, float) and math.isfinite(metric) and 0 < metric < 3600,
               "invalid physical-cost meter")
    thinking = action == "reason"
    insist(type(row.get("thinking_mode")) is bool and row["thinking_mode"] == thinking,
           "thinking flag contradicts original action")
    insist(type(row.get("thinking_complete")) is bool, "invalid thinking closure")
    insist(type(row.get("thinking_segment_tokens")) is int
           and 0 <= row["thinking_segment_tokens"] <= row["output_tokens"],
           "invalid thinking-token meter")
    if not thinking:
        insist(row["thinking_segment_tokens"] == 0, "no-thinking mode invented thinking tokens")
    if thinking and not row["thinking_complete"]:
        insist(row["answer"] == "" and row["predicted_class"] is None,
               "truncated thinking masquerades as final answer")
    parsed = parse_answer(row["answer"])
    insist(sha(row["answer"].encode("utf-8")) == row["answer_sha256"], "raw answer hash mismatch")
    insist(parsed == row.get("predicted_class") and (parsed is None or type(row["predicted_class"]) is int),
           "answer-class grammar mismatch")
    return parsed


def validate_journal(journal, traces, plan):
    insist(type(journal) is list and len(journal) == 385, "truncated/expanded original start/done history")
    train, online, contrast = traces
    expected = [("train", row) for row in train]
    for case in plan["public_record"]["cases"]:
        task = case["task_id"]
        expected.extend(("held", row) for row in online if row["task_id"] == task)
        expected.extend(("contrast", row) for row in contrast if row["task_id"] == task)
    insist(len(expected) == 192, "not all physical model calls represented")
    cursor = 0
    for idx, (stage, trace) in enumerate(expected):
        if idx == 48:
            insist(journal[cursor].get("event") == "plan_frozen" and
                   journal[cursor].get("sha256") == digest(plan),
                   "missing pre-held sealed-plan boundary")
            cursor += 1
        for ev in ("start", "done"):
            row = journal[cursor]
            insist(row.get("event") == ev and row.get("stage") == stage
                   and row.get("action") == trace["action"]
                   and row.get("task_id") == trace["task_id"],
                   "original journal order/membership mismatch")
            if stage != "train":
                insist(row.get("policy") == trace["policy"]
                       and row.get("plan_sha256") == digest(plan),
                       "journal plan/policy mismatch")
            if ev == "done":
                insist(row.get("output_sha256") == digest(trace),
                       "original done-record digest mismatch")
            cursor += 1
    insist(cursor == len(journal), "unaccounted original journal entries")


def verify_portfolio_plan(plan, train, held, completed):
    insist(plan.get("schema") == BASE + ".frozen-plan", "frozen plan schema mismatch")
    insist(completed.get("frozen_plan_sha256") == digest(plan), "original generation predates/differs from plan")
    insist(plan.get("train_source_sha256") == digest(train)
           and plan.get("held_public_sha256") == digest(held), "sealed public source mismatch")
    insist(plan.get("train_original_outputs_sha256") == digest(completed["original_train_trace"])
           and completed.get("train_original_sha256") == digest(completed["original_train_trace"]),
           "TRAIN model trace mismatch")
    attempt = plan.get("portfolio_attempt")
    insist(type(attempt) is dict and digest(attempt.get("attempt")) == attempt.get("seal_sha256"),
           "sealed portfolio decision mismatch")
    policies = attempt["attempt"]["policies"]
    insist(tuple(p["policy"] for p in policies) == POLICIES, "policy inventory drift")
    expected = {}
    for p in policies:
        assignments = p.get("assignments")
        insist(type(assignments) is dict and set(assignments) == {r["task_id"] for r in held["rows"]},
               "missing original policy task assignment")
        for task_id, action in assignments.items():
            insist(action in ACTIONS, "illegal sealed action")
            expected[(task_id, p["policy"])] = action
    return expected


def close_match(value, reported, name):
    insist(type(reported) in (float, int) and abs(value-reported) <= 1e-5*max(1,abs(value)),
           "independent physical cost mismatch: " + name)


def audit(doc: dict):
    insist(set(doc) == set(REQUIRED), "evidence schema mismatch")
    train, held, gold = (doc[k] for k in ("train-public.json", "held-public.json", "held-private-labels.json"))
    completed, plan, journal, review = (doc[k] for k in ("completed-original.json", "frozen-plan.json",
                                                 "original-starts-and-dones.jsonl", "hepta-p5-sanitized-review.json"))
    t, h, g = validate_source(train, held, gold)
    insist(completed.get("schema") == BASE + ".completed-original", "original execution schema drift")
    insist(review.get("schema") == BASE + ".postseal-review", "original independent review schema drift")
    insist(completed.get("authority") == POSTURE and review.get("authority") == POSTURE,
           "authority posture drift")
    insist(completed.get("original_pretrained_reader_execution") is True
           and completed.get("independent_model_execution_attestation") is False
           and completed.get("prospective_source_windows") == 0
           and completed.get("actual_model_savings_verified") is False,
           "fabricated production/pretraining/effect evidence")
    insist(review.get("independent_hardware_attestation") is False
           and review.get("actual_model_savings_proven") is False
           and review.get("historical_public_test_set_not_future_window") is True,
           "review falsely asserts independent physical savings")
    identity = completed["physical_model_identity"]
    insist(identity == review["model_identity"] == plan["reader"], "model evidence identity split")
    insist(identity.get("weights_sha256") == WEIGHTS_SHA256
           and identity.get("tokenizer_sha256") == TOKENIZER_SHA256
           and identity.get("repo") == "Qwen/Qwen3-0.6B"
           and identity.get("revision") == "16706fc57485378d4ffaf54139b29ccc66ae08fa",
           "original Qwen3 checkpoint identity drift")
    for field, src in (("original_publisher_gold_sha256", gold),
                       ("completed_original_sha256", completed),
                       ("frozen_plan_sha256", plan)):
        insist(review.get(field) == digest(src), "P5 independent reviewer mismatches raw origin")
    expected = verify_portfolio_plan(plan, train, held, completed)
    tr = completed["original_train_trace"]
    online = completed["actual_policy_trace"]
    contrast = completed["paired_equalcap_trace"]
    insist(len(tr) == 48 and len(online) == 112 and len(contrast) == 32
           and completed.get("total_generation_invocations") == 192
           and completed.get("actual_training_requests") == 48
           and completed.get("actual_online_policy_requests") == 112
           and completed.get("actual_equalcap_contrast_requests") == 32,
           "incomplete original model forward census")
    train_calls, online_calls, contrast_calls = set(), set(), set()
    derived_train = []
    for call in tr:
        pred = validate_model_row(call,t,"train")
        k=(call["task_id"],call["action"])
        insist(k not in train_calls,"replayed duplicate train action")
        train_calls.add(k)
        derived_train.append({"task_id":call["task_id"],"action":call["action"],
                              "group":t[call["task_id"]]["group"],"bucket":t[call["task_id"]]["bucket"],
                              "success":int(pred==t[call["task_id"]]["label"])})
    insist(train_calls == {(k, a) for k in t for a in ACTIONS}, "missing TRAIN physical call")
    insist(plan["train_record"]["rows"] == derived_train, "TRAIN forward output/labels changed after seal")
    insist(plan["public_record"]["cases"] ==
           [{"task_id":r["task_id"],"group":r["group"],"bucket":r["bucket"]} for r in held["rows"]],
           "public-only plan contains drifted/labeled held records")
    per_policy = {p: {} for p in POLICIES}
    for idx, call in enumerate(online):
        pred = validate_model_row(call,h,"held")
        k=(call["task_id"],call["policy"])
        insist(k not in online_calls and k in expected and call["action"] == expected[k],
               "unregistered / repeated original held policy action")
        online_calls.add(k)
        selected = plan["selected_request_schedule"][idx]
        insist(selected == {"task_id":call["task_id"], "action":call["action"],
                            "policy":call["policy"]}, "held execution order changed after seal")
        per_policy[call["policy"]][call["task_id"]] = (pred,call)
    insist(online_calls == set(expected), "original held policy suite incomplete")
    contrast_by_task = {k:{} for k in h}
    for idx, call in enumerate(contrast):
        pred=validate_model_row(call,h,"contrast")
        k=(call["task_id"],call["action"])
        insist(k not in contrast_calls and call["policy"] == "equal_cap", "replayed contrast action")
        contrast_calls.add(k)
        insist(plan["paired_equalcap_schedule"][idx] ==
               {"task_id":call["task_id"],"action":call["action"],"policy":"equal_cap"},
               "equal-cap scheduling drift")
        contrast_by_task[call["task_id"]][call["action"]] = (pred, call)
    insist(contrast_calls == {(k,a) for k in h for a in ("reason","reason_equalcap")},
           "missing 96/96 original paired comparison")
    for pair in contrast_by_task.values():
        reason=pair["reason"][1]; plain=pair["reason_equalcap"][1]
        insist(reason["prompt_sha256"] == plain["prompt_sha256"]
               and reason["sampling_seed"] == plain["sampling_seed"],
               "unequal original prompt or seed at equal-cap intervention")
        insist(reason["output_tokens"] <= 96 and plain["output_tokens"] <= 96,
               "unfair equal-generation-cap comparator")
    validate_journal(journal,(tr,online,contrast),plan)
    result_rows=[]
    correct={}
    costs={}
    per_task={}
    for policy in POLICIES:
        sequence=per_policy[policy]
        correct[policy] = sum(pred==g[k]["label"] for k,(pred,_call) in sequence.items())
        costs[policy]=sum(c["input_tokens"]+c["output_tokens"] for _,c in sequence.values())
        per_task[policy]={k:int(pred == g[k]["label"]) for k,(pred,_call) in sequence.items()}
        cpu=sum(c["measured_cpu_seconds"] for _,c in sequence.values())
        wall=sum(c["measured_wall_seconds"] for _,c in sequence.values())
        original=next((v for v in review["seven_policy_results"] if v["policy"]==policy),None)
        insist(original is not None and original.get("correct") == correct[policy]
               and original.get("of") == 16
               and original.get("actual_full_input_and_output_tokens") == costs[policy],
               "independent reviewer policy task/cost mismatch")
        close_match(cpu,original["actual_cpu_seconds"],policy+" CPU")
        close_match(wall,original["actual_wall_seconds"],policy+" wall")
        insist(Fraction(original["external_correct_minus_FULL_serving_token_tariff"])==
               Fraction(correct[policy]) - Fraction(costs[policy],2048),
               "external utility incorrectly accounts for full input/output tokens")
        wins=sum(per_task[policy][k] > per_task["direct"][k] for k in h) if policy!="direct" else 0
        losses=sum(per_task[policy][k] < per_task["direct"][k] for k in h) if policy!="direct" else 0
        # Reference policy should be the first processed row; direct is first.
        insist(original.get("task_rescues_against_direct") == wins
               and original.get("task_losses_against_direct") == losses,
               "paired taskwise claims changed")
        insist(original.get("actual_token_difference_vs_independently_executed_direct") ==
               costs[policy]-costs["direct"], "real token-delta accounting changed")
        result_rows.append({"policy":policy,"correct":correct[policy],"tasks":16,
                            "actual_input_output_tokens":costs[policy],
                            "actual_cpu_seconds":round(cpu,6),"actual_wall_seconds":round(wall,6),
                            "rescue_vs_direct":wins,"loss_vs_direct":losses,
                            "net_after_full_serving_token_tariff":str(Fraction(correct[policy])-Fraction(costs[policy],2048))})
    insist(set(x["policy"] for x in review["seven_policy_results"]) == set(POLICIES),
           "review policy inventory corrupted")
    insist(all(per_policy["ndu_discrete"][k][1]["action"] ==
               per_policy["ordinary_same_profile"][k][1]["action"] for k in h),
           "same-profile ordinary optimizer differs in selected control")
    wins=losses=neither=both=0
    groups={"reason":[],"reason_equalcap":[]}
    for k in h:
        a,b=contrast_by_task[k]["reason"],contrast_by_task[k]["reason_equalcap"]
        ac=int(a[0]==g[k]["label"]);bc=int(b[0]==g[k]["label"])
        wins+=int(ac>bc);losses+=int(ac<bc);both+=int(ac and bc);neither+=int(not ac and not bc)
        groups["reason"].append(a[1]);groups["reason_equalcap"].append(b[1])
    reviewer_contrast=review["paired_equalcap_96_token_contrast"]
    insist((wins,losses,both,neither)==tuple(reviewer_contrast[k] for k in
           ("taskwise_thinking_wins","taskwise_thinking_losses","taskwise_both_correct","taskwise_neither_correct")),
           "raw paired think/no-think scoring changed")
    for axis in ("reason","reason_equalcap"):
        metric=next((x for x in reviewer_contrast["thinking_mode_vs_equalcap_nonthinking"] if x["action"]==axis),None)
        rows=groups[axis]
        insist(metric is not None and metric["actual_independent_model_invocations"]==16
               and metric["correct"] == sum(int(c["predicted_class"]==g[c["task_id"]]["label"]) for c in rows)
               and metric["total_generated_tokens"] == sum(c["output_tokens"] for c in rows)
               and metric["total_input_tokens"] == sum(c["input_tokens"] for c in rows)
               and metric["total_thinking_tokens"] == sum(c["thinking_segment_tokens"] for c in rows)
               and metric["incomplete_thinking"] == sum(c["thinking_mode"] and not c["thinking_complete"] for c in rows),
               "independent equal-cap physical evidence mismatch")
        close_match(sum(c["measured_cpu_seconds"] for c in rows),metric["cpu_seconds"],axis+" CPU")
    close_match(sum(c["measured_cpu_seconds"] for c in tr),review["actual_training_cpu_seconds"],"TRAIN CPU")
    close_match(completed["execution_cpu_seconds"],review["original_total_execution_cpu_seconds"],"total CPU")
    close_match(completed["execution_wall_seconds"],review["original_total_execution_wall_seconds"],"total wall")
    close_match(completed["model_load_cpu_seconds"],review["actual_model_load_cpu_seconds"],"load CPU")
    close_match(completed["model_load_wall_seconds"],review["actual_model_load_wall_seconds"],"load wall")
    insist(completed["total_generation_invocations"]==review["physical_on_policy_generation_invocations_self_reported"],
           "false total original inference census")
    # Research conclusion deliberately never authorizes adaptation or promotion.
    no_lift = correct["ndu_discrete"] <= correct["direct"] and costs["ndu_discrete"] >= costs["direct"]
    result = {
        "schema":SCHEMA,"authority":POSTURE,"decision":"OBSERVED_NO_NDU_TASK_COST_LIFT" if no_lift
          else "INSUFFICIENT_PROSPECTIVE_EVIDENCE",
        "source_run_id":RUN_ID,"original_source_sha":ORIGINAL_SHA,
        "original_inference_calls":192,"held_source_class_balance":{"0":4,"1":4,"2":4,"3":4},
        "policy_results":result_rows,
        "equal_cap": {"pairs":16,"thinking_wins":wins,"thinking_losses":losses,"both_correct":both,
                       "neither_correct":neither,"thinking_incomplete":sum(not c["thinking_complete"] for c in groups["reason"]),
                       "thinking_output_tokens":sum(c["output_tokens"] for c in groups["reason"]),
                       "no_thinking_output_tokens":sum(c["output_tokens"] for c in groups["reason_equalcap"])},
        "lifecycle": {"train_input_output_tokens":sum(c["input_tokens"]+c["output_tokens"] for c in tr),
                      "train_cpu_seconds":round(sum(c["measured_cpu_seconds"] for c in tr),6),
                      "total_cpu_seconds":round(completed["execution_cpu_seconds"],6),
                      "total_wall_seconds":round(completed["execution_wall_seconds"],6)},
        "limitations":["same_historically_public_AG_News_not_independent_future_source_families",
                       "completed_origins_self_metered_no_independent_hardware_attestation",
                       "comparison_policies_all_physically_paid_no_realized_compute_savings",
                       "no_NDU_specific_advantage_over_identical_profile_Bellman",
                       "does_not_prove_global_optimizer_or_neural_FBSDE_or_world_model_efficacy",
                       "no_production_authority_or_model_selection"],
    }
    result["audit_sha256"]=digest(result)
    return result


def main():
    p=argparse.ArgumentParser(description="P7 P5 physical NDU-Merton independent DENY_ALL audit")
    p.add_argument("--public",type=Path,required=True)
    p.add_argument("--gold",type=Path,required=True)
    p.add_argument("--original",type=Path,required=True)
    p.add_argument("--review",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    names={
        "train-public.json": args.public/"train-public.json",
        "held-public.json": args.public/"held-public.json",
        "held-private-labels.json": args.gold/"held-private-labels.json",
        "completed-original.json": args.original/"completed-original.json",
        "frozen-plan.json": args.original/"frozen-plan.json",
        "original-starts-and-dones.jsonl": args.original/"original-starts-and-dones.jsonl",
        "hepta-p5-sanitized-review.json": args.review/"hepta-p5-sanitized-review.json",
    }
    result = audit(read_evidence(names))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    descriptor=os.open(args.output,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(descriptor,"wb") as target:
        target.write(canonical(result)+b"\n")
        target.flush()
        os.fsync(target.fileno())
    print(json.dumps({"decision":result["decision"],"calls":result["original_inference_calls"],
                     "audit_sha256":result["audit_sha256"],"authority":POSTURE},sort_keys=True))


if __name__ == "__main__":
    main()
