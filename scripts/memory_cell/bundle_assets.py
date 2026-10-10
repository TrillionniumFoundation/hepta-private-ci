"""Public model staging and read-only matrix aggregation; no serving adoption."""

import argparse
import hashlib
import json
from pathlib import Path

from native import digest
from bundle_trial import read, write

MODELS = {
    "135M": (
        "HuggingFaceTB/SmolLM2-135M-Instruct",
        "12fd25f77366fa6b3b4b768ec3050bf629380bac",
    ),
    "360M": (
        "HuggingFaceTB/SmolLM2-360M-Instruct",
        "a10cc1512eabd3dde888204e902eca88bddb4951",
    ),
    "1.7B": (
        "HuggingFaceTB/SmolLM2-1.7B-Instruct",
        "31b70e2e869a7173562077fd711b654946d38674",
    ),
}


def stage(tier, output):
    from huggingface_hub import snapshot_download
    from pretrained import file_inventory

    repo, revision = MODELS[tier]
    output.mkdir()
    snapshot_download(
        repo,
        revision=revision,
        local_dir=output / "reader",
        token=False,
        allow_patterns=["*.json", "model.safetensors", "merges.txt", "vocab.json"],
    )
    inventory = file_inventory(output / "reader")
    if "model.safetensors" not in inventory:
        raise ValueError("missing pinned model tensor file")
    write(
        output / "inventory.json",
        dict(
            tier=tier,
            repository=repo,
            revision=revision,
            inventory=inventory,
            inventory_digest=digest(inventory),
            model_qualification=False,
        ),
    )


def collect(root, plan_path, output):
    plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    plan = read(plan_path)
    summaries, seen = {}, set()
    for path in sorted(root.glob("*/execution/report.json")):
        run = read(path.parent / "execution.json")
        report = read(path)
        inv = read(path.parent.parent / "inventory.json")
        tier = inv["tier"]
        if (
            tier in seen
            or tier not in MODELS
            or (inv["repository"], inv["revision"]) != MODELS[tier]
            or run["plan_sha256"] != plan_sha
            or report["plan_digest"] != digest(plan)
            or run["reader_identity"] != inv["inventory_digest"]
            or digest(inv["inventory"]) != inv["inventory_digest"]
        ):
            raise ValueError("matrix model/plan drift or duplicate tier")
        seen.add(tier)
        summaries[tier] = dict(
            model=inv["repository"],
            revision=inv["revision"],
            results=report["summaries"],
            within_reader_contrasts=report["same_reader_contrasts"],
        )
    if seen != set(MODELS):
        raise ValueError("incomplete reader-size matrix")
    result = dict(
        schema="hepta.bundle-diagnostic.matrix.v1",
        plan_sha256=plan_sha,
        readers=summaries,
        model_size_change_is_not_memory_gain=True,
        selected_reader=None,
        independent_human_oracle_verified=False,
        production_accepted=False,
        superiority_claim=False,
    )
    write(output, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("stage")
    s.add_argument("tier", choices=tuple(MODELS))
    s.add_argument("output", type=Path)
    c = sub.add_parser("collect")
    c.add_argument("root", type=Path)
    c.add_argument("plan", type=Path)
    c.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.command == "stage":
        stage(args.tier, args.output)
    else:
        collect(args.root, args.plan, args.output)
