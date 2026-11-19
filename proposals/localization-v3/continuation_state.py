"""Fail-closed parent identities and stopping state for epoch continuation."""

import ast
import hashlib
import json
import math
from pathlib import Path

import torch


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def plateau_state(epochs, delta):
    best, best_epoch, anchor, stale = -1.0, None, -1.0, 0
    for number, row in enumerate(epochs, 1):
        if row["epoch"] != number or not row.get("complete", True):
            raise ValueError("only a contiguous complete epoch prefix can continue")
        score = row["development"]["macro_f1_11_classes"]
        if not math.isfinite(score):
            raise ValueError("nonfinite inherited development score")
        if score > best:
            best, best_epoch = score, number
        if score > anchor + delta:
            anchor, stale = score, 0
        else:
            stale += 1
    return best, best_epoch, anchor, stale


def _load_parent(parent_dir, parent_outer_record):
    parent = Path(parent_dir).resolve()
    outer = json.loads(Path(parent_outer_record).read_text())
    report = json.loads((parent / "result.json").read_text())
    if (
        outer.get("name") != parent.name
        or outer.get("status") != "completed"
        or outer.get("returncode") != 0
        or outer.get("fit_status") != "completed_development"
        or outer.get("source_unchanged") is not True
        or outer.get("common_weights_unchanged") is not True
        or outer.get("result_sha256") != sha((parent / "result.json").read_bytes())
        or not math.isfinite(outer.get("whole_process_wall_seconds", float("nan")))
        or outer["whole_process_wall_seconds"] <= 0
        or report.get("status") != "completed_development"
        or report.get("stop_reason") != "epoch_cap_not_convergence"
        or report.get("source_unchanged") is not True
        or report.get("common_weights_unchanged") is not True
        or not report.get("epochs")
        or "model_configuration" not in report
    ):
        raise ValueError("parent is not a verified completed v8 epoch-cap attempt")
    identities = {
        "plan.json": "plan_sha256",
        "initial.pt": "initialization_sha256",
        "last.pt": "last_checkpoint_sha256",
        "best.pt": "best_checkpoint_sha256",
        "events.jsonl": "events_sha256",
    }
    for name, field in identities.items():
        if sha((parent / name).read_bytes()) != report[field]:
            raise ValueError("parent artifact changed: " + name)
    for name, digest in report["source_before"].items():
        if not Path(name).is_file() or sha(Path(name).read_bytes()) != digest:
            raise ValueError("original parent source is no longer exact: " + name)
    if report["source_after"] != report["source_before"]:
        raise ValueError("parent source receipt is inconsistent")
    plan = json.loads((parent / "plan.json").read_text())
    if plan["train_shared"] or len(report["epochs"]) != plan["max_epochs"]:
        raise ValueError(
            "only the frozen-shared complete epoch-cap regime is supported"
        )
    if any(row.get("complete") is not True for row in report["epochs"]):
        raise ValueError("parent contains an incomplete epoch")
    plif = plan.get("plif_config_json")
    if plan["arm"] == "snn_plif" and plif is None:
        plif = {
            "init_tau": 2.0,
            "threshold": 1.0,
            "input_weight_gain": 1.0,
            "readout": "spikes",
            "trace_decay": 0.75,
        }
    expected_configuration = {
        "arm": plan["arm"],
        "width": plan["width"],
        "seed": plan["seed"],
        "s4_repo": str(plan["s4_repo"]) if plan["s4_repo"] is not None else None,
        "hcsn_grid": plan["hcsn_grid_json"],
        "freeze_shared": not plan["train_shared"],
        "cache_frozen_tables": plan["cache_frozen_tables"],
        "learn_core_adapter": plan["learn_core_adapter"],
        "plif_configuration": plif if plan["arm"] == "snn_plif" else None,
    }
    if report["model_configuration"] != expected_configuration:
        raise ValueError(
            "checkpoint dynamics differ from the original independent plan"
        )
    inherited = plateau_state(report["epochs"], plan["plateau_delta"])
    if inherited[1] != report["best_epoch"]:
        raise ValueError("parent strict-best epoch is inconsistent")
    checkpoint = torch.load(parent / "last.pt", weights_only=False)
    if (
        checkpoint["epochs_completed"] != len(report["epochs"])
        or checkpoint["main_updates"] != report["main_updates"]
        or checkpoint["data_manifest_sha256"] != plan["manifest_sha256"]
        or checkpoint["model_configuration"] != report["model_configuration"]
        or checkpoint.get("optimizer") is None
    ):
        raise ValueError("last checkpoint is not the declared complete epoch boundary")
    return parent, outer, report, plan, checkpoint, inherited


def load_parent(parent_dir, parent_outer_record):
    try:
        return _load_parent(parent_dir, parent_outer_record)
    except ValueError:
        raise
    except (KeyError, TypeError, OSError) as error:
        raise ValueError("invalid or missing parent evidence") from error


def source_equivalence(current, original):
    """Allow recorded formatting only in inherited repository Python code."""
    checks = {}
    for name in current:
        path = Path(name)
        if name in original:
            checks[name] = sha(path.read_bytes()) == original[name]
            continue
        parts = path.parts
        markers = [
            i for i, part in enumerate(parts) if part in ("proposals", "qualification")
        ]
        if not markers:
            raise ValueError("unbound new dependency source: " + name)
        suffix = "/".join(parts[markers[-1] :])
        matches = [p for p in original if p.endswith("/" + suffix)]
        if not matches and path.name in (
            "continuation.py",
            "continuation_state.py",
            "test_continuation.py",
        ):
            continue
        if len(matches) != 1:
            raise ValueError("inherited source cannot be matched: " + suffix)
        left = ast.dump(ast.parse(path.read_text()), include_attributes=False)
        right = ast.dump(
            ast.parse(Path(matches[0]).read_text()), include_attributes=False
        )
        checks[name] = left == right
    if not all(checks.values()):
        raise ValueError("continuation changed inherited implementation semantics")
    return checks
