"""Read-only plan/identity review; no C2 outputs, model or curve execution."""

import hashlib
import json
from pathlib import Path
import time
import zipfile


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
EXPECTED = "4ccfa7cc21ec37312e48d095e8f4b7373c765dd6d33fa9314ce724d161e8b06b"


def ident(payload):
    return {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def save(name, value):
    payload = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    with (HERE / name).open("xb") as stream:
        stream.write(payload)
    return ident(payload)


def main():
    started, cpu = time.monotonic(), time.process_time()
    plan_path = WORK / "c2-resource-analysis-plan-v1/PLAN.json"
    raw = plan_path.read_bytes()
    assert ident(raw) == {"bytes": 8456, "sha256": EXPECTED}
    with (HERE / "INPUT-PLAN.json").open("xb") as stream:
        stream.write(raw)
    plan = json.loads(raw)
    inputs = {str(plan_path): ident(raw)}
    for path, expected in plan["fixed_inputs"].items():
        observed = ident(Path(path).read_bytes())
        assert observed == expected, path
        inputs[path] = observed
    snapshot = HERE / "source-context"
    snapshot.mkdir(exist_ok=False)
    for name in ("c2_runner.py", "c2_controller.py"):
        path = WORK / "c2-execution-candidate-v4" / name
        payload = path.read_bytes()
        inputs[str(path)] = ident(payload)
        with (snapshot / name).open("xb") as stream:
            stream.write(payload)
    checks = {
        "original_views": "Copy/hash-check prior original42 and separate C1 views; missing remains missing; no C2-selected LR or later score retrofitted into 300/900/1800.",
        "terminal_selection": "All six HCSN qualities independently verified before one all-three-seed mean/common LR; exact ties .001; no selected-seed or failed-fit deletion.",
        "training_scientific_separation": "Producer and independent adequacy shown separately; all selected seeds needed for an adequately trained comparison; numerical/scientific/P5 gates unchanged.",
        "crossing": "Original .30 target and first complete-epoch crossing retained; no before-training/epoch mixing, interpolation or successful-seed-only group median.",
        "costs": "All original and C1/C2 opportunities, discarded partial work and failures charged; final nonoverlapping outer scopes, parallel calendar and uncertainty in original final CPU remain distinct.",
        "memory": "Per-attempt observed RSS and max across chain only; not summed peaks, GPU VRAM or memory exactly at a quality crossing.",
        "chronology": "Explicitly written after C2 launch/three-epoch observations/one reported terminal; not retrospective experiment preregistration.",
        "access_budget": "Metadata only after all terminal or reviewed postmortem; separate 120-second/512MiB/single-worker/thread, no retry, E/model/oracle access forbidden.",
    }
    finding = {
        "id": "CLOCK-SCOPE-01",
        "severity": "implementation_precision_note_not_plan_blocker",
        "evidence": "c2_runner.epoch_clocks samples child elapsed once and returns cumulative_process_wall_seconds = parent_wall + elapsed. c2_controller finally records attempt_wrapper_wall_seconds and cumulative_parent_and_c2_active_wall_seconds separately.",
        "implication": "Epoch quality coordinates are parent complete outer plus child process-prefix time; final training cost is parent complete outer plus whole attempt-wrapper time. They are not identical clock scopes.",
        "required_reporting": "Label quality_clock_scope and terminal_cost_scope. Keep the original epoch timestamp; do not distribute or add the final wrapper difference to earlier target crossings. If exact wrapper-inclusive readiness is needed, state the unsupported offset/interval explicitly.",
        "requires_frozen_plan_change": False,
        "requires_model_or_curve_rerun": False,
    }
    for path, expected in inputs.items():
        assert ident(Path(path).read_bytes()) == expected, path
    result = {
        "schema": "hcsn-C2-resource-plan-independent-static-review-v1",
        "status": "no_blocking_plan_inconsistency_found",
        "review_scope": "Independent prose/rule review plus exact byte identities. No implementation or numerical/cost-curve result is approved by this preparation review.",
        "inputs": inputs,
        "input_bytes_unchanged": True,
        "checks": checks,
        "findings": [finding],
        "actual_C2_output_reads": 0,
        "E_reads": 0,
        "model_or_logits_reads": 0,
        "model_oracle_curve_executions": 0,
        "producer_mutations": 0,
        "execution_authorized_by_review": False,
        "scientific_admission": "HOLD",
        "whole_training_numerical_admission": "HOLD",
        "assembly_wall_prefix_seconds": time.monotonic() - started,
        "assembly_own_CPU_prefix_seconds": time.process_time() - cpu,
        "cost_scope": "Assembly prefix after interpreter imports; excludes manual reading, final serialization/archive and outer tool time. Complete manual-review/outer CPU and wall were not measured and remain unknown; no rerun was made to manufacture timing.",
    }
    save("RESULT.json", result)
    report = """# C2 resource-reporting plan: independent static review

**No blocking plan inconsistency found.** This is a read-only review of the frozen 8,456-byte plan and its declared identities, not execution of the future analysis. No actual C2 output, model, logits or E data was accessed.

The plan preserves both earlier budget views verbatim, retains missing observations and all opportunities, requires all six independently verified HCSN qualities before common-LR selection, and separates descriptive quality from training adequacy and numerical/scientific admission. The original .30 first-complete-epoch target remains fixed. It also distinguishes full attempt cost, parallel calendar, incomplete original CPU, observed RSS and unknown energy/billing. Its post-launch chronology and separate metadata-only 120-second/512MiB budget are explicit.

## One precision note for the later implementation

The frozen producer's epoch clocks report **parent full outer + child process prefix**. The controller's final attempt cost reports **parent full outer + full C2 attempt wrapper**. Preserve those named scopes. A final wrapper delta must not be distributed backward over earlier quality observations or silently treated as known crossing-time overhead. This needs clear fields in the eventual result; it does not require changing the frozen plan or rerunning any model/curve.

Exact inputs, the complete note and scope limits are in [RESULT.json](RESULT.json); [INPUT-PLAN.json](INPUT-PLAN.json) is the unchanged plan. The two frozen producer files are saved under `source-context/` solely to bind the clock definitions. All source checks here are metadata integrity checks, not new behavior tests or scientific qualification.
"""
    with (HERE / "REPORT.md").open("x") as stream:
        stream.write(report)
    files = {str(path.relative_to(HERE)): ident(path.read_bytes()) for path in sorted(HERE.rglob("*")) if path.is_file()}
    save("MANIFEST.json", {"schema": "hcsn-independent-plan-review-manifest-v1", "files": files})
    target = HERE.with_suffix(".zip")
    with zipfile.ZipFile(target, "x", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(HERE.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(HERE))
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == len(set(archive.namelist())) == len(files) + 1
        for name, expected in files.items():
            assert ident(archive.read(name)) == expected
    print(json.dumps({"directory": str(HERE), "RESULT": ident((HERE / "RESULT.json").read_bytes()), "manifest": ident((HERE / "MANIFEST.json").read_bytes()), "zip": {"path": str(target), **ident(target.read_bytes())}}, sort_keys=True))


if __name__ == "__main__":
    main()
