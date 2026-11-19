#!/usr/bin/env python3
"""Read-only audit of the six original campaign-v2 last.pt save boundaries.

This is a post-result custody/semantics audit. It executes no Torch, model,
forward, backward, or optimizer code and grants no replay qualification.
"""

import hashlib
import json
from pathlib import Path

ROOT = Path("/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training")
SOURCE = ROOT / "run-source-v8/proposals/localization-v3/train.py"
SOURCE_SHA256 = "06cb85c7a0da85fb8d656526c2b07285979bc6c47c2e00c154e89f43bcfc1a22"
FITS = {
    "hcsn-s101-lr0.001": {
        "epochs": 46,
        "checkpoint_updates": 552,
        "last_sha256": "e0c8c946aa8010bfcf4df5b9e155235d2fb6b12a9832e4eaa5db3d9afb154d78",
    },
    "hcsn-s101-lr0.003": {
        "epochs": 47,
        "checkpoint_updates": 564,
        "last_sha256": "bea446e64571e7cd424411036eff207bb6839af4495a7b60cf0f9df81181ba05",
    },
    "hcsn-s211-lr0.001": {
        "epochs": 46,
        "checkpoint_updates": 552,
        "last_sha256": "cdbca6e633c6aba5f72f08f259ab08b1c5c2c5745d1dbd2f323a78df876e1e79",
    },
    "hcsn-s211-lr0.003": {
        "epochs": 47,
        "checkpoint_updates": 564,
        "last_sha256": "b7d162101f18628fcfcabb21e9609499d62c8a26ad6d53b9c375ed2e0439d2f4",
    },
    "hcsn-s307-lr0.001": {
        "epochs": 46,
        "checkpoint_updates": 552,
        "last_sha256": "17d6ad363d82ba31b006d0a4f55ca9c63453fa2c9c34f7370f022e2ff66a4f5c",
    },
    "hcsn-s307-lr0.003": {
        "epochs": 46,
        "checkpoint_updates": 552,
        "last_sha256": "736ee7d7afe911a3cf5bb7f7ad97babff4dfb74e28a46ec9c148579160a5075c",
    },
}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def source_boundary():
    raw = SOURCE.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == SOURCE_SHA256, "train.py SHA mismatch")
    text = raw.decode("utf-8")
    markers = [
        'losses = [',
        'report["epochs"].append(row)',
        'event("epoch_completed", **row)',
        'report["last_checkpoint_sha256"] = checkpoint(out / "last.pt")',
    ]
    positions = []
    for marker in markers:
        require(text.count(marker) == 1, "source marker count mismatch: " + marker)
        positions.append(text.index(marker))
    require(positions == sorted(positions), "last.pt is not after completed epoch record")
    require(text.count('"resume_supported": False') == 1, "resume_supported negative missing")
    require("for epoch in range(1, args.max_epochs + 1):" in text, "epoch loop missing")
    require("order_rng.shuffle(order)" in text, "order shuffle missing")
    require('"order_rng": order_rng.getstate()' in text, "order RNG save missing")
    require('"epochs_completed": len(report["epochs"])' in text, "epoch count save missing")
    require('"main_updates": report["main_updates"]' in text, "update count save missing")
    return {
        "train_sha256": SOURCE_SHA256,
        "markers": markers,
        "marker_positions": positions,
        "resume_supported_literal": False,
        "last_checkpoint_after_complete_epoch": True,
    }


def audit_fit(name, expected):
    directory = ROOT / "campaign-v2" / name
    result_path = directory / "result.json"
    events_path = directory / "events.jsonl"
    last_path = directory / "last.pt"
    interrupted_path = directory / "interrupted.pt"
    result = json.loads(result_path.read_text(encoding="utf-8"))

    require(result["status"] == "budget_exhausted", name + ": unexpected terminal status")
    require(result["resume_supported"] is False, name + ": original resume flag changed")
    require(result["last_checkpoint_sha256"] == expected["last_sha256"], name + ": result last SHA mismatch")
    require(sha256(last_path) == expected["last_sha256"], name + ": last.pt byte mismatch")
    require(len(result["epochs"]) == expected["epochs"], name + ": result epoch count mismatch")
    require(all(row.get("complete") is True for row in result["epochs"]), name + ": incomplete recorded epoch")
    require(result["main_updates"] >= expected["checkpoint_updates"], name + ": terminal updates precede checkpoint")
    require(
        result["interrupted_checkpoint_sha256"] == sha256(interrupted_path),
        name + ": interrupted.pt byte mismatch",
    )
    source_map = result["source_before"]
    require(source_map[str(SOURCE)] == SOURCE_SHA256, name + ": source-before mismatch")
    require(result["source_after"][str(SOURCE)] == SOURCE_SHA256, name + ": source-after mismatch")
    require(result["source_unchanged"] is True, name + ": source changed")

    last_completed_epoch = None
    last_completed_line = None
    post_boundary_main_updates = 0
    next_epoch_started = None
    optimizer_numbers = []
    line_count = 0
    with events_path.open("r", encoding="utf-8") as stream:
        for line_count, line in enumerate(stream, 1):
            event = json.loads(line)
            kind = event.get("kind")
            if kind == "epoch_completed":
                last_completed_epoch = event["epoch"]
                last_completed_line = line_count
                post_boundary_main_updates = 0
                next_epoch_started = None
                optimizer_numbers = []
            elif last_completed_line is not None and kind == "epoch_started":
                require(next_epoch_started is None, name + ": multiple next epoch starts")
                next_epoch_started = event["epoch"]
            elif (
                last_completed_line is not None
                and kind == "optimizer_completed"
                and event.get("phase") == "main"
            ):
                post_boundary_main_updates += 1
                optimizer_numbers.append(event["number"])

    delta = result["main_updates"] - expected["checkpoint_updates"]
    require(last_completed_epoch == expected["epochs"], name + ": last completed epoch mismatch")
    require(next_epoch_started == expected["epochs"] + 1, name + ": next epoch start missing")
    require(post_boundary_main_updates == delta, name + ": post-boundary optimizer count mismatch")
    require(
        optimizer_numbers == list(range(expected["checkpoint_updates"] + 1, result["main_updates"] + 1)),
        name + ": post-boundary optimizer numbers are not contiguous",
    )
    return {
        "fit": name,
        "status": result["status"],
        "result_sha256": sha256(result_path),
        "events_sha256": sha256(events_path),
        "events_lines": line_count,
        "last_sha256": expected["last_sha256"],
        "interrupted_sha256": result["interrupted_checkpoint_sha256"],
        "epochs_completed_at_last": expected["epochs"],
        "updates_at_last": expected["checkpoint_updates"],
        "terminal_main_updates": result["main_updates"],
        "post_last_optimizer_updates": delta,
        "next_epoch_started": next_epoch_started,
        "resume_supported": result["resume_supported"],
    }


def main():
    output = {
        "schema": "hcsn-c2-original-parent-boundary-audit-v1",
        "identity": "hcsn-c2-original-parent-boundary-audit-20261114-c06d-v1",
        "scope": "post-result read-only source/result/event/byte audit",
        "source_boundary": source_boundary(),
        "fits": [audit_fit(name, expected) for name, expected in FITS.items()],
        "counts": {
            "fits": len(FITS),
            "torch_imports": 0,
            "checkpoint_deserializations": 0,
            "models_constructed": 0,
            "forwards": 0,
            "backwards": 0,
            "optimizers_constructed": 0,
            "optimizer_calls": 0,
        },
        "conclusion": {
            "all_six_last_pt_are_completed_epoch_boundaries": True,
            "missing_explicit_cursor_implies_mid_epoch_snapshot": False,
            "original_training_resume_supported": False,
            "new_runner_continuation_equivalence_proved": False,
            "full_training_replay_completed": False,
            "scientific_admission": "HOLD",
            "all_closed": False,
        },
    }
    print(json.dumps(output, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
