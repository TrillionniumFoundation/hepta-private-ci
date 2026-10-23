"""Locked experiment identities, without arbitrary plan or opening-marker paths.

Each identity is a separate prospective claim. In particular, core-c1 neither
changes efficient-r2 gates nor permits reuse of its data or opening marker.
"""

from dataclasses import dataclass
import hashlib
from pathlib import Path


EXPERIMENTS = ("efficient-r2", "core-c1", "codec-train-d1")
_SYSTEMS = ("supervised", "anchor", "additive", "ndu", "ndu_control")
_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ExperimentProfile:
    name: str
    plan_path: Path
    marker_path: Path
    systems: tuple
    family: str = "efficient"
    can_evaluate: bool = True


def resolve_experiment(name="efficient-r2", *, root=None):
    """Resolve only a predefined identity; callers cannot inject marker paths."""
    if type(name) is not str or name not in EXPERIMENTS:
        raise ValueError("unknown fixed experiment identity")
    root = _ROOT if root is None else Path(root)
    if name == "efficient-r2":
        return ExperimentProfile(name, root / "independent/plan.json",
                                 root / "independent/efficient-r2-test-opened.json", _SYSTEMS)
    if name == "core-c1":
        return ExperimentProfile(name, root / "core_confirmation/plan.json",
                                 root / "core_confirmation/core-c1-test-opened.json", _SYSTEMS[:-1], "core-content")
    return ExperimentProfile(name, root / "training_diagnostics/codec-d1/plan.json",
                             root / "training_diagnostics/codec-d1/NO_FORMAL_EVALUATION",
                             _SYSTEMS[:-1], "core-content", False)


def bind_identity(profile, receipt):
    """Legacy receipts without an identity belong exclusively to efficient-r2."""
    identity = receipt.get("experiment_id", "efficient-r2")
    if identity != profile.name:
        raise ValueError("frozen experiment identity changed")


def validate_plan(profile, plan):
    bind_identity(profile, plan)
    if "systems" in plan and tuple(plan["systems"]) != profile.systems:
        raise ValueError("experiment requires its exact predefined systems")
    if profile.family == "core-content":
        if (tuple(plan.get("systems", ())) != profile.systems
                or plan.get("static_modes") != ["full"]
                or "controller" in plan
                or plan.get("control_reserve_units") != 0
                or plan.get("control_reserve_cpu_seconds") != 0):
            raise ValueError("content profile requires four full-view content arms without a controller")
        document = profile.plan_path.parent / "PROTOCOL.md"
        expected = ("core_confirmation/PROTOCOL.md" if profile.can_evaluate
                    else "training_diagnostics/codec-d1/PROTOCOL.md")
        if (plan.get("protocol_path") != expected
                or not document.is_file() or document.is_symlink()
                or hashlib.sha256(document.read_bytes()).hexdigest() != plan.get("protocol_sha256")):
            raise ValueError("content protocol document bytes changed")
    if not profile.can_evaluate:
        config = plan.get("training_diagnostic", {})
        if (plan.get("qualification_eligible") is not False
                or config.get("parent_train_seed") != 304797655
                or config.get("fit_sources_per_class") != 12
                or config.get("monitor_sources_per_class") != 4
                or config.get("source_partition_salt") != "hepta-codec-d1-train-source-partition-v1"
                or config.get("prefix_checkpoint_steps") != [1, 32]
                or config.get("build_order") != ["rowwise-png-v1", "local-png-codebook-v1",
                                                  "local-png-codebook-v1", "rowwise-png-v1"]):
            raise ValueError("fixed TRAIN-only diagnostic scope changed")
        driver = plan.get("diagnostic_driver", {})
        path = profile.plan_path.parent / "run_once.py"
        if (driver.get("path") != "training_diagnostics/codec-d1/run_once.py"
                or not path.is_file() or path.is_symlink()
                or hashlib.sha256(path.read_bytes()).hexdigest() != driver.get("sha256")):
            raise ValueError("diagnostic driver bytes changed")
