"""Bind every executable source and prepared model before fresh confirmation."""

from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import platform
import sys

from ..run import digest, write_json


PROJECT = Path(__file__).resolve().parent
BASE = PROJECT.parent
REPO = PROJECT.parents[2]
PREPARED = ("training", "native", "feedback_prepared", "calibration_prepared")


def sources():
    return sorted(path for directory in (BASE, BASE / "round2", PROJECT)
                  for path in directory.iterdir() if path.is_file()
                  and path.suffix in {".py", ".rs", ".json", ".md", ".txt"}
                  and path.name != "README.md")


def freeze(run_dir, source_commit):
    run_dir = Path(run_dir).resolve()
    if len(source_commit) != 40 or any(c not in "0123456789abcdef" for c in source_commit):
        raise ValueError("A full published Git commit identity is required")
    if (run_dir / "FREEZE.json").exists():
        raise ValueError("Freeze is immutable")
    if any((run_dir / name).exists() for name in
           ("main", "feedback_confirmation", "calibration_confirmation", "runtime_confirmation")):
        raise ValueError("Confirmation output exists before freeze")
    protocol = json.loads((PROJECT / "PROTOCOL.json").read_text())
    for seed in protocol["training_seeds"]:
        model_file = run_dir / "training" / f"seed_{seed}" / "MODELS.json"
        models = json.loads(model_file.read_text())
        if not {"analytic", "history", "native", "event_adaptive", "event_direct",
                "event_fixed", "event_no_residual", "event_round2"}.issubset(models):
            raise ValueError("Required trained models missing")
        if not (run_dir / "feedback_prepared" / f"seed_{seed}" / "MODELS.json").is_file():
            raise ValueError("Feedback training must finish before freeze")
    if not (run_dir / "calibration_prepared" / "PREPARED.json").is_file():
        raise ValueError("All retention checkpoints must precede confirmation")
    files = sorted(p for name in PREPARED for p in (run_dir / name).rglob("*") if p.is_file())
    result = {"schema": "hepta.analytic-event.round3.freeze.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "base_commit": protocol["base_commit"], "source_commit": source_commit,
        "protocol_sha256": digest(PROJECT / "PROTOCOL.json"),
        "sources_sha256": {str(p.relative_to(REPO)): digest(p) for p in sources()},
        "artifacts_sha256": {str(p.relative_to(run_dir)): digest(p) for p in files},
        "environment": {"python": sys.version, "platform": platform.platform(),
            "packages": {name: importlib.metadata.version(name) for name in ("numpy", "scipy", "Pillow")}},
        "confirmation_generated_before_freeze": False,
        "prior_confirmation_not_used_for_fitting": True,
        "publication_scope": "source commit includes frozen source and prepared model artifacts"}
    write_json(run_dir / "FREEZE.json", result)
    return result


def verify(run_dir):
    run_dir = Path(run_dir).resolve()
    result = json.loads((run_dir / "FREEZE.json").read_text())
    if {str(p.relative_to(REPO)) for p in sources()} != set(result["sources_sha256"]):
        raise ValueError("Scientific source inventory changed after freeze")
    if digest(PROJECT / "PROTOCOL.json") != result["protocol_sha256"]:
        raise ValueError("Frozen protocol digest differs")
    for key, root in (("sources_sha256", REPO), ("artifacts_sha256", run_dir)):
        if not result[key]:
            raise ValueError("Empty freeze binding")
        for relative, expected in result[key].items():
            path = (root / relative).resolve()
            if not path.is_relative_to(root) or digest(path) != expected:
                raise ValueError("Frozen bytes changed: " + relative)
    return result
