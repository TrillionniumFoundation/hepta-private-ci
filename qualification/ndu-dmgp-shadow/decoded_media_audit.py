"""Independent, bounded original-byte/media-decode gate (SHADOW_ONLY).

Checks that declared output assets exist, match hashes, physically decode, and
have coherent typed streams/timeline envelopes. Does NOT recognize semantic
entities, validate perceptual truth, meter power, qualify a neural decoder,
verify signed observers, or grant a capability. External semantic claims must
still be authenticated/validated by an independent owner.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from time import perf_counter_ns

MODALITIES = frozenset({"text", "image", "audio", "video"})
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
MAX_ASSET_BYTES = 64 * 1024 * 1024
MAX_CLIP_SECONDS = 30.0
MAX_PIXEL_COUNT = 1920 * 1080
MAX_EVENTS = 64
MAX_SKEW_MS = 120


class DecodedMediaRejected(ValueError):
    """Untrusted/unsupported media or incoherent temporal envelope."""


def _require(valid, reason):
    if not valid:
        raise DecodedMediaRejected(reason)


def _sha(value):
    return type(value) is str and SHA_RE.fullmatch(value) is not None


def _int(value, lo=0, hi=1_000_000):
    return type(value) is int and lo <= value <= hi


def _events(records, *, tolerance_ms, canonical=None):
    _require(type(records) is list and 0 < len(records) <= MAX_EVENTS,
             "missing/unbounded timeline events")
    out = {}
    for row in records:
        _require(type(row) is dict and set(row) == {"id", "entity", "start_ms", "end_ms"},
                 "invalid timeline record")
        eid, ent = row["id"], row["entity"]
        start, end = row["start_ms"], row["end_ms"]
        _require(type(eid) is str and NAME_RE.fullmatch(eid) is not None and
                 type(ent) is str and 0 < len(ent) <= 128 and
                 all(ord(c) >= 32 for c in ent) and
                 _int(start, 0, 30000) and _int(end, 1, 30000) and
                 start < end and eid not in out,
                 "invalid/duplicate entity or event bounds")
        if canonical is not None:
            expected = canonical.get(eid)
            _require(expected is not None and expected[0] == ent and
                     abs(start - expected[1]) <= tolerance_ms and
                     abs(end - expected[2]) <= tolerance_ms,
                     "unmatched timeline/entity claim")
        out[eid] = (ent, start, end)
    if canonical is not None:
        _require(set(out) == set(canonical), "missing/extra cross-modal event")
    return out


def _run(command, timeout=20):
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=False,
                                timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DecodedMediaRejected("bounded external media decoder unavailable") from exc
    _require(result.returncode == 0, "media probe/decode failure")
    return result.stdout


def _stream_probe(filename, modality):
    # Input is a PRIVATE, byte-snapshotted regular file. Explicitly disallow
    # nested HTTP/concat/network protocols inside complex media containers.
    raw = _run(["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
                "-show_entries",
                "stream=index,codec_type,codec_name,width,height,duration:format=duration",
                "-of", "json", str(filename)])
    try:
        info = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise DecodedMediaRejected("invalid decoder stream information") from exc
    streams = info.get("streams", [])
    _require(type(streams) is list and 0 < len(streams) <= 16,
             "missing/unbounded decoded streams")
    required_kind = "audio" if modality == "audio" else "video"
    _require(all(type(s) is dict for s in streams),
             "malformed decoder stream information")
    matching = [s for s in streams if s.get("codec_type") == required_kind]
    # V1 is deliberately one physical stream per declared asset; reject
    # unmeasured extra audio/video/subtitle/data tracks instead of hiding them.
    _require(len(matching) == 1 and len(streams) == 1,
             "wrong/missing/extra actual media streams")
    chosen = matching[0]
    index = chosen.get("index")
    _require(_int(index, 0, 15) and type(chosen.get("codec_name")) is str,
             "invalid decoder stream index/codec")
    if required_kind == "video":
        width, height = chosen.get("width"), chosen.get("height")
        _require(_int(width, 1, 1920) and _int(height, 1, 1080) and
                 width * height <= MAX_PIXEL_COUNT,
                 "oversize/missing decoded video dimensions")
    if modality == "image":
        _run(["ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist",
              "file,pipe", "-i", str(filename), "-map", f"0:{index}",
              "-frames:v", "1", "-f", "null", "-"], timeout=15)
        return {"stream": required_kind, "stream_index": index,
                "duration_ms": None}
    raw_duration = chosen.get("duration") or info.get("format", {}).get("duration")
    try:
        duration = float(raw_duration)
    except (TypeError, ValueError, OverflowError) as exc:
        raise DecodedMediaRejected("unknown measured media duration") from exc
    _require(math.isfinite(duration) and 0 < duration <= MAX_CLIP_SECONDS,
             "unsupported media duration")
    _run(["ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist",
          "file,pipe", "-i", str(filename), "-map", f"0:{index}",
          "-f", "null", "-"], timeout=20)
    return {"stream": required_kind, "stream_index": index,
            "duration_ms": round(duration * 1000)}


def _snapshot_regular(root, name, declared_digest):
    _require(type(name) is str and NAME_RE.fullmatch(name) is not None and
             name not in {".", ".."} and _sha(declared_digest),
             "unsafe asset name/digest")
    # No-follow prevents symlink substitution; bytes are re-bound into an
    # isolated snapshot before being passed to an external decoder.
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(root / name, flags)
        with os.fdopen(fd, "rb") as file:
            meta = os.fstat(file.fileno())
            _require(stat.S_ISREG(meta.st_mode) and
                     0 < meta.st_size <= MAX_ASSET_BYTES and
                     meta.st_nlink == 1,
                     "nonregular, oversized or linked asset")
            raw = file.read(MAX_ASSET_BYTES + 1)
    except OSError as exc:
        raise DecodedMediaRejected("missing/unsafe original asset") from exc
    _require(len(raw) <= MAX_ASSET_BYTES and
             hashlib.sha256(raw).hexdigest() == declared_digest,
             "raw media hash mismatch")
    return raw


def audit_decoded_media(plan: dict, manifest: dict, *, asset_root: Path) -> dict:
    """Validate one bounded run without granting truth or execution authority."""
    _require(type(plan) is dict and set(plan) == {
                 "schema", "objective_digest", "input_digest", "generation",
                 "required_modalities", "max_skew_ms", "timeline"},
             "invalid independently frozen plan schema")
    _require(plan["schema"] == "hepta.ndu-dmgp.media-plan.v1" and
             _sha(plan["objective_digest"]) and _sha(plan["input_digest"]) and
             _int(plan["generation"], 1, 2**63 - 1) and
             _int(plan["max_skew_ms"], 0, MAX_SKEW_MS),
             "invalid objective/source/generation/tolerance")
    required = plan["required_modalities"]
    _require(type(required) is list and len(required) == len(MODALITIES) and
             all(type(x) is str for x in required) and
             set(required) == MODALITIES,
             "complete four-modal output required")
    canonical = _events(plan["timeline"], tolerance_ms=0)
    _require(type(manifest) is dict and set(manifest) == {
                 "schema", "objective_digest", "input_digest", "generation", "outputs"}
             and manifest["schema"] == "hepta.ndu-dmgp.media-output.v1"
             and all(manifest.get(x) == plan[x] for x in (
                 "objective_digest", "input_digest", "generation")),
             "unbound output manifest")
    assets = manifest["outputs"]
    _require(type(assets) is list and len(assets) == 4,
             "missing/extra four-modal outputs")
    _require(isinstance(asset_root, Path) and asset_root.is_dir(),
             "missing local asset directory")
    start_time = perf_counter_ns()
    observed = {}
    claims = {}
    used_files = set()
    with tempfile.TemporaryDirectory(prefix="hepta-media-audit-") as workdir:
        for row in assets:
            _require(type(row) is dict and set(row) == {
                         "modality", "filename", "sha256", "events"},
                     "unsupported media output record")
            m, filename = row["modality"], row["filename"]
            _require(type(m) is str and m in MODALITIES and m not in observed
                     and type(filename) is str and filename not in used_files,
                     "duplicate/illegal output or reused asset filename")
            events = _events(row["events"], tolerance_ms=plan["max_skew_ms"],
                             canonical=canonical)
            raw = _snapshot_regular(asset_root, filename, row["sha256"])
            used_files.add(filename)
            if m == "text":
                try:
                    text = raw.decode("utf-8", "strict")
                except UnicodeError as exc:
                    raise DecodedMediaRejected("non-UTF8 text output") from exc
                _require(bool(text.strip()) and len(raw) <= 1024 * 1024,
                         "empty/unbounded text output")
                stream = {"stream": "utf8", "stream_index": None,
                          "duration_ms": None}
            else:
                suffix = {"image": ".png", "audio": ".wav", "video": ".mp4"}[m]
                _require(Path(filename).suffix == suffix, "invalid media type/extension")
                copied = Path(workdir) / f"{m}{suffix}"
                copied.write_bytes(raw)
                stream = _stream_probe(copied, m)
                if m in {"audio", "video"}:
                    _require(all(end <= stream["duration_ms"] + 5
                                 for _, _, end in events.values()),
                             "event exceeds physically decoded duration")
            claims[m] = events
            observed[m] = {"sha256": row["sha256"], "bytes": len(raw),
                           **stream}
    _require(set(observed) == MODALITIES, "incomplete physical modal outputs")
    # Bound paired modality clocks; timeline claims are still declarative.
    for eid in canonical:
        begin = [claims[m][eid][1] for m in MODALITIES]
        end = [claims[m][eid][2] for m in MODALITIES]
        _require(max(begin) - min(begin) <= plan["max_skew_ms"] and
                 max(end) - min(end) <= plan["max_skew_ms"],
                 "cross-modal event clock divergence")
    elapsed = (perf_counter_ns() - start_time) / 1_000_000
    return {
        "schema": "hepta.ndu-dmgp.decoded-media-audit.v1",
        "objective_digest": plan["objective_digest"],
        "input_digest": plan["input_digest"],
        "generation": plan["generation"],
        "content_digest": hashlib.sha256(json.dumps(
            {"plan": plan, "manifest": manifest}, sort_keys=True,
            separators=(",", ":"), ensure_ascii=False,
            allow_nan=False).encode("utf-8")).hexdigest(),
        "verified_original_bytes_and_real_media_decode": True,
        "observed": observed,
        "local_decoder_audit_wall_ms": round(elapsed, 3),
        "semantic_entities_independently_recognized": False,
        "bidirectional_perceptual_model_verified": False,
        "audio_video_lip_sync_verified": False,
        "model_generated_output_verified": False,
        "host_energy_calibrated": False,
        "signed_observer_verified": False,
        "production_blockers_closed": False,
        "no_promotion_authority": True,
    }