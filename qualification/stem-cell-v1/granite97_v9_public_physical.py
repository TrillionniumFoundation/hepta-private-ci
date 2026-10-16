"""One public, SHA-pinned genuine Granite97 producer/reviewer/native study.

The model and evidence files are downloaded/acquired by workflow owners, not
this module. All records remain RESEARCH_ONLY/DENY_ALL. A byte lock is NOT an
independent signer or evidence of physical inference; live producer, reviewer
and native processes must separately run and seal their actual results.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time

MODEL_ID = "ibm-granite/granite-embedding-97m-multilingual-r2"
REVISION = "835ad14087e140460703cf0fae09f97d469d65c2"
FILES = (
    "config.json", "model.safetensors", "tokenizer.json",
    "tokenizer_config.json", "special_tokens_map.json",
)
SOURCE_SHA = "8d6dd20b7f64904c33b81a90a204d6f123e87b45b40cf7ac519862ef96812610"
# Recorded from an earlier independently rehashed 5-file REAL model artifact,
# not an upstream publisher's signature or an authenticated owner grant.
REVIEWED_MATERIAL_SHA256 = "9d39552804582ee18cd61992e012510feae4cddb492b3b74808f6f46f494b0d8"
SCHEMA = "hepta.stem.granite97-public-physical-lock.v9"
PRINCIPAL = "research:granite97-public-v9"
PURPOSE = "research:constructed-source-only"
GENERATION = 9
EPOCH = 1
Q24 = 1 << 24
FEATURE_ADAPTER = "rational8-v1"
ADAPTER_DIGEST = hashlib.sha256(b"hepta.granite97.rational8-adapter.v6\0").hexdigest()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(path: Path, limit: int) -> tuple[dict, bytes]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise ValueError("missing, linked, or oversized sealed research input")
    data = path.read_bytes()

    def no_duplicates(pairs):
        found = {}
        for key, value in pairs:
            if key in found:
                raise ValueError("duplicate JSON key")
            found[key] = value
        return found

    result = json.loads(data, object_pairs_hook=no_duplicates,
                        parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))
    if not isinstance(result, dict):
        raise ValueError("expected JSON object")
    return result, data


def _write_exclusive(path: Path, obj: dict) -> None:
    data = (json.dumps(obj, sort_keys=True, ensure_ascii=False,
                       allow_nan=False, separators=(",", ":")) + "\n").encode()
    with path.open("xb") as f:
        f.write(data)
        f.flush()


def source_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("the constructed original source must be a regular file")
    raw = path.read_bytes()
    if not raw or len(raw) > 65536 or sha(raw) != SOURCE_SHA:
        raise ValueError("source content does not match the frozen public-source digest")
    raw.decode("utf-8", errors="strict")
    return raw


def calculate_material(root: Path) -> tuple[dict, str]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("original material root required")
    sizes, hashes = {}, {}
    pieces = [b"hepta.stem.granite97.material.v5\0"]
    total = 0
    for name in sorted(FILES):
        p = root / name
        if p.is_symlink() or not p.is_file():
            raise ValueError(f"original material unavailable: {name}")
        size = p.stat().st_size
        if not 0 < size <= 512_000_000:
            raise ValueError("invalid original model file size")
        total += size
        if total > 512_000_000:
            raise ValueError("original material budget exceeded")
        with p.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        sizes[name], hashes[name] = size, digest
        b = name.encode()
        pieces.extend((len(b).to_bytes(4, "big"), b,
                       size.to_bytes(8, "big"), bytes.fromhex(digest)))
    material = {"model_id": MODEL_ID, "revision": REVISION,
                "files": sizes, "sha256": hashes}
    return material, sha(b"".join(pieces))


def prepare(source: Path, model_root: Path, lock_output: Path, *, now_ms: int) -> dict:
    source_bytes(source)
    manifest, digest = calculate_material(model_root)
    _write_exclusive(model_root / "material.json", manifest)
    lock = {
        "schema": SCHEMA, "model_id": MODEL_ID, "revision": REVISION,
        "material_sha256": digest, "source_sha256": SOURCE_SHA,
        "principal_id": PRINCIPAL, "purpose_id": PURPOSE,
        "generation": GENERATION, "authority_epoch": EPOCH,
        "feature_adapter": FEATURE_ADAPTER, "adapter_digest": ADAPTER_DIGEST,
        "expires_at_ms": now_ms + 2 * 60 * 60 * 1000,
        "upstream_commit_pinned": True,
        "independent_model_owner_authenticated": False,
        "independent_source_owner_authenticated": False,
        "independent_hardware_attested": False,
        "labels_exposed": False, "model_selected": False,
        "production_authorized": False, "authority": "DENY_ALL",
    }
    _write_exclusive(lock_output, lock)
    return lock


def check_lock_static(lock: dict) -> None:
    """Validate old model/source record as content metadata, never a live lease.

    This cannot authenticate a source signer or renew an existing authority.
    """
    expected = {"schema", "model_id", "revision", "material_sha256",
                "source_sha256", "principal_id", "purpose_id", "generation",
                "authority_epoch", "feature_adapter", "adapter_digest",
                "expires_at_ms", "upstream_commit_pinned",
                "independent_model_owner_authenticated", "independent_source_owner_authenticated",
                "independent_hardware_attested", "labels_exposed", "model_selected",
                "production_authorized", "authority"}
    if set(lock) != expected or any((lock.get(key) != value) for key, value in {
        "schema": SCHEMA, "model_id": MODEL_ID, "revision": REVISION,
        "source_sha256": SOURCE_SHA, "principal_id": PRINCIPAL, "purpose_id": PURPOSE,
        "generation": GENERATION, "authority_epoch": EPOCH,
        "feature_adapter": FEATURE_ADAPTER, "adapter_digest": ADAPTER_DIGEST,
        "upstream_commit_pinned": True, "independent_model_owner_authenticated": False,
        "independent_source_owner_authenticated": False,
        "independent_hardware_attested": False, "labels_exposed": False,
        "model_selected": False, "production_authorized": False,
        "authority": "DENY_ALL"}.items()):
        raise ValueError("unqualified source/model/authority lock")
    material = lock["material_sha256"]
    if not isinstance(material, str) or len(material) != 64 or any(c not in "0123456789abcdef" for c in material):
        raise ValueError("invalid original material lock")
    expires = lock["expires_at_ms"]
    if type(expires) is not int or expires <= 0:
        raise ValueError("invalid historical research TTL")


def check_lock(lock: dict, *, now_ms: int | None = None) -> None:
    check_lock_static(lock)
    if lock["expires_at_ms"] <= (
            now_ms if now_ms is not None else time.time_ns() // 1_000_000):
        raise ValueError("expired research material lock")


def restage_fresh_physical_session(previous: Path, fresh: Path, *,
                                   now_ms: int,
                                   expected_reviewed_material_sha256: str | None = None) -> dict:
    """Create NEW research-only data from rehashed originals, not old authority.

    The previous TTL may be expired in the Actions queue. It is never
    extended: all original source/model bytes are copied, rehashed, and a
    separate create-only short-lived data record is generated instead.
    """
    if type(now_ms) is not int or now_ms <= 0:
        raise ValueError("fresh positive wall-clock integer required")
    if previous.is_symlink() or not previous.is_dir():
        raise ValueError("archived material directory required")
    former, _ = _json(previous / "lock.json", 8192)
    check_lock_static(former)
    _, digest = calculate_material(previous / "model")
    if expected_reviewed_material_sha256 is not None and (
            expected_reviewed_material_sha256 != REVIEWED_MATERIAL_SHA256
            or digest != REVIEWED_MATERIAL_SHA256):
        raise ValueError("archived original bytes differ from reviewed real-material baseline")
    if digest != former["material_sha256"]:
        raise ValueError("original material changed relative to prior data receipt")
    source_bytes_original = source_bytes(previous / "source.txt")
    if (former["feature_adapter"] != FEATURE_ADAPTER or
            former["adapter_digest"] != ADAPTER_DIGEST):
        raise ValueError("registered adapter differs from previous material census")
    if (fresh.exists() or fresh.is_symlink() or fresh.parent.is_symlink()
            or fresh.resolve().is_relative_to(previous.resolve())):
        raise ValueError("fresh session must be a distinct unlinked directory")
    fresh.mkdir(parents=False, exist_ok=False)
    model = fresh / "model"
    model.mkdir()
    for name in FILES:
        original = previous / "model" / name
        if original.is_symlink() or not original.is_file():
            raise ValueError("archived original model is not a regular file")
        with original.open("rb") as src, (model / name).open("xb") as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)
    if calculate_material(model)[1] != digest:
        raise ValueError("fresh model differs from independently rehashed original")
    new_source = fresh / "source.txt"
    with new_source.open("xb") as dst:
        dst.write(source_bytes_original)
    lock = prepare(new_source, model, fresh / "lock.json", now_ms=now_ms)
    if (lock["material_sha256"] != digest
            or lock["source_sha256"] != SOURCE_SHA
            or lock["feature_adapter"] != FEATURE_ADAPTER
            or lock["adapter_digest"] != ADAPTER_DIGEST
            or lock["authority"] != "DENY_ALL"
            or lock["production_authorized"] is not False):
        raise ValueError("new data session mismatch")
    summary = {
        "schema": "hepta.stem.granite97-fresh-session-metadata.v1",
        "new_research_data_session": True,
        "expired_lock_reused_or_extended": False,
        "source_sha256": SOURCE_SHA,
        "material_sha256": digest,
        "feature_adapter": FEATURE_ADAPTER,
        "independent_model_or_source_signer_verified": False,
        "production_authorized": False,
        "authority": "DENY_ALL",
    }
    _write_exclusive(fresh / "session.json", summary)
    return summary


def _check_export_and_review(lock: dict, source: bytes, export: dict,
                             review: dict, exp_raw: bytes) -> None:
    if sha(source) != lock["source_sha256"]:
        raise ValueError("source content changed")
    ex_required = ("source_sha256", "input_digest", "material_digest", "encoder_digest",
                   "tokenizer_digest", "normalizer_digest", "quantization_digest",
                   "preprocessing_digest", "adapter_digest", "expires_at_ms")
    if not all(isinstance(export.get(k), str) for k in ex_required[:-1]):
        raise ValueError("incomplete original feature identity")
    if (export["material_digest"] != lock["material_sha256"] or
            export["source_sha256"] != lock["source_sha256"] or
            export["adapter_digest"] != lock["adapter_digest"] or
            export["expires_at_ms"] != lock["expires_at_ms"] or
            export.get("encoder_forwards") != 1):
        raise ValueError("original model source/work/expiry mismatch")
    if (review.get("schema") != "hepta.stem.granite97-independent-physical-review.v1" or
            review.get("export_sha256") != sha(exp_raw) or
            review.get("source_sha256") != lock["source_sha256"] or
            review.get("input_digest") != export["input_digest"] or
            review.get("material_sha256") != lock["material_sha256"] or
            review.get("encoder_digest") != export["encoder_digest"] or
            review.get("reviewer_encoder_forwards") != 1 or
            review.get("model_replayed") is not True or
            review.get("authority") != "DENY_ALL" or
            review.get("selected_model") is not False or
            review.get("production_authorized") is not False):
        raise ValueError("missing complete physical reviewer or immutable identity")
    vals = export.get("values_q24")
    ids = export.get("input_ids")
    if (not isinstance(ids, list) or not 1 <= len(ids) <= 256
        or not isinstance(vals, list) or len(vals) != 384 * len(ids)
        or any(type(v) is not int or abs(v) > 8 * Q24 for v in vals)):
        raise ValueError("invalid complete original token-tensor inventory")
    observed_q24 = sha(b"".join(v.to_bytes(8, "big", signed=True) for v in vals))
    if review.get("feature_q24_sha256") != observed_q24:
        raise ValueError("independent reviewer feature digest mismatch")
    for k in ("reviewer_encoder_cpu_ns", "reviewer_encoder_wall_ns", "exact_tensors"):
        if type(review.get(k)) is not int or review[k] <= 0:
            raise ValueError("impossible physical review work receipt")


def head(cell_id: str, *, differentiate: bool) -> dict:
    # Two independently addressed Q24 numeric Heads, NOT learned model weights.
    local = [0] * 384
    if differentiate:
        local[0] = Q24
    return {"cell_id": cell_id, "attention": "causal",
            "query_q24": [0] * 384, "key_q24": [0] * 384,
            "value_q24": [0] * 384, "local_q24": local, "bias_q24": 0}


def admit(lock_file: Path, source_file: Path, export_file: Path,
          review_file: Path, output: Path) -> dict:
    lock, _ = _json(lock_file, 8192)
    check_lock(lock)
    source = source_bytes(source_file)
    export, exp_raw = _json(export_file, 2_500_000)
    review, review_raw = _json(review_file, 65536)
    _check_export_and_review(lock, source, export, review, exp_raw)
    result = {
        "schema": "hepta.stem.granite-v3-local-admission.v7",
        "principal_id": lock["principal_id"], "purpose_id": lock["purpose_id"],
        "generation": lock["generation"], "authority_epoch": lock["authority_epoch"],
        "material_digest": lock["material_sha256"],
        "source_digest": lock["source_sha256"],
        "complete_input_digest": export["input_digest"],
        "tokenizer_digest": export["tokenizer_digest"],
        "normalizer_digest": export["normalizer_digest"],
        "quantization_digest": export["quantization_digest"],
        "preprocessing_digest": export["preprocessing_digest"],
        "adapter_digest": export["adapter_digest"],
        "export_bytes_digest": sha(exp_raw),
        "independent_review_bytes_digest": sha(review_raw),
        "maximum_expires_at_ms": lock["expires_at_ms"],
        "maximum_attention_pairs": 2_000_000,
        "heads": [head("cell:reference", differentiate=False),
                  head("cell:local-q24", differentiate=True)],
    }
    _write_exclusive(output, result)
    return result


def audit_native(lock_file: Path, admission: Path, native: Path, output: Path) -> dict:
    lock, _ = _json(lock_file, 8192)
    check_lock(lock)
    admitted, admitted_raw = _json(admission, 1_000_000)
    result, result_raw = _json(native, 65536)
    if (result.get("schema") != "hepta.stem.granite-v3-local-shadow-result.v7"
        or result.get("authority") != "DENY_ALL"
        or result.get("model_selected") is not False
        or result.get("production_authorized") is not False
        or result.get("admission_bytes_digest") != sha(admitted_raw)
        or result.get("original_source_digest") != lock["source_sha256"]
        or result.get("exported_bytes_digest") != admitted["export_bytes_digest"]
        or result.get("independently_reviewed_bytes_digest") != admitted["independent_review_bytes_digest"]
        or result.get("complete_input_digest") != admitted["complete_input_digest"]
        or result.get("claimed_reviewer_encoder_forwards") != 1
        or type(result.get("actual_reader_attention_pairs")) is not int
        or result["actual_reader_attention_pairs"] <= 0
        or len(result.get("cells", [])) != 2
        or [x.get("cell_id") for x in result["cells"]] != ["cell:reference", "cell:local-q24"]):
        raise ValueError("native physical Q24 Reader outcome/authority mismatch")
    report = {
        "schema": "hepta.stem.granite97-public-physical-result.v9",
        "original_pretrained_forward_attested_by_source_bytes": False,
        "independent_source_or_model_signer": False,
        "pretrained_task_correctness_established": False,
        "trained_head_superiority_established": False,
        "end_to_end_cost_superiority_established": False,
        "model_selected": False, "production_authorized": False,
        "authority": "DENY_ALL", "source_sha256": lock["source_sha256"],
        "model_material_sha256": lock["material_sha256"],
        "native_raw_receipt_sha256": sha(result_raw),
        "admission_sha256": sha(admitted_raw),
        "cell_count": 2,
        "native_q24_attention_pairs": result["actual_reader_attention_pairs"],
        "claimed_independent_reviewer_forwards": result["claimed_reviewer_encoder_forwards"],
    }
    _write_exclusive(output, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="cmd", required=True)
    stage = commands.add_parser("prepare")
    for key in ("model-root", "source", "lock-output"):
        stage.add_argument("--" + key, required=True)
    stage.add_argument("--material-baseline-sha256", required=True)
    renewed = commands.add_parser("restage")
    renewed.add_argument("--original-root", required=True)
    renewed.add_argument("--fresh-root", required=True)
    adm = commands.add_parser("admit")
    for key in ("lock", "source", "export", "review", "output"):
        adm.add_argument("--" + key, required=True)
    audit = commands.add_parser("audit")
    for key in ("lock", "admission", "native", "output"):
        audit.add_argument("--" + key, required=True)
    args = parser.parse_args()
    if args.cmd == "prepare":
        # Source-only synthetic fixture tests invoke prepare() directly. Actual
        # physical CLI must admit ONLY the previously reviewed original bytes.
        if args.material_baseline_sha256 != REVIEWED_MATERIAL_SHA256:
            raise ValueError("wrong independently reviewed model-material baseline")
        if calculate_material(Path(args.model_root))[1] != REVIEWED_MATERIAL_SHA256:
            raise ValueError("physical model differs from prior real-material audit")
        prepare(Path(args.source), Path(args.model_root), Path(args.lock_output),
                now_ms=time.time_ns() // 1_000_000)
    elif args.cmd == "restage":
        restage_fresh_physical_session(
            Path(args.original_root), Path(args.fresh_root),
            now_ms=time.time_ns() // 1_000_000,
            expected_reviewed_material_sha256=REVIEWED_MATERIAL_SHA256)
    elif args.cmd == "admit":
        admit(Path(args.lock), Path(args.source), Path(args.export),
              Path(args.review), Path(args.output))
    else:
        audit_native(Path(args.lock), Path(args.admission),
                     Path(args.native), Path(args.output))


if __name__ == "__main__":
    main()
