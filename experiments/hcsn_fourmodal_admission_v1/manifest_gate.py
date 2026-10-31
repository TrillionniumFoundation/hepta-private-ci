"""Strict *research* preflight for four-source HCSN multimodal experiments.

Checks bytes, per-modality decoding, event/entity/time pairing and split leakage.
This does NOT authenticate human annotations, train encoders, prove temporal
semantics, or qualify a foundation model for production use.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any

MODALITIES = ("text", "image", "audio", "video")
SPLITS = ("train", "val", "test")
SCHEMA = "hcsn-fourmodal-source-v1"
_MAX_TEXT_BYTES = 16 * 1024 * 1024
_MAX_SKEW_MS = 1000
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")


class AdmissionError(ValueError):
    """A required scientific source-integrity gate failed."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


def _deny(code: str, detail: str) -> None:
    raise AdmissionError(code, detail)


def _dict_exact(value: Any, keys: set[str], context: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        _deny("SCHEMA", f"{context}: expected keys {sorted(keys)}")
    return value


def _id(value: Any, context: str) -> str:
    if type(value) is not str or not value.strip() or len(value) > 256:
        _deny("SCHEMA", f"{context}: nonempty <=256-character string required")
    return value


def _sha(value: Any, context: str) -> str:
    if type(value) is not str or not _DIGEST_RE.fullmatch(value):
        _deny("SCHEMA", f"{context}: lowercase SHA256 required")
    return value


def _int(value: Any, context: str) -> int:
    if type(value) is not int or value < 0:
        _deny("SCHEMA", f"{context}: nonnegative integer required")
    return value


def _read_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            _deny("SCHEMA", f"duplicate JSON object key {key!r}")
        obj[key] = value
    return obj


def load_manifest(path: Path) -> dict[str, Any]:
    """Reject duplicate keys and non-standard NaN/Infinity JSON constants."""
    try:
        with Path(path).open("r", encoding="utf-8") as stream:
            return json.load(
                stream,
                object_pairs_hook=_read_object_pairs,
                parse_constant=lambda value: _deny("SCHEMA", f"non-JSON numeric {value}"),
            )
    except AdmissionError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _deny("SCHEMA", f"cannot read valid UTF-8 JSON: {exc}")


def _regular_asset(root: Path, relative: Any) -> Path:
    if type(relative) is not str or not relative or "\\" in relative or relative.startswith("/"):
        _deny("PATH", "asset path must be a POSIX-relative string")
    if any(part in ("", ".", "..") for part in relative.split("/")):
        _deny("PATH", f"noncanonical or traversing asset path: {relative!r}")
    candidate = root / relative
    node = root
    for part in relative.split("/"):
        node = node / part
        if node.is_symlink():
            _deny("PATH", f"symlink assets are forbidden: {relative!r}")
    try:
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            _deny("PATH", f"asset outside root or not a regular file: {relative!r}")
    except (OSError, RuntimeError) as exc:
        _deny("PATH", f"missing or inaccessible asset {relative!r}: {exc}")
    return resolved


def _digest_file(path: Path) -> tuple[str, int]:
    try:
        old = path.stat()
        if old.st_size <= 0:
            _deny("MEDIA", f"zero-byte asset {path}")
        h = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(chunk)
        new = path.stat()
        if (old.st_size, old.st_mtime_ns, old.st_ino) != (new.st_size, new.st_mtime_ns, new.st_ino):
            _deny("PATH", f"asset changed while being checked: {path}")
        return h.hexdigest(), new.st_size
    except AdmissionError:
        raise
    except OSError as exc:
        _deny("PATH", f"cannot hash asset {path}: {exc}")


def _decode_text(path: Path, size: int) -> None:
    if size > _MAX_TEXT_BYTES:
        _deny("MEDIA", "text asset exceeds declared 16 MiB preflight cap")
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        _deny("MEDIA", f"invalid UTF-8 text: {exc}")
    if not content.strip() or "\x00" in content:
        _deny("MEDIA", "text is blank or contains NUL bytes")


def _decode_image(path: Path) -> None:
    try:
        from PIL import Image, UnidentifiedImageError  # type: ignore[import-not-found]
    except ImportError:
        _deny("DEPENDENCY", "Pillow required to verify image decode")
    try:
        with Image.open(path) as im:
            if im.format not in ("PNG", "JPEG", "WEBP"):
                _deny("MEDIA", "image is not a declared PNG/JPEG/WebP asset")
            if im.width < 1 or im.height < 1 or im.width * im.height > 256_000_000:
                _deny("MEDIA", "image dimensions outside safe preflight domain")
            im.verify()
        with Image.open(path) as im:
            im.load()  # verify only checks the container; also decode image pixels
    except AdmissionError:
        raise
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        _deny("MEDIA", f"image failed full image decode: {exc}")


def _decode_audio(path: Path) -> None:
    try:
        with wave.open(str(path), "rb") as wav:
            frame_count = wav.getnframes()
            if not (frame_count > 0 and wav.getframerate() > 0 and wav.getnchannels() > 0):
                _deny("MEDIA", "WAV has no valid PCM frames")
            expected = frame_count * wav.getnchannels() * wav.getsampwidth()
            actual = 0
            while True:
                chunk = wav.readframes(65536)
                if not chunk:
                    break
                actual += len(chunk)
            if actual != expected:
                _deny("MEDIA", f"truncated WAV frames: expected {expected}, got {actual}")
    except AdmissionError:
        raise
    except (OSError, EOFError, wave.Error) as exc:
        _deny("MEDIA", f"audio must be completely readable PCM WAV: {exc}")


def _run_probe(args: list[str], label: str) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        _deny("MEDIA", f"{label}: decoder unavailable or timed out: {exc}")
    if result.returncode != 0:
        _deny("MEDIA", f"{label}: decoder returned {result.returncode}: {result.stderr[:300]}")
    return result


def _decode_video(path: Path) -> None:
    probe = shutil.which("ffprobe")
    decoder = shutil.which("ffmpeg")
    if not probe or not decoder:
        _deny("DEPENDENCY", "ffprobe and ffmpeg required for video admission")
    result = _run_probe(
        [probe, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=codec_type,width,height,nb_frames", "-of", "json", str(path)],
        "video stream probe",
    )
    try:
        streams = json.loads(result.stdout)["streams"]
        valid = len(streams) == 1 and streams[0]["codec_type"] == "video" and (
            type(streams[0]["width"]) is int and streams[0]["width"] > 0 and
            type(streams[0]["height"]) is int and streams[0]["height"] > 0
        )
    except (KeyError, ValueError, TypeError, IndexError):
        valid = False
    if not valid:
        _deny("MEDIA", "video has no valid decodable video stream metadata")
    # A successful first frame is not evidence that the remaining video is
    # decodable. Decode the full selected video stream with -xerror, and
    # check framecrc records against the container-declared frame count when
    # present. N/A/missing nb_frames cannot certify a complete length; this
    # remains a source-integrity preflight, not a temporal-grounding oracle.
    raw_count = streams[0].get("nb_frames")
    expected = None
    if raw_count not in (None, "N/A"):
        if (type(raw_count) is not str or not raw_count.isdecimal()
                or len(raw_count) > 7 or not 1 <= int(raw_count) <= 500_000):
            _deny("MEDIA", "invalid declared video frame count")
        expected = int(raw_count)
    decoded = _run_probe([decoder, "-nostdin", "-v", "error", "-xerror", "-i", str(path),
                          "-map", "0:v:0", "-f", "framecrc", "-"],
                         "full-stream video decode")
    frames = 0
    for row in decoded.stdout.splitlines():
        if not row.strip() or row.startswith("#"):
            continue
        fields = [part.strip() for part in row.split(",")]
        # FFmpeg framecrc: stream_index, dts, pts, duration, bytes, crc.
        if (len(fields) != 6 or fields[0] != "0"
                or not all(re.fullmatch(r"-?\d+", value) for value in fields[1:4])
                or not fields[4].isdecimal() or int(fields[4]) <= 0
                or not re.fullmatch(r"0x[0-9a-fA-F]{8}", fields[5])):
            _deny("MEDIA", "invalid full-video framecrc record")
        frames += 1
        if frames > 500_000:
            _deny("MEDIA", "full-video decode exceeds preflight frame ceiling")
    if frames == 0:
        _deny("MEDIA", "video stream produced no decoded frames")
    if expected is not None and frames != expected:
        _deny("MEDIA", f"decoded {frames} frames, declared {expected} frames")


def validate_manifest(manifest: dict[str, Any], asset_root: Path) -> dict[str, Any]:
    """Fail closed on all declared checks; return descriptive *preflight* receipt."""
    try:
        root = Path(asset_root).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        _deny("PATH", f"asset root missing or inaccessible: {exc}")
    if not root.is_dir():
        _deny("PATH", "asset root must be a directory")
    _dict_exact(manifest, {"schema_version", "max_skew_ms", "encoders", "samples"}, "manifest")
    if manifest["schema_version"] != SCHEMA:
        _deny("SCHEMA", "unknown manifest schema")
    max_skew_ms = _int(manifest["max_skew_ms"], "max_skew_ms")
    if max_skew_ms > _MAX_SKEW_MS:
        _deny("TIME", "max_skew_ms may not exceed 1000")
    encoders = _dict_exact(manifest["encoders"], set(MODALITIES), "encoders")
    encoder_ids: set[str] = set()
    encoder_revisions: set[str] = set()
    for name in MODALITIES:
        enc = _dict_exact(encoders[name], {"encoder_id", "revision_sha256"}, f"encoder.{name}")
        encoder_id = _id(enc["encoder_id"], f"encoder.{name}.id")
        revision = _sha(enc["revision_sha256"], f"encoder.{name}.revision")
        if encoder_id in encoder_ids or revision in encoder_revisions:
            _deny("ENCODER", "four distinct versioned modality encoders required")
        encoder_ids.add(encoder_id)
        encoder_revisions.add(revision)
    samples = manifest["samples"]
    if type(samples) is not list or not samples:
        _deny("SCHEMA", "nonempty sample list required")

    seen_sample_ids: set[str] = set()
    split_by_actor: dict[str, str] = {}
    split_by_session: dict[str, str] = {}
    split_by_event: dict[str, str] = {}
    split_by_source: dict[str, str] = {}
    split_by_content: dict[tuple[str, str], str] = {}
    split_by_path: dict[str, str] = {}
    counts = {split: 0 for split in SPLITS}
    total_bytes = 0
    for i, obj in enumerate(samples):
        sample = _dict_exact(obj, {
            "sample_id", "split", "actor_id", "session_id", "event_id",
            "entity_id", "label", "modalities",
        }, f"sample[{i}]")
        sample_id = _id(sample["sample_id"], f"sample[{i}].id")
        if sample_id in seen_sample_ids:
            _deny("LEAKAGE", f"duplicate sample ID {sample_id!r}")
        seen_sample_ids.add(sample_id)
        split = sample["split"]
        if type(split) is not str or split not in SPLITS:
            _deny("SCHEMA", f"sample[{i}]: invalid split")
        counts[split] += 1
        actor = _id(sample["actor_id"], f"sample[{i}].actor")
        session = _id(sample["session_id"], f"sample[{i}].session")
        event = _id(sample["event_id"], f"sample[{i}].event")
        entity = _id(sample["entity_id"], f"sample[{i}].entity")
        _id(sample["label"], f"sample[{i}].label")
        for name, key, seen in (
            ("actor", actor, split_by_actor), ("session", session, split_by_session),
            ("event", event, split_by_event),
        ):
            old_split = seen.setdefault(key, split)
            if old_split != split:
                _deny("LEAKAGE", f"{name} {key!r} appears in {old_split} and {split}")
        items = _dict_exact(sample["modalities"], set(MODALITIES), f"sample[{i}].modalities")
        start_times: list[int] = []
        end_times: list[int] = []
        paths_here: set[str] = set()
        for modality in MODALITIES:
            src = _dict_exact(items[modality], {
                "path", "sha256", "source_id", "event_id", "entity_id", "start_ms", "end_ms",
            }, f"sample[{i}].{modality}")
            src_event = _id(src["event_id"], "source event")
            src_entity = _id(src["entity_id"], "source entity")
            if src_event != event or src_entity != entity:
                _deny("PAIRING", f"{sample_id}/{modality} event/entity disagrees with parent")
            start = _int(src["start_ms"], "source.start_ms")
            end = _int(src["end_ms"], "source.end_ms")
            if end < start:
                _deny("TIME", f"{sample_id}/{modality} has reversed timestamp interval")
            start_times.append(start)
            end_times.append(end)
            source_id = _id(src["source_id"], "source.id")
            old_split = split_by_source.setdefault(source_id, split)
            if old_split != split:
                _deny("LEAKAGE", f"source {source_id!r} shared across {old_split}/{split}")
            raw_path = src["path"]
            path = _regular_asset(root, raw_path)
            if raw_path in paths_here:
                _deny("PAIRING", f"{sample_id} uses one asset for multiple modalities")
            paths_here.add(raw_path)
            old_split = split_by_path.setdefault(raw_path, split)
            if old_split != split:
                _deny("LEAKAGE", f"file path {raw_path!r} shared across splits")
            digest_expected = _sha(src["sha256"], f"{sample_id}.{modality}.sha256")
            digest_actual, size = _digest_file(path)
            if digest_expected != digest_actual:
                _deny("HASH", f"{sample_id}/{modality}: asset SHA256 mismatch")
            old_split = split_by_content.setdefault((modality, digest_actual), split)
            if old_split != split:
                _deny("LEAKAGE", f"identical {modality} asset reused across {old_split}/{split}")
            if modality == "text":
                _decode_text(path, size)
            elif modality == "image":
                _decode_image(path)
            elif modality == "audio":
                _decode_audio(path)
            else:
                _decode_video(path)
            total_bytes += size
        if max(start_times) > min(end_times) + max_skew_ms:
            _deny("TIME", f"{sample_id} has non-overlapping temporal evidence")
    if any(value == 0 for value in counts.values()):
        _deny("SPLIT", "train, val and test must each contain real source samples")
    digest = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, ensure_ascii=False,
                   allow_nan=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "status": "STRUCTURAL_SOURCE_PREFLIGHT_ONLY",
        "schema_version": SCHEMA,
        "manifest_sha256": digest,
        "sample_counts": counts,
        "samples": len(samples),
        "modality_assets_verified": len(samples) * len(MODALITIES),
        "sum_verified_asset_bytes_with_reuse": total_bytes,
        "encoder_count": len(encoder_ids),
        "all_scientific_and_production_gates_closed": False,
        "real_four_modal_quality_established": False,
        "production_activation_allowed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("asset_root", type=Path)
    args = parser.parse_args(argv)
    try:
        receipt = validate_manifest(load_manifest(args.manifest), args.asset_root)
    except AdmissionError as exc:
        print(json.dumps({"status": "DENY", "code": exc.code, "reason": str(exc),
                          "production_activation_allowed": False}, sort_keys=True))
        return 2
    print(json.dumps(receipt, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
