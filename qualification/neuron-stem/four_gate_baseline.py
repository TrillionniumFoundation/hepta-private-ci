"""Typed production no-change supplement to the ONE canonical Four-Gate reviewer.

Reuses #1494's original pinned signature/source verifier in an isolated process.
No signing, model execution, owner authority, or fabricated probability vectors.
This diagnostic cannot replace the existing probability-based learning gate.
"""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile

from four_gate_common import canonical, digest, integer, read_pinned, require, sha, strict_loads, timestamp
from prequential_threeway_review import measure, verify_cell_trace

OWNER_SOURCE = "aef947be91c9fbcac7f9f7315ecbc99122349e7d"
OWNER_BLOBS = {
    "hepta_neuron_real_cohort_preflight.py": "8bc8178ca9b21f46ef17f0d18ac72222a3491b6a",
    "hepta_neuron_model_trials.py": "914acd69ad313888002b024bc4b7ea64560b3017",
    "hepta_neuron_production_baseline_compare.py": "be8d9a41fefe71f2e63f37e687240a2c9eb7f285",
}
PROFILE = "typed_production_policy_pairing.v1"
REFS = {"cohort", "sealed", "manifest", "baseline", "dataset", "trial", "prelabel_journal"}
MAX_OWNER_BYTES = 4 * 1024 * 1024
# Executes only the three source files whose full Git blobs were checked below.
# Existing underscore API is pinned explicitly; changes require compatibility review.
OWNER_DRIVER = '''
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
import hepta_neuron_real_cohort_preflight as c
import hepta_neuron_production_baseline_compare as b
from hepta_neuron_model_trials import blind_rows, canonical_jsonl
p = Path.cwd()
verified = c.verify(p/'cohort', p/'sealed', p/'trust', sys.argv[1])
cohort, manifest, trust, packet = (c.read_json(p/n) for n in ('cohort','manifest','trust','baseline'))
rows = c.read_sealed(p/'sealed')
if manifest['family'] not in ('decisions', 'multilingual') or manifest['family'] != cohort['payload']['family']:
    raise ValueError('typed baseline bridge requires matching choice families; Q24 is not probabilities')
if manifest['dataset_sha256'] != c.sha_bytes((p/'sealed').read_bytes()):
    raise ValueError('manifest does not bind original sealed bytes')
if manifest['blind_dataset_sha256'] != c.sha_bytes(canonical_jsonl(blind_rows(rows, manifest['family']))):
    raise ValueError('manifest does not bind the original blinded input inventory')
observed, signed = b._check_baseline_receipt(packet, cohort, rows, p/'manifest', manifest, trust, p/'cohort')
print(json.dumps({'verification': verified, 'owner_signature_payload_sha256': signed,
                  'observations': observed}, sort_keys=True, allow_nan=False))
'''


def validate_baseline_plan(cfg):
    require(type(cfg) is dict and set(cfg) == {"profile", "owner_source_sha", "expected_descriptor_sha256",
            "owner_frozen_plan_sha256", "max_revalidation_age_us"}, "registered typed baseline profile required")
    require(cfg["profile"] == PROFILE and cfg["owner_source_sha"] == OWNER_SOURCE,
            "unsupported baseline owner/profile revision")
    sha(cfg["expected_descriptor_sha256"])
    sha(cfg["owner_frozen_plan_sha256"])
    integer(cfg["max_revalidation_age_us"], "baseline revalidation age", 0, 86_400_000_000)


def _micros(value):
    delta = timestamp(value) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def verify_owner(raw, owner_root, trust_path, trust_sha256):
    """Snapshot original bytes, then invoke the actual unmodified owner checks.

    owner_root and the public-key trust pin come from operator configuration,
    NOT from an evidence-selected script or the cohort's self-described keys.
    Private source/evidence roots are required; this is not a hostile-FS sandbox.
    """
    if owner_root is None or trust_path is None or trust_sha256 is None:
        raise FileNotFoundError("independently configured owner source and trust pin required")
    require(type(raw) is dict and set(raw) == {"cohort", "sealed", "manifest", "baseline"},
            "only original owner evidence may enter verifier")
    trust_path = Path(trust_path)
    trust = read_pinned(trust_path.parent, {"path": trust_path.name, "sha256": trust_sha256}, form="bytes")
    require(len(trust) <= MAX_OWNER_BYTES, "oversized baseline trust file")
    sources = {}
    for name, expected in OWNER_BLOBS.items():
        path = Path(owner_root) / "scripts" / name
        require(not path.parent.is_symlink() and not path.is_symlink(), "symlink verifier source")
        require(path.is_file() and path.stat().st_size <= MAX_OWNER_BYTES, "bounded verifier source required")
        data = path.read_bytes()
        require(len(data) <= MAX_OWNER_BYTES and hashlib.sha1(
            f"blob {len(data)}\0".encode() + data).hexdigest() == expected,
            "baseline verifier source drift")
        sources[name] = data
    with tempfile.TemporaryDirectory(prefix="hepta-baseline-verify-") as tmp:
        work = Path(tmp)
        for name, data in {**sources, **raw, "trust": trust}.items():
            require(name in set(OWNER_BLOBS) | {"cohort", "sealed", "manifest", "baseline", "trust"},
                    "unexpected verifier input")
            require(len(data) <= MAX_OWNER_BYTES, "oversized owner input")
            (work / name).write_bytes(data)
        # File-backed stdout is bounded before materialization; no unbounded PIPE.
        with (work / "stdout").open("wb") as stdout, (work / "stderr").open("wb") as stderr:
            try:
                process = subprocess.run([sys.executable, "-I", "-B", "-c", OWNER_DRIVER, trust_sha256],
                    cwd=work, stdout=stdout, stderr=stderr, timeout=30, check=False)
            except subprocess.TimeoutExpired as exc:
                raise ValueError("baseline owner verification time budget exhausted") from exc
        if process.returncode:
            # Never leak sealed labels/source text through exception diagnostics.
            raise ValueError("pinned baseline owner verification rejected original packet")
        output = work / "stdout"
        require(output.stat().st_size <= 16 * 1024 * 1024, "oversized owner verification output")
        return strict_loads(output.read_bytes())


def pair_verified(plan, dataset, trial, journal, cohort, sealed, packet, verified):
    """Pair original Cell trace with signed source IDs, never by guessed labels.

    Internal helper: public entry invokes verify_owner first. Candidate argmax is
    a shadow prediction rule, NOT evidence of deployed or authorized behavior.
    """
    cfg = plan["production_baseline"]
    validate_baseline_plan(cfg)
    payload = cohort["payload"]
    descriptor = payload["no_change"]
    require(digest(descriptor) == cfg["expected_descriptor_sha256"], "selected no-change descriptor drift")
    require(payload["frozen_plan_digest"] == cfg["owner_frozen_plan_sha256"], "owner frozen plan drift")
    require(payload["dataset"]["objective_digest"] == plan["objective_sha256"], "baseline objective drift")
    assessed = _micros(plan["assessment_time"])
    revalidated = payload["source_current_revalidated_at_unix_micros"]
    require(type(revalidated) is int and 0 <= assessed - revalidated <= cfg["max_revalidation_age_us"],
            "stale or future baseline source revalidation")
    signed = [s["signed_at_unix_micros"] for s in cohort["attestations"].values()]
    signed.append(packet["owner_signature"]["signed_at_unix_micros"])
    require(all(type(t) is int and revalidated <= t <= assessed for t in signed),
            "signature timestamp outside assessment")
    indexed, audit, changed = verify_cell_trace(dataset, trial, journal)
    original = {r["id"]: r for r in sealed}
    sources = {r["id"]: r for r in payload["rows"]}
    require(len(original) == len(sealed) and len(sources) == len(payload["rows"]), "duplicate owner source IDs")
    expected = {k for k, r in sources.items() if r["split"] in ("future_1", "future_2")}
    require(set(indexed) == expected, "Cell/owner future coverage differs; no subsetting by success")
    result = {w: {"rows": 0, "groups": set(), "no_change": {"selected": 0, "correct": 0,
        "abstained": 0, "slow_path": 0, "brier": None, "ece": None},
        **{a: {"correct": 0, "brier_sum": 0.0, "baseline_selected_pairs": 0,
               "better": 0, "worse": 0, "same": 0} for a in ("frozen", "trained")}}
        for w in ("future_1", "future_2")}
    observed = verified["observations"]
    for cid, item in indexed.items():
        row, source, gold = item["dataset"], sources[cid], original[cid]
        window = source["split"]
        require(row["future_window"] == window and row["group_id"] == source["source_group"],
                "Cell/source group or window changed")
        require(row.get("native_scope_digest") == descriptor["scope_digest"], "Cell/owner scope mismatch")
        for left, right in (("state", "state"), ("question", "question"), ("options", "option_order"),
                            ("language", "language"), ("domain", "domain")):
            require(row.get(left) == gold.get(right) and left in row and right in gold,
                    "Cell and production baseline did not observe identical input")
        options = row["options"]
        require(len(set(options)) == len(options) and gold["gold"] in options and
                type(row["label"]) is int and options[row["label"]] == gold["gold"], "sealed label/option mapping drift")
        require(_micros(row["event_time"]) == source["observed_at_unix_micros"], "Cell/source chronology drift")
        lo, hi = map(_micros, plan["windows"][window])
        require(lo <= source["observed_at_unix_micros"] <= source["terminal_at_unix_micros"] <= hi <= assessed,
                "unobserved or out-of-window terminal outcome")
        baseline = observed[cid]
        require(baseline["generation"] == descriptor["generation"], "baseline generation drift")
        disposition = baseline["disposition"]
        require(disposition in ("selected", "abstained", "slow_path"), "unsupported baseline disposition")
        require((disposition == "selected" and baseline["selected_option"] in options) or
                (disposition != "selected" and baseline["selected_option"] is None), "inconsistent baseline selection")
        stats = result[window]
        stats["rows"] += 1
        stats["groups"].add(source["source_group"])
        stats["no_change"][disposition] += 1
        old_correct = disposition == "selected" and baseline["selected_option"] == gold["gold"]
        stats["no_change"]["correct"] += int(old_correct)
        for arm in ("frozen", "trained"):
            correct, brier = measure(item[arm], row["label"])
            stats[arm]["correct"] += int(correct)
            stats[arm]["brier_sum"] += brier
            if disposition == "selected":
                stats[arm]["baseline_selected_pairs"] += 1
                stats[arm]["better" if correct > old_correct else "worse" if correct < old_correct else "same"] += 1
    for stats in result.values():
        stats["groups"] = len(stats["groups"])
        stats["source_floor_met"] = stats["groups"] >= plan["min_groups"]
        n, b = stats["rows"], stats["no_change"]
        b["coverage"] = b["selected"] / n
        b["selective_accuracy"] = b["correct"] / b["selected"] if b["selected"] else None
        b["correct_decision_coverage"] = b["correct"] / n
        for arm in ("frozen", "trained"):
            stats[arm]["accuracy"] = stats[arm]["correct"] / n
            stats[arm]["normalized_brier"] = stats[arm].pop("brier_sum") / n
    return {"status": "diagnostic_complete", "profile": PROFILE, "windows": result,
        "cell_trace_verified": True, "cell_weights_changed": changed,
        "candidate_trace_signature_verified": False, "candidate_input_delivery_authenticated": False,
        "dataset_digest": audit["dataset_digest"], "descriptor_sha256": digest(descriptor),
        "owner_verification": verified["verification"],
        "owner_signature_payload_sha256": verified["owner_signature_payload_sha256"],
        "candidate_behavior": "shadow_argmax_not_deployed_policy", "baseline_probabilities_fabricated": False,
        "replaces_probability_learning_gate": False, "scientific_superiority_established": False,
        "native_owner_currently_queried": False, "production_promotion_permitted": False}


def review_production_baseline(plan, refs, root, *, owner_root=None, trust_path=None, trust_sha256=None):
    validate_baseline_plan(plan["production_baseline"])
    require(type(refs) is dict and set(refs) == REFS, "complete original baseline and Cell references required")
    raw = {name: read_pinned(root, refs[name], form="bytes") for name in ("cohort", "sealed", "manifest", "baseline")}
    # Validate JSON/JSONL before invoking upstream code, without rewriting bytes.
    documents = {name: strict_loads(data) for name, data in raw.items() if name != "sealed"}
    lines = raw["sealed"].splitlines()
    require(0 < len(lines) <= 4096 and all(line.strip() for line in lines), "blank or oversized sealed cohort")
    sealed = [strict_loads(line) for line in lines]
    require(all(type(row) is dict for row in sealed), "sealed cohort must contain objects")
    verified = verify_owner(raw, owner_root, trust_path, trust_sha256)
    report = pair_verified(plan, read_pinned(root, refs["dataset"], form="jsonl"),
        read_pinned(root, refs["trial"]), read_pinned(root, refs["prelabel_journal"], form="bytes"),
        documents["cohort"], sealed, documents["baseline"], verified)

    report["original_file_sha256s"] = {name: ref["sha256"] for name, ref in refs.items()}
    report["verifier_source_sha"] = OWNER_SOURCE
    report["independent_trust_file_sha256"] = trust_sha256
    return report
