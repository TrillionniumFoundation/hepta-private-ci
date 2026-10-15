"""Exact upstream LongMemEval-V2 Memory API integration smoke, no Reader/model.

Run only with an independently checked checkout of official LongMemEval-V2
commit 2cc8c540bdb87fe6761629b585e727e1c4704520. This verifies actual
Memory.build/query/persist/load semantics, NOT benchmark answer quality.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ORIGINAL_REPOSITORY = "xiaowu0162/LongMemEval-V2"
ORIGINAL_COMMIT = "2cc8c540bdb87fe6761629b585e727e1c4704520"
PROFILE = "hepta.amcn.official-longmemeval-v2-api.v1"


def check(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def run(original: Path, bridge: Path):
    original = original.resolve(strict=True)
    check((original / "memory_modules" / "memory.py").is_file()
          and (original / "LICENSE").is_file(), "official V2 material missing")
    commit = subprocess.check_output(
        ["git", "-C", str(original), "rev-parse", "HEAD"],
        text=True, timeout=15).strip()
    check(commit == ORIGINAL_COMMIT, "unpinned official LongMemEval-V2")
    check("Apache License" in (original / "LICENSE").read_text(),
          "official license mismatch")
    target = original / "memory_modules" / "amcn_shadow.py"
    check(not target.exists() and bridge.is_file() and not bridge.is_symlink(),
          "source injection conflict")
    copied_sha = sha(bridge.read_bytes())
    shutil.copyfile(bridge, target)

    sys.path.insert(0, str(original))
    from memory_modules.memory import (  # noqa: PLC0415
        MEMORY_TYPES, build_memory, load_memory, save_memory
    )
    import memory_modules.amcn_shadow  # noqa: F401,PLC0415

    check(MEMORY_TYPES.get("amcn_shadow_lexical") is not None,
          "official Memory decorator failed registration")
    config = {
        "memory_type": "amcn_shadow_lexical",
        "memory_params": {"top_k": 3, "max_records": 64,
                          "max_total_bytes": 1048576, "max_text_bytes": 4096}
    }
    instance = build_memory(config)
    traj = {
        "id": "official-interface-fixture-run-1",
        "goal": "Find the cause of a deadlock in the billing dashboard",
        "start_url": "https://example.invalid/billing",
        "states": [
            {"url": "https://example.invalid/billing", "action": "inspect logs",
             "accessibility_tree": "The billing transaction deadlock prevents checkout.",
             "screenshot": "/not-opened-without-vision.png"},
            {"url": "https://example.invalid/billing", "action": "retry",
             "accessibility_tree": "A bounded retry after rollback succeeded.",
             "screenshot": "/not-opened-without-vision.png"},
        ]
    }
    instance.insert(traj)
    instance.set_query_context(query_invocation_id="opaque-official-invocation")
    found = instance.query("billing transaction deadlock")
    check(1 <= len(found) <= 3
          and all(set(x) == {"type", "value"} and x["type"] == "text"
                  and isinstance(x["value"], str) and x["value"]
                  for x in found), "invalid official memory output")
    metadata = instance.post_query_hook(
        query="billing transaction deadlock", query_image=None,
        memory_context=found)
    check(metadata.get("trained_neural_cell") is False
          and metadata.get("production_qualified") is False,
          "shadow status misrepresented")
    hidden = instance.query("billing transaction deadlock", query_image="/unread-image.png")
    limitation = instance.post_query_hook(
        query="billing transaction deadlock", query_image="/unread-image.png",
        memory_context=hidden)
    check(limitation.get("image_unsupported") is True
          and all(x["type"] == "text" for x in hidden),
          "invented image capability")
    instance.clear_query_context()
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp) / "storage"
        save_memory(instance, root)
        check((root / "memory_config.json").is_file()
              and (root / "amcn-shadow.json").is_file(), "official save failed")
        restored = load_memory(root, requested_config=config)
        check(restored.query("billing transaction deadlock") == found,
              "official restore semantics changed")
        with (root / "amcn-shadow.json").open(encoding="utf-8") as f:
            state = json.load(f)
        state["rows"][0]["text"] = "forged source bytes"
        (root / "amcn-shadow.json").write_text(json.dumps(state), encoding="utf-8")
        try:
            load_memory(root, requested_config=config)
        except RuntimeError:
            tamper_rejected = True
        else:
            tamper_rejected = False
        check(tamper_rejected, "official restore accepted mutated original source")
    return {
        "schema": PROFILE,
        "official_repository": ORIGINAL_REPOSITORY,
        "official_commit": commit,
        "amcn_bridge_sha256": copied_sha,
        "registered_memory_type": "amcn_shadow_lexical",
        "actual_official_api_roundtrip": True,
        "source_tampering_rejected": True,
        "image_inputs_understood": False,
        "real_benchmark_questions_executed": 0,
        "natural_task_score": None,
        "real_pretrained_encoder_loaded": False,
        "production_accepted": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--bridge", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    check(not args.receipt.exists(), "immutable outcome must be a new path")
    result = run(args.upstream, args.bridge)
    with args.receipt.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, sort_keys=True, ensure_ascii=False) + "\n")
        stream.flush()
        import os
        os.fsync(stream.fileno())
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
