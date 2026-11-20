"""CPU tokenizer-only measurement of complete frozen prompts and full actions."""

import argparse
import json
import os
import resource
import time
from pathlib import Path

from source_actions import canonical
from source_units import sha


def main():
    parser = argparse.ArgumentParser()
    for option in ("request", "tokenizer-freeze", "output"):
        parser.add_argument("--" + option, type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    started, cpu = time.monotonic(), time.process_time()
    request = json.loads(args.request.read_bytes())
    frozen = json.loads(args.tokenizer_freeze.read_bytes())
    assert sha(args.tokenizer_freeze.read_bytes()) == request["tokenizer_freeze_sha256"]
    base = Path(frozen["base_directory"])
    for row in frozen["files"]:
        raw = (base / row["path"]).read_bytes()
        assert len(raw) == row["bytes"] and sha(raw) == row["sha256"]
    # No AutoModel/Predictor, weights file, remote code, or forward path exists.
    import transformers
    import tokenizers
    import jinja2
    from transformers import AutoTokenizer

    versions = {
        "transformers": transformers.__version__,
        "tokenizers": tokenizers.__version__,
        "jinja2": jinja2.__version__,
    }
    assert versions == frozen["versions"]
    tokenizer = AutoTokenizer.from_pretrained(
        base, local_files_only=True, trust_remote_code=False, token=False
    )
    assert (
        sha(tokenizer.chat_template.encode()) == frozen["native_chat_template_sha256"]
    )
    assert {k: getattr(tokenizer, k) for k in frozen["special_token_ids"]} == frozen[
        "special_token_ids"
    ]
    rows = []
    for record in request["records"]:
        prompt, target = record["prompt"], record["target"]
        assert sha(prompt.encode()) == record["prompt_sha256"]
        wire = [{"role": "user", "content": prompt}]
        prefix = tokenizer.apply_chat_template(
            wire, tokenize=False, add_generation_prompt=True
        )
        prefix_ids = tokenizer.encode(prefix, add_special_tokens=False)
        row = {
            "ordinal": record["ordinal"],
            "source_id": record["source_id"],
            "prompt_sha256": record["prompt_sha256"],
            "prompt_bytes": len(prompt.encode()),
            "prefix_tokens": len(prefix_ids),
            "prefix_ids_sha256": sha(canonical(prefix_ids)),
            "fits_original_native_message_bytes_65536": len(prompt.encode()) <= 65536,
            "fits_original_input_4096": len(prefix_ids) <= 4096,
            "target_tokens": None,
            "complete_sft_positions": None,
            "fits_original_sft_3584": False,
            "fits_original_generation_384": False,
            "static_representation_admitted": False,
            "training_execution_admitted": False,
        }
        if target is not None:
            complete = tokenizer.apply_chat_template(
                wire + [{"role": "assistant", "content": target}],
                tokenize=False,
                add_generation_prompt=False,
            )
            assert complete.startswith(prefix)
            target_ids = tokenizer.encode(
                complete[len(prefix) :], add_special_tokens=False
            )
            row.update(
                {
                    "target_bytes": len(target.encode()),
                    "target_sha256": sha(target.encode()),
                    "target_tokens": len(target_ids),
                    "complete_sft_positions": len(prefix_ids) + len(target_ids),
                    "target_ids_sha256": sha(canonical(target_ids)),
                    "prefix_labels_masked": len(prefix_ids),
                    "all_target_labels_retained": len(target_ids),
                    "fits_original_sft_3584": len(prefix_ids) + len(target_ids) <= 3584,
                    "fits_original_generation_384": len(target_ids) <= 384,
                    "fits_original_answer_bytes_32768": len(target.encode()) <= 32768,
                }
            )
            row["static_representation_admitted"] = all(
                [
                    record["v1_static_context_closed"],
                    record["structural_roundtrip"],
                    record["visible_action_roundtrip"],
                    row["fits_original_native_message_bytes_65536"],
                    row["fits_original_input_4096"],
                    row["fits_original_sft_3584"],
                    row["fits_original_generation_384"],
                    row["fits_original_answer_bytes_32768"],
                ]
            )
        rows.append(row)
    result = {
        "schema": "hepta.e5-codec-tokenizer-readout.v1",
        "request_sha256": sha(args.request.read_bytes()),
        "source_freeze_sha256": request["source_freeze_sha256"],
        "target_readout_sha256": request["target_readout_sha256"],
        "tokenizer_freeze_sha256": request["tokenizer_freeze_sha256"],
        "versions": versions,
        "serialization": "native_chat_v2; separately encode exact inference prefix and full assistant continuation",
        "rows": rows,
        "prefix_1_4_16_representable": {
            str(n): all(r["static_representation_admitted"] for r in rows[:n])
            for n in (1, 4, 16)
        },
        "wall_seconds": time.monotonic() - started,
        "self_cpu_seconds": time.process_time() - cpu,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "truncation": False,
        "model_loads": 0,
        "forward_calls": 0,
        "generation_calls": 0,
        "training_updates": 0,
        "native_replays": 0,
        "optimizer_unit_mapping": None,
        "new_compute_or_verification_budget": None,
        "independent_future_panel": None,
    }
    (args.output / "RESULT.json").write_bytes(canonical(result) + b"\n")
    print(
        json.dumps(
            {
                "path": str(args.output / "RESULT.json"),
                "sha256": sha((args.output / "RESULT.json").read_bytes()),
                "static_representations": sum(
                    r["static_representation_admitted"] for r in rows
                ),
                "prefixes": result["prefix_1_4_16_representable"],
                "wall_seconds": result["wall_seconds"],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
