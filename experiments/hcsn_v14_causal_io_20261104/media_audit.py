"""One frozen historical TRAIN clip: raw-media diagnostics, never qualification."""

import argparse
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import hashlib, json, math, re
from pathlib import Path
import subprocess, sys, time, traceback
import urllib.error, urllib.request
from .boundary import BoundaryError, FrozenInput
ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "experiments/hcsn_v13_followup_20261102/frontend/reused_train001/inputs/train001"
COHORT_SHA = "9272d2e7939a240557b0bada9f2c0fd161f64521702da63c03ed276bb2dd9e51"
IDENTITY_SHA = "ac52fa2560e36f967d428bc84220148477f0f8e38feca020a14421c73ca1c8f2"
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    out = parser.parse_args().out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    report = {"schema": "hcsn-v14-historical-media-diagnostic.v1", "status": "HOLD",
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "claims": {"new_recording": False, "historical_training_source_reused": True,
            "encoder_quality": "UNMEASURED", "learned_identity_correctness": "UNMEASURED",
            "independentness": "NOT_ESTABLISHED", "quality_qualification": False,
            "snr_db": None, "energy_joules": None, "production_activation": False}}
    def run(name, args, payload=None):
        started = time.monotonic()
        entry = {"name": name, "argv": args, "status": "attempted"}
        report.setdefault("commands", []).append(entry)
        try:
            result = subprocess.run(args, input=payload, capture_output=True, timeout=30)
        except subprocess.TimeoutExpired as error:
            entry.update(status="timed_out", wall_seconds=time.monotonic() - started)
            (out / f"{name}.stdout.bin").write_bytes(error.stdout or b"")
            (out / f"{name}.stderr.bin").write_bytes(error.stderr or b"")
            raise
        (out / f"{name}.stdout.bin").write_bytes(result.stdout)
        (out / f"{name}.stderr.bin").write_bytes(result.stderr)
        entry.update(status="completed", returncode=result.returncode, wall_seconds=time.monotonic() - started)
        if result.returncode:
            raise RuntimeError(f"{name} exited {result.returncode}; raw logs retained")
        return result.stdout, result.stderr
    try:
        documents = []
        for name, expected in (("COHORT.json", COHORT_SHA), ("IDENTITY.json", IDENTITY_SHA)):
            raw = (INPUT / name).read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected:
                raise BoundaryError(f"Frozen {name} bytes changed")
            documents.append(json.loads(raw))
        cohort, identity = documents
        row = min((r for r in cohort["records"] if r["split"] == "train"), key=lambda r: r["clip"])
        prior = next(r for r in identity["details"] if r["clip"] == row["clip"])
        if identity["manifest_sha256"] != COHORT_SHA or prior["raw_sha256"] != row["sha256"]:
            raise BoundaryError("Historical source/identity binding mismatch")
        report.update({"selection": "lexicographically first TRAIN clip", "source": row,
            "cohort_sha256": COHORT_SHA, "identity_sha256": IDENTITY_SHA, "prior_prefix": prior["prefix"]})
        started = time.monotonic()
        with urllib.request.urlopen(row["url"], timeout=30) as response:
            raw = response.read(row["bytes"] + 1)
            report["download"] = {"final_url": response.url, "status": response.status,
                "bytes": len(raw), "wall_seconds": time.monotonic() - started}
        (out / "source.flv").write_bytes(raw)
        if len(raw) != row["bytes"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise BoundaryError("Downloaded media length/hash differs from frozen source")
        source = {"source_id": row["clip"], "family_id": "CREMA-D-historical-training",
            "session_id": row["clip"], "world_id": "exposed-training-world", "clock_id": "container-PTS",
            "sha256": row["sha256"], "origin": "recorded",
            "max_end_ns": int(Decimal(str(prior["prefix"]["accepted_end"])) * 1_000_000_000),
            "sync_uncertainty_ns": 0, "release_offset_ns": 0, "raw_reader_only": True,
            "encoders": {"audio": {"sha256": report["source_sha256"], "width": 1}}}
        frozen = FrozenInput({"schema": "hcsn-v14-frozen-input.v1", "role": "development",
            "arrival_clock_id": "media-diagnostic", "sources": [source]})
        raw = frozen.read_bytes(out, "source.flv", row["clip"], max_bytes=row["bytes"])
        report["byte_boundary"] = {**frozen.claims(), "verified_bytes": len(raw),
            "consumed_via_stdin": True, "encoder_fields_unused": True, "clock_fields_unused": True,
            "encoder_executed": False}
        for tool in ("ffprobe", "ffmpeg"):
            run(tool + "-version", [tool, "-version"])
        probe, _ = run("probe", ["ffprobe", "-v", "error", "-show_format", "-show_streams",
            "-show_frames", "-show_entries", "frame=media_type,best_effort_timestamp_time,nb_samples",
            "-of", "json", "pipe:0"], raw)
        metadata = json.loads(probe)
        audio = next(s for s in metadata["streams"] if s["codec_type"] == "audio")
        video = next(s for s in metadata["streams"] if s["codec_type"] == "video")
        frames = [f for f in metadata["frames"] if f["media_type"] == "video"]
        rate, channels = int(audio["sample_rate"]), int(audio["channels"])
        audio_start = Decimal(audio["start_time"])
        origin = max(audio_start, Decimal(frames[0]["best_effort_timestamp_time"]))
        end = origin + Decimal(1)
        lo = int(((origin - audio_start) * rate).to_integral_value(rounding=ROUND_CEILING))
        hi = int(((end - audio_start) * rate).to_integral_value(rounding=ROUND_FLOOR))
        report["raw_media"] = {"format": metadata["format"], "audio_stream": audio, "video_stream": video}
        report["prefix"] = {"origin_seconds": str(origin), "end_seconds": str(end),
            "native_rate": rate, "channels": channels, "sample_lo": lo, "sample_hi_exclusive": hi,
            "resampling": False, "normalization": False, "full_recording_statistics": False,
            "sample_index_clock_assumption": "continuous decoded audio from stream start; not physical sync proof"}
        pcm, _ = run("native-prefix", ["ffmpeg", "-v", "error", "-threads", "1", "-i", "pipe:0",
            "-map", "0:a:0", "-af", f"atrim=start_sample={lo}:end_sample={hi}",
            "-c:a", "pcm_f32le", "-f", "f32le", "pipe:1"], raw)
        import numpy as np
        samples = np.frombuffer(pcm, dtype="<f4").astype(np.float64)
        if samples.size != (hi - lo) * channels or not np.isfinite(samples).all() or samples.size == 0:
            raise BoundaryError("Missing, nonfinite or incomplete native PCM prefix")
        (out / "prefix.f32le").write_bytes(pcm)
        report["audio"] = {"samples_per_channel": hi - lo, "pcm_sha256": hashlib.sha256(pcm).hexdigest(),
            "rms": float(np.sqrt(np.mean(samples ** 2))), "peak": float(np.max(np.abs(samples))),
            "at_or_over_full_scale_fraction": float(np.mean(np.abs(samples) >= 1)),
            "near_silence_sample_fraction": float(np.mean(np.abs(samples) < 1e-4)), "silence_threshold": 1e-4,
            "interpretation": "fixed full-scale amplitude heuristics; neither speech quality nor original clipping verdict"}
        from scipy.signal import resample_poly
        accepted_sha = None
        if channels == 1:
            divisor = math.gcd(rate, 16000)
            projected = resample_poly(samples, 16000 // divisor, rate // divisor, padtype="constant")
            accepted = np.pad(projected, (0, 16000 - len(projected))).astype(np.float32)
            accepted_sha = hashlib.sha256(accepted.tobytes()).hexdigest()
        expected = prior["prefix"]
        report["historical_alignment"] = {"index_equal": (lo, hi, rate) ==
            (expected["native_lo"], expected["native_hi"], expected["native_sample_rate"]),
            "clock_equal": (origin, end, audio_start) == tuple(Decimal(str(expected[k]))
                for k in ("origin", "accepted_end", "audio_start")), "historical_native_pcm_hash": None,
            "hash_scope": "IDENTITY stores cropped-then-resampled 16k mono float32; native hash unavailable",
            "accepted_sha256": accepted_sha, "expected_accepted_sha256": expected["waveform_sha256"],
            "accepted_hash_equal": accepted_sha == expected["waveform_sha256"] if accepted_sha else None}
        if (not all(report["historical_alignment"][k] for k in ("index_equal", "clock_equal"))
                or Decimal(frames[-1]["best_effort_timestamp_time"]) < end):
            raise BoundaryError("Decoded source window drifted from frozen prefix or video is incomplete")
        eligible = [(i, Decimal(f["best_effort_timestamp_time"])) for i, f in enumerate(frames)
                    if origin <= Decimal(f["best_effort_timestamp_time"]) <= origin + Decimal("0.5")]
        index, pts = eligible[-1]
        png, log = run("frame", ["ffmpeg", "-v", "info", "-copyts", "-threads", "1", "-i", "pipe:0",
            "-map", "0:v:0", "-vf", f"select=eq(n\\,{index}),showinfo", "-vsync", "0", "-frames:v", "1",
            "-threads", "1", "-c:v", "png", "-pix_fmt", "rgb24", "-f", "image2pipe", "pipe:1"], raw)
        observed = re.findall(rb"pts_time:([-+0-9.eE]+)", log)
        if len(observed) != 1 or abs(Decimal(observed[0].decode()) - pts) > Decimal("0.000001") or pts > end:
            raise BoundaryError("Extracted frame timestamp differs from the accepted source frame")
        (out / "frame.png").write_bytes(png)
        report["frame"] = {"source_frame_index": index, "source_pts_seconds": str(pts),
            "png_sha256": hashlib.sha256(png).hexdigest(), "width": video["width"], "height": video["height"]}
        report["status"] = "HISTORICAL_DIAGNOSTIC_COMPLETE"
    except Exception as error:
        if isinstance(error, urllib.error.HTTPError):
            (out / "download-error-body.bin").write_bytes(error.read(16384))
        report["error"] = {"type": type(error).__name__, "message": str(error)}
        (out / "failure.txt").write_text(traceback.format_exc())
    (out / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"status": report["status"], "report": str(out / "report.json")}))
    return 0 if report["status"] == "HISTORICAL_DIAGNOSTIC_COMPLETE" else 1
if __name__ == "__main__":
    sys.exit(main())
