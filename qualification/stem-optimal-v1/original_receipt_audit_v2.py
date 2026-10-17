"""Original GitHub Actions Stem canary: immutable ZIP custody and no-gold comparison.

Research only; does not rerun models, reopen publisher labels, attest hardware,
select a Stem or authorize a Cell Split or production FinalUse.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import zipfile

ORIGINAL_RUN_ID = 38989271689
ORIGINAL_SOURCE_SHA = "2fc6a8d9ed331a78827281eee360c5a8d47fa1d2"
COHORT_SHA = "2306a568f1e7df2d2ab7f13c703288f9cf787cba5f975677c06faf0e1918b0ca"
MATERIAL_SHA = "1b8734b6d0ffa99ff1342b8f8c7cd9f1d15fbcf086f3b3e994fb673e41c39a5e"
# artifact-id, exact original ZIP sha256, inner JSON sha256
ARTIFACTS = {
 "granite47": (12087631926, "cc537606e6f9d32f207859b0f69fc77d3f9b331d9b18c416307c97c0edc151b5", "5e5b4857743206650cc711bdd01a9ced181664825177703f625a6b1677a6c447"),
 "granite97": (12087287939, "c9de406122566d4dbfecd9ebf8ac1df1bd7f34baa1c1bd48c88be01389e43fbd", "20344a444eabe9fbd78ebd3e59c8ebf3a82171419234c36b87105b866b0a1b01"),
 "mmbert140": (12087925793, "c748825a5af0ced3b3755517cc0b3e976bb4b229a0eaf37d29b89d892852ace9", "ca7b0571316def6398093a9dd55b8d175bf688abb4eb1597b1aac36fd75431f0"),
 "review": (12087024866, "7920437ca3dfc48a10df44e3d9a335643427cc8ec263998671021501faf40f02", "8b962769e7959825044b19b2d6d7df74e48bac32a47c3e452798deeb2274f5e1"),
}
CANDIDATES = ("granite47", "granite97", "mmbert140")
ARMS = ("centroid", "frozen_init", "learned")


def check(ok, reason):
    if not ok:
        raise ValueError(reason)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def original_zip(path, name):
    check(name in ARTIFACTS, "unknown immutable experiment slot")
    path = Path(path)
    check(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size < 65536, "unsafe original artifact path")
    _, outer_sha, json_sha = ARTIFACTS[name]
    check(sha256(path.read_bytes()) == outer_sha, "original Actions artifact bytes drift")
    member = "stem-review.json" if name == "review" else "receipt-" + name + ".json"
    members = {member} if name == "review" else {member, "receipt-" + name + ".sha256"}
    with zipfile.ZipFile(path) as z:
        info = z.infolist()
        check(len(info) == len(members) and {e.filename for e in info} == members, "unexpected original ZIP member")
        check(all(e.file_size < 32768 and e.compress_size < 32768 and
                  ((e.external_attr >> 16) & 0o170000) != 0o120000 for e in info), "unsafe ZIP member")
        raw = z.read(member)
        if name != "review":
            check(z.read("receipt-" + name + ".sha256") == (json_sha + "  " + member + "\n").encode(), "original sidecar mismatch")
    check(sha256(raw) == json_sha, "original JSON byte identity drift")
    return json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite model output")))


def predicted_class(x):
    check(type(x) is list and len(x) == 4, "4-class original output required")
    check(all(type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1 for p in x), "invalid model probability")
    check(abs(sum(x) - 1) < 1e-5, "incorrect softmax normalization")
    return max(range(4), key=lambda i: x[i])


def audit(runs, review):
    check(set(runs) == set(CANDIDATES), "incomplete actual original candidates")
    check(type(review) is dict and review.get("schema") == "hepta.stem.optimal.independent-review.v1", "wrong reviewer version")
    check(review.get("publisher_original_sha_verified") is True and review.get("independent_publisher_label_recount") is True, "unverified publisher source")
    check(review.get("case_count") == 32 and review.get("source_independent_families") == 1 and review.get("training_continuation_future_windows") == 0, "not a source-independent future study")
    for flag in ("production_authorized", "stem_winner_verified", "ndu_benefit_verified",
                 "trained_4096_cells", "host_cost_attestation", "human_semantic_evaluation",
                 "matched_421m_total_lifecycle"):
        check(review.get(flag) is False, "forged reviewer authority or physical evidence " + flag)
    check(review.get("disposition") == "HOLD_NO_GO" and set(review.get("models", {})) == set(CANDIDATES), "not historical no-go review")
    data, correct, rss, seconds = {}, {}, {}, {}
    for name in CANDIDATES:
        m = runs[name]
        check(type(m) is dict and m.get("schema") == "hepta.stem.optimal.physical-unattested.v1" and m.get("candidate") == name, "different producer")
        check(m.get("source_plan_sha256") == COHORT_SHA and m.get("material_manifest_sha256") == MATERIAL_SHA, "altered source/model plan")
        check(m.get("optimizer_steps") == 100 and m.get("head_parameters") == 27656, "unequal Head training")
        check(m.get("initial_head_sha256") == runs["granite47"].get("initial_head_sha256"), "unequal initialization")
        check(m.get("production_authorized") is False and m.get("physical_claim_unattested") is True and m.get("disposition") == "HOLD_NO_GO", "producer authority forged")
        check(m.get("future_windows_verified") == 0 and m.get("real_4096_cell_training_verified") is False, "imaginary future/scale evidence")
        cost = m.get("cost")
        check(type(cost) is dict and cost.get("physical_encoder_sequences") == 96 and cost.get("encoder_forward_batches") == 6, "not 96 actual Encoder sequence forwards")
        check(cost.get("energy_joules") is None and cost.get("p99_latency_ms") is None, "unattested energy/p99")
        for k in ("elapsed_cpu_seconds", "elapsed_wall_seconds", "maxrss_bytes",
                  "head_train_wall_seconds", "model_download_load_wall_seconds", "feature_encode_wall_seconds"):
            check(type(cost.get(k)) in (int, float) and math.isfinite(cost[k]) and cost[k] > 0, "bad original cost")
        score = review["models"][name]
        check(score.get("cost_observed_unattested") == cost and set(score.get("arms", {})) == set(ARMS), "reviewer cost/controls mismatch")
        correct[name] = {}
        for arm in ARMS:
            row = score["arms"][arm]
            check(row.get("n") == 32 and type(row.get("correct")) is int and 0 <= row["correct"] <= 32, "impossible score")
            check(type(row.get("mean_multiclass_brier")) in (int, float) and math.isfinite(row["mean_multiclass_brier"]) and 0 <= row["mean_multiclass_brier"] <= 2, "Brier invalid")
            correct[name][arm] = row["correct"]
        records = m.get("rows")
        check(type(records) is list and len(records) == 32, "missing original predictions")
        by_case = {}
        for row in records:
            check(type(row) is dict and set(row) == {"case_id", "source_sha256", "scores"}, "held label or unknown field in producer")
            ident = row["case_id"]
            check(type(ident) is str and ident == "heldout:" + row["source_sha256"] and len(ident) == 72, "wrong source identity")
            check(ident not in by_case and type(row["scores"]) is dict and set(row["scores"]) == set(ARMS), "duplicate original or missing control")
            by_case[ident] = {arm: predicted_class(p) for arm, p in row["scores"].items()}
        data[name] = by_case
        rss[name] = cost["maxrss_bytes"]
        seconds[name] = cost["feature_encode_wall_seconds"]
    ids = set(data["granite47"])
    check(len(ids) == 32 and all(set(data[n]) == ids for n in CANDIDATES), "candidate case/source mismatch")
    different = {}
    for a,b in (("granite47","granite97"),("granite47","mmbert140"),("granite97","mmbert140")):
        different[a+"_vs_"+b] = {
            arm: sum(data[a][key][arm] != data[b][key][arm] for key in ids)
            for arm in ("learned", "centroid")
        }
    return {
        "schema": "hepta.stem.original-custody.v2", "source_head": ORIGINAL_SOURCE_SHA,
        "original_run_id": ORIGINAL_RUN_ID, "original_cohort_sha256": COHORT_SHA,
        "independent_original_review_json_sha256": ARTIFACTS["review"][2],
        "original_reviewed_correct": correct, "no_gold_prediction_disagreements": different,
        "learned_equals_cheap_centroid_correct_count": {
            n: correct[n]["learned"] == correct[n]["centroid"] for n in CANDIDATES
        },
        "unattested_process_peak_rss_bytes": rss,
        "unattested_feature_encode_wall_seconds": seconds,
        "original_cases": 32, "original_encoder_sequences_per_candidate": 96,
        "this_v2_recomputed_publisher_labels": False, "source_disjoint_future_windows": 0,
        "target_host_qualified": False, "stem_winner_verified": False,
        "cell_split_authorized": False, "production_authorized": False,
        "disposition": "HOLD_NO_GO", "authority": "DENY_ALL"
    }


def main():
    parser = argparse.ArgumentParser()
    for name in ARTIFACTS:
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = audit({n: original_zip(getattr(args, n), n) for n in CANDIDATES},
                   original_zip(args.review, "review"))
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as out:
        out.write(json.dumps(result, sort_keys=True, allow_nan=False, separators=(",", ":")).encode() + b"\n")
    print(json.dumps({"sha256": sha256(path.read_bytes()), "disposition": "HOLD_NO_GO",
                      "authority": "DENY_ALL"}, sort_keys=True))


if __name__ == "__main__":
    main()
