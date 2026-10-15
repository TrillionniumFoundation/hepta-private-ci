#!/usr/bin/env python3
"""Source-bound, research-only physical Granite97 -> native FeatureSequence V3.

Only the frozen, SHA-pinned, local ModernBERT 97M original may produce these
records. The Rust admission consumer independently replays source/token/mask
digests. Records do NOT authenticate the source owner or grant FinalUse.
No model or source download and no test labels enter this process.
"""
import argparse
import hashlib
import json
import math
import re
from pathlib import Path
import time

MODEL_ID = "ibm-granite/granite-embedding-97m-multilingual-r2"
REVISION = "835ad14087e140460703cf0fae09f97d469d65c2"
FILES = (
    "config.json", "model.safetensors", "tokenizer.json",
    "tokenizer_config.json", "special_tokens_map.json",
)
SCHEMA = "hepta.stem.granite97-token-export.v5"
INPUT_DOMAIN = b"hepta.stem.granite97.complete-token-input.v5\0"
MODEL_DOMAIN = b"hepta.stem.granite97.frozen-model.v5\0"
Q24 = 1 << 24


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def profile_digests(material_digest, material, *, max_tokens, torch_version,
                    transformers_version):
    """Opaque, immutable identities; all output-affecting profiles are included."""
    if not 1 <= max_tokens <= 256:
        raise ValueError("token ceiling outside V3")
    tokenizer_files = {key: material["sha256"][key] for key in FILES
                       if "token" in key or key == "special_tokens_map.json"}
    return dict(
        encoder_digest=sha(MODEL_DOMAIN + bytes.fromhex(material_digest)),
        tokenizer_digest=sha(b"hepta.granite97.tokenizer.v5\0" + canonical_json(tokenizer_files)),
        normalizer_digest=sha(b"hepta.granite97.identity-normalizer.v5"),
        quantization_digest=sha(b"hepta.granite97.fp32-q24-ties-even.v5"),
        preprocessing_digest=sha(b"hepta.granite97.preprocessing.v5\0" + canonical_json(dict(
            max_tokens=max_tokens, truncation=False, add_special_tokens=True,
            padding=False, precision="fp32", attention="eager",
            output="last_hidden_state", tokenizer=tokenizer_files,
            torch_version=torch_version, transformers_version=transformers_version,
            model_config_sha256=material["sha256"]["config.json"]))),
        adapter_digest=sha(b"hepta.granite97.identity-adapter.v5"),
    )


def load_material(root):
    """Reject incomplete, changed, path-escaping and unpinned file inventories."""
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("local snapshot directory required")
    metadata = root / "material.json"
    if metadata.is_symlink() or not metadata.is_file() or metadata.stat().st_size > 16_384:
        raise ValueError("bounded material manifest required")
    manifest = json.loads(metadata.read_bytes())
    if (not isinstance(manifest, dict) or
            manifest.get("model_id") != MODEL_ID or
            manifest.get("revision") != REVISION or
            set(manifest.get("files", {})) != set(FILES) or
            set(manifest.get("sha256", {})) != set(FILES)):
        raise ValueError("unapproved model revision or inventory")
    parts = [b"hepta.stem.granite97.material.v5\0"]
    total = 0
    for name in sorted(FILES):
        file = root / name
        if file.is_symlink() or not file.is_file():
            raise ValueError("missing or linked checkpoint file")
        observed_size = file.stat().st_size
        expected_size = manifest["files"][name]
        if type(expected_size) is not int or not 0 < expected_size <= 512_000_000:
            raise ValueError("invalid approved file size")
        if observed_size != expected_size:
            raise ValueError("pretrained checkpoint size changed")
        total += observed_size
        if total > 512_000_000:
            raise ValueError("pretrained materials exceed 512MB")
        digest = sha(file.read_bytes())
        if digest != manifest["sha256"][name]:
            raise ValueError("pretrained file digest changed")
        raw = name.encode("utf8")
        parts.extend((len(raw).to_bytes(4, "big"), raw,
                      observed_size.to_bytes(8, "big"), bytes.fromhex(digest)))
    return manifest, sha(b"".join(parts))


def complete_input_digest(original, ids, mask):
    if (not isinstance(original, bytes) or not 1 <= len(original) <= 65_536
            or not isinstance(ids, (list, tuple)) or not 1 <= len(ids) <= 256
            or len(ids) != len(mask) or
            any(type(x) is not int or not 0 <= x <= 1_000_000 for x in ids)
            or any(type(x) is not int or x != 1 for x in mask)):
        raise ValueError("complete bounded original/token input required")
    stream = bytearray(INPUT_DOMAIN)
    stream.extend(len(original).to_bytes(8, "big"))
    stream.extend(original)
    stream.extend(len(ids).to_bytes(4, "big"))
    for token_id in ids:
        stream.extend(token_id.to_bytes(4, "big"))
    stream.extend(bytes(mask))
    return sha(stream)


def quantize_rows(rows, mask):
    """No clipping or token dropping. Reject NaN, Inf and |feature| > 8."""
    if (not isinstance(rows, (list, tuple)) or not 1 <= len(rows) <= 256
            or len(rows) != len(mask)):
        raise ValueError("invalid token row count")
    output = []
    for features, keep in zip(rows, mask):
        if len(features) != 384:
            raise ValueError("Granite token hidden width must be 384")
        if type(keep) is not int or keep not in (0, 1):
            raise ValueError("nonbinary token mask")
        for value in features:
            v = float(value)
            if not math.isfinite(v) or abs(v) > 8:
                raise ValueError("nonfinite/out-of-range physical feature")
            q = round(v * Q24)
            if keep == 0 and q != 0:
                raise ValueError("noncanonical padded feature row")
            output.append(q)
    if 1 not in mask:
        raise ValueError("all rows masked")
    return output


def build_record(original, token_ids, mask, hidden, identity, material_digest,
                 expires_at_ms, forward_cpu_ns, forward_wall_ns, *,
                 principal_id, purpose_id, generation, authority_epoch):
    if type(expires_at_ms) is not int or expires_at_ms <= 0:
        raise ValueError("positive expiry required")
    if any(type(x) is not int or x <= 0 for x in (forward_cpu_ns, forward_wall_ns)):
        raise ValueError("measured positive forward costs required")
    if (any(not isinstance(value, str) or
            re.fullmatch(r"[A-Za-z0-9_.:-]{1,256}", value) is None
            for value in (principal_id, purpose_id))
            or any(type(v) is not int or not 1 <= v < 2**64
                   for v in (generation, authority_epoch))):
        raise ValueError("bounded principal/purpose/generation/epoch required")
    input_digest = complete_input_digest(original, token_ids, mask)
    return dict(schema=SCHEMA, model_id=MODEL_ID, revision=REVISION,
                principal_id=principal_id, purpose_id=purpose_id,
                generation=generation, authority_epoch=authority_epoch,
                material_digest=material_digest, source_sha256=sha(original),
                input_digest=input_digest, input_ids=list(token_ids),
                attention_mask=list(mask), width=384,
                values_q24=quantize_rows(hidden, mask),
                expires_at_ms=expires_at_ms, encoder_forwards=1,
                encoder_cpu_ns=forward_cpu_ns, encoder_wall_ns=forward_wall_ns,
                **identity)


def check_loaded_tensors(torch, model, model_path):
    from safetensors import safe_open
    parameters = model.state_dict()
    if not parameters:
        raise ValueError("empty loaded model")
    observed = set()
    with safe_open(str(model_path), framework="pt", device="cpu") as stored:
        for key in stored.keys():
            if key in observed or key not in parameters:
                raise ValueError("unexpected or duplicate model parameter")
            actual = parameters[key].detach().cpu()
            expected = stored.get_tensor(key).to(dtype=actual.dtype)
            if not torch.equal(actual, expected):
                raise ValueError("loaded parameter differs from safetensors")
            observed.add(key)
    if observed != set(parameters):
        raise ValueError("incomplete loaded tensor inventory")


def physical_export(root, original, *, max_tokens, expires_at_ms,
                    principal_id, purpose_id, generation, authority_epoch,
                    expected_material_digest):
    import torch
    import transformers
    from transformers import AutoConfig, AutoModel, AutoTokenizer
    if transformers.__version__ != "4.57.1":
        raise ValueError("exact Transformers 4.57.1 required")
    material, material_digest = load_material(root)
    if material_digest != expected_material_digest:
        raise ValueError("pretrained material differs from independent pinned manifest")
    identities = profile_digests(
        material_digest, material, max_tokens=max_tokens,
        torch_version=torch.__version__, transformers_version=transformers.__version__)
    config = AutoConfig.from_pretrained(str(root), local_files_only=True,
                                        trust_remote_code=False)
    if config.model_type != "modernbert" or config.hidden_size != 384:
        raise ValueError("unapproved architecture")
    config.reference_compile = False
    model, loading_info = AutoModel.from_pretrained(
        str(root), config=config, local_files_only=True, trust_remote_code=False,
        use_safetensors=True, output_loading_info=True,
        attn_implementation="eager", torch_dtype=torch.float32)
    for key in ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs"):
        if key not in loading_info or loading_info[key]:
            raise ValueError("incomplete pretrained model load")
    check_loaded_tensors(torch, model, Path(root) / "model.safetensors")
    model.eval().requires_grad_(False)
    tokenizer = AutoTokenizer.from_pretrained(
        str(root), local_files_only=True, trust_remote_code=False)
    source = original.decode("utf8", errors="strict")
    tokens = tokenizer(source, return_tensors="pt", truncation=False,
                       padding=False, add_special_tokens=True)
    if set(tokens) != {"input_ids", "attention_mask"}:
        raise ValueError("unexpected tokenizer model-input fields")
    input_ids = tokens["input_ids"]
    attention_mask = tokens["attention_mask"]
    if (tuple(input_ids.shape) != tuple(attention_mask.shape)
            or input_ids.ndim != 2 or input_ids.shape[0] != 1
            or not 1 <= input_ids.shape[1] <= max_tokens):
        raise ValueError("full, untruncated token sequence exceeds bounds")
    ids = input_ids[0].tolist()
    mask = attention_mask[0].tolist()
    complete_input_digest(original, ids, mask)
    before_wall, before_cpu = time.perf_counter_ns(), time.process_time_ns()
    with torch.no_grad():
        features = model(**tokens).last_hidden_state
    forward_wall = time.perf_counter_ns() - before_wall
    forward_cpu = time.process_time_ns() - before_cpu
    if tuple(features.shape) != (1, len(ids), 384) or not torch.isfinite(features).all():
        raise ValueError("invalid pretrained feature tensor")
    # Verify files again after materialization/forward; a model reload must
    # never silently assume previously checked path bytes remained unchanged.
    if load_material(root)[1] != material_digest:
        raise ValueError("checkpoint mutated during physical forward")
    return build_record(original, ids, mask, features[0].detach().cpu().tolist(),
                        identities, material_digest, expires_at_ms,
                        max(1, forward_cpu), max(1, forward_wall),
                        principal_id=principal_id, purpose_id=purpose_id,
                        generation=generation, authority_epoch=authority_epoch)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--model-root", required=True)
    cli.add_argument("--source", required=True)
    cli.add_argument("--source-sha256", required=True)
    cli.add_argument("--expected-material-sha256", required=True)
    cli.add_argument("--output", required=True)
    cli.add_argument("--expires-at-ms", required=True, type=int)
    cli.add_argument("--max-tokens", type=int, default=192)
    cli.add_argument("--principal-id", required=True)
    cli.add_argument("--purpose-id", required=True)
    cli.add_argument("--generation", required=True, type=int)
    cli.add_argument("--authority-epoch", required=True, type=int)
    args = cli.parse_args()
    source_path = Path(args.source)
    if source_path.is_symlink() or not source_path.is_file():
        raise SystemExit("regular source file required")
    original = source_path.read_bytes()
    if not 1 <= len(original) <= 65_536 or sha(original) != args.source_sha256:
        raise SystemExit("original source digest/limit mismatch")
    output = Path(args.output)
    if output.exists() or output.is_symlink():
        raise SystemExit("refusing to replace an export artifact")
    record = physical_export(Path(args.model_root), original,
                             max_tokens=args.max_tokens,
                             expires_at_ms=args.expires_at_ms,
                             principal_id=args.principal_id,
                             purpose_id=args.purpose_id,
                             generation=args.generation,
                             authority_epoch=args.authority_epoch,
                             expected_material_digest=args.expected_material_sha256)
    payload = canonical_json(record) + b"\n"
    if len(payload) > 2_500_000:
        raise SystemExit("export size exceeds Rust admission bound")
    with output.open("xb") as stream:
        stream.write(payload)


if __name__ == "__main__":
    main()
