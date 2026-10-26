"""Physical video input with an explicit clock and lossless byte roundtrip.

The source is constructed digit motion, not natural video. Only the decoded
frames enter the model; labels, target tensors and filenames do not.
"""

import hashlib
import json
from pathlib import Path
import resource
import subprocess
import time

import numpy as np
import torch


def _run(arguments, data=None):
    result = subprocess.run(arguments, input=data, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=30, check=False)
    if result.returncode:
        raise RuntimeError(f"Input codec failed ({result.returncode}): {result.stderr[:2048]!r}")
    return result.stdout


def video_roundtrip(frames, directory, ffmpeg="/usr/bin/ffmpeg", ffprobe="/usr/bin/ffprobe"):
    """Write one real MP4, independently decode it, and check every PTS."""
    if (frames.shape != (1, 20, 1, 28, 28) or not torch.isfinite(frames).all()
            or frames.min() < 0 or frames.max() > 1):
        raise ValueError("Expected twenty bounded source frames")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    path = directory / "input.mp4"
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    child_cpu = children.ru_utime + children.ru_stime
    gray = (frames[0, :, 0].detach().cpu().numpy() * 255).round().astype(np.uint8)
    raw = np.repeat(gray[:, :, :, None], 3, -1).tobytes()
    _run([str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
          "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "28x28", "-r", "5",
          "-i", "pipe:0", "-an", "-c:v", "libx264rgb", "-crf", "0",
          "-preset", "ultrafast", "-threads", "1", "-map_metadata", "-1", str(path)], raw)
    probe = json.loads(_run([str(ffprobe), "-v", "error", "-select_streams", "v:0",
                            "-show_streams", "-show_frames", "-of", "json", str(path)]))
    stream = probe["streams"]
    pts = [float(frame["best_effort_timestamp_time"]) for frame in probe["frames"]]
    if (len(stream) != 1 or stream[0]["codec_name"] != "h264"
            or (stream[0]["width"], stream[0]["height"]) != (28, 28)
            or len(pts) != 20 or any(abs(p - i / 5) > 1e-8 for i, p in enumerate(pts))
            or abs(float(stream[0]["duration"]) - 4) > 1e-8):
        raise ValueError("Actual input presentation clock differs from the fixed four-second contract")
    decoded = _run([str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin",
                    "-threads", "1", "-i", str(path), "-map", "0:v:0", "-f", "rawvideo",
                    "-pix_fmt", "rgb24", "-threads", "1", "pipe:1"])
    if decoded != raw:
        raise ValueError("Actual video decoder changed the quantized source pixels")
    actual = np.frombuffer(decoded, np.uint8).reshape(20, 28, 28, 3)[..., 0].copy()
    tensor = torch.from_numpy(actual).float().div(255).reshape(1, 20, 1, 28, 28)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = {"schema": "hepta.advance.actual-input-video.v1", "path": str(path.resolve()),
               "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size,
               "decoded_rgb_sha256": hashlib.sha256(decoded).hexdigest(),
               "clock": {"frame_pts_seconds": pts, "fps": 5, "duration_seconds": 4},
               "lossless_roundtrip": True, "target_supplied_to_decoder": False,
               "source_scope": "constructed motion of actual source digit pixels",
               "codec_wall_ns": time.perf_counter_ns() - started,
               "parent_cpu_ns": time.process_time_ns() - cpu,
               "child_cpu_seconds": children.ru_utime + children.ru_stime - child_cpu}
    (directory / "INPUT_CODEC.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    return tensor, receipt
