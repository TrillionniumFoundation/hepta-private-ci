#!/usr/bin/env python3
"""Cumulative control evidence with unchanged public ten-step plan and owners."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

CHAIN_SHA = "c96022b897c1235fdbdbfcfa32764403511c6aab"
CONTRACT = "c9b06f9a029a3257801844f89acb59b5f59f6a39087335af323f274e9152992f"
PLAN_SHA = "01ec1a644f37b9fc7a4c6616f589768df97f8eed7a289b5de86afadaa7ce6165"
ROLES = {
    "fresh-budget-matched-lora": "cumulative-lora",
    "budget-matched-full-tune": "cumulative-full-tune",
}
COUNT_FIELDS = ("steps", "tokens", "supervised_tokens")
NO_AUTHORITY = dict.fromkeys(
    (
        "installation",
        "selection",
        "product_qualification",
        "public_reward",
        "current_write",
    ),
    False,
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def checked_runtime(chain):
    require(chain.is_absolute(), "absolute Chain source")
    require(
        subprocess.check_output(
            ["git", "-C", str(chain), "rev-parse", "HEAD"], text=True
        ).strip()
        == CHAIN_SHA,
        "exact original Chain source required",
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(chain),
            "diff",
            "--exit-code",
            "HEAD",
            "--",
            "scripts",
            "formal",
            "config",
        ],
        check=True,
    )
    sys.path.insert(0, str(chain / "scripts"))
    import llm_runtime_pilot as runtime

    plan_path = (
        Path(__file__).resolve().parents[1]
        / "codex-rs/hepta-learning-artifacts/profiles/smollm2-public-initial-v2.plan.json"
    )
    raw = plan_path.read_bytes()
    require(
        hashlib.sha256(raw).hexdigest() == PLAN_SHA, "unchanged ten-step plan bytes"
    )
    plan = runtime.validate_plan(json.loads(raw))
    require(
        plan["runtime_source"] == runtime.file_sha(runtime.__file__),
        "fixed trainer source",
    )
    return runtime, plan


def verify_runtime_snapshot():
    snapshot = Path(os.environ["HEPTA_PUBLIC_INITIAL_RUNTIME_SNAPSHOT"])
    require(
        snapshot.is_absolute() and sys.flags.no_user_site == 1, "isolated cold runtime"
    )
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(Path(__file__).with_name("hepta_smollm_runtime_snapshot.py")),
            "verify",
            "--snapshot",
            str(snapshot),
        ],
        check=True,
    )


def check_parent(parent, role, number, runtime, plan):
    """Verify actual receipt ancestry and current parent bytes before continuation."""
    require(parent["role"] == role and parent["round"] == number, "parent role/round")
    directory = Path(parent["directory"])
    require(directory.is_absolute(), "absolute parent directory")
    for name, pin in (
        ("artifact.json", "metadata_sha256"),
        ("artifact.safetensors", "file_sha256"),
    ):
        require(
            runtime.file_sha(directory / name) == parent[pin], "parent material changed"
        )
    require(
        runtime.file_sha(parent["contract_path"]) == parent["contract_sha256"],
        "parent contract bytes changed",
    )
    metadata = runtime.read_json(directory / "artifact.json")
    require(
        metadata["role"] == role
        and metadata["artifact"] == parent["artifact"]
        and metadata["file_sha256"] == parent["file_sha256"]
        and metadata["experiment"] == runtime.identity(plan)
        and metadata["contract"] == CONTRACT
        and metadata["kind"] == plan["recipes"][role]["kind"],
        "parent material context",
    )
    total = dict.fromkeys(COUNT_FIELDS, 0)
    require(
        len(parent["history"]) == number, "complete actual control history required"
    )
    previous = None
    for ordinal, entry in enumerate(parent["history"], 1):
        require(
            runtime.file_sha(entry["receipt_path"]) == entry["receipt_sha256"],
            "ancestor receipt changed",
        )
        receipt = runtime.read_json(entry["receipt_path"])
        require(
            receipt["outcome"] == "success" and receipt["role"] == role,
            "ancestor receipt role/outcome",
        )
        if ordinal == 1:
            require(
                receipt["schema"] == "llm-runtime-actual-child-v1"
                and receipt["phase"] == "train"
                and receipt["contract"] == CONTRACT,
                "actual original round-one control required",
            )
            actual_artifact = receipt["artifact"]
        else:
            require(
                receipt["schema"] == "hepta-cumulative-control-actual-v1"
                and receipt["round"] == ordinal
                and receipt["actual_parent_readback"] == previous
                and receipt["optimizer_reset_each_round"] is True
                and receipt["authority"] == NO_AUTHORITY,
                "cumulative control consumed a different parent",
            )
            actual_artifact = receipt["artifact"]["artifact"]
        require(
            receipt["experiment"] == runtime.identity(plan)
            and actual_artifact == entry["artifact"],
            "ancestor experiment/artifact",
        )
        for field in COUNT_FIELDS:
            count = receipt["training"][field]
            require(
                type(count) is int and count > 0 and count == entry["counts"][field],
                "ancestor measured training count",
            )
            total[field] += count
        require(
            receipt["training"]["steps"] == plan["training_steps"],
            "original per-round steps",
        )
        previous = actual_artifact
    require(
        previous == parent["artifact"] and total == parent["cumulative_campaign"],
        "parent cumulative ledger does not match actual receipts",
    )


def parent_descriptor(directory, contract_path, role, number, history, runtime):
    metadata = runtime.read_json(directory / "artifact.json")
    receipt_path = directory / "actual-receipt.json"
    receipt = runtime.read_json(receipt_path)
    history = [
        *history,
        dict(
            receipt_path=str(receipt_path),
            receipt_sha256=runtime.file_sha(receipt_path),
            artifact=metadata["artifact"],
            counts={field: receipt["training"][field] for field in COUNT_FIELDS},
        ),
    ]
    return dict(
        role=role,
        round=number,
        directory=str(directory),
        artifact=metadata["artifact"],
        file_sha256=metadata["file_sha256"],
        metadata_sha256=runtime.file_sha(directory / "artifact.json"),
        contract_path=str(contract_path),
        contract_sha256=runtime.file_sha(contract_path),
        history=history,
        cumulative_campaign={
            field: sum(entry["counts"][field] for entry in history)
            for field in COUNT_FIELDS
        },
    )
