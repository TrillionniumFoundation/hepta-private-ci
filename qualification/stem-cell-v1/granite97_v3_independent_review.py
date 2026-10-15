#!/usr/bin/env python3
"""Independent source-first physical replay of a pinned Granite97 V3 export.

This reviewer does NOT import the exporter or believe its self-reported forward
counts. If authentic model files are present, it separately loads every
safetensors weight, retokenizes the admitted original bytes, executes another
actual frozen FP32 forward and checks every Q24 value in the proposed export.
The independent original-source/model identities are CLI inputs. Outputs are
diagnostic-only (DENY_ALL); never a producer signature or execution grant.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import time

MODEL_ID = "ibm-granite/granite-embedding-97m-multilingual-r2"
REVISION = "835ad14087e140460703cf0fae09f97d469d65c2"
SCHEMA = "hepta.stem.granite97-token-export.v5"
FILES = ("config.json", "model.safetensors", "tokenizer.json",
         "tokenizer_config.json", "special_tokens_map.json")
EXPORT_FIELDS = frozenset((
    "schema", "model_id", "revision", "material_digest", "encoder_digest",
    "tokenizer_digest", "normalizer_digest", "quantization_digest",
    "preprocessing_digest", "adapter_digest", "source_sha256", "input_digest",
    "principal_id", "purpose_id", "generation", "authority_epoch", "input_ids",
    "attention_mask", "values_q24", "width", "expires_at_ms",
    "encoder_forwards", "encoder_cpu_ns", "encoder_wall_ns"))
DOMAIN_INPUT = b"hepta.stem.granite97.complete-token-input.v5\0"
DOMAIN_MATERIAL = b"hepta.stem.granite97.material.v5\0"
DOMAIN_MODEL = b"hepta.stem.granite97.frozen-model.v5\0"
Q24 = 1 << 24


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def digest(raw):
    if not isinstance(raw, str) or re.fullmatch(r"[0-9a-f]{64}", raw) is None or raw == "0" * 64:
        raise ValueError("canonical nonzero SHA256 digest required")
    return raw


def stable_id(value):
    if (not isinstance(value, str)
            or re.fullmatch(r"[A-Za-z0-9_.:-]{1,256}", value) is None):
        raise ValueError("bounded stable ID required")
    return value


def exact_integer(value, *, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("bounded nonboolean integer required")
    return value


def no_duplicate_pairs(items):
    data = {}
    for key, value in items:
        if key in data:
            raise ValueError("duplicate JSON property: " + key)
        data[key] = value
    return data


def load_json_file(path, maximum_bytes):
    p = Path(path)
    if p.is_symlink() or not p.is_file() or not 0 < p.stat().st_size <= maximum_bytes:
        raise ValueError("missing, linked or excessive artifact")
    raw = p.read_bytes()
    if len(raw) > maximum_bytes:
        raise ValueError("artifact grew during read")
    return json.loads(raw, object_pairs_hook=no_duplicate_pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError("nonfinite JSON"))), sha(raw)


def complete_digest(source, token_ids, mask):
    data = bytearray(DOMAIN_INPUT)
    data.extend(len(source).to_bytes(8, "big"))
    data.extend(source)
    data.extend(len(token_ids).to_bytes(4, "big"))
    for value in token_ids:
        data.extend(value.to_bytes(4, "big"))
    data.extend(bytes(mask))
    return sha(data)


def preflight_export(export, source, *, source_sha256, material_sha256, principal,
                     purpose, generation, authority_epoch, now_ms, maximum_expiry_ms):
    """Validate everything that does not require an actual model forward."""
    if not isinstance(export, dict) or set(export) != EXPORT_FIELDS:
        raise ValueError("unknown or missing token-export fields")
    if (export["schema"], export["model_id"], export["revision"]) != (
            SCHEMA, MODEL_ID, REVISION):
        raise ValueError("unregistered original model")
    for name in ("material_digest", "encoder_digest", "tokenizer_digest",
                 "normalizer_digest", "quantization_digest", "preprocessing_digest",
                 "adapter_digest", "source_sha256", "input_digest"):
        digest(export[name])
    if (export["material_digest"] != digest(material_sha256)
            or export["encoder_digest"] != sha(DOMAIN_MODEL + bytes.fromhex(material_sha256))
            or export["source_sha256"] != digest(source_sha256)
            or sha(source) != source_sha256):
        raise ValueError("external material/source identity changed")
    if not 1 <= len(source) <= 65536:
        raise ValueError("complete original source bound")
    for field, expected in (
        ("principal_id", stable_id(principal)),
        ("purpose_id", stable_id(purpose)),
        ("generation", exact_integer(generation, minimum=1, maximum=2**64 - 1)),
        ("authority_epoch", exact_integer(authority_epoch, minimum=1, maximum=2**64 - 1)),
    ):
        if type(export[field]) is not type(expected) or export[field] != expected:
            raise ValueError("principal, purpose or generation does not match owner")
    ids, mask = export["input_ids"], export["attention_mask"]
    if (not isinstance(ids, list) or not isinstance(mask, list)
            or not 1 <= len(ids) <= 256 or len(ids) != len(mask)
            or any(type(x) is not int or not 0 <= x <= 1_000_000 for x in ids)
            or any(type(x) is not int or x != 1 for x in mask)):
        raise ValueError("noncanonical, incomplete or padded source tokens")
    if export["input_digest"] != complete_digest(source, ids, mask):
        raise ValueError("token IDs do not match externally admitted source identity")
    if exact_integer(export["width"], minimum=384, maximum=384) != 384:
        raise ValueError("unregistered model width")
    rows = export["values_q24"]
    if (not isinstance(rows, list) or len(rows) != len(ids) * 384
            or any(type(x) is not int or not -(8 * Q24) <= x <= (8 * Q24)
                   for x in rows)):
        raise ValueError("invalid ordered Q24 features")
    exact_integer(now_ms, minimum=1, maximum=2**64 - 1)
    exact_integer(maximum_expiry_ms, minimum=now_ms + 1, maximum=2**64 - 1)
    exp = exact_integer(export["expires_at_ms"], minimum=now_ms + 1,
                        maximum=maximum_expiry_ms)
    if not now_ms < exp <= maximum_expiry_ms:
        raise ValueError("out-of-window cached source")
    for n in ("encoder_forwards", "encoder_cpu_ns", "encoder_wall_ns"):
        exact_integer(export[n], minimum=1, maximum=2**64 - 1)
    if export["encoder_forwards"] != 1:
        raise ValueError("unverified producer forward claim")
    return dict(input_digest=export["input_digest"], source_digest=sha(source),
                rows=len(ids), width=384)


def inspect_original_material(root, independent_digest):
    """Recompute material identity from every exact path and file content."""
    folder = Path(root)
    if not folder.is_dir() or folder.is_symlink():
        raise ValueError("pinned local model directory required")
    manifest, _ = load_json_file(folder / "material.json", 16384)
    if (not isinstance(manifest, dict)
            or manifest.get("model_id") != MODEL_ID
            or manifest.get("revision") != REVISION
            or set(manifest.get("files", {})) != set(FILES)
            or set(manifest.get("sha256", {})) != set(FILES)):
        raise ValueError("unreviewed checkpoint inventory")
    result = [DOMAIN_MATERIAL]
    total = 0
    for name in sorted(FILES):
        path = folder / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("missing model file or symlink")
        size = path.stat().st_size
        if (type(manifest["files"][name]) is not int
                or not 0 < size <= 512_000_000
                or size != manifest["files"][name]):
            raise ValueError("material size mismatch")
        total += size
        if total > 512_000_000:
            raise ValueError("material budget exceeded")
        with path.open("rb") as fd:
            file_hash = hashlib.file_digest(fd, "sha256").hexdigest()
        if digest(manifest["sha256"][name]) != file_hash:
            raise ValueError("model SHA mismatch")
        encoded = name.encode("utf8")
        result.extend((len(encoded).to_bytes(4, "big"), encoded,
                       size.to_bytes(8, "big"), bytes.fromhex(file_hash)))
    calculated = sha(b"".join(result))
    if calculated != digest(independent_digest):
        raise ValueError("external pinned material digest mismatch")
    return calculated



def verify_preprocessing_profile(export, manifest, *, maximum_tokens,
                                 torch_version, transformers_version):
    """Independently recompute each public parameterization/profile digest.

    Matching tokenizer IDs alone cannot authorize a different normalization,
    truncation, precision or runtime configuration.
    """
    file_shas = manifest["sha256"]
    tokenizer_files = {
        key: file_shas[key] for key in FILES
        if "token" in key or key == "special_tokens_map.json"
    }
    canonical = lambda value: json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False).encode()
    profile = dict(
        tokenizer_digest=sha(
            b"hepta.granite97.tokenizer.v5\0" + canonical(tokenizer_files)),
        normalizer_digest=sha(b"hepta.granite97.identity-normalizer.v5"),
        quantization_digest=sha(b"hepta.granite97.fp32-q24-ties-even.v5"),
        preprocessing_digest=sha(
            b"hepta.granite97.preprocessing.v5\0"
            + canonical(dict(
                max_tokens=maximum_tokens, truncation=False,
                add_special_tokens=True, padding=False, precision="fp32",
                attention="eager", output="last_hidden_state",
                tokenizer=tokenizer_files, torch_version=torch_version,
                transformers_version=transformers_version,
                model_config_sha256=file_shas["config.json"]))),
        adapter_digest=sha(b"hepta.granite97.identity-adapter.v5"),
    )
    for name, value in profile.items():
        if export[name] != value:
            raise ValueError("physical profile differs from export: " + name)
    return profile


def verify_real_weights(torch, model, model_root):
    from safetensors import safe_open
    state = model.state_dict()
    if not state or any(value.device.type == "meta" for value in state.values()):
        raise ValueError("incomplete physical model")
    observed = set()
    with safe_open(str(Path(model_root) / "model.safetensors"), framework="pt",
                   device="cpu") as stored:
        for name in stored.keys():
            if name in observed or name not in state:
                raise ValueError("unexpected or duplicated pretrained tensor")
            tensor = state[name].detach().cpu()
            if not torch.equal(tensor, stored.get_tensor(name).to(dtype=tensor.dtype)):
                raise ValueError("physical parameter differs from immutable snapshot")
            observed.add(name)
    if observed != set(state):
        raise ValueError("missing tensor in pretrained physical model")
    return len(observed)


def independent_replay(export, source, root, *, material_sha256, maximum_tokens):
    """A separately loaded, frozen real forward; no shared exporter callbacks."""
    import torch
    import transformers
    from transformers import AutoConfig, AutoModel, AutoTokenizer

    if transformers.__version__ != "4.57.1" or not 1 <= maximum_tokens <= 256:
        raise ValueError("unapproved model software or token ceiling")
    inspect_original_material(root, material_sha256)
    material, _ = load_json_file(Path(root) / "material.json", 16384)
    verify_preprocessing_profile(
        export, material, maximum_tokens=maximum_tokens,
        torch_version=torch.__version__, transformers_version=transformers.__version__)
    config = AutoConfig.from_pretrained(str(root), local_files_only=True,
                                        trust_remote_code=False)
    if config.model_type != "modernbert" or config.hidden_size != 384:
        raise ValueError("unregistered Encoder architecture")
    config.reference_compile = False
    model, info = AutoModel.from_pretrained(
        str(root), config=config, local_files_only=True, trust_remote_code=False,
        use_safetensors=True, output_loading_info=True,
        attn_implementation="eager", torch_dtype=torch.float32)
    for key in ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs"):
        if not isinstance(info, dict) or key not in info or info[key]:
            raise ValueError("pretrained load was incomplete")
    tensors = verify_real_weights(torch, model, root)
    model.eval().requires_grad_(False)
    tokenizer = AutoTokenizer.from_pretrained(str(root), local_files_only=True,
                                               trust_remote_code=False)
    tokens = tokenizer(source.decode("utf8", errors="strict"), return_tensors="pt",
                       truncation=False, padding=False, add_special_tokens=True)
    if set(tokens) != {"input_ids", "attention_mask"}:
        raise ValueError("unexpected tokenizer inputs")
    ids = tokens["input_ids"][0].tolist()
    masks = tokens["attention_mask"][0].tolist()
    if (len(ids) > maximum_tokens or ids != export["input_ids"]
            or masks != export["attention_mask"]):
        raise ValueError("claimed tokens differ from independently encoded source")
    before_wall, before_cpu = time.perf_counter_ns(), time.process_time_ns()
    with torch.no_grad():
        y = model(**tokens).last_hidden_state
    real_cpu = time.process_time_ns() - before_cpu
    real_wall = time.perf_counter_ns() - before_wall
    if real_cpu <= 0 or real_wall <= 0:
        raise ValueError("unmeasured reviewer model execution")
    if tuple(y.shape) != (1, len(ids), 384) or not torch.isfinite(y).all():
        raise ValueError("incomplete physical Encoder output")
    actual = []
    for row in y[0].detach().cpu().tolist():
        for number in row:
            if not -8 <= number <= 8:
                raise ValueError("native Q24 range exceeded; no clipping")
            actual.append(round(number * Q24))
    if actual != export["values_q24"]:
        raise ValueError("model did not physically reproduce submitted Q24 tokens")
    if inspect_original_material(root, material_sha256) != material_sha256:
        raise ValueError("model changed after re-execution")
    return dict(reviewer_encoder_forwards=1, reviewer_encoder_cpu_ns=real_cpu,
                reviewer_encoder_wall_ns=real_wall, exact_tensors=tensors)


def run(args):
    source_path = Path(args.source)
    if (source_path.is_symlink() or not source_path.is_file()
            or not 0 < source_path.stat().st_size <= 65536):
        raise ValueError("invalid source")
    source = source_path.read_bytes()
    if digest(args.source_sha256) != sha(source):
        raise ValueError("independent original source hash mismatch")
    export, export_file_sha = load_json_file(args.export, 2_500_000)
    observed_now_ms = time.time_ns() // 1_000_000
    # Real physical admission cannot be revived with a caller-supplied stale
    # timestamp. The caller clock is a diagnostic consistency check only.
    if (type(args.now_ms) is not int
            or abs(args.now_ms - observed_now_ms) > 10_000):
        raise ValueError("physical admission clock differs from wall clock")
    expected = preflight_export(
        export, source, source_sha256=args.source_sha256,
        material_sha256=args.expected_material_sha256,
        principal=args.principal_id, purpose=args.purpose_id,
        generation=args.generation, authority_epoch=args.authority_epoch,
        now_ms=observed_now_ms, maximum_expiry_ms=args.maximum_expiry_ms)
    proof = independent_replay(
        export, source, args.model_root, material_sha256=args.expected_material_sha256,
        maximum_tokens=args.max_tokens)
    output = dict(schema="hepta.stem.granite97-independent-physical-review.v1",
                  source_sha256=expected["source_digest"],
                  input_digest=expected["input_digest"],
                  export_sha256=export_file_sha,
                  material_sha256=args.expected_material_sha256,
                  encoder_digest=export["encoder_digest"],
                  feature_q24_sha256=sha(b"".join(
                      value.to_bytes(8, "big", signed=True) for value in export["values_q24"])),
                  producer_claimed_forwards=export["encoder_forwards"],
                  producer_claimed_cpu_ns=export["encoder_cpu_ns"],
                  producer_claimed_wall_ns=export["encoder_wall_ns"],
                  **proof,
                  model_replayed=True, selected_model=False,
                  production_authorized=False, authority="DENY_ALL")
    destination = Path(args.output)
    if destination.exists() or destination.is_symlink():
        raise ValueError("never overwrite an original physical review")
    payload = json.dumps(output, sort_keys=True, allow_nan=False,
                         separators=(",", ":")).encode() + b"\n"
    with destination.open("xb") as handle:
        handle.write(payload)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("model-root", "source", "source-sha256", "export",
                  "expected-material-sha256", "principal-id", "purpose-id", "output"):
        parser.add_argument("--" + field, required=True)
    for field in ("generation", "authority-epoch", "now-ms", "maximum-expiry-ms"):
        parser.add_argument("--" + field, required=True, type=int)
    parser.add_argument("--max-tokens", type=int, default=192)
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
