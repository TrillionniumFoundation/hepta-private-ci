"""Bind the registered source and prepared observations before confirmation."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys


PROJECT = Path(__file__).resolve().parent
REPO = PROJECT.parents[2]
OLD_FREEZE = PROJECT.parent / "round3/evidence/FREEZE.json"
PREPARED = ("calibration_prepared", "runtime_prepared", "runtime_bridge_prepared", "native")
CONFIRMATION = ("calibration_confirmation", "runtime_confirmation", "runtime_qualification")


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def scientific_sources():
    old = json.loads(OLD_FREEZE.read_text())["sources_sha256"]
    paths = {relative: REPO / relative for relative in old}
    for path in PROJECT.iterdir():
        if path.is_file() and path.suffix in {".py", ".json", ".md"} and path.name != "README.md":
            paths[str(path.relative_to(REPO))] = path
    return dict(sorted(paths.items()))


def verify_old_sources():
    old = json.loads(OLD_FREEZE.read_text())
    for relative, expected in old["sources_sha256"].items():
        if digest(REPO / relative) != expected:
            raise ValueError("Round3 frozen source changed: " + relative)
    return {"round3_source_files_unchanged": len(old["sources_sha256"]),
            "round3_freeze_sha256": digest(OLD_FREEZE)}


def freeze(run_dir, source_commit):
    run_dir = Path(run_dir).resolve()
    if len(source_commit) != 40 or any(c not in "0123456789abcdef" for c in source_commit):
        raise ValueError("A full published commit identity is required")
    if (run_dir / "FREEZE.json").exists():
        raise FileExistsError("Freeze is immutable")
    if any((run_dir / name).exists() for name in CONFIRMATION):
        raise ValueError("Confirmation output must not precede freeze")
    previous = verify_old_sources()
    files = sorted(path for directory in PREPARED for path in (run_dir / directory).rglob("*")
                   if path.is_file() and "__pycache__" not in path.parts)
    for directory in PREPARED:
        if not any(path.is_relative_to(run_dir / directory) for path in files):
            raise ValueError("Missing prepared collection: " + directory)
    review = run_dir / "validation/PREFREEZE_REVIEW.json"
    if not review.is_file() or json.loads(review.read_text()).get("passed") is not True:
        raise ValueError("Independent preconfirmation review must pass")
    sources = scientific_sources()
    source_hashes = {name: digest(path) for name, path in sources.items()}
    reviewed = json.loads(review.read_text())
    if reviewed.get("source_sha256") != source_hashes:
        raise ValueError("Passed review does not bind the current scientific source")
    bridge = reviewed.get("calibration_runtime_bridge", {}).get("artifacts_sha256", {})
    if not bridge or any(digest(run_dir / relative) != expected for relative, expected in bridge.items()):
        raise ValueError("Passed review does not bind the current conditioning bridge")
    result = {
        "schema": "hepta.analytic-event.round4.freeze.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "base_commit": "ad83ccf383baaca8a346a871d51dbbac51c9873d",
        "source_commit": source_commit,
        "protocol_sha256": digest(PROJECT / "PROTOCOL.json"),
        "sources_sha256": source_hashes,
        "artifacts_sha256": {str(path.relative_to(run_dir)): digest(path) for path in files},
        "prefreeze_review_sha256": digest(review),
        "previous_round": previous,
        "environment": {"python": sys.version, "platform": platform.platform(),
                        "packages": {name: importlib.metadata.version(name)
                                     for name in ("numpy", "scipy", "Pillow")}},
        "confirmation_generated_before_freeze": False,
        "prior_confirmation_not_used_for_fitting": True,
        "source_and_prepared_artifacts_published_before_confirmation": True,
    }
    write_json(run_dir / "FREEZE.json", result)
    return result


def verify(run_dir):
    run_dir = Path(run_dir).resolve()
    frozen = json.loads((run_dir / "FREEZE.json").read_text())
    if set(scientific_sources()) != set(frozen["sources_sha256"]):
        raise ValueError("Scientific source inventory changed")
    for key, root in (("sources_sha256", REPO), ("artifacts_sha256", run_dir)):
        for relative, expected in frozen[key].items():
            path = (root / relative).resolve()
            if not path.is_relative_to(root) or digest(path) != expected:
                raise ValueError("Frozen bytes changed: " + relative)
    if digest(PROJECT / "PROTOCOL.json") != frozen["protocol_sha256"]:
        raise ValueError("Frozen protocol changed")
    return frozen


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--source-commit")
    args = parser.parse_args()
    result = freeze(args.run_dir, args.source_commit) if args.source_commit else verify(args.run_dir)
    print(json.dumps({"source_commit": result["source_commit"],
                      "source_files": len(result["sources_sha256"]),
                      "prepared_files": len(result["artifacts_sha256"])}))
