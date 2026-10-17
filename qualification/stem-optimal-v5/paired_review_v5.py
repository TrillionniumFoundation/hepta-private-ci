"""Original ZIP-bound neural vs lexical Stem comparison; never grants authority.

Only a reviewer may open publisher heldout labels after original prelabel ZIPs
have been sealed. Nothing here trains, downloads model weights, selects a model,
or mutates the production owner. Single-source retrospective case only.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from zipfile import ZipFile

SOURCE_PLAN_SHA = "3e79b3449f3b63d1f261ae4ad9632ae4cff07262a82c5259a17d040e61929900"
SOURCE_JSON_SHA = "008e1ab79f689694bb20eab2b5b25039266ab66f181295014fda51e35647ed0b"
V3_SOURCE_SHA = "bc8e83331294d43daf122224941e967bd29af15d"
V4_SOURCE_SHA = "88aa3e6be99feee305bb308078240ed04820268e"
ROLES = ("source_v3", "source_v4", "granite47", "granite97", "mmbert140", "cheap_v4")
NEURAL = ("granite47", "granite97", "mmbert140")
CHEAP = ("word_12_tfidf_centroid", "char_345_tfidf_centroid")
ARMS = ("frozen_init", "centroid", "learned")
SHA = re.compile(r"[0-9a-f]{64}\Z")


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(data):
    return json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def locked_json(path, lock, role):
    """Verify entire original uploaded ZIP *before* deserializing any evidence."""
    require(role in ROLES and set(lock) == set(ROLES), "incomplete artifact roster")
    identity = lock[role]
    require(type(identity) is dict and set(identity) == {"run_id", "artifact_id", "archive_sha256", "json_member", "json_sha256"},
            "incomplete artifact identity")
    for key in ("run_id", "artifact_id"):
        require(type(identity[key]) is int and identity[key] > 0, "unbound artifact provenance")
    for key in ("archive_sha256", "json_sha256"):
        require(type(identity[key]) is str and SHA.fullmatch(identity[key]) is not None,
                "original artifact not SHA locked or not yet produced")
    member = identity["json_member"]
    require(type(member) is str and re.fullmatch(r"[a-zA-Z0-9._-]{1,96}\.json", member),
            "unregistered evidence member")
    p = Path(path)
    require(p.is_file() and not p.is_symlink() and 0 < p.stat().st_size <= 65536,
            "unbounded or missing immutable ZIP")
    raw = p.read_bytes()
    require(sha(raw) == identity["archive_sha256"], "original ZIP SHA mismatch")
    with ZipFile(p) as z:
        entries = z.infolist()
        allowed = {member} if role in ("source_v3", "source_v4") else {member, member.replace(".json", ".sha256")}
        if role in ("source_v3", "source_v4"):
            allowed.add(member.replace(".json", ".sha256"))
        require(len(entries) == len(allowed) and {i.filename for i in entries} == allowed,
                "extra, missing or duplicate ZIP member")
        require(all(0 < i.file_size <= 100000 and 0 < i.compress_size <= 65536
                    and (i.external_attr >> 16) & 0o170000 != 0o120000
                    for i in entries), "unsafe ZIP member")
        doc = z.read(member)
        sidecar = z.read(member.replace(".json", ".sha256"))
    require(sha(doc) == identity["json_sha256"], "original JSON content SHA mismatch")
    require(sidecar == (identity["json_sha256"] + "  " + member + "\n").encode(),
            "original sidecar mismatch")
    return json.loads(doc, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite evidence")))


def _pred(row, arm):
    probs = row["scores"][arm]
    require(type(probs) is list and len(probs) == 4 and
            all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in probs)
            and abs(sum(probs) - 1) <= 1e-5, "invalid sealed score")
    return max(range(4), key=lambda k: probs[k])


def original_nogold(source, models):
    """Use actual original prelabel artifacts without falsely knowing the gold."""
    require(source["schema"] == "hepta.stem.charge-stress.source.v3" and
            source["source_plan_sha256"] == SOURCE_PLAN_SHA,
            "not original frozen hard-charge cohort")
    require(len(source["train"]) == 64 and len(source["heldout"]) == 32 and
            all("label" not in x and "category" not in x for x in source["heldout"]),
            "heldout label exposed or roster drift")
    expected = {x["case_id"] for x in source["heldout"]}
    require(len(expected) == 32, "duplicate original heldout")
    predictions = {}
    heads = set()
    material = set()
    for model in NEURAL:
        x = models[model]
        require(x["schema"] == "hepta.stem.charge-stress.physical-unattested.v3" and
                x["cohort"] == source["cohort"] and
                x["candidate"] == model and
                x["source_plan_sha256"] == SOURCE_PLAN_SHA,
                "incorrect original pretrained model evidence")
        require(x["authority"] == "DENY_ALL" and x["disposition"] == "HOLD_NO_GO" and
                x["production_authorized"] is False and
                x["physical_claim_unattested"] is True and
                x["publisher_future_windows"] == 0 and
                x["matched_421m_lifecycle"] is False,
                "forged producer authority")
        require(x["head_parameters"] == 27656 and x["optimizer_steps"] == 100,
                "mismatched original Head budget")
        require(len(x["rows"]) == 32 and {r["case_id"] for r in x["rows"]} == expected,
                "original heldout identity mismatch")
        require(len({r["case_id"] for r in x["rows"]}) == 32 and
                all(r["case_id"] == "heldout:" + r["source_sha256"] and
                    set(r) == {"case_id", "source_sha256", "scores"} and
                    set(r["scores"]) == set(ARMS) for r in x["rows"]),
                "invalid prelabel score rows")
        cost = x["cost"]
        require(cost["physical_encoder_sequences"] == 96 and cost["encoder_forward_batches"] == 6
                and cost["p99_latency_ms"] is None and cost["energy_joules"] is None,
                "false model physical performance claim")
        heads.add(x["initial_head_sha256"])
        material.add(x["material_manifest_sha256"])
        predictions[model] = {r["case_id"]: r["scores"] for r in x["rows"]}
    require(len(heads) == len(material) == 1, "non-comparable model/head inputs")
    disagreement = {}
    for a, b in (("granite47", "granite97"), ("granite47", "mmbert140"), ("granite97", "mmbert140")):
        disagreement[a + "_vs_" + b] = {
            arm: sum(_pred({"scores": predictions[a][key]}, arm) !=
                     _pred({"scores": predictions[b][key]}, arm) for key in expected)
            for arm in ("learned", "centroid")}
    return {"source_plan_sha256": SOURCE_PLAN_SHA, "original_case_count": 32,
            "head_initial_sha256": next(iter(heads)), "material_manifest_sha256": next(iter(material)),
            "nogold_disagreement": disagreement,
            "original_publisher_labels_opened": False,
            "disposition": "HOLD_NO_GO", "authority": "DENY_ALL"}


def mcnemar(only_a, only_b):
    require(type(only_a) is int and type(only_b) is int and
            0 <= only_a <= 32 and 0 <= only_b <= 32 and only_a + only_b <= 32,
            "invalid paired disagreement")
    n = only_a + only_b
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, k) for k in range(min(only_a, only_b) + 1)) / (2**n))


def holm(pvalues):
    """Deterministic multiplicity correction across the *three fixed* primary pairs."""
    require(type(pvalues) is dict and set(pvalues) == set(NEURAL) and
            all(type(p) is float and math.isfinite(p) and 0 <= p <= 1 for p in pvalues.values()),
            "unregistered or invalid multiple comparisons")
    order = sorted(pvalues, key=lambda key: (pvalues[key], key))
    out = {}
    largest = 0.0
    for index, key in enumerate(order):
        largest = max(largest, min(1.0, (len(order) - index) * pvalues[key]))
        out[key] = largest
    return out


def paired_counts(pred_a, pred_b, gold):
    require(set(pred_a) == set(pred_b) == set(gold) and len(gold) == 32,
            "unmatched independently labelled heldout")
    only_a = only_b = correct_a = correct_b = 0
    for key, actual in gold.items():
        a, b = pred_a[key] == actual, pred_b[key] == actual
        correct_a += a
        correct_b += b
        only_a += a and not b
        only_b += b and not a
    return {"correct_candidate": correct_a, "correct_baseline": correct_b,
            "candidate_only": only_a, "baseline_only": only_b,
            "delta_accuracy": (correct_a - correct_b) / 32,
            "nominal_exact_mcnemar_p": mcnemar(only_a, only_b)}


def run_original(train, test, source_v3, source_v4, model_runs, cheap, materials):
    """Compute descriptive original paired contrasts using independent reviewers."""
    import stem_hard_charge_review_v3 as v3
    import cheap_lexical_review_v4 as v4
    original_nogold(source_v3, model_runs)
    require(source_v3 == source_v4, "original V3/V4 source cohort is not byte-equivalent")
    require(cheap["source_plan_sha256"] == SOURCE_PLAN_SHA, "cheap control from different cohort")
    neural_review = v3.review_original(train, test, source_v3,
                                       [model_runs[n] for n in NEURAL], materials)
    cheap_review = v4.review_original(train, test, source_v3, cheap)
    require(neural_review["publisher_original_sha_verified"] is True and
            cheap_review["publisher_original_sha_verified"] is True and
            cheap_review["independent_algorithm_replay"] is True and
            all(x["disposition"] == "HOLD_NO_GO" for x in (neural_review, cheap_review)),
            "independent publisher review not qualified")
    _, gold = v3.reconstruct(train, test, v3.original.FIXED_SHA)
    predictor = {
        (model, arm): {row["case_id"]: _pred(row, arm) for row in model_runs[model]["rows"]}
        for model in NEURAL for arm in ARMS}
    lexical = {
        arm: {row["case_id"]: _pred(row, arm) for row in cheap["rows"]}
        for arm in CHEAP}
    contrasts = {}
    for model in NEURAL:
        contrasts[model] = {
            "learned_vs_char": paired_counts(predictor[model, "learned"], lexical[CHEAP[1]], gold),
            "learned_vs_word": paired_counts(predictor[model, "learned"], lexical[CHEAP[0]], gold),
            "learned_vs_own_centroid": paired_counts(predictor[model, "learned"],
                                                     predictor[model, "centroid"], gold)}
    corrected = holm({model: float(contrasts[model]["learned_vs_char"]["nominal_exact_mcnemar_p"])
                      for model in NEURAL})
    for model in NEURAL:
        contrasts[model]["learned_vs_char"]["holm_three_primary_pairs_p"] = corrected[model]
    return {"schema": "hepta.stem.original-hard-charge.paired-v5", "source_plan_sha256": SOURCE_PLAN_SHA,
            "case_count": 32, "same_original_publisher": True, "publisher_original_sha_verified": True,
            "independent_neural_label_review": True, "independent_lexical_numeric_replay": True,
            "primary_lexical_control": CHEAP[1], "comparison": contrasts,
            "neural_arm_brier_and_correct": neural_review["models"],
            "cheap_arm_brier_and_correct": cheap_review["cheap_controls"],
            "source_independent_families": 1, "future_windows": 0,
            "validated_421m_lifecycle": False, "target_host_cost_attested": False,
            "stem_winner_verified": False, "ndu_benefit_verified": False,
            "production_authorized": False, "cell_split_authorized": False,
            "disposition": "HOLD_NO_GO", "authority": "DENY_ALL"}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", required=True)
    for role in ROLES:
        p.add_argument("--" + role.replace("_", "-"), required=True)
    for name in ("train", "test", "materials", "output"):
        p.add_argument("--" + name, required=True)
    args = p.parse_args()
    registry = json.loads(Path(args.manifest).read_text())
    require(registry["schema"] == "hepta.stem.original-hard-charge.lock.v5" and
            registry["v3_source_sha"] == V3_SOURCE_SHA and
            registry["v4_source_sha"] == V4_SOURCE_SHA and
            registry["source_plan_sha256"] == SOURCE_PLAN_SHA,
            "original source/branch identity mismatch")
    paths = {key: getattr(args, key) for key in ROLES}
    docs = {role: locked_json(paths[role], registry["artifacts"], role) for role in ROLES}
    source_v3 = docs.pop("source_v3")
    source_v4 = docs.pop("source_v4")
    cheap = docs.pop("cheap_v4")
    material = json.loads(Path(args.materials).read_text())
    result = run_original(Path(args.train).read_bytes(), Path(args.test).read_bytes(),
                          source_v3, source_v4, docs, cheap, material)
    dest = Path(args.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("xb") as f:
        f.write(canonical(result) + b"\n")
        f.flush()
    print(json.dumps({"sha256": sha(dest.read_bytes()), "status": "HOLD_NO_GO", "authority": "DENY_ALL"}, sort_keys=True))


if __name__ == "__main__":
    main()
