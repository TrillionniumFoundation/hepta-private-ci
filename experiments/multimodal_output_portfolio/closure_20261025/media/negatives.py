"""Physical negative controls starting from a fully successful real bundle."""

from pathlib import Path
import shutil

import numpy as np
import torch

from ...v7_media.audit import observe_four_modal_bundle
from ...v7_media.media import read_media, write_media
from .run import content_checks
from .sources import save_json


def run_negatives(directory, rows, image_observer, speech_observer, minimum_frames, codec=None):
    read = codec.read_media if codec else read_media
    write = codec.write_media if codec else write_media
    observe = codec.observe_four_modal_bundle if codec else observe_four_modal_bundle
    check = codec.content_checks if codec else content_checks
    samples = codec.WORD_SAMPLES if codec else 8000
    directory = Path(directory)
    directory.mkdir(exist_ok=False)
    eligible = [row for row in rows if row["condition"] == "hard" and row["success"]
                and len(set(row["audit"]["expected_labels"])) == 2]
    if not eligible:
        result = {"status": "no_qualifying_positive", "nonvacuous": False, "all_rejected": False}
        save_json(directory / "summary.json", result)
        return result
    baseline = eligible[0]
    labels = baseline["audit"]["expected_labels"]
    paths = {key: value["path"] for key, value in baseline["output"]["files"].items()}
    decoded = read(paths)
    baseline_audit = observe(paths, image_observer, speech_observer, labels)
    baseline_checks = check(decoded, minimum_frames)
    if not (baseline_audit["joint_success"] and baseline_checks["moving_video"]
            and baseline_checks["nonempty_audio"]):
        raise ValueError("Negative-control source is no longer a genuine positive")
    pixels = torch.from_numpy(decoded["image"].copy()).float()[None] / 255
    waveforms = torch.from_numpy(np.frombuffer(decoded["audio_bytes"], dtype="<i2").copy()).float().reshape(2, samples) / 32767
    frames = torch.from_numpy(np.frombuffer(decoded["video_bytes"], dtype=np.uint8).copy().reshape(20, 28, 28, 3)[..., 0]).float()[:, None] / 255
    mutations = {
        "silence": (torch.zeros_like(waveforms), frames),
        "swapped_audio_events": (waveforms.flip(0), frames),
        "swapped_video_events": (waveforms, frames.reshape(2, 10, 1, 28, 28).flip(0).reshape(20, 1, 28, 28)),
        "repeated_video_frames": (waveforms, torch.cat((frames[:1].expand(10, -1, -1, -1), frames[10:11].expand(10, -1, -1, -1)))),
    }
    results = {}
    for name, (sound, video) in mutations.items():
        media = write(directory / name, decoded["caption"], pixels, sound, video,
                            baseline["output"]["bindings"], shutil.which("ffmpeg"), shutil.which("ffprobe"))
        changed = {key: value["path"] for key, value in media["files"].items()}
        audit = observe(changed, image_observer, speech_observer, labels)
        checks = check(read(changed), minimum_frames)
        required_failure = {
            "silence": not checks["nonempty_audio"],
            "swapped_audio_events": not audit["success"]["audio"] and audit["success"]["video"],
            "swapped_video_events": not audit["success"]["video"] and audit["success"]["audio"],
            "repeated_video_frames": not checks["moving_video"] and audit["joint_success"],
        }[name]
        results[name] = {"media": media, "audit": audit, "content_checks": checks,
                         "clock_pass": True, "required_failure_observed": required_failure,
                         "rejected": not (audit["joint_success"] and checks["moving_video"] and checks["nonempty_audio"])}
    missing = directory / "missing_modality"
    missing.mkdir()
    absent_paths = {}
    for name, original in paths.items():
        destination = missing / Path(original).name
        if name != "audio":
            shutil.copyfile(original, destination)
        absent_paths[name] = destination
    try:
        read(absent_paths)
        results["missing_modality"] = {"rejected": False, "required_failure_observed": False}
    except ValueError as error:
        results["missing_modality"] = {"rejected": True, "required_failure_observed": True, "error": str(error)}
    result = {"status": "completed", "nonvacuous": True,
              "baseline": {"index": baseline["index"], "mode": baseline["mode"],
                           "files": baseline["output"]["files"], "audit": baseline_audit},
              "controls": results,
              "all_rejected": all(row["rejected"] and row["required_failure_observed"] for row in results.values()),
              "meaning": "Event swaps keep valid container PTS but must fail content alignment; repeated frames keep semantics but fail motion"}
    save_json(directory / "summary.json", result)
    return result
