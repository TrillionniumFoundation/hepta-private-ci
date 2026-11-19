"""Runtime contract for the public HPCA greedy diagnostic, not independent B."""
import copy
import hashlib
import json
import os
from pathlib import Path
import uuid

MAX_NEW_TOKENS = 8
EXPECTED_PLAN_SHA = "acb16047e5942d317262ddb8273a2d62e9131e758d6627dcf1c2f42081d98043"

# These alter greedy logits, early stopping, or the returned sequence count.
NEUTRAL = {
    "num_beam_groups": (1,), "num_return_sequences": (1,),
    "min_length": (0,), "min_new_tokens": (None, 0), "max_time": (None,),
    "stop_strings": (None,), "penalty_alpha": (None,),
    "repetition_penalty": (1.0,), "encoder_repetition_penalty": (1.0,),
    "no_repeat_ngram_size": (0,), "encoder_no_repeat_ngram_size": (0,),
    "bad_words_ids": (None,), "force_words_ids": (None,), "constraints": (None,),
    "forced_bos_token_id": (None,), "forced_eos_token_id": (None,),
    "suppress_tokens": (None,), "begin_suppress_tokens": (None,),
    "sequence_bias": (None,), "guidance_scale": (None, 1.0),
    "watermarking_config": (None,), "token_healing": (False,),
    "exponential_decay_length_penalty": (None,),
    "remove_invalid_values": (False,), "renormalize_logits": (False,),
    "return_dict_in_generate": (False,), "decoder_start_token_id": (None,),
}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pin_files(paths):
    return {name: sha256(path) for name, path in paths.items()}


def require_file_pins(paths, pins):
    if pin_files(paths) != pins:
        raise ValueError("frozen file bytes changed during generation")


def asset_manifest(model_root, adapter_root):
    """Capture loadable file bytes; cache bookkeeping is not a model dependency."""
    roots = {"model": Path(model_root)}
    roots.update({f"seed{s}-{arm}": Path(adapter_root) / f"seed{s}-{arm}-adapter"
                  for s in (11, 17, 23, 29) for arm in ("interleaved", "bursty")})
    manifest = {}
    for name, root in roots.items():
        if not root.is_dir():
            raise ValueError(f"missing asset directory: {name}")
        files = {}
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            if any(part in {".git", ".cache", "__pycache__"} for part in relative.parts):
                continue
            if path.is_file():
                files[relative.as_posix()] = {
                    "bytes": path.stat().st_size, "sha256": sha256(path)}
        if not files:
            raise ValueError(f"empty asset directory: {name}")
        manifest[name] = files
    return manifest


def check_generation_config(config, eos_id, bos_id):
    expected = {"do_sample": False, "num_beams": 1, "max_new_tokens": MAX_NEW_TOKENS,
                "use_cache": True, "eos_token_id": eos_id, "pad_token_id": eos_id,
                "bos_token_id": bos_id}
    if type(eos_id) is not int or eos_id < 0:
        raise ValueError("tokenizer EOS identity is missing")
    for key, value in expected.items():
        if config.get(key) != value:
            raise ValueError(f"generation contract mismatch: {key}")
    for key, allowed in NEUTRAL.items():
        if config.get(key, allowed[0]) not in allowed:
            raise ValueError(f"non-neutral generation setting: {key}")


def resolve_generation_config(model, tokenizer):
    # Preserve and inspect the model's effective settings instead of silently
    # discarding a hidden logit processor or stopping rule.
    config = copy.deepcopy(model.generation_config)
    config.update(do_sample=False, num_beams=1, max_new_tokens=MAX_NEW_TOKENS,
                  pad_token_id=tokenizer.eos_token_id, use_cache=True)
    check_generation_config(config.to_dict(), tokenizer.eos_token_id,
                            tokenizer.bos_token_id)
    if config.get_generation_mode().value != "greedy_search":
        raise ValueError("resolved decoding mode is not greedy_search")
    return config


def write_json_exclusive(path, payload):
    with Path(path).open("x", encoding="utf-8") as output:
        json.dump(payload, output, indent=2, sort_keys=True, allow_nan=False)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


class RunJournal:
    """Each completed row survives a later interrupted process, without a PASS."""
    def __init__(self, path):
        self.run_id = uuid.uuid4().hex
        self.sequence = 0
        self.stream = Path(path).open("x", encoding="utf-8")

    def append(self, kind, **payload):
        record = {"run_id": self.run_id, "sequence": self.sequence,
                  "kind": kind, **payload}
        self.stream.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.sequence += 1

    def close(self):
        self.stream.close()
