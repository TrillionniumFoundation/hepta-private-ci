"""Package exact additive evidence and pinned baseline source without Git metadata."""

import argparse
import hashlib
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[2]
ADDITIVE = (
    "hcsn_addressed_continuation_20261101",
    "hcsn_missing_answers_20261101",
    "hcsn_joint_dynamics_20261101",
    "hcsn_propagation_perf_20261101",
    "hcsn_video_followup_20261101",
)
INHERITED = (
    "hcsn_addressed_flow_20261101",
    "hcsn_four_stage_flow_20261031",
    "hcsn_distributional_v2",
)


def files():
    chosen = []
    for name in ADDITIVE:
        for path in (ROOT / "experiments" / name).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and "transport" not in path.parts:
                if path.name not in ("PACKAGE_MANIFEST.json", "EVIDENCE_TRANSPORT.json"):
                    chosen.append(path)
    for name in INHERITED:
        for path in (ROOT / "experiments" / name).iterdir():
            if path.is_file() and path.suffix in (".py", ".json", ".md"):
                chosen.append(path)
    return sorted(set(chosen))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    manifest = {
        "schema": "hcsn-addressed-continuation-package.v1",
        "baseline_commit": "a793d55c23a7742378b081b162252da428a9fdb2",
        "scope": "All additive outputs, failed attempts, checkpoints, derived inputs; pinned inherited source. No raw media or Git credentials.",
        "files": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files():
            data = path.read_bytes()
            relative = path.relative_to(ROOT).as_posix()
            archive.writestr(relative, data)
            manifest["files"].append({"path": relative, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        archive.writestr("PACKAGE_MANIFEST.json", json.dumps(manifest, indent=2) + "\n")
    with zipfile.ZipFile(args.output) as archive:
        assert archive.testzip() is None
        for record in manifest["files"]:
            data = archive.read(record["path"])
            assert len(data) == record["bytes"] and hashlib.sha256(data).hexdigest() == record["sha256"]
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    print(json.dumps({"path": str(args.output.resolve()), "files": len(manifest["files"]), "bytes": args.output.stat().st_size, "sha256": digest, "verified": True}))


if __name__ == "__main__":
    main()
