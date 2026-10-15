"""Official Hugging Face tokenizer/model parity on original pinned SmolLM2 bytes.

Fail closed: this is an engine diagnostic, not learned memory, a human
sufficiency certificate, a new held-out population, or production permission.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import time
import zipfile

import torch

from offline_event_reader_trial import ARCHIVE_SHA, inputs
from offline_smol_reader import OriginalSmol, PINS, digest, verify_files
from prompt_representation_probe import ARMS, STYLES, build_messages

ORIGINAL_ZIP_SHA = "07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af"
MODEL_FILES = {
    "model.safetensors": 269060552,
    "config.json": 861,
    "tokenizer.json": 2104556,
    "tokenizer_config.json": 3764,
    "generation_config.json": 132,
    "vocab.json": 800662,
    "merges.txt": 466391,
    "special_tokens_map.json": 655,
}
TOKEN_LIMIT = 2048
MAX_ABS_TOLERANCE = 0.002
MEAN_ABS_TOLERANCE = 0.0001


def sha_file(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("regular original artifact required")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def extract_allowed(source, target):
    """Never unpack metadata, symlinks, duplicate files or arbitrary tar paths."""
    seen = set()
    with tarfile.open(fileobj=source, mode="r|gz") as archive:
        for member in archive:
            prefix = "memory-inputs/reader/"
            if not member.name.startswith(prefix):
                continue
            name = member.name[len(prefix):]
            if name not in MODEL_FILES:
                continue
            if name in seen or not member.isfile() or member.size != MODEL_FILES[name]:
                raise ValueError("unsafe or duplicate reader archive entry")
            seen.add(name)
            with archive.extractfile(member) as original:
                with (Path(target) / name).open("xb") as output:
                    shutil.copyfileobj(original, output, 1024 * 1024)
    if seen != set(MODEL_FILES):
        raise ValueError("incomplete pinned original model files")
    verify_files(target)
    return {name: sha_file(Path(target) / name) for name in sorted(seen)}


def stage(archive, target):
    if sha_file(archive) != ORIGINAL_ZIP_SHA:
        raise ValueError("original model outer ZIP digest mismatch")
    target = Path(target)
    target.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as package:
        if package.namelist() != ["memory-inputs.tar.gz"]:
            raise ValueError("original ZIP membership changed")
        with package.open("memory-inputs.tar.gz") as source:
            files = extract_allowed(source, target)
    return dict(outer_sha256=ORIGINAL_ZIP_SHA, model_files=files)


def census(plan, sources, native, official):
    """Check *all* 64 original matched prompts, not one convenient example."""
    if len(plan["cases"]) != 8 or tuple(ARMS) != (
        "empty", "hybrid", "organized", "without_prerequisite"
    ):
        raise ValueError("frozen question/arm census changed")
    rows = []
    mismatches = []
    for case in plan["cases"]:
        for style in STYLES:
            for arm in ARMS:
                messages, selected = build_messages(case, arm, style, sources)
                native_prompt = native.tokenizer.render(messages)
                official_prompt = official.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True
                )
                expected = native.tokenizer.encode(native_prompt)
                actual = official.apply_chat_template(
                    messages, tokenize=True, add_generation_prompt=True
                )
                from_render = official.encode(
                    official_prompt, add_special_tokens=False
                )
                if not 1 <= len(expected) <= TOKEN_LIMIT:
                    raise ValueError("original reader full prompt exceeds fixed budget")
                label = dict(
                    question=case["query"]["identity"], style=style, arm=arm,
                    selection_digest=digest(selected),
                    native_input_digest=digest(expected),
                    official_input_digest=digest(actual),
                    native_tokens=len(expected), official_tokens=len(actual),
                )
                rows.append(label)
                if (
                    native_prompt != official_prompt
                    or expected != actual
                    or actual != from_render
                ):
                    first = next(
                        (i for i, (a, b) in enumerate(zip(expected, actual)) if a != b),
                        min(len(expected), len(actual)),
                    )
                    mismatches.append(label | dict(first_differing_token=first))
    if len(rows) != 64 or len({
        (row["question"], row["style"], row["arm"]) for row in rows
    }) != 64:
        raise ValueError("duplicate or incomplete comparison matrix")
    return rows, mismatches


def audit(source_archive, model_directory, output, source_commit):
    """Require the official runtime; NEVER simulate its tokenization or logits."""
    import tokenizers
    import transformers
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("exact tested Git commit required")
    if (transformers.__version__, tokenizers.__version__) != ("4.49.0", "0.21.1"):
        raise ValueError("unexpected official reference library versions")
    if torch.__version__.split("+")[0] != "2.5.1":
        raise ValueError("unexpected CPU torch runtime")
    torch.set_num_threads(2)
    plan, sources, _ = inputs(source_archive)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    result = dict(
        schema="hepta.memory.original-hf-runtime-parity.v1",
        tested_commit=source_commit,
        frozen_event_archive_sha256=ARCHIVE_SHA,
        original_model_archive_sha256=ORIGINAL_ZIP_SHA,
        pinned_original_model_files=PINS,
        torch=torch.__version__,
        transformers=transformers.__version__,
        tokenizers=tokenizers.__version__,
        official_tokenizer_executed=False,
        official_model_executed=False,
        tokenization_parity=False,
        logit_parity=False,
        greedy_parity=False,
        training_executed=False,
        held_out_tasks_new=False,
        independent_human_sufficiency=False,
        model_capacity_advantage=False,
        parametric_memory_benefit=False,
        production_accepted=False,
    )
    try:
        native = OriginalSmol(model_directory)
        hf_tokenizer = AutoTokenizer.from_pretrained(
            model_directory, use_fast=True, local_files_only=True,
            trust_remote_code=False
        )
        result["official_tokenizer_executed"] = True
        if hf_tokenizer.is_fast is not True:
            raise ValueError("native fast HF tokenizer required")
        requests, mismatches = census(plan, sources, native, hf_tokenizer)
        result["matched_requests"] = requests
        result["tokenizer_mismatches"] = mismatches
        if mismatches:
            raise ValueError("original offline tokenizer differs from official")
        result["tokenization_parity"] = True
        hf = AutoModelForCausalLM.from_pretrained(
            model_directory, torch_dtype=torch.float32,
            local_files_only=True, trust_remote_code=False,
            use_safetensors=True, attn_implementation="eager"
        ).eval()
        hf.requires_grad_(False)
        result["official_model_executed"] = True
        result["model_parameters"] = sum(p.numel() for p in hf.parameters())
        if hf.config.model_type != "llama" or result["model_parameters"] != 134515008:
            raise ValueError("original model architecture or parameters changed")
        comparisons = []
        for index, case in enumerate(plan["cases"]):
            style, arm = STYLES[index % len(STYLES)], ARMS[index % len(ARMS)]
            messages, _ = build_messages(case, arm, style, sources)
            ids = native.tokenizer.encode(native.tokenizer.render(messages))
            with torch.inference_mode():
                native_logits, _ = native.forward(ids)
                hf_logits = hf(
                    input_ids=torch.tensor([ids], dtype=torch.long),
                    use_cache=False,
                ).logits[0, -1].float()
            error = (native_logits - hf_logits).abs()
            maximum, mean = float(error.max()), float(error.mean())
            same_top = int(native_logits.argmax()) == int(hf_logits.argmax())
            comparisons.append(dict(
                question=case["query"]["identity"], style=style, arm=arm,
                input_digest=digest(ids), max_logit_error=maximum,
                mean_logit_error=mean, same_next_token=same_top,
            ))
            if (
                not torch.isfinite(hf_logits).all()
                or not same_top
                or maximum > MAX_ABS_TOLERANCE
                or mean > MEAN_ABS_TOLERANCE
            ):
                raise ValueError("official HF model logits diverge")
        result["logit_pairs"] = comparisons
        result["logit_parity"] = True
        greedy_pairs = []
        for case in (plan["cases"][0], plan["cases"][3]):
            messages, _ = build_messages(case, "organized", "normalized", sources)
            ids = native.tokenizer.encode(native.tokenizer.render(messages))
            native_tokens = native.generate(ids, maximum=8)
            with torch.inference_mode():
                hf_tokens = hf.generate(
                    input_ids=torch.tensor([ids], dtype=torch.long),
                    max_new_tokens=8, do_sample=False, num_beams=1,
                    use_cache=True, eos_token_id=2, pad_token_id=2,
                )[0, len(ids):].tolist()
            native_text = native.tokenizer.decode(native_tokens)
            hf_text = hf_tokenizer.decode(
                hf_tokens, skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )
            equal = native_tokens == hf_tokens and native_text == hf_text
            greedy_pairs.append(dict(
                question=case["query"]["identity"],
                native_token_digest=digest(native_tokens),
                official_token_digest=digest(hf_tokens), identical=equal,
            ))
            if not equal:
                raise ValueError("official HF greedy token/text decoding drift")
        native.verify_frozen()
        result["greedy_pairs"] = greedy_pairs
        result["greedy_parity"] = True
        result["full_parity_observed"] = True
    except Exception as error:
        result["full_parity_observed"] = False
        result["failure_type"] = type(error).__name__
        result["failure_reason"] = str(error)[:256]
        raise
    finally:
        result["local_wall_seconds"] = time.perf_counter() - started
        with (output / "hf-parity.json").open("x", encoding="utf-8") as receipt:
            json.dump(result, receipt, ensure_ascii=False, indent=2, allow_nan=False)
            receipt.write("\n")
            receipt.flush()
            os.fsync(receipt.fileno())
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("stage")
    prepare.add_argument("archive", type=Path)
    prepare.add_argument("target", type=Path)
    check = sub.add_parser("audit")
    check.add_argument("source", type=Path)
    check.add_argument("model", type=Path)
    check.add_argument("result", type=Path)
    check.add_argument("--tested-commit", required=True)
    args = parser.parse_args()
    if args.command == "stage":
        print(json.dumps(stage(args.archive, args.target), sort_keys=True))
    else:
        audit(args.source, args.model, args.result, args.tested_commit)
