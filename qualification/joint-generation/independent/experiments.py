"""Locked experiment identities, without arbitrary plan or opening-marker paths.

Each identity is a separate prospective claim. In particular, core-c1 neither
changes efficient-r2 gates nor permits reuse of its data or opening marker.
"""

from dataclasses import dataclass
import hashlib
from pathlib import Path


EXPERIMENTS = ("efficient-r2", "core-c1")
_SYSTEMS = ("supervised", "anchor", "additive", "ndu", "ndu_control")
_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ExperimentProfile:
    name: str
    plan_path: Path
    marker_path: Path
    systems: tuple


def resolve_experiment(name="efficient-r2", *, root=None):
    """Resolve only a predefined identity; callers cannot inject marker paths."""
    if type(name) is not str or name not in EXPERIMENTS:
        raise ValueError("unknown fixed experiment identity")
    root = _ROOT if root is None else Path(root)
    if name == "efficient-r2":
        return ExperimentProfile(name, root / "independent/plan.json",
                                 root / "independent/efficient-r2-test-opened.json", _SYSTEMS)
    return ExperimentProfile(name, root / "core_confirmation/plan.json",
                             root / "core_confirmation/core-c1-test-opened.json", _SYSTEMS[:-1])


def bind_identity(profile, receipt):
    """Legacy receipts without an identity belong exclusively to efficient-r2."""
    identity = receipt.get("experiment_id", "efficient-r2")
    if identity != profile.name:
        raise ValueError("frozen experiment identity changed")


def validate_plan(profile, plan):
    bind_identity(profile, plan)
    if "systems" in plan and tuple(plan["systems"]) != profile.systems:
        raise ValueError("experiment requires its exact predefined systems")
    if profile.name == "core-c1":
        if (tuple(plan.get("systems", ())) != profile.systems
                or plan.get("static_modes") != ["full"]
                or "controller" in plan
                or plan.get("control_reserve_units") != 0
                or plan.get("control_reserve_cpu_seconds") != 0):
            raise ValueError("core-c1 requires four full-view content arms without a controller")
        document = profile.plan_path.parent / "PROTOCOL.md"
        if (plan.get("protocol_path") != "core_confirmation/PROTOCOL.md"
                or not document.is_file() or document.is_symlink()
                or hashlib.sha256(document.read_bytes()).hexdigest() != plan.get("protocol_sha256")):
            raise ValueError("core-c1 protocol document bytes changed")
