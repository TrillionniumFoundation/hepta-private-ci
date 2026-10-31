"""Actual natural-video decoding and frozen-template local/global control."""
import json
from pathlib import Path
import re
import subprocess
import time

import numpy as np
from scipy.signal import fftconvolve


def decode(source, spec):
    started = time.perf_counter_ns()
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
        "-of", "json", source["video"]["path"]], check=True, capture_output=True, text=True).stdout)["streams"][0]
    config = Path(source["config"]["path"]).read_text()
    first_index = int(re.search(r"^start:\s*(\d+)", config, re.M).group(1)) - 1
    width = spec["resize_width"]
    height = round(probe["height"] * width / probe["width"])
    limit = spec["frames_per_sequence"]
    filters = f"trim=start_frame={first_index}:end_frame={first_index+limit},scale={width}:{height},format=gray"
    raw = subprocess.run(["ffmpeg", "-v", "error", "-threads", "1", "-i", source["video"]["path"],
        "-vf", filters, "-f", "rawvideo", "-pix_fmt", "gray", "-"], check=True, capture_output=True).stdout
    if len(raw) != limit * width * height:
        raise ValueError("Natural video did not yield the frozen frame count")
    frames = np.frombuffer(raw, np.uint8).reshape(limit, height, width).astype(np.float32) / 255
    # Only the task's permitted initialization label is visible to tracking.
    with Path(source["annotation"]["path"]).open() as stream:
        box = np.array([float(x) for x in stream.readline().strip().split(",")])
    scale = np.array([width/probe["width"], height/probe["height"], width/probe["width"], height/probe["height"]])
    return frames, np.rint(box * scale).astype(int), scale, (time.perf_counter_ns() - started) / 1e9, first_index


def window_sums(image, height, width):
    integral = np.pad(image, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    return integral[height:, width:] - integral[:-height, width:] - integral[height:, :-width] + integral[:-height, :-width]


def search(frame, template, previous, radius):
    h, w = template.shape
    if radius is None:
        x0 = y0 = 0
        x1, y1 = frame.shape[1] - w + 1, frame.shape[0] - h + 1
    else:
        x, y = map(int, previous[:2])
        x0, y0 = max(0, x-radius), max(0, y-radius)
        x1, y1 = min(frame.shape[1]-w+1, x+radius+1), min(frame.shape[0]-h+1, y+radius+1)
    region = frame[y0:y1+h-1, x0:x1+w-1].astype(np.float64)
    centered = template.astype(np.float64) - template.mean(dtype=np.float64)
    numerator = fftconvolve(region, centered[::-1, ::-1], mode="valid")
    variance = np.maximum(0, window_sums(region * region, h, w) - window_sums(region, h, w)**2/(h*w))
    denominator = np.sqrt(variance * np.square(centered).sum())
    correlations = np.divide(numerator, denominator, out=np.full_like(numerator, -1.0), where=denominator > 1e-10)
    py, px = np.unravel_index(correlations.argmax(), correlations.shape)
    return [int(x0+px), int(y0+py), int(w), int(h)], float(correlations[py, px])


def track(source, spec, arm, threshold, output):
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    frames, initial, scale, decode_seconds, source_start = decode(source, spec)
    x, y, w, h = initial.tolist()
    if w < 2 or h < 2 or x < 0 or y < 0 or x+w > frames.shape[2] or y+h > frames.shape[1]:
        raise ValueError("Invalid public initialization box")
    template = frames[0, y:y+h, x:x+w].copy()
    previous = initial.tolist()
    boxes, rows, full_calls = [previous], [], 0
    control_start = time.perf_counter_ns()
    for i, frame in enumerate(frames[1:], 1):
        if arm == "fixed_global":
            box, confidence = search(frame, template, previous, None)
            global_call = True
        else:
            box, confidence = search(frame, template, previous, spec["local_radius"])
            global_call = arm == "dynamic" and confidence < threshold
            if global_call:
                box, _ = search(frame, template, previous, None)
        full_calls += int(global_call)
        rows.append({"frame": i, "initial_local_confidence": confidence, "global_search": global_call})
        boxes.append(box)
        previous = box
    control_seconds = (time.perf_counter_ns() - control_start) / 1e9
    public = {"source": source["name"], "arm": arm, "threshold": threshold, "boxes": boxes,
        "decisions": rows, "scale": scale.tolist(), "decoded_source_start_index": source_start,
        "template_sha256": __import__("hashlib").sha256(template.tobytes()).hexdigest(),
        "later_ground_truth_supplied": False, "actual_global_searches": full_calls,
        "decode_wall_seconds": decode_seconds, "control_wall_seconds": control_seconds}
    target = output / "TRACK.json"
    target.write_text(json.dumps(public, sort_keys=True, indent=2) + "\n")
    observed = json.loads(target.read_text())
    if observed["boxes"] != boxes:
        raise ValueError("Actual tracking output readback differs")
    public.update(whole_wall_seconds=(time.perf_counter_ns() - started) / 1e9,
                  python_cpu_seconds=(time.process_time_ns() - cpu) / 1e9)
    # Full annotations become available only after public output is persisted.
    truth = np.loadtxt(source["annotation"]["path"], delimiter=",")[:len(boxes)] * scale
    predicted = np.array(observed["boxes"])
    low = np.maximum(truth[:, :2], predicted[:, :2])
    high = np.minimum(truth[:, :2]+truth[:, 2:], predicted[:, :2]+predicted[:, 2:])
    intersection = np.maximum(0, high-low).prod(1)
    union = truth[:, 2:].prod(1)+predicted[:, 2:].prod(1)-intersection
    iou = intersection / union
    result = {**public, "mean_IoU": float(iou[1:].mean()), "fraction_IoU_at_least_0_5": float((iou[1:] >= .5).mean()),
              "IoU_by_frame": iou.tolist(), "evaluated_frames": len(boxes)-1}
    (output / "PRIVATE_SCORE.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    return result


def run_video(manifest, spec, output):
    output.mkdir(parents=True, exist_ok=False)
    fit_source = next(r for r in manifest["video"] if r["role"] == "fit")
    candidates = []
    for i, threshold in enumerate(spec["global_threshold_candidates"]):
        trial = track(fit_source, spec, "dynamic", threshold, output / "fit" / str(i))
        candidates.append({"threshold": threshold, "mean_IoU": trial["mean_IoU"],
            "global_searches": trial["actual_global_searches"],
            "fit_objective": trial["mean_IoU"]-.02*trial["actual_global_searches"]/trial["evaluated_frames"]})
    chosen = min(candidates, key=lambda r: (-r["fit_objective"], r["threshold"]))
    gate = {"selected_threshold": chosen["threshold"], "candidates": candidates, "fit_sources": spec["fit_sequences"],
            "test_sources": spec["test_sequences"], "test_has_not_started": True, "fitted_parameters": 1}
    (output / "GATE_FROZEN.json").write_text(json.dumps(gate, sort_keys=True, indent=2) + "\n")
    rows = []
    for source in (r for r in manifest["video"] if r["role"] == "test"):
        for arm in spec["arms"]:
            rows.append(track(source, spec, arm, chosen["threshold"], output / "test" / source["name"] / arm))
    result = {"status": "completed", "gate": gate, "rows": rows, "independent_test_sources": len(spec["test_sequences"]),
        "frame_count_is_not_independent_source_count": True, "natural_video_generation": False,
        "neural_parameter_updates": False, "statistical_population_superiority_claim": False}
    (output / "RESULT.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    return result
