"""Read-only cross-check of pinned physical Granite/mmBERT and historical Gemma/Laya.

The original 128-label cross-sectional AG News cohort is in an independent
historical Actions ZIP. No trained weight, tokenizer, mutable task or label
is loaded from a candidate model process. This is numerical evidence only;
provenance signer, full training parity and future-time efficacy are NOT proven.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import zipfile

SOURCE_ARCHIVE_SHA = "e5d945c655112139fce51b989023abd5111c9e7ab28d9bd4e8a771b86dd95f9d"
PHYSICAL_ARCHIVE_SHA = "d8e2af397d7ea862245fae0337588ab491dd70e8a8a9a42879e4a7f2d4be3afa"
SOURCE_PANEL_SHA = "8090d3b006364f3da780cea7f1bb91827e8024776e175aa99f5636597bfa644a"
EXPECTED_MODELS = {
    "granite97": ("835ad14087e140460703cf0fae09f97d469d65c2", "cls_l2"),
    "mmbert_small": ("0eb3d056ec1d6333cf4e19b0966dfde342a41a3a", "masked_mean_l2"),
}
HEADS = ("frozen_gate", "learned_gate", "trained_linear")
OLD_ARMS = ("gemma2_frozen_head", "gemma2_trained_head", "gemma2_trained_head_scaled_1024", "laya421_frozen")

class AuditError(ValueError):
    pass


def require(ok: bool, msg: str):
    if not ok:
        raise AuditError(msg)


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def parse(raw: bytes):
    return json.loads(raw, parse_constant=lambda x: (_ for _ in ()).throw(AuditError("invalid JSON number: " + x)))


def read_archive(path, expected_sha):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "missing original artifact")
    raw = path.read_bytes()
    require(0 < len(raw) <= 2_000_000 and sha_bytes(raw) == expected_sha, "Actions archive bytes changed")
    with zipfile.ZipFile(path) as zipf:
        inventory = zipf.infolist()
        require(0 < len(inventory) <= 100 and len({i.filename for i in inventory}) == len(inventory),
                "bad artifact inventory")
        require(all(not PurePosixPath(i.filename).is_absolute()
                    and ".." not in PurePosixPath(i.filename).parts
                    and not i.is_dir() and i.file_size <= 500_000
                    and not ((i.external_attr >> 16) & 0o170000 == 0o120000)
                    for i in inventory), "unsafe archive members")
        require(sum(i.file_size for i in inventory) <= 6_000_000, "archive expansion budget")
        return {name:zipf.read(name) for name in zipf.namelist()}


def nearest_rank(samples: list[float], percentile: float) -> float:
    require(len(samples) >= 100 and 0 < percentile <= 1, "not enough physical timing samples")
    require(all(type(v) in (float, int) and math.isfinite(v) and v > 0 for v in samples),
            "invalid physical timing")
    return sorted(samples)[math.ceil(percentile * len(samples)) - 1]


def exact_mcnemar(recovered: int, lost: int):
    require(type(recovered) is int and type(lost) is int and recovered >= 0 and lost >= 0,
            "nonintegral discordant pair")
    n = recovered + lost
    if not n:
        return 1.0
    return min(1.0, 2.0 * sum(math.comb(n, k) for k in range(min(recovered, lost) + 1)) / (2 ** n))


def validate_panel(panel):
    require(panel.get("schema") == "hepta.stem.agnews-fresh-cross-sectional-cohort.v1"
            and panel.get("production_promotion") == "DENY_ALL"
            and panel.get("chronological_future_claim") is False
            and panel.get("source_signer_independently_authenticated") is False
            and panel.get("same_public_source_family") is True, "invalid cohort claims")
    require(sha_bytes(canonical(panel)) == SOURCE_PANEL_SHA, "pinned historical panel mismatch")
    cohort = panel.get("cases")
    require(type(cohort) is list and len(cohort) == 128, "128 historical cohort required")
    labels = {}
    seen_group = set()
    for row in cohort:
        require(type(row) is dict and row.get("split") == "new_holdout" and
                type(row.get("label")) is int and row["label"] in (0, 1), "invalid ground truth")
        require(row["case_id"] == row["group_id"][:24] and row["source_digest"] == row["group_id"]
                and row["group_id"] not in seen_group, "duplicate/unbound source")
        require(sha_bytes(canonical(row["joint_input"])) == row["joint_input_digest"], "source text changed")
        seen_group.add(row["group_id"])
        labels[row["case_id"]] = row
    require(Counter(x["label"] for x in cohort) == {0: 64, 1: 64}, "original 64/64 labels")
    return labels


def compute_arm(lookup, labels):
    require(set(lookup) == set(labels), "not all 128 source identities scored")
    predicted = {}
    brier = 0.0
    for cid, (prob, identity) in lookup.items():
        gold = labels[cid]
        require(identity == (gold["group_id"], gold["joint_input_digest"]), "prediction/source mismatch")
        require(type(prob) in (int, float) and math.isfinite(prob) and 0 <= prob <= 1,
                "missing valid probability")
        predicted[cid] = (prob >= 0.5) == bool(gold["label"])
        brier += (prob - gold["label"]) ** 2
    return {"correct":sum(predicted.values()), "n":len(labels),
            "accuracy":sum(predicted.values()) / len(labels),
            "brier": brier / len(labels)}, predicted


def parse_reports(old_data, real_data, labels):
    checkout = real_data["current-source.sha"].decode("ascii").strip()
    require(len(checkout) == 40 and all(c in "0123456789abcdef" for c in checkout),
            "invalid physical source checkout")
    preseal = real_data["pre-score-seals.sha256"].decode("utf-8")
    new_results = {}
    new_preds = {}
    expected_input_digest = None
    for name, (revision, pooling) in EXPECTED_MODELS.items():
        blob = real_data[name + ".report.json"]
        require(sha_bytes(blob) in preseal, "report not in pre-scoring seal")
        shell = parse(real_data[name + ".stdout.log"])
        require(shell.get("report_sha256") == sha_bytes(blob), "model report stdout drift")
        report = parse(blob)
        require(report.get("schema") == "hepta.p0.compact.physical-trial.v1"
                and report.get("model_id") == name and report.get("revision") == revision
                and report.get("pooling") == pooling and report.get("authority") == "DENY_ALL"
                and report.get("production_accepted") is False and report.get("p0_accepted") is False
                and report.get("p1_accepted") is False and report.get("model_weights_executed_locally") is True
                and report.get("authenticity_independently_verified") is False
                and report.get("chronological_future_verified") is False
                and report.get("matched_full_lifecycle_cost") is False,
                "incorrect pretrained execution claims")
        require(report.get("actual_encoder_forward_count") == 352 and
                report.get("q24_feature_dimension") == 384 and
                type(report.get("snapshot_file_sha256")) is dict and
                len(report["snapshot_file_sha256"]) >= 4, "missing model identity or physical counts")
        require(type(report.get("head_stats")) is dict and set(report["head_stats"]) == set(HEADS),
                "head coverage missing")
        require(report["head_stats"]["frozen_gate"]["updates"] == 0 and
                all(report["head_stats"][a]["updates"] == 40 for a in HEADS[1:]),
                "learned/frozen control missing")
        if expected_input_digest is None:
            expected_input_digest = (report["source_sha256"], report["source_only_future_sha256"])
        require(expected_input_digest == (report["source_sha256"], report["source_only_future_sha256"]),
                "mismatched model input set")
        records = report.get("future_predictions")
        require(type(records) is list and len(records) == 192 and
                Counter(x.get("split") for x in records) == {"test": 64, "new_holdout": 128},
                "physical output inventory")
        selected = [x for x in records if x["split"] == "new_holdout"]
        sample = [x["encoder_forward_ns"] / 1e6 for x in selected]
        per_arm = {a:{} for a in HEADS}
        for a in HEADS:
            rows={}
            for x in selected:
                require(set(x) == {"case_id", "group_id", "split", "joint_input_digest", "probs",
                                    "encoder_forward_ns", "head_ns", "input_tokens"},
                        "unknown output row fields")
                require(set(x["probs"]) == set(HEADS) and set(x["head_ns"]) == set(HEADS) and
                        0 < x["input_tokens"] <= 512 and all(type(v) is int and v > 0 for v in x["head_ns"].values()),
                        "incomplete feature and Head execution")
                require(x["case_id"] not in rows, "duplicate model prediction")
                rows[x["case_id"]] = (x["probs"][a], (x["group_id"], x["joint_input_digest"]))
            per_arm[a], new_preds[name + "." + a] = compute_arm(rows, labels)
        new_results[name] = {"arms":per_arm,"observed_per_input_encoder_ms":{
            "p50":nearest_rank(sample,.5),"p95":nearest_rank(sample,.95),
            "p99":nearest_rank(sample,.99)},"full_run_cpu_s":report["entire_run_cpu_ns"] / 1e9,
            "load_wall_s":report["model_load_wall_ns"] / 1e9,
            "peak_process_rss_mib": report["linux_process_peak_rss_kib"] / 1024,
            "trained_head_params":report["head_stats"]["learned_gate"]["parameters"],
            "recorded_encoder_forwards":report["actual_encoder_forward_count"]}
    old_results = {}
    old_preds = {}
    fresh = parse(old_data["stem-gemma-fresh-arms.json"])
    require(type(fresh) is list and len(fresh) == 3, "Gemma historical arm census")
    oldarms = fresh + [parse(old_data["stem-laya-fresh-arm.json"])]
    require({x.get("arm_id") for x in oldarms} == set(OLD_ARMS), "historical arm inventory")
    for item in oldarms:
        name = item["arm_id"]
        require(item.get("panel_digest") == SOURCE_PANEL_SHA and
                item.get("production_promotion") == "DENY_ALL" and
                item.get("raw_source_and_model_origin_independently_attested") is False
                and item.get("matched_full_lifecycle_cost") is False,
                "historical evidence authenticity/independence claim")
        rows = item.get("rows")
        require(type(rows) is list and len(rows) == 128, "historical prediction coverage")
        lookup = {}
        for row in rows:
            cid = row["case_id"]
            require(cid not in lookup and row.get("split") == "new_holdout", "duplicate historical row")
            lookup[cid] = (row["prob_sports"], (row["source_digest"], row["joint_input_digest"]))
        old_results[name], old_preds[name] = compute_arm(lookup, labels)
    return new_results, new_preds, old_results, old_preds


def audit(historical_path, physical_path):
    old_data = read_archive(historical_path, SOURCE_ARCHIVE_SHA)
    real_data = read_archive(physical_path, PHYSICAL_ARCHIVE_SHA)
    labels = validate_panel(parse(old_data["stem-agnews-new-source-panel.json"]))
    new, pred_new, old, pred_old = parse_reports(old_data, real_data, labels)
    status = {"granite97 vs mmbert_small learned_gate":(
        "granite97.learned_gate", "mmbert_small.learned_gate"),
        "granite97 vs gemma2 learned":("granite97.learned_gate", "gemma2_trained_head"),
        "granite97 vs laya421 frozen":("granite97.learned_gate", "laya421_frozen")}
    full = {**pred_new, **pred_old}
    paired = {}
    for name,(left,right) in status.items():
        aa,bb=full[left],full[right]
        recovered=sum(aa[c] and not bb[c] for c in labels)
        lost=sum(bb[c] and not aa[c] for c in labels)
        paired[name] = {"left_correct_only":recovered,"right_correct_only":lost,
                        "delta_correct":recovered-lost,"exploratory_exact_mcnemar_p":exact_mcnemar(recovered,lost)}
    report = {"schema":"hepta.p0.real-four-model-independent-numeric-replay.v1",
        "input_artifact_shas":{"historical":SOURCE_ARCHIVE_SHA,"physical":PHYSICAL_ARCHIVE_SHA},
        "val2_panel_digest":SOURCE_PANEL_SHA,"observed_source_groups":len(labels),
        "labels_replayed_from_distinct_pinned_historical_artifact":True,
        "publisher_label_origin_independently_authenticated":False,
        "production_accepted":False,
        "authority":"DENY_ALL","pretrained_weight_origin_authenticated":False,
        "full_four_model_equal_resource_winner":False,"future_observation_time_verified":False,
        "full_encoder_4096_cell_execution":False,"native_neuron_checkpoint_witness":False,
        "all_original_352_model_inputs_independently_recreated":False,
        "real_stem_models":new,"historical_context":old,"paired_new_holdout":paired,
        "interpretation":"192 physical predictions per new model but only 128 independent source labels replayed; one AGNews family, historical cross-model costs not equalized; no winner or production qualification"}
    require(new["granite97"]["arms"]["learned_gate"]["correct"] == 122 and
            new["mmbert_small"]["arms"]["learned_gate"]["correct"] == 73 and
            old["laya421_frozen"]["correct"] == 124, "unexpected historical numbers")
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--historical",required=True)
    parser.add_argument("--physical",required=True)
    parser.add_argument("--output",required=True)
    options=parser.parse_args()
    result=audit(options.historical,options.physical)
    with Path(options.output).open("xb") as f:
        f.write(canonical(result))
    print(json.dumps({"sha256":sha_bytes(Path(options.output).read_bytes()),
                      "granite_correct":result["real_stem_models"]["granite97"]["arms"]["learned_gate"]["correct"],
                      "mmbert_correct":result["real_stem_models"]["mmbert_small"]["arms"]["learned_gate"]["correct"],
                      "production_accepted":False},sort_keys=True))


if __name__ == "__main__":
    main()
