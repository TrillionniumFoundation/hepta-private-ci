"""Resume untouched speech after a decoder dependency failure; preserve video."""
import argparse
import importlib.metadata
import json
from pathlib import Path
import time

from .run import sha
from .speech import run_speech


def recover(assets, previous, output):
    failed = json.loads((previous / "FAILED.json").read_text())
    if "metadata_errors" not in failed["error"] or any((previous / "speech").rglob("*.txt")):
        raise ValueError("Recovery is restricted to the observed pre-output decoder compatibility failure")
    source = Path(__file__).parent
    frozen = json.loads((previous / "FROZEN_REGISTRATION.json").read_text())
    if any(sha(source / name) != digest for name, digest in frozen["source_pins"].items()):
        raise ValueError("Original scientific sources or protocol changed")
    if sha(assets / "MANIFEST.json") != frozen["asset_manifest_sha256"]:
        raise ValueError("Source allocation changed")
    manifest = json.loads((assets / "MANIFEST.json").read_text())
    if any(sha(r["path"]) != r["sha256"] for r in manifest["files"]):
        raise ValueError("Natural input or model bytes changed")
    output.mkdir(parents=True, exist_ok=False)
    registration = {"schema": "hepta.repair.natural.speech-recovery.v1", "registered_ns": time.time_ns(),
        "previous_failure": failed, "previous_failure_sha256": sha(previous / "FAILED.json"),
        "original_registration_sha256": sha(previous / "FROZEN_REGISTRATION.json"),
        "video_result_sha256": sha(previous / "video/RESULT.json"), "video_not_rerun": True,
        "original_protocol_and_model_unchanged": True, "recovery_source_sha256": sha(Path(__file__)),
        "packages": {name: importlib.metadata.version(name) for name in ("faster-whisper", "av", "ctranslate2", "numpy")}}
    (output / "RECOVERY_REGISTRATION.json").write_text(json.dumps(registration, sort_keys=True, indent=2) + "\n")
    result = run_speech(manifest, frozen["protocol"]["speech"], output / "speech")
    combined = {"schema": "hepta.repair.natural.result.v1", "status": "completed_after_dependency_repair",
        "recovery": registration, "video": json.loads((previous / "video/RESULT.json").read_text()), "speech": result,
        "original_failure_retained": True, "all_blockers_closed": False, "native_owner_integrated": False,
        "any_to_any_neural_generation_proven": False, "complex_image_text_reasoning_proven": False}
    (output / "RESULT.json").write_text(json.dumps(combined, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"status": combined["status"], "speech_gate": result["gate"]["selected_threshold"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    recover(args.assets, args.previous, args.output)
