"""Network-enabled public-input staging ONLY; all subsequent model work is offline."""

import argparse
import hashlib
import json
import platform
import shutil
import urllib.request
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download, snapshot_download

PINS = {
    "reader": (
        "HuggingFaceTB/SmolLM2-135M-Instruct",
        "12fd25f77366fa6b3b4b768ec3050bf629380bac",
    ),
    "encoder": (
        "sentence-transformers/all-MiniLM-L6-v2",
        "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
    ),
    "laya": ("convaiinnovations/laya", "7b928d828b7b0e022f929d9bd2e44165aa270148"),
}
LAYA_SOURCE = "c7527708f9f5220c669d8aa385077cd28d04708a"
LOCOMO_SOURCE = "3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376"


def public_download(url, destination, maximum):
    with urllib.request.urlopen(url, timeout=90) as response:
        content = response.read(maximum + 1)
    if len(content) > maximum:
        raise ValueError("download byte limit")
    destination.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def prepare(root: Path, profile: str):
    root.mkdir(parents=True, exist_ok=False)
    record = {
        "profile": profile,
        "public_only": True,
        "python": platform.python_version(),
        "models": {},
    }
    names = ("laya",) if profile == "laya" else ("reader", "encoder")
    for name in names:
        repo, revision = PINS[name]
        patterns = [
            "config.json",
            "model.safetensors",
            "tokenizer*",
            "special_tokens_map.json",
            "vocab*",
            "merges.txt",
            "generation_config.json",
        ]
        if name == "laya":
            patterns = [
                "rl_agent_config.json",
                "model.safetensors",
                "encoder/*",
                "tokenizer/*",
            ]
        snapshot_download(
            repo,
            revision=revision,
            allow_patterns=patterns,
            local_dir=root / name,
            token=False,
        )
        record["models"][name] = {"repository": repo, "revision": revision}
    record["locomo"] = {
        "revision": LOCOMO_SOURCE,
        "sha256": public_download(
            f"https://raw.githubusercontent.com/snap-research/locomo/{LOCOMO_SOURCE}/data/locomo10.json",
            root / "locomo.json",
            32 * 1024 * 1024,
        ),
    }
    if profile == "laya":
        record["laya_source"] = {
            "revision": LAYA_SOURCE,
            "sha256": public_download(
                f"https://raw.githubusercontent.com/NandhaKishorM/laya/{LAYA_SOURCE}/laya/common.py",
                root / "laya_common.py",
                128 * 1024,
            ),
        }
    else:
        dataset = "xiaowu0162/longmemeval-cleaned"
        revision = HfApi(token=False).dataset_info(dataset).sha
        if len(revision) != 40:
            raise ValueError("dataset revision not immutable")
        filename = "longmemeval_s_cleaned.json"
        path = Path(
            hf_hub_download(
                dataset, filename, repo_type="dataset", revision=revision, token=False
            )
        )
        if path.stat().st_size > 512 * 1024 * 1024:
            raise ValueError("dataset size")
        shutil.copyfile(path, root / "longmemeval.json")
        record["longmemeval"] = {
            "repository": dataset,
            "revision": revision,
            "file": filename,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    (root / "staging.json").write_text(json.dumps(record, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("profile", choices=["native", "laya"])
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare(args.output, args.profile)
