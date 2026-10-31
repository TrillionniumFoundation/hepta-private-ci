"""Nonvacuous physical mutations preserve the same presentation clock."""

from pathlib import Path
import shutil

import numpy as np
import torch

from ...closure_20261025.media import carrier_media
from ...closure_20261025.media.sources import save_json
from .runtime import observe_bundle
from .selected_event import score_selected_observation as score_observation


def run_negatives(directory, rows, image_observer, speech_observer):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    candidates = [row for row in rows if row["score"]["joint_success"]
                  and len(set(row["score"]["expected_after_observation"])) == 2]
    if not candidates:
        result = {"nonvacuous": False, "all_rejected": False, "reason": "No successful unequal-digit positive"}
        save_json(directory / "summary.json", result)
        return result
    baseline = candidates[0]
    decoded = carrier_media.read_media({k: v["path"] for k, v in baseline["generation"]["output"]["files"].items()})
    pixels = torch.from_numpy(decoded["image"].copy()).float()[None] / 255
    sound = torch.from_numpy(np.frombuffer(decoded["audio_bytes"], dtype="<i2").copy().reshape(2, 16000)).float() / 32767
    frames = torch.from_numpy(np.frombuffer(decoded["video_bytes"], dtype=np.uint8).copy().reshape(20, 28, 28, 3)[..., 0]).float()[:, None] / 255
    mutations = {"silence": (torch.zeros_like(sound), frames),
                 "swapped_audio_events": (sound.flip(0), frames),
                 "swapped_video_events": (sound, torch.cat((frames[10:], frames[:10]))),
                 "repeated_video_frames": (sound, frames[[0] * 10 + [10] * 10])}
    results = {}
    for name, (audio, video) in mutations.items():
        media = carrier_media.write_media(directory / name, decoded["caption"], pixels, audio, video,
                                         baseline["generation"]["output"]["bindings"], shutil.which("ffmpeg"), shutil.which("ffprobe"))
        observed = observe_bundle({k: v["path"] for k, v in media["files"].items()}, image_observer, speech_observer)
        score = score_observation(observed, baseline["score"]["expected_after_observation"])
        row = {"output": media, "observation": observed, "score": score,
               "rejected": not score["joint_success"], "valid_clock_retained": True}
        save_json(directory / (name + ".json"), row)
        results[name] = row["rejected"]
    paths = {k: v["path"] for k, v in baseline["generation"]["output"]["files"].items() if k != "video"}
    try:
        carrier_media.read_media(paths)
        results["missing_modality"] = False
    except ValueError as error:
        results["missing_modality"] = True
        save_json(directory / "missing_modality.json", {"rejected": True, "error": str(error), "physical_path_omitted": "video"})
    result = {"nonvacuous": True, "baseline_index": baseline["index"],
              "baseline_mode": baseline["mode"], "mutations": results,
              "all_rejected": len(results) == 5 and all(results.values())}
    save_json(directory / "summary.json", result)
    return result
