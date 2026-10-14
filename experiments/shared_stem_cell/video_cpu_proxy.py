"""CPU resource qualification with a real but UNTRAINED frozen Conv2d pixel tower.

This is deliberately NOT CLIP, not a pretrained representation, and not a
semantic-capability experiment. It tests net host/PIL/Conv2d/GRU/cache dispatch
cost rather than pretending that counting model forwards proves acceleration.
The same trained Reader weights and source-bound frames are used in both arms.
"""
from __future__ import annotations

import argparse
import io
from pathlib import Path
import statistics
import time

import numpy as np
from PIL import Image
import torch
from torch import nn

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell import media_execution as media
from experiments.shared_stem_cell import video_anytime as anytime
from experiments.shared_stem_cell import video_batch as batch
from experiments.shared_stem_cell import video_temporal as temporal

MODEL_SEED = 20261014
PROFILES = ("forward_only", "paired")
DEPTHS = (2, 8)
BATCHES = (1, 4)
SIZES = (8, 16, 32)
WIDTH = 32
RESIZE = 96


class FrozenPixelConv(nn.Module):
    """Real CPU conv arithmetic, frozen random weights, no model download."""
    def __init__(self):
        super().__init__()
        self.blocks = nn.Sequential(
            nn.Conv2d(3, 8, kernel_size=7, stride=4, padding=3), nn.GELU(),
            nn.Conv2d(8, 16, kernel_size=3, stride=2, padding=1), nn.GELU(),
            nn.Conv2d(16, 32, kernel_size=3, stride=2, padding=1), nn.GELU(),
            nn.AdaptiveAvgPool2d(1), nn.Flatten(),
        )
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(MODEL_SEED)
            for item in self.modules():
                if isinstance(item, nn.Conv2d):
                    nn.init.kaiming_uniform_(item.weight, a=0.5)
                    nn.init.zeros_(item.bias)
        self.eval().requires_grad_(False)

    @torch.no_grad()
    def forward(self, batch):
        if (not isinstance(batch, torch.Tensor) or batch.dtype != torch.float32
                or batch.device.type != "cpu" or batch.ndim != 4 or batch.shape[1:] != (3, RESIZE, RESIZE)
                or not 1 <= len(batch) <= 16 or not bool(torch.isfinite(batch).all())):
            raise e.InputError("bounded RGB CPU Conv2d workload required")
        return self.blocks(batch).float().contiguous()


class PixelTower:
    """Adapter to the exact existing FrameCacheTowers and stream_cases path."""
    def __init__(self, network):
        if (not isinstance(network, FrozenPixelConv) or network.training
                or any(p.requires_grad for p in network.parameters())):
            raise e.InputError("frozen known pixel surrogate required")
        self.network = network
        self.calls = {"clip": 0}
        self.simulated = False   # genuine CPU pixel convolutions, NOT fake features
        self.pretrained = False  # NOT a pretrained CLIP model
        self.processor = "Pillow RGB LANCZOS resize96, float32 RGB/255"
        self.preprocess_ns = 0
        self.conv_forward_ns = 0
        self.loaded_bytes = 0
        self.encoded_frames = 0
        self.forward_batch_sizes = []

    @torch.no_grad()
    def encode(self, name, item, root):
        if name != "video" or not isinstance(item, list) or not 1 <= len(item) <= 16:
            raise e.InputError("video only; at most 16 frames per physical batch")
        start = time.perf_counter_ns()
        pictures = []
        for frame in item:
            if (not isinstance(frame, dict) or set(frame) != {"path", "sha256", "timestamp_us"}
                    or type(frame["timestamp_us"]) is not int):
                raise e.InputError("bound frame SHA and timestamp required")
            raw = media.reference(Path(root), {"path": frame["path"], "sha256": frame["sha256"]})
            self.loaded_bytes += len(raw)
            # The real CLIP path decodes and transforms images before each forward.
            with Image.open(io.BytesIO(raw)) as src:
                if src.format not in ("PNG", "JPEG") or src.width*src.height > 4_194_304:
                    raise e.InputError("bounded PNG/JPEG surrogate source required")
                src.load()
                rgb = src.convert("RGB").resize((RESIZE, RESIZE), Image.Resampling.LANCZOS)
                arr = np.asarray(rgb, dtype=np.uint8).copy()
            pictures.append(torch.from_numpy(arr).permute(2, 0, 1).float().div_(255.0))
        self.preprocess_ns += time.perf_counter_ns() - start
        batch = torch.stack(pictures)
        start = time.perf_counter_ns()
        features = self.network(batch).detach()
        self.conv_forward_ns += time.perf_counter_ns() - start
        self.calls["clip"] += 1
        self.encoded_frames += len(item)
        self.forward_batch_sizes.append(len(item))
        return features, torch.tensor([f["timestamp_us"] for f in item], dtype=torch.long)

    def close(self):
        if self.network.training or any(p.requires_grad for p in self.network.parameters()):
            raise e.InputError("surrogate weights unfrozen")


def cohorts(root, manifest):
    """Select benchmarks by source metadata only; never inspect holdout answers."""
    if (manifest.get("schema") != "hepta.shared-stem-media.v1"
            or manifest.get("video_profile") != "paired_temporal_order_v1"
            or manifest.get("classes") != 2 or set(manifest.get("models", {})) != {"clip"}):
        raise e.InputError("exact paired video manifest required")
    all_cases, _labels = media.read_cases(root, manifest["dataset"], 2)
    cohort, _ = temporal.cohort(root, manifest["cohort"])
    if [c.case_id for c in all_cases] != [r["case_id"] for r in cohort]:
        raise e.InputError("source video cohort identity drift")
    forward = [c for c, r in zip(all_cases, cohort) if r["direction"] == "forward"]
    if len(all_cases) != 80 or len(forward) != 40:
        raise e.InputError("ten-source paired video cohort required")
    return {"forward_only": forward, "paired": all_cases}, all_cases


def train_reader(root, manifest, network, cases):
    """Train a Reader once, on original source-train labels, then freeze both."""
    _, labels = media.read_cases(root, manifest["dataset"], 2)
    train = [c for c in cases if c.split == "train"]
    if len(train) != 48:
        raise e.InputError("source-disjoint train cohort required")
    base = PixelTower(network)
    with e.measured() as cost:
        cache = temporal.FrameCacheTowers(base)
        values = media.extract(cache, train, root)["video"]
        model, work = anytime.fit(values, torch.tensor([labels[c.case_id] for c in train],
                            dtype=torch.long), steps=80, seed=MODEL_SEED)
    return model, {"full_training_and_feature_wall": cost,
                   "reader_training": work, "training_physical_tower_calls": cache.physical_video_calls,
                   "training_unique_frames": len(cache.cache), "training_preprocess_ns": base.preprocess_ns,
                   "training_conv_ns": base.conv_forward_ns}


def summarize(records):
    data = sorted(int(v) for v in records)
    if not data or any(v <= 0 for v in data):
        raise e.InputError("nonempty positive measured timings required")
    return {"samples_ns": list(records), "median_ns": int(statistics.median(data)),
            "nearest_rank_p95_ns": data[(95*len(data)+99)//100-1],
            "nearest_rank_p99_ns": data[(99*len(data)+99)//100-1],
            "tail_is_descriptive_not_statistically_certified": True}


def measure(root, output, *, sizes=SIZES, rounds=5, warmups=1):
    """Paired trials; fresh exact-SHA feature cache each arm, fixed Reader weights.

    Entire reported inference wall includes PIL/bytes hashing/Conv2d/cache/GRU,
    not just tower.forward. CPU process time separately captures contention.
    This is a local hardware baseline, never an estimate for pretrained CLIP.
    """
    root, output = Path(root), Path(output)
    if (not isinstance(sizes, tuple) or not sizes or any(type(n) is not int or n not in SIZES for n in sizes)
            or len(set(sizes)) != len(sizes) or type(rounds) is not int or not 1 <= rounds <= 9
            or type(warmups) is not int or not 0 <= warmups <= 3):
        raise e.InputError("predeclared bounded CPU workload grid required")
    if torch.get_num_threads() != 1:
        raise e.InputError("single-CPU-thread benchmark required")
    experiment_start = time.perf_counter_ns()
    output.mkdir(parents=True, exist_ok=False)
    manifest_raw = (root / "manifest.json").read_bytes()
    manifest = e.decode(manifest_raw)
    network = FrozenPixelConv()
    before = e.parameters(network)
    # The entire grid is immutable before loading ANY train or evaluation label.
    protocol_sha = e.write_once(output / "protocol.json", {
        "schema": "hepta.video-cpu-proxy-protocol.v1",
        "source_sha256": e.sha(Path(__file__).read_bytes()),
        "manifest_sha256": e.sha(manifest_raw), "frozen_proxy_sha256": before["sha256"],
        "reader_seed": MODEL_SEED, "reader_steps": 80,
        "profiles": PROFILES, "sizes": sizes, "depths": DEPTHS, "batch_sizes": BATCHES,
        "rounds": rounds, "warmups": warmups, "torch_threads": 1,
        "frozen_random_conv_not_clip": True, "label_free_benchmark": True,
        "pretraining_qualified": False, "production_accepted": False})
    pools, all_cases = cohorts(root, manifest)
    with e.measured() as loading:
        model, fit_cost = train_reader(root, manifest, network, all_cases)
    reader_identity = e.parameters(model)
    e.write_once(output / "plan.json", {"schema": "hepta.video-cpu-proxy-plan.v1",
        "source_sha256": e.sha(Path(__file__).read_bytes()),
        "protocol_sha256": protocol_sha,
        "manifest_sha256": e.sha(manifest_raw), "frozen_proxy_sha256": before["sha256"],
        "trained_reader_sha256": reader_identity["sha256"],
        "profiles": PROFILES, "sizes": sizes, "depths": DEPTHS, "batch_sizes": BATCHES,
        "rounds": rounds, "warmups": warmups, "torch_threads": 1,
        "processor": "Pillow RGB 224->96 LANCZOS then float32/255",
        "frozen_random_conv_not_clip": True, "source_media_not_exported": True,
        "no_holdout_label_for_benchmark": True, "production_accepted": False})
    sample_runs, summary, predictions = {}, {}, {}
    warmup_wall_ns = 0
    try:
        for profile in PROFILES:
            for n in sizes:
                cases = pools[profile][:n]
                if len(cases) != n:
                    raise e.InputError("missing declared CPU bench Cell rows")
                for depth in DEPTHS:
                    k = f"{profile}:{n}:{depth}"
                    # Alternating counterbalanced order over rounds (warmups excluded).
                    timings = {1: [], 4: []}
                    for iteration in range(-warmups, rounds):
                        order = BATCHES if iteration % 2 == 0 else tuple(reversed(BATCHES))
                        for size in order:
                            base = PixelTower(network)
                            with e.measured() as elapsed:
                                observed = batch.stream_cases(model, cases, root, base,
                                    {"kind": "fixed", "depth": depth}, None, batch_size=size)
                            wall = elapsed["wall_ns"]
                            stream_ns = observed["physical_work"]["whole_stream_wall"]["wall_ns"]
                            if type(stream_ns) is not int or stream_ns <= 0:
                                raise e.InputError("measured actual stream work required")
                            rows = observed["records"]
                            if [row["case_id"] for row in rows] != [c.case_id for c in cases]:
                                raise e.InputError("benchmark Cell order drift")
                            if any(row["depth"] != depth for row in rows):
                                raise e.InputError("benchmark selected depth drift")
                            signature = [(row["prediction"], row["probabilities"]) for row in rows]
                            if k not in predictions:
                                predictions[k] = signature
                            else:
                                for a, b in zip(predictions[k], signature):
                                    if a[0] != b[0] or max(abs(x-y) for x,y in zip(a[1], b[1])) > 2e-5:
                                        raise e.InputError("same trained Reader changed across batch schedules")
                            if e.parameters(network) != before or e.parameters(model) != reader_identity:
                                raise e.InputError("frozen benchmark model weights drift")
                            if iteration < 0:
                                warmup_wall_ns += wall
                            if iteration >= 0:
                                metrics = {"wall_ns": wall, "stream_wall_ns": stream_ns,
                                    "research_wrapper_overhead_ns": wall - stream_ns,
                                    "process_cpu_ns": elapsed["process_cpu_ns"],
                                    "preprocess_ns": base.preprocess_ns, "conv_forward_ns": base.conv_forward_ns,
                                    "read_source_bytes": base.loaded_bytes,
                                    "physical_calls": observed["physical_work"]["physical_video_calls"],
                                    "unique_frames": observed["physical_work"]["unique_frames"],
                                    "requested_rows": observed["physical_work"]["requested_frame_rows"],
                                    "conv_batch_sizes": base.forward_batch_sizes,
                                    "rss_start_bytes": elapsed["rss_start_bytes"],
                                    "rss_end_bytes": elapsed["rss_end_bytes"],
                                    "rss_is_endpoint_only_not_peak": True}
                                timings[size].append(metrics)
                                if iteration == 0:
                                    sample_runs[f"{k}:{size}"] = observed
                    serial = timings[1]
                    grouped = timings[4]
                    summary[k] = {"profile": profile, "cases": n, "fixed_depth": depth,
                        "batch_1": serial, "batch_4": grouped,
                        "serial_wall": summarize([x["wall_ns"] for x in serial]),
                        "batched_wall": summarize([x["wall_ns"] for x in grouped]),
                        "ratio_median_wall": statistics.median([x["wall_ns"] for x in serial])/
                                             statistics.median([x["wall_ns"] for x in grouped]),
                        "no_quality_metric_claimed": True,
                        "same_predictions_and_reader_weights": True}
        e.write_once(output / "trace.json", {"records": sample_runs,
            "trained_reader_sha256": reader_identity["sha256"],
            "frozen_proxy_sha256": before["sha256"]})
        if e.parameters(network) != before or e.parameters(model) != reader_identity:
            raise e.InputError("frozen surrogate or Reader changed")
        arm_wall_ns = sum(x["wall_ns"] for measurement in summary.values()
                          for b in BATCHES for x in measurement[f"batch_{b}"])
        report = {"schema": "hepta.video-cpu-proxy-benchmark.v1",
            "whole_study_wall_ns_excludes_report_write": time.perf_counter_ns()-experiment_start,
            "measured_arm_wall_ns": arm_wall_ns,
            "warmup_wall_ns": warmup_wall_ns,
            "warmup_executions_charged": len(summary)*len(BATCHES)*warmups,
            "all_comparator_arms_charged": True,
            "source_sha256": e.sha(Path(__file__).read_bytes()),
            "manifest_sha256": e.sha(manifest_raw), "protocol_sha256": protocol_sha,
            "proxy": before,
            "reader": reader_identity, "load_and_training": loading,
            "training_breakdown": fit_cost, "measurements": summary,
            "trace_sha256": e.sha((output / "trace.json").read_bytes()),
            "selection_uses_holdout_labels": False, "experiment_has_real_rgb_conv2d": True,
            "pretrained_vision_model": False, "real_clip_acceleration_established": False,
            "net_full_study_savings_established": False,
            "independent_source_population_generalization": False,
            "resource_conditions": "single_thread local CPU; OS caches warm; CPU allocation/RSS noisy",
            "energy_joules": None, "peak_rss_bytes": None, "production_accepted": False}
        e.write_once(output / "report.json", report)
        return report
    except Exception as exc:
        e.write_once(output / "failure.json", {"type": type(exc).__name__,
                       "message": str(exc), "production_accepted": False})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=5)
    args = parser.parse_args()
    torch.set_num_threads(1)
    measure(args.root, args.output, rounds=args.rounds)
