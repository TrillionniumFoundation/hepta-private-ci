"""Read-only evidence auditor for pinned *historical* real mmBERT/BSDE ZIPs.

No import from the model/trainer/BSDE source; no model execution, owner authority,
normalization fitting or evaluation-label access by candidate prediction code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import zipfile
from pathlib import Path

MODEL_REV = "abc32620dd4f6ab06f5fbe905dc25f310618e09f"
MODEL_ID = "jhu-clsp/mmBERT-small"
SOURCE_SHA = "a31321e8c95872d2239afcc1d42fb1c4f2c1f03f"
LIMIT_NS = 100_000_000
MAX_ZIP_ENTRIES = 120
MAX_UNCOMPRESSED = 52_000_000

REAL = {
    "composition_v3": (11883369189, "fe4e431223d31f92c9ce62b5906e8159bdfd262464bdb59d85fc39822324e928", "independent_targets_composition_v3"),
    "independent_targets_v2": (11883734135, "700dcf2e370e648dec3249954e7394b09bca84cf1ae93d061d8149f2fdd27017", "independent_targets_v2"),
    "label_balanced_v1": (11884466452, "f989b01b4c9ada906648eb95aa5f50761cbd9e31b2ddc12ea6aa9068f4f79b6e", "label_balanced_v1"),
}
FAILED = {
    "hashing_banking": (11883753667, "a6ff38082a4169fd69a02bde4b448c240552743b09381021acea94afdc104d98", "hashing_reference_v1", "banking_v1"),
    "mmbert_travel_guard": (11896021005, "88f5f4d012153c7697ccdeb8f07217b16493cc9dbf9c80f02d5beb0210ffc47b", "mmbert", "travel_guard_v1"),
    "mmbert_banking": (11889260783, "f53229b650e2f8e25db78f892d750323495fb06446cb7a0ed9916be40fc15df4", "mmbert", "banking_v1"),
}

class EvidenceError(ValueError):
    pass


def require(cond, msg):
    if not cond:
        raise EvidenceError(msg)


def sha256_bytes(buf):
    return hashlib.sha256(buf).hexdigest()


def hash_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def valid_digest(s):
    return type(s) is str and len(s) == 64 and all(c in "0123456789abcdef" for c in s)


def read_evidence(path, expected_sha):
    require(valid_digest(expected_sha) and hash_file(path) == expected_sha, "pinned outer archive mismatch")
    z = zipfile.ZipFile(path)
    try:
        items = z.infolist()
        names = [i.filename for i in items]
        require(len(names) == len(set(names)) and len(names) <= MAX_ZIP_ENTRIES,
                "duplicate/oversized archive inventory")
        require(sum(i.file_size for i in items) <= MAX_UNCOMPRESSED, "uncompressed archive size exceeded")
        require(all(not n.startswith("/") and ".." not in Path(n).parts for n in names), "unsafe member")
        return z
    except Exception:
        z.close()
        raise


def load(z, name):
    try:
        return json.loads(z.read(name))
    except (KeyError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise EvidenceError("missing/corrupt original member " + name) from e


def finite_probability(v):
    return type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1


def closed_form(formula, pp, used):
    if type(formula) is int:
        require(0 <= formula < len(pp) and formula not in used, "repeated/unknown leaf")
        used.add(formula)
        return pp[formula]
    require(type(formula) in (list, tuple) and len(formula) == 3 and
            formula[0] in ("and", "or"), "unsupported formula")
    a = closed_form(formula[1], pp, used)
    b = closed_form(formula[2], pp, used)
    return a * b if formula[0] == "and" else a + b - a * b


def score_predictions(z, profile):
    public = load(z, "real-study/public-cases.json")
    beliefs = load(z, "real-study/belief-inputs.json")
    truth = load(z, "real-study/private-test-truths.json")
    comparison = load(z, "real-study/comparison.json")
    physical = load(z, "real-study/physical-summary.json")
    design = load(z, "real-study/design.json")
    exact = load(z, "real-study/exact_formula-predictions.json")
    bsde = load(z, "real-study/fbsde_tree-predictions.json")
    require(physical.get("model") == MODEL_ID and physical.get("revision") == MODEL_REV and
            physical.get("source_sha") == SOURCE_SHA and physical.get("real_weights_executed") is True,
            "wrong physical research identity")
    require(physical.get("production_promotion_permitted") is False and
            comparison.get("equal_compute_superiority_claimed") is False and
            comparison.get("full_lifecycle_resource_gate_passed") is False and
            design.get("real_future_windows") is False and design.get("question_profile") == profile,
            "historical eligibility claim changed")
    cases = public.get("test")
    require(type(cases) is list and len(cases) == 192 and
            type(beliefs) is dict and type(truth) is dict and
            len(beliefs) == len(truth) == 192 and len(exact) == len(bsde) == 192,
            "not complete paired 192-case inventory")
    cases_by_id = {}
    for c in cases:
        require(type(c) is dict and type(c.get("case_id")) is str and
                c["case_id"] not in cases_by_id, "duplicate public case")
        cases_by_id[c["case_id"]] = c
    require(set(cases_by_id) == set(beliefs) == set(truth), "public/belief/truth identities drift")
    for id_, t in truth.items():
        require(type(t) is bool, "non-binary independent truth")
    arrays = {}
    for arm, vals in (("exact_formula", exact), ("fbsde_tree", bsde)):
        seen = {}
        for row in vals:
            require(type(row) is dict and type(row.get("case_id")) is str and
                    row["case_id"] in cases_by_id and row["case_id"] not in seen,
                    "duplicate or absent answer case")
            q = row.get("probability")
            require(finite_probability(q) and type(row.get("cpu_ns")) is int and row["cpu_ns"] > 0 and
                    type(row.get("public_input_sha256")) is str and
                    row["public_input_sha256"] == beliefs[row["case_id"]].get("public_input_sha256"),
                    "unbound probability/meter/source identity")
            expected_text = ("Yes, the stated condition is satisfied." if q >= 0.5
                             else "No, the stated condition is not satisfied.")
            require(row.get("text") == expected_text, "decoded language conflicts with output")
            if arm == "fbsde_tree":
                require(type(row.get("scenario_nodes")) is int and row["scenario_nodes"] > 0 and
                        type(row.get("bsde_interface_residual")) in (int, float) and
                        0 <= row["bsde_interface_residual"] < 1e-8,
                        "unverified BSDE edge / node count")
            else:
                require(row.get("scenario_nodes") == 0, "cheap comparator counted BSDE work")
            seen[row["case_id"]] = row
        require(set(seen) == set(cases_by_id), "missing original prediction")
        arrays[arm] = seen

    errors = []
    observations = {"exact_formula": [], "fbsde_tree": []}
    for id_, c in cases_by_id.items():
        v = beliefs[id_]
        pp = v.get("leaf_probabilities")
        require(type(pp) is list and 1 <= len(pp) <= 8 and all(finite_probability(x) for x in pp),
                "invalid belief feature")
        used = set()
        expected = closed_form(c.get("formula"), pp, used)
        require(used == set(range(len(pp))), "unused/missing probability leaf")
        for arm in arrays:
            got = arrays[arm][id_]["probability"]
            error = abs(got - expected)
            require(error <= 1e-12, "probability inconsistent with independent closed-form reference")
            errors.append(error)
            observations[arm].append((got, truth[id_]))
    metrics = {}
    for arm, samples in observations.items():
        rows = arrays[arm]
        correct = sum((q >= 0.5) == label for q, label in samples)
        brier = math.fsum((q - float(label))**2 for q, label in samples) / len(samples)
        cpu = sum(row["cpu_ns"] for row in rows.values())
        reported_cpu = comparison.get("inference_cpu_ns", {}).get(arm)
        require(type(reported_cpu) is int and cpu == reported_cpu, "archived CPU summary does not reconcile")
        reported = comparison.get("metrics", {}).get(arm, {})
        require(reported.get("count") == 192 and
                abs(reported.get("decoded_exact_accuracy", -1) - correct / 192) < 1e-12 and
                abs(reported.get("binary_brier", -1) - brier) < 1e-12,
                "archived metric does not reconcile")
        metrics[arm] = dict(correct=correct, total=192, accuracy=correct/192,
                            brier=brier, inference_cpu_ns=cpu,
                            scenario_nodes=sum(row["scenario_nodes"] for row in rows.values()))
    cheaper = metrics["exact_formula"]
    expensive = metrics["fbsde_tree"]
    require(expensive["inference_cpu_ns"] > cheaper["inference_cpu_ns"], "changed observed resource ordering")
    return {"profile": profile, "real_pretrained_execution_recorded": True,
            "archive_source_sha": SOURCE_SHA,
            "max_formula_bsde_probability_gap": max(errors),
            "exact_formula": cheaper, "finite_tree_bsde": expensive,
            "incremental_bsde_task_success_gain": expensive["correct"]-cheaper["correct"],
            "incremental_bsde_cpu_ns": expensive["inference_cpu_ns"]-cheaper["inference_cpu_ns"],
            "gain_vs_exact_formula_supported": False,
            "source_family_independence_authenticated": False,
            "pretraining_overlap_excluded": False,"chronological_future_verified": False,
            "full_lifecycle_equal_budget": False,"production_accepted": False}


def score_failure(z, expected_backend, expected_cohort):
    plan = load(z, "acquisition-study/plan.json")
    failed = load(z, "acquisition-study/failure.json")
    clock = load(z, "cpu-tail-replay/original-clock-audit.json").get("budget", {})
    require(plan.get("backend") == expected_backend and plan.get("cohort") == expected_cohort and
            plan.get("prediction_cpu_limit_ns") == LIMIT_NS and clock.get("budget_unchanged_ns") == LIMIT_NS,
            "predeclared CPU cap changed")
    require(failed.get("schema") == "hepta.acquisition.failure.v1" and
            failed.get("error_type") == "ViewBudgetExceeded" and
            failed.get("budget_relaxed") is False and failed.get("run_complete") is False and
            failed.get("scientific_pass") is False and
            failed.get("last_attempt_sha256") is not None,
            "failed run reclassified as success")
    failures = clock.get("failures")
    require(type(failures) is list and len(failures) == 1, "failure inventory changed")
    record = failures[0]
    split = failed["split"]
    member = "acquisition-study/" + split + "-view-attempts.jsonl"
    try:
        raw = z.read(member)
    except KeyError as e:
        raise EvidenceError("missing attempts") from e
    lines = raw.splitlines()
    require(len(lines) == failed["attempts_in_split"] == clock["journals"][split]["attempts"],
            "missing attempt slots")
    attempts = [json.loads(line) for line in lines]
    require(attempts[0].get("previous_sha256") is None, "invalid attempt chain start")
    seen = set()
    for idx, row in enumerate(attempts):
        phases = row.get("phase_cpu_ns")
        cpu = row.get("cpu_ns")
        require(valid_digest(row.get("attempt_sha256")) and
                row["attempt_sha256"] not in seen, "nonunique/bad attempt identity")
        seen.add(row["attempt_sha256"])
        require(type(cpu) is int and cpu >= 0 and type(phases) is dict and
                set(phases) == {"encoder_cpu_ns", "head_cpu_ns", "receipt_cpu_ns", "text_cpu_ns"} and
                all(type(v) is int and v >= 0 for v in phases.values()) and
                sum(phases.values()) == cpu and row.get("limit_ns") == LIMIT_NS,
                "attempt cost or original budget changed")
        require(row.get("status") == ("budget_exceeded" if idx == len(attempts)-1 else "returned") and
                row.get("prediction_returned") is (idx != len(attempts)-1) and
                (cpu > LIMIT_NS) is (idx == len(attempts)-1),
                "earlier attempt hidden or failure silently accepted")
    for prev, current in zip(attempts, attempts[1:]):
        require(current.get("previous_sha256") == prev.get("attempt_sha256"), "attempt chain broken")
    terminal = attempts[-1]
    require(terminal.get("attempt_sha256") == record.get("attempt_sha256") ==
            failed["last_attempt_sha256"] == clock["journals"][split]["last_attempt_sha256"],
            "terminal attempt identity drift")
    for key in ("id", "arm", "view", "cpu_ns", "phase_cpu_ns", "head_sha256"):
        require(terminal.get(key) == record.get(key), "terminal attempt fields disagree " + key)
    cost = terminal["cpu_ns"]
    phases = terminal["phase_cpu_ns"]
    require(type(cost) is int and cost > LIMIT_NS and
            all(type(v) is int and v >= 0 for v in phases.values()) and
            sum(phases.values()) == cost and
            terminal.get("limit_ns") == LIMIT_NS and
            terminal.get("prediction_returned") is False and
            terminal.get("status") == "budget_exceeded",
            "wrong failure amount/type")
    largest = max(phases, key=phases.__getitem__)
    require(largest == record.get("dominant_measured_phase"), "altered dominant phase")
    # The archived SHA-256 chains are self-generated, not independently signed.
    # Bind these assertions to the original pinned ZIP, not to a replacement record.
    return dict(backend=expected_backend,cohort=expected_cohort,failed_split=split,
                view_id=terminal["id"], arm=terminal["arm"],
                observation_cpu_ns=cost,original_limit_ns=LIMIT_NS,
                excess_cpu_ns=cost-LIMIT_NS, dominant_phase=largest,
                dominant_phase_cpu_ns=phases[largest], attempted_rows=len(lines),
                source_self_hash_chain_linked=True,
                source_chain_externally_authenticated=False,
                failure_preserved=True, cpu_budget_relaxed=False,
                trial_completed=False, scientific_pass=False,
                production_accepted=False)


def run_archive_set(directory):
    base = Path(directory)
    found = {p.name for p in base.glob("*.zip")}
    expected = {f"artifact-{spec[0]}.zip" for spec in (*REAL.values(), *FAILED.values())}
    require(found == expected, "exact six-archive inventory required")
    scored = {}
    for label, (artifact_id, pinned, profile) in REAL.items():
        with read_evidence(base / f"artifact-{artifact_id}.zip", pinned) as z:
            scored[label] = dict(artifact_id=artifact_id, zip_sha256=pinned,
                                 **score_predictions(z, profile))
    failed = {}
    for label,(artifact_id,pinned,backend,cohort) in FAILED.items():
        with read_evidence(base / f"artifact-{artifact_id}.zip", pinned) as z:
            failed[label] = dict(artifact_id=artifact_id,zip_sha256=pinned,
                                 **score_failure(z, backend, cohort))
    return {"schema":"hepta.ndu.pretrained-fbsde-original-artifact-replay.v1",
            "source_commit_sha": SOURCE_SHA,"historical_actions_run_id":38532946146,
            "real_model_profiles":scored,"original_budget_failures":failed,
            "all_six_original_archives_sha256_verified":True,
            "real_pretrained_execution_was_historical":True,
            "new_pretrained_execution_performed":False,
            "new_FBSDE_reasoning_gain_supported":False,
            "independent_computation_replayed":True,
            "independent_execution_signer_verified":False,
            "generic_continuous_FBSDE_qualified":False,
            "neuron_production_activation":False,
            "production_promotion_permitted":False,
            "authority":"DENY_ALL"}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archives",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args()
    result=run_archive_set(args.archives)
    output=Path(args.output)
    with output.open("xb") as o:
        o.write(json.dumps(result,sort_keys=True,allow_nan=False,separators=(",", ":")).encode()+b"\n")
    print(json.dumps({"result_sha256":hash_file(output),
                      "profiles":len(REAL),"failed_originals":len(FAILED),
                      "production_promotion_permitted":False},sort_keys=True))


if __name__=="__main__":
    main()
