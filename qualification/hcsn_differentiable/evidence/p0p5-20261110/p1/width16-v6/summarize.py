"""Aggregate execution, numerical status and scientific admission separately."""
import hashlib
import json
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads((root / path).read_text())


stages = ["export", "training-audit", "eval-A01-0", "eval-A01-256", "eval-A04-3072"] + [f"finite-{i}" for i in range(5)]
plan = read("plan.json")
independent = read("independent-review/width16-law-binding-v1.json")
assert independent["passed"] and all(row["passed"] for row in independent["checks"])
receipts = {stage: read(f"{stage}-receipt.json") for stage in stages}
assert all(r["source_unchanged"] and r["source_before"] == plan["source_before"]
           and r["source_after"] == plan["source_before"] and r["status"].startswith("completed")
           for r in receipts.values())
assert receipts["export"]["wrapper_unchanged"]
audit_rows, failures = [], []
for stage in stages[1:5]:
    receipt, audit = receipts[stage], read(f"{stage}.json")
    assert receipt["audit_sha256"] == sha(root / f"{stage}.json")
    assert audit["source_matches_trace"] and audit["complete_retained_coverage"]
    assert all(row["status"] in ("passed", "failed") for row in audit["visits"])
    assert sum(row["gradient_posterior_count"] for row in audit["visits"]) == audit["audited_records"]
    failed = [{"stage": stage, "index": row["index"], "dt": row["dt"],
               "scaled_value_error": row["maximum_scaled_value_error"]}
              for row in audit["visits"] if row["status"] == "failed"]
    failures.extend(failed)
    audit_rows.append({"stage": stage, "artifact": f"{stage}.json", "sha256": sha(root / f"{stage}.json"),
        "numerical_status": audit["status"], "records": audit["audited_records"],
        "passed_records": sum(row["status"] == "passed" for row in audit["visits"]),
        "failed_records": len(failed), "source_matches_trace": True, "complete_retained_coverage": True,
        "maximum_scaled_value_error": max(row["maximum_scaled_value_error"] for row in audit["visits"]),
        "maximum_basis_gradient_absolute_error": max(row["maximum_basis_gradient_absolute_error"] for row in audit["visits"]),
        "maximum_mass_error": max(row["maximum_mass_error"] for row in audit["visits"])})
finite_rows = []
for index, fixture in enumerate(plan["finite_fixtures"]):
    stage = f"finite-{index}"
    receipt, result = receipts[stage], read(f"{stage}.json")
    assert receipt["result_sha256"] == sha(root / f"{stage}.json")
    assert result["fixture"] == fixture
    digest = hashlib.sha256(json.dumps(result["inputs"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert result["inputs_sha256"] == digest
    passed = (max(result["scaled_errors"]) <= .01 and result["mass_residual"] <= 5e-11
              and result["reference_refinement_delta"] <= 2e-8)
    assert (result["status"] == "passed_fixture") == passed
    finite_rows.append({"stage": stage, "fixture": fixture, "artifact": f"{stage}.json",
        "sha256": sha(root / f"{stage}.json"), "numerical_status": result["status"],
        **{k: result[k] for k in ("projected", "reference", "scaled_errors", "horizon", "mass_residual", "reference_refinement_delta")}})
summary = {"schema": "hcsn-width16-independent-audit-summary-v1", "execution_status": "completed_all_declared_stages",
    "scientific_admission": "HOLD", "whole_training_domain_admission": "HOLD",
    "training_adequacy_established": False, "plan_sha256": sha(root / "plan.json"),
    "checkpoint_sha256": plan["checkpoint_sha256"], "training_trace_sha256": plan["training_trace_sha256"],
    "data_manifest_sha256": plan["data_manifest_sha256"], "source_unchanged_all_stages": True,
    "actual_training_updates": 2, "optimizer": "AdamW, learning rate .003, weight decay 0, gradient clip norm 1",
    "model": plan["model"], "grid": plan["grid"],
    "audit_records": audit_rows, "pressure_failures": failures, "finite_fixtures": finite_rows,
    "finite_fixture_all_passed": all(row["numerical_status"] == "passed_fixture" for row in finite_rows),
    "perpetual_pressure_all_passed": not failures,
    "visitation_summary_sha256": sha(root / "visitation-summary.json"),
    "independent_input_binding_review": {"passed": True, "checks": len(independent["checks"]),
        "artifact": "independent-review/width16-law-binding-v1.json",
        "sha256": sha(root / "independent-review/width16-law-binding-v1.json"),
        "scope": independent["scope"], "slow_oracles_recomputed": False},
    "error_scale": "abs(candidate-reference)/max(1,abs(reference)); subunit quantities are tested in absolute error, not relative tail error.",
    "reference": "Independent 80-digit renewal formulas; 8/16 Gaussian quadrature sensitivity, not a certified error bound.",
    "scope": "512 actual training visits at zero/one update and 768 supplementary evaluations after two updates. Finite shadow fixtures disable future observations. This is not an adequately trained or complete-task qualification.",
    "cost": {"stage_wall_seconds": {stage: r["wall_seconds"] for stage, r in receipts.items()},
             "sum_stage_wall_seconds": sum(r["wall_seconds"] for r in receipts.values()),
             "maximum_stage_rss_kib_linux": max(r["maximum_resident_kib_linux"] for r in receipts.values()),
             "energy_joules": None, "currency_cost": None,
             "concurrency": "Audit stages ran serially, one torch CPU thread each; possible overlap with fixed-update PLIF diagnostic is disclosed in UTC launch records. Not a fair-training timing comparison."}}
(root / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
readme = """# Independent audit of the trained width-16 HCSN adapter model

Read summary.json for separate execution, numerical and scientific status.
The exact checkpoint follows two full 256-event A01-0 AdamW updates using the
common frozen frontend/head and a learned output-coordinate adapter. The
training-probe directory retains the original checkpoint, trace, source receipt,
plan and logs. Its source hashes were checked before this independent audit.
The independent-review directory retains a second agent's five source,
checkpoint, training/evaluation identity and exact law/schedule binding checks.

The 512 training visits are distinct from the 768 supplementary evaluations of
the final checkpoint on A01-0, A01-256 and A04-3072. A forward hook reads the
same network result used by the actual wrapper and recorder. Recorded laws and
future schedules in finite checks are bound in full, with exact rewards/grid/
physical configuration. All tested source bytes are in the isolated source tree.

Every retained state receives the perpetual constant-gap pressure comparison.
This repeats its positive gap forever (zero gaps use the disclosed d/2 probe).
That pressure test is distinct from actual finite schedules. In particular,
the two tiny A04 intervals must not be removed from the failure ledger if their
pressure test fails, even when the real 8/32-gap burst passes its finite check.

Value, count, discounted count and active probability use the scale
abs(candidate-reference)/max(1,abs(reference)). Small counts therefore use an
absolute error threshold. Reference quadrature doubling is measured sensitivity,
not a rigorous error bound. Finite shadows have no future observation updates.

Source identity, complete retained coverage and every numerical result are
validated during aggregation. A stage marked completed or exiting zero merely
finished the calculation; its audit_status/fixture_status can still be HOLD.
Scientific and whole-training-domain admission remain HOLD. These two repeated
windows are not sufficient training and do not establish a task benefit.

For reproduction use the pinned cloud study runtime described by the separate
runtime evidence asset. Copy runner.py and the isolated source tree with plan,
data and training-probe inputs into a fresh sibling experiment directory, then
run export and the nine audit/finite stage names listed in summarize.py. Do not
overwrite retained results. launch_stage.py records UTC/process boundaries and
discloses possible concurrent diagnostic work. The final summary includes the
sum of measured stage durations; these are audit costs, not training speed or
energy measurements.
"""
(root / "README.md").write_text(readme)
files = {str(p.relative_to(root)): {"bytes": p.stat().st_size, "sha256": sha(p)}
    for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts and p.name != "manifest.json"}
(root / "manifest.json").write_text(json.dumps({"schema": "hcsn-width16-audit-artifact-manifest-v1", "files": files}, indent=2) + "\n")
archive = root.parent / "hcsn-width16-v6-audit-20261110.zip"
with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED, compresslevel=9) as stream:
    for relative in [*files, "manifest.json"]:
        stream.write(root / relative, str(Path(root.name) / relative))
with zipfile.ZipFile(archive) as stream:
    assert stream.testzip() is None
    for relative, entry in files.items():
        payload = stream.read(str(Path(root.name) / relative))
        assert len(payload) == entry["bytes"] and hashlib.sha256(payload).hexdigest() == entry["sha256"]
receipt = {"archive": str(archive), "bytes": archive.stat().st_size, "sha256": sha(archive),
           "summary_sha256": sha(root / "summary.json"), "manifest_sha256": sha(root / "manifest.json"),
           "files": len(files) + 1, "verification": "All ZIP CRCs and file byte sizes/SHA256 checked"}
(root.parent / "hcsn-width16-v6-audit-20261110-archive-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps(receipt, indent=2))
