"""Create-only source/decision/roster freeze. Does not run a scalar case."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent


def identity(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def save(name, value):
    with (ROOT / name).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def main():
    source = ROOT / "source-inputs"
    source.mkdir(exist_ok=False)
    originals = {
        "operator.py": WORK / "v8-local-validation/source/qualification/hcsn_differentiable/operator.py",
        "analytic-NOTE.md": WORK / "p1-fixed-grid-short-time-diagnosis-v1/NOTE.md",
        "SOURCE-INDEX.json": WORK / "p1-fixed-grid-short-time-diagnosis-v1/SOURCE-INDEX.json",
    }
    inputs = {}
    for name, path in originals.items():
        with (source / name).open("xb") as stream:
            stream.write(path.read_bytes())
        inputs[name] = {"path": str(path), **identity(path)}
    plan = WORK / "p1-fixed-grid-short-time-diagnosis-v1/FOLLOWUP-PLAN.json"
    with (ROOT / "FOLLOWUP-PLAN.json").open("xb") as stream:
        stream.write(plan.read_bytes())
    inputs["FOLLOWUP-PLAN.json"] = {"path": str(plan), **identity(plan)}
    assert json.loads(plan.read_text())["execution_authorized"] is False
    roster = []
    for cells in (128, 256):
        for order in (16, 32, 64):
            for label, factor in (("star1e-4", 1e-4), ("star1e-2", 1e-2), ("star1", 1.), ("star1e2", 1e2), ("star1e4", 1e4)):
                roster.append({"id": f"active-n{cells}-q{order}-{label}", "kind": "active", "width": 4.8 / cells, "order": order, "h": None, "h_star_factor": factor})
            for label, h in (("h1e-7", 1e-7), ("h8e-7", 8e-7)):
                roster.append({"id": f"active-n{cells}-q{order}-{label}", "kind": "active", "width": 4.8 / cells, "order": order, "h": h, "h_star_factor": None})
    for ratio in (.5, .25, .125, .0625):
        roster.append({"id": f"phase-ratio{ratio}", "kind": "phase", "h_over_width": ratio})
    for shift in (0., 1.):
        roster.append({"id": f"tail-shift{shift:g}", "kind": "tail", "shift": shift})
    assert len(roster) == len({case["id"] for case in roster}) == 48
    save("ROSTER.json", {"schema": "hcsn-fixed48-scalar-roster-v1", "cases": roster, "result_values_observed": False})
    code = {}
    for path in sorted(ROOT.glob("*.py")):
        compile(path.read_bytes(), str(path), "exec")
        code[path.name] = identity(path)
    save("ROOT-DECISION-TRANSCRIPTION.json", {
        "schema": "hcsn-parent-authorized-scalar-execution-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "authority": "/root collaboration task message",
        "provenance": "Assistant transcript of explicit parent instruction, not a signed external policy object.",
        "instruction": "After uploader/progress read-only review, implement and execute the fixed48 scalar toy design once in new exclusive source/execution directories;120s whole hard wall,256MiB,standard library,one worker/thread,zero retries. Preserve original design false-authorization snapshot; freeze code before execution. No models,posterior,E,native training or original audit. No training-domain qualification or decomposition of real pressure-value errors.",
        "execution_authorized": True,
        "maximum_runs": 1,
        "key": "hcsn-p1-short-time-scalar-c385-v1",
        "scope": "exact fixed48 toy roster only",
        "whole_wall_seconds": 120,
        "RSS_bytes": 268435456,
        "workers": 1,
        "threads": 1,
        "automatic_retry": False,
        "original_plan_identity": inputs["FOLLOWUP-PLAN.json"],
        "code_identities_before_run": code,
        "numerical_qualification_granted": False,
        "scientific_or_P5_benefit_granted": False,
    })
    save("INPUTS.json", {"files": inputs, "scope": "frozen source and analytic documents only; no live data or model access"})
    for item in inputs.values():
        assert identity(Path(item["path"])) == {key: item[key] for key in ("bytes", "sha256")}
    entries = {str(path.relative_to(ROOT)): identity(path) for path in sorted(ROOT.rglob("*")) if path.is_file()}
    save("PROGRAM-MANIFEST.json", {"schema": "hcsn-fixed48-scalar-program-manifest-v1", "files": entries})
    target = ROOT.with_suffix(".zip")
    with zipfile.ZipFile(target, "x", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(ROOT))
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
    print(json.dumps({"program": str(ROOT), "manifest": identity(ROOT / "PROGRAM-MANIFEST.json"), "program_zip": {"path": str(target), **identity(target)}, "code": code, "scalar_cases_executed": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
