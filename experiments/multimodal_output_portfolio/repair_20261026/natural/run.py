"""Freeze sources and execute one small natural perception/control evaluation."""
import argparse
import hashlib
import json
from pathlib import Path
import time

from .speech import run_speech
from .video import run_video


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(assets, output):
    source = Path(__file__).parent
    spec = json.loads((source / "PROTOCOL.json").read_text())
    manifest = json.loads((assets / "MANIFEST.json").read_text())
    output.mkdir(parents=True, exist_ok=False)
    pins = {p.name: sha(p) for p in source.glob("*.py")}
    pins["PROTOCOL.json"] = sha(source / "PROTOCOL.json")
    for row in manifest["files"]:
        if sha(row["path"]) != row["sha256"]:
            raise ValueError("Pinned public source changed")
    (output / "FROZEN_REGISTRATION.json").write_text(json.dumps({"registered_ns": time.time_ns(),
        "protocol": spec, "source_pins": pins, "asset_manifest_sha256": sha(assets / "MANIFEST.json"),
        "all_input_bytes_verified": True, "test_execution_has_not_started": True}, sort_keys=True, indent=2) + "\n")
    started = time.perf_counter_ns()
    video = run_video(manifest, spec["video"], output / "video")
    print(json.dumps({"natural_video_finished": True, "selected_threshold": video["gate"]["selected_threshold"]}), flush=True)
    speech = run_speech(manifest, spec["speech"], output / "speech")
    unchanged = all(sha(source / name) == digest for name, digest in pins.items())
    unchanged = unchanged and all(sha(row["path"]) == row["sha256"] for row in manifest["files"])
    result = {"schema": "hepta.repair.natural.result.v1", "status": "completed", "source_and_model_unchanged": unchanged,
        "wall_seconds": (time.perf_counter_ns() - started) / 1e9, "speech": speech, "video": video,
        "all_blockers_closed": False, "native_owner_integrated": False, "any_to_any_neural_generation_proven": False,
        "complex_image_text_reasoning_proven": False}
    (output / "RESULT.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    if not unchanged:
        raise ValueError("Source or frozen model changed during the experiment")
    print(json.dumps({"status": "completed", "wall_seconds": result["wall_seconds"], "source_unchanged": unchanged}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.assets, args.output)
    except Exception as error:
        if args.output.exists():
            (args.output / "FAILED.json").write_text(json.dumps({"error": f"{type(error).__name__}: {error}",
                "retain_all_partial_outputs": True}, indent=2) + "\n")
        raise
