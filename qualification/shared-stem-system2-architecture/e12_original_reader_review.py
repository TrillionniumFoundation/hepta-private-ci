"""Postseal independent scoring of real frozen Reader routing (DENY_ALL).

Does not import the proposer. Reopens the original three GitHub Actions ZIP
archives, checks their byte digests, reconstructs choices/physical work and
only then loads authentic (but unsigned) historical public-source labels.
"""
import argparse
from collections import defaultdict
from hashlib import sha256
import json
import math
from pathlib import Path
import zipfile

SCHEMA = "hepta.e12.original-reader-voi-prelabel.v1"
ZIPS = {
    "physical": "d8e2af397d7ea862245fae0337588ab491dd70e8a8a9a42879e4a7f2d4be3afa",
    "labels": "e5d945c655112139fce51b989023abd5111c9e7ab28d9bd4e8a771b86dd95f9d",
    "multirc": "1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17",
}
MEMBERS = {
    "granite": ("physical", "granite97.report.json", "6098b3e5141694fbf841f092631ef7f00abee606eca12a6c82d6249211ee4e57"),
    "mmbert": ("physical", "mmbert_small.report.json", "d5382f28e60627c0b4e35446b7bef84e9dc5ffb00cd76e4c1ab1b2a99f1cb2ac"),
    "original_scores": ("physical", "independent-scores.json", "f091d12bb29aac0880399350295dce93e44326de4a1da602fc2f99926b406d0f"),
    "original_labels": ("labels", "stem-agnews-new-source-panel.json", "8090d3b006364f3da780cea7f1bb91827e8024776e175aa99f5636597bfa644a"),
    "multirc_audit": ("multirc", "multirc-native-candidate-audit/audit.json", "c0a7ae08d682349ce8b8ebd3bce14fcfe5203f9c636cea3944a85a10f45f4840"),
    "multirc_scores": ("multirc", "multirc-native-candidate-scores/scores.json", "3a3fd807585dd09ef4f089391dc68db4b008e87b69060f68f384a07daaa9f8e4"),
}
POLICIES = ("stop", "uncertain_060", "uncertain_075", "always_mmbert")


def parse_strict(raw):
    def duplicate(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError("duplicate original JSON field")
            result[k] = v
        return result
    return json.loads(raw, object_pairs_hook=duplicate,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError("nonfinite original JSON")))


def load_archives(physical, labels, multirc):
    filenames = {"physical": physical, "labels": labels, "multirc": multirc}
    zips = {}
    for key, path in filenames.items():
        data = Path(path).read_bytes()
        if sha256(data).hexdigest() != ZIPS[key]:
            raise ValueError("original archive digest changed: "+key)
        zips[key] = zipfile.ZipFile(path)
    output = {}
    for key, (zipkey, member, expected) in MEMBERS.items():
        raw = zips[zipkey].read(member)
        if sha256(raw).hexdigest() != expected:
            raise ValueError("original member digest changed: "+key)
        output[key] = parse_strict(raw)
    for zipobj in zips.values():
        zipobj.close()
    return output


def review(prelabel, prelabel_sha256, physical, labels, multirc, output):
    source = Path(prelabel).read_bytes()
    if sha256(source).hexdigest() != prelabel_sha256:
        raise ValueError("unsealed/altered prediction-only decision artifact")
    proposal = parse_strict(source)
    original = load_archives(physical, labels, multirc)
    if (type(proposal) is not dict or set(proposal) != {
        "schema", "authority", "rows", "source_sha256", "model_revisions",
        "model_archived_outputs_not_fresh_calls", "multirc_prelabel", "policies",
        "task_identified_fbsde_coefficients_present",
        "neural_continuation_real_task_gain_qualified",
        "system2_full_fbsde_admitted", "production_authorized"
    } or proposal["schema"] != SCHEMA or proposal["authority"] != "DENY_ALL" or
        proposal["policies"] != list(POLICIES) or
        proposal["model_archived_outputs_not_fresh_calls"] is not True or
        any(proposal[k] is not False for k in (
            "task_identified_fbsde_coefficients_present",
            "neural_continuation_real_task_gain_qualified",
            "system2_full_fbsde_admitted", "production_authorized"))):
        raise ValueError("unauthorized or incompletely declared prelabel policy")
    if proposal["source_sha256"] != {k: MEMBERS[{"granite":"granite", "mmbert":"mmbert", "multirc":"multirc_audit"}[k]][2] for k in ("granite", "mmbert", "multirc")}:
        raise ValueError("original feature material identities do not match")
    if proposal["model_revisions"] != {
        "granite97": "835ad14087e140460703cf0fae09f97d469d65c2",
        "mmbert_small": "0eb3d056ec1d6333cf4e19b0966dfde342a41a3a"}:
        raise ValueError("unknown physical model revision")
    labels_rows = original["original_labels"]["cases"]
    if (original["original_labels"].get("case_count") != 128 or
        original["original_labels"].get("selection_uses_model_predictions") is not False or
        type(labels_rows) is not list or len(labels_rows) != 128):
        raise ValueError("unknown independent source labels")
    ground = {v["case_id"]:v for v in labels_rows}
    if len(ground) != 128:
        raise ValueError("duplicate label-case identity")
    preds = {}
    for model in ("granite", "mmbert"):
        rows = [v for v in original[model]["future_predictions"] if v["split"] == "new_holdout"]
        if len(rows) != 128 or len({v["case_id"] for v in rows}) != 128:
            raise ValueError("missing original physical prediction")
        preds[model] = {v["case_id"]:v for v in rows}
    if (set(ground) != set(preds["granite"]) or set(ground) != set(preds["mmbert"]) or
        type(proposal["rows"]) is not list or len(proposal["rows"]) != 128):
        raise ValueError("original-source group/label coverage is incomplete")

    info = proposal["multirc_prelabel"]
    if (type(info) is not dict or set(info) != {
        "questions", "answers", "source_groups", "max_conditioned_span",
        "mean_conditioned_span", "questions_with_span_at_most_001",
        "answer_sufficient_for_fbsde_admission",
        "answer_information_diagnostic_only"
    } or info["answer_sufficient_for_fbsde_admission"] is not False or
        info["answer_information_diagnostic_only"] is not True):
        raise ValueError("forged source-blind Reader capability")
    scored = {name: {"correct":0,"brier_sum":0.0,"switches":0,"second_forward_proxy_ns":0} for name in POLICIES}
    possible = 0
    forgone = 0
    for result, case_id in zip(proposal["rows"], sorted(ground)):
        a, b = preds["granite"][case_id], preds["mmbert"][case_id]
        real = ground[case_id]
        if (type(result) is not dict or set(result) != {
            "case_id", "group_id", "joint_input_digest", "granite_prob",
            "mmbert_prob", "base_observed_forward_ns", "arms"
        } or result["case_id"] != case_id or result["group_id"] != real["group_id"] or
            real["group_id"] != a["group_id"] or real["group_id"] != b["group_id"] or
            result["joint_input_digest"] != real["joint_input_digest"] or
            result["joint_input_digest"] != a["joint_input_digest"] or
            result["joint_input_digest"] != b["joint_input_digest"] or
            type(real["label"]) is not int or real["label"] not in (0,1)):
            raise ValueError("frozen joint input or independent label mismatch")
        gp, mp = (a["probs"]["learned_gate"], b["probs"]["learned_gate"])
        if (result["granite_prob"] != gp or result["mmbert_prob"] != mp or
            result["base_observed_forward_ns"] != a["encoder_forward_ns"]+a["head_ns"]["learned_gate"] or
            type(result["arms"]) is not dict or set(result["arms"]) != set(POLICIES)):
            raise ValueError("altered original model prediction, meter or action roster")
        gc = (gp>=0.5) == real["label"]
        mc = (mp>=0.5) == real["label"]
        possible += int(gc or mc)
        forgone += int(not gc and mc)
        conf = max(gp, 1-gp)
        for name in POLICIES:
            use = (name == "always_mmbert" or
                   name == "uncertain_060" and conf < .60 or
                   name == "uncertain_075" and conf < .75)
            pred = mp if use else gp
            actual = result["arms"][name]
            expected = {"model":"mmbert_small" if use else "granite97",
                        "probability":pred,"additional_encoder_calls":int(use),
                        "additional_observed_forward_ns": (b["encoder_forward_ns"]+b["head_ns"]["learned_gate"] if use else 0)}
            if (type(actual) is not dict or set(actual) != set(expected) or
                type(actual["additional_encoder_calls"]) is not int or
                type(actual["additional_observed_forward_ns"]) is not int or
                actual != expected):
                raise ValueError("original deterministic request produced contradictory model/answer/cost")
            count = scored[name]
            count["correct"] += int((pred>=.5) == real["label"])
            count["brier_sum"] += (pred-real["label"])**2
            count["switches"] += int(use)
            count["second_forward_proxy_ns"] += expected["additional_observed_forward_ns"]
    for name, v in scored.items():
        v["brier"] = v.pop("brier_sum")/128
        v["correct_fraction"] = f'{v["correct"]}/128'
        v["incremental_secondary_model_load_wall_ns"] = (original["mmbert"]["model_load_wall_ns"] if v["switches"] else 0)
    published = original["original_scores"]["models"]
    if (scored["stop"]["correct"] != published["granite97"]["quality"]["new_holdout"]["learned_gate"]["correct"] or
        scored["always_mmbert"]["correct"] != published["mmbert_small"]["quality"]["new_holdout"]["learned_gate"]["correct"] or
        abs(scored["stop"]["brier"] - published["granite97"]["quality"]["new_holdout"]["learned_gate"]["brier"]) > 1e-12 or
        abs(scored["always_mmbert"]["brier"]-published["mmbert_small"]["quality"]["new_holdout"]["learned_gate"]["brier"]) > 1e-12):
        raise ValueError("independent original published physical task results fail to replay")
    reported = original["multirc_scores"]["results"]["conditioned"]
    by_question = defaultdict(list)
    for row in original["multirc_audit"]["predictions"]["conditioned"]:
        lo, hi = row["logits"]
        p = 1/(1+math.exp(lo-hi))
        by_question[(row["source_group"],row["question_slot"])].append(p)
    widths = [max(xs)-min(xs) for xs in by_question.values()]
    if (len(by_question) != 8 or len(original["multirc_audit"]["rows"]) != 33 or
        proposal["multirc_prelabel"]["questions"] != 8 or
        proposal["multirc_prelabel"]["answers"] != 33 or
        proposal["multirc_prelabel"]["questions_with_span_at_most_001"] != 8 or
        abs(proposal["multirc_prelabel"]["mean_conditioned_span"]-sum(widths)/8)>1e-12 or
        abs(proposal["multirc_prelabel"]["max_conditioned_span"]-max(widths))>1e-12 or
        reported["correct"] != 16 or reported["total"] != 33 or
        reported["near_invariant_native_answer_question_count"] != 8 or
        reported["mixed_label_question_count"] != 8):
        raise ValueError("unqualified original MultiRC answer-adequacy statement")
    # Accuracy-first, then incremental-calls criterion, predeclared before score.
    no_net_accuracy_gain = all(v["correct"] <= scored["stop"]["correct"] for v in scored.values())
    report = {
        "schema":SCHEMA+".review.v1", "prelabel_sha256":sha256(source).hexdigest(),
        "original_archive_sha256":ZIPS, "authority":"DENY_ALL",
        "policy_outcomes":scored,"original_model_forwards_during_this_replay":0,
        "frozen_original_pretrained_forward_receipts_checked":True,
        "original_data_family_overlap_not_excluded":True,
        "two_model_oracle_correct_upper_bound":possible,
        "oracle_recoverable_granite_errors":forgone,
        "oracle_policy_was_not_proposed_or_executed":True,
        "original_multirc_correct":reported["correct"],
        "original_multirc_candidate_count":reported["total"],
        "original_multirc_complete_mixed_label_questions":8,
        "accuracy_first_additional_computation_no_go":no_net_accuracy_gain,
        "whole_service_cost_and_physical_conditional_route_qualified":False,
        "task_identified_ndu_fbsde_coefficients_present":False,
        "system2_full_fbsde_admitted":False,
        "natural_task_generalization_established":False,
        "production_accepted":False,
    }
    data=(json.dumps(report,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
    with open(output,'xb') as f:
        f.write(data)
        f.flush()
        import os
        os.fsync(f.fileno())
    return sha256(data).hexdigest()


if __name__ == "__main__":
    ap=argparse.ArgumentParser()
    for name in ("prelabel","prelabel-sha256","physical","labels","multirc","output"):
        ap.add_argument("--"+name,required=True)
    args=ap.parse_args()
    print(json.dumps({"sha256":review(args.prelabel,args.prelabel_sha256,args.physical,
                                      args.labels,args.multirc,args.output),"authority":"DENY_ALL"}))
