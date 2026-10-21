#!/usr/bin/env python3
"""Local-file-only paired text/Omni alignment qualification (no training).

Measures real text-media ranking, latency and RSS on an independently supplied
held-out dataset. No URL fetch, media upload, placeholder embeddings or
production-promotion path. Media bytes are never written to the result.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time

from jina_v5 import FrozenJinaV5, MODELS, research_environment, sha256_record, validate_identity
from qualified_eval import read_jsonl, write_json

EXTENSIONS = {
    "image": {".jpg", ".jpeg", ".png", ".webp"},
    "audio": {".wav", ".flac", ".mp3", ".ogg"},
    "video": {".mp4", ".mov", ".mkv", ".webm"},
}
MAX_MEDIA_BYTES = 512 * 1024 * 1024


def safe_media(root, row):
    modality = row["modality"]
    if modality not in EXTENSIONS:
        raise ValueError("unsupported media modality")
    relative = Path(row["path"])
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("media paths must be relative and contained")
    root = Path(root).resolve(strict=True)
    file = (root / relative).resolve(strict=True)
    if not file.is_relative_to(root) or not file.is_file():
        raise ValueError("media escapes approved root")
    if file.suffix.lower() not in EXTENSIONS[modality]:
        raise ValueError("media type is not in approved decoder allowlist")
    if not 0 < file.stat().st_size <= MAX_MEDIA_BYTES:
        raise ValueError("media size outside bound")
    hasher = hashlib.sha256()
    with file.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    observed = hasher.hexdigest()
    if row["media_sha256"] != observed:
        raise ValueError("media digest mismatch; source is not frozen")
    return str(file), observed


def audit_multimodal(rows):
    seen, groups, texts, media_splits = set(), {}, set(), {}
    timestamps = defaultdict(list)
    valid_splits = {"test", "future", "ood"}
    for row in rows:
        required = ("case_id", "group_id", "scope_id", "split",
                    "modality", "path", "paired_text", "media_sha256", "event_time")
        if any(not isinstance(row.get(k), str) or not row[k] for k in required):
            raise ValueError("invalid or missing paired row fields")
        if row["case_id"] in seen:
            raise ValueError("duplicate case")
        seen.add(row["case_id"])
        if row["split"] not in valid_splits or row["modality"] not in EXTENSIONS:
            raise ValueError("invalid modality or held-out split")
        if len(row["media_sha256"]) != 64 or any(c not in "0123456789abcdef"
                                                  for c in row["media_sha256"]):
            raise ValueError("invalid media SHA256")
        try:
            instant = datetime.fromisoformat(row["event_time"].replace("Z", "+00:00"))
            if instant.tzinfo is None:
                raise ValueError("naive event time")
            timestamps[row["split"]].append(instant.astimezone(timezone.utc))
        except ValueError as exc:
            raise ValueError("invalid UTC-resolvable media event time") from exc
        prior_split = media_splits.setdefault(row["media_sha256"], row["split"])
        if prior_split != row["split"]:
            raise ValueError("identical media bytes leaked across time windows")
        group_key = (row["scope_id"], row["group_id"])
        if group_key in groups and groups[group_key] != row["split"]:
            raise ValueError("paired media leakage across splits")
        groups[group_key] = row["split"]
        semantic_key = (row["scope_id"], row["split"], row["paired_text"])
        if semantic_key in texts:
            raise ValueError("ambiguous duplicate positive text within ranking cohort")
        texts.add(semantic_key)
    if not timestamps["test"] or not timestamps["future"]:
        raise ValueError("both held-out test and genuine future splits are required")
    if max(timestamps["test"]) >= min(timestamps["future"]):
        raise ValueError("future media window is not strictly after test window")
    return {"cases": len(rows), "independent_groups": len(groups),
            "dataset_digest": sha256_record(rows),
            "future_temporal_order_checked": True}


def paired_ranking(examples, direction="media-to-text"):
    """Evaluate a registered asymmetric Jina query/document direction.

    Both modalities use task-aligned encoders; cosine is a dot product
    because the feature adapter verifies L2 normalization.
    """
    if direction not in ("media-to-text", "text-to-media"):
        raise ValueError("unregistered cross-modal retrieval direction")
    query_key, document_key = (
        ("media_vector", "text_vector") if direction == "media-to-text"
        else ("text_vector", "media_vector")
    )
    buckets = defaultdict(list)
    for row in examples:
        buckets[(row["scope_id"], row["split"])].append(row)
    results = []
    for (scope, split), items in sorted(buckets.items()):
        if len(items) < 2:
            raise ValueError("at least two independently labeled pairs per ranking cohort")
        for row in items:
            similarities = [sum(a * b for a, b in zip(
                row[query_key], other[document_key])) for other in items]
            if not all(math.isfinite(x) for x in similarities):
                raise ValueError("non-finite similarity")
            ranked = sorted(range(len(items)), key=lambda i: (-similarities[i], items[i]["case_id"]))
            actual = next(i for i, other in enumerate(items)
                          if other["case_id"] == row["case_id"])
            position = ranked.index(actual)
            results.append({
                "case_id": row["case_id"], "scope_id": scope, "split": split,
                "modality": row["modality"],
                "retrieval_direction": direction,
                "recall_at_1": int(position == 0),
                "rank": position + 1, "paired_cosine": similarities[actual],
                "media_sha256": row["media_sha256"],
                "media_wall_ms": row["media_wall_ms"],
                "text_wall_ms": row["text_wall_ms"],
                "rss_bytes": row["rss_bytes"],
            })
    return results


def run(args):
    import psutil
    if args.omni_model not in ("jina-v5-omni-nano", "jina-v5-omni-small"):
        raise ValueError("an Omni model must be selected")
    spec = MODELS[args.omni_model]
    expected_text = "jina-v5-text-" + spec.family
    if args.text_model != expected_text:
        raise ValueError("Text and Omni must be from matching Nano/Small families")
    if args.modality not in ("vision", "audio", "omni"):
        raise ValueError("the approved multimodal tower must be explicit")
    if args.direction not in ("media-to-text", "text-to-media"):
        raise ValueError("unknown asymmetric retrieval direction")
    text_intent = "document" if args.direction == "media-to-text" else "query"
    media_intent = "query" if args.direction == "media-to-text" else "document"
    validate_identity(args.omni_model, args.omni_revision, "retrieval",
                      args.dimension, args.modality, args.max_tokens)
    validate_identity(args.text_model, args.text_revision, "retrieval",
                      args.dimension, "text", args.max_tokens)
    rows = read_jsonl(args.dataset)
    audit = audit_multimodal(rows)
    if args.output.exists():
        raise ValueError("refusing to overwrite prior measured evidence")
    checked = []
    for row in rows:
        media_file, media_digest = safe_media(args.media_root, row)
        if args.modality == "vision" and row["modality"] == "audio":
            raise ValueError("audio requested from vision-only tower")
        if args.modality == "audio" and row["modality"] != "audio":
            raise ValueError("non-audio requested from audio-only tower")
        checked.append((row, media_file, media_digest))
    text_stem = FrozenJinaV5(
        args.text_model, args.text_revision, task="retrieval",
        dimension=args.dimension, max_tokens=args.max_tokens,
        allow_pinned_remote_code=args.allow_pinned_remote_code,
        allow_download=args.allow_model_download, device=args.device,
        snapshot_dir=args.text_snapshot, store_root=args.text_store_root,
        expected_snapshot_digest=args.text_snapshot_digest)
    omni_stem = FrozenJinaV5(
        args.omni_model, args.omni_revision, task="retrieval",
        dimension=args.dimension, max_tokens=args.max_tokens,
        modality=args.modality, allow_pinned_remote_code=args.allow_pinned_remote_code,
        allow_download=args.allow_model_download, device=args.device,
        snapshot_dir=args.omni_snapshot, store_root=args.omni_store_root,
        expected_snapshot_digest=args.omni_snapshot_digest)
    process = psutil.Process()
    observations = []
    for row, path, media_digest in checked:
        start = time.perf_counter_ns()
        tvec, _ = text_stem.encode_batch(
            [row["paired_text"]], scope_id=row["scope_id"], principal_id=args.principal_id,
            generation=args.generation, authority_epoch=args.authority_epoch, intent=text_intent)
        text_ms = (time.perf_counter_ns() - start) / 1e6
        start = time.perf_counter_ns()
        mvec, _ = omni_stem.encode_batch(
            [path], scope_id=row["scope_id"], principal_id=args.principal_id,
            generation=args.generation, authority_epoch=args.authority_epoch, intent=media_intent)
        media_ms = (time.perf_counter_ns() - start) / 1e6
        # Detect common stale-file races. This is not a filesystem-level
        # immutable CAS proof; host artifact ownership remains external.
        safe_media(args.media_root, row)
        observations.append({
            "case_id": row["case_id"], "scope_id": row["scope_id"],
            "split": row["split"], "modality": row["modality"],
            "text_vector": tvec[0], "media_vector": mvec[0],
            "media_sha256": media_digest,
            "text_wall_ms": text_ms, "media_wall_ms": media_ms,
            "rss_bytes": process.memory_info().rss,
        })
    results = paired_ranking(observations, direction=args.direction)
    by_modality = {}
    for modality in EXTENSIONS:
        vals = [row for row in results if row["modality"] == modality]
        if vals:
            by_modality[modality] = {
                "cases": len(vals),
                "recall_at_1": sum(row["recall_at_1"] for row in vals) / len(vals),
                "mean_paired_cosine": sum(row["paired_cosine"] for row in vals) / len(vals),
            }
    write_json(args.output, {
        "schema": "hepta.jina-v5-omni-paired-shadow.v1",
        "status": "research_backend_unqualified",
        "production_promotion_permitted": False,
        "independent_ndu_signature_verified": False,
        "text_model": args.text_model, "text_revision": args.text_revision,
        "omni_model": args.omni_model, "omni_revision": args.omni_revision,
        "text_feature_manifest_digest": text_stem.manifest_digest,
        "omni_feature_manifest_digest": omni_stem.manifest_digest,
        "text_snapshot_census_sha256": text_stem.snapshot_attestation["manifest_sha256"],
        "omni_snapshot_census_sha256": omni_stem.snapshot_attestation["manifest_sha256"],
        "both_snapshots_attested_twice": (
            text_stem.snapshot_attestation["attested_twice_around_model_load"] and
            omni_stem.snapshot_attestation["attested_twice_around_model_load"]
        ),
        "snapshot_attestation_ms": {
            "text": text_stem.snapshot_attestation_ms,
            "omni": omni_stem.snapshot_attestation_ms,
        },
        "model_code_and_adapter_bytes_hashed": True,
        "modality_loading": args.modality, "task_adapter": "retrieval",
        "retrieval_direction": args.direction,
        "text_embedding_intent": text_intent, "media_embedding_intent": media_intent,
        "embedding_dimensions": args.dimension,
        "data": audit, "results": results, "by_modality": by_modality,
        "environment": research_environment(),
        "observed_total_physical_ram_bytes": psutil.virtual_memory().total,
        "model_load_ms": {"text": text_stem.load_ms, "omni": omni_stem.load_ms},
        "limitations": [
            "Only independently provided media/text pairs, not relation reasoning",
            "Not a verified Hepta production worker or signed NDU benefit",
            "No claim of complete Text/Omni numeric equality from ranking",
        ],
    })


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--text-model", required=True)
    p.add_argument("--text-revision", required=True)
    p.add_argument("--text-store-root", type=Path, required=True)
    p.add_argument("--text-snapshot", type=Path, required=True)
    p.add_argument("--text-snapshot-digest", required=True,
                   help="separately approved text file-census digest")
    p.add_argument("--omni-model", required=True)
    p.add_argument("--omni-revision", required=True)
    p.add_argument("--omni-store-root", type=Path, required=True)
    p.add_argument("--omni-snapshot", type=Path, required=True)
    p.add_argument("--omni-snapshot-digest", required=True,
                   help="separately approved Omni file-census digest")
    p.add_argument("--dataset", required=True)
    p.add_argument("--media-root", required=True)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--principal-id", required=True)
    p.add_argument("--dimension", type=int, default=256)
    p.add_argument("--max-tokens", type=int, default=512)
    p.add_argument("--modality", choices=("vision", "audio", "omni"), default="omni")
    p.add_argument("--direction", choices=("media-to-text", "text-to-media"),
                   default="media-to-text")
    p.add_argument("--device", default="cpu")
    p.add_argument("--generation", type=int, default=1)
    p.add_argument("--authority-epoch", type=int, default=1)
    p.add_argument("--allow-pinned-remote-code", action="store_true")
    p.add_argument("--allow-model-download", action="store_true")
    run(p.parse_args())


if __name__ == "__main__":
    main()
