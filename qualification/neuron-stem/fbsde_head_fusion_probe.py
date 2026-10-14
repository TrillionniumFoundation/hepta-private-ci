"""Actual archived failed Head: frozen-gate fusion CPU control; no FBSDE promotion.

Trained weights are from the exactly pinned 2026-10-14 failed research
artifact, while numerical inputs are SYNTHETIC. No producer/Reader inference,
labels, model training, native NDU state, or production decision is performed.
"""
from __future__ import annotations

import argparse
from io import BytesIO
import hashlib
import json
import math
from pathlib import Path
import time
from zipfile import ZipFile

ARTIFACT_ID = 11875899646
ZIP_SHA256 = "cd9997b69e88b88f0817985fca00cb5b359936bcd5589fd49cc2c5ac78cb200a"
PREFIX = "acquisition-study/"
VIEW_LIMIT_NS = 100_000_000
NAMES = ("value.weight", "value.bias", "gate.weight", "gate.bias",
         "out.weight", "out.bias")
SHAPES = ((16, 384), (16,), (16, 384), (16,), (8, 16), (8,))


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def original_material(source):
    """Load ONLY the externally pinned archive; weights_only Torch decoding."""
    import torch
    from four_gate_common import digest
    from four_gate_capture import tensor_digest
    from fbsde_acquisition_study import make_head

    source = Path(source)
    require(source.is_file() and not source.is_symlink() and
            source.stat().st_size < 32 * 1024**2,
            "bounded ordinary original artifact required")
    zipped = source.read_bytes()
    require(sha(zipped) == ZIP_SHA256, "different historical ZIP bytes")
    with ZipFile(BytesIO(zipped)) as package:
        require(package.testzip() is None, "invalid archived CRC")
        def read(name):
            info = [p for p in package.infolist() if p.filename == PREFIX + name]
            require(len(info) == 1 and 0 < info[0].file_size < 16 * 1024**2,
                    "incomplete or duplicate historical source")
            raw = package.read(info[0])
            require(len(raw) == info[0].file_size, "truncated evidence bytes")
            return raw
        weights = read("candidate-head.pt")
        physical_raw = read("physical.json")
        failure_raw = read("failure.json")
    physical, failure = json.loads(physical_raw), json.loads(failure_raw)
    require(physical.get("backend") == "hashing_reference_v1"
            and physical.get("real_pretrained_weights_executed") is False
            and physical.get("candidate_head_file_sha256") == sha(weights),
            "wrong archived CPU Head identity or source backend")
    require(failure.get("error_type") == "ViewBudgetExceeded"
            and failure.get("budget_relaxed") is False
            and failure.get("run_complete") is False
            and failure.get("scientific_pass") is False,
            "cannot relabel the historical over-budget failure")
    package = torch.load(BytesIO(weights), map_location="cpu", weights_only=True)
    require(type(package) is dict and set(package) == {"state", "mean", "scale"},
            "pure tensor checkpoint required")
    state = package["state"]
    require(isinstance(state, dict) and set(state) == set(NAMES),
            "complete six-tensor trained Head required")
    for key, shape in zip(NAMES, SHAPES):
        val = state[key]
        require(type(val) is torch.Tensor and tuple(val.shape) == shape and
                val.dtype == torch.float32 and val.device.type == "cpu" and
                bool(torch.isfinite(val).all()),
                "invalid trained Head state shape, dtype or value")
    for name in ("mean", "scale"):
        val = package[name]
        require(type(val) is torch.Tensor and tuple(val.shape) == (384,)
                and val.dtype == torch.float32 and bool(torch.isfinite(val).all()),
                "invalid frozen training normalizer")
    with torch.random.fork_rng(devices=[]):
        model = make_head(torch)
    model.load_state_dict(state, strict=True)
    model = model.cpu().eval().requires_grad_(False)
    identity = digest({k: tensor_digest(v) for k, v in model.state_dict().items()})
    require(identity == physical["candidate_head_identity"],
            "original trained model state has changed")
    receipt = {"model_sha256": identity, "weight_file_sha256": sha(weights),
               "physical_sha256": sha(physical_raw), "failure_sha256": sha(failure_raw),
               "failed_attempt_sha256": failure["last_attempt_sha256"],
               "original_test_attempts": failure["attempts_in_split"],
               "original_run_completed": False}
    return model, receipt


def pack_gates(model):
    """Materialize ONE W/b for both gate projections, outside timed inference."""
    import torch
    with torch.no_grad():
        return (torch.cat((model.value.weight.detach(), model.gate.weight.detach())),
                torch.cat((model.value.bias.detach(), model.gate.bias.detach())))


def fused_logits(model, features, packed):
    from torch.nn import functional as F
    value, gate = F.linear(features, packed[0], packed[1]).chunk(2, dim=-1)
    return model.out(value.tanh() * gate.sigmoid())


def benchmark(archive, output, *, threads=1, repetitions=513, warmup=20):
    import torch
    require(type(threads) is int and threads in (1, 2)
            and type(repetitions) is int and 101 <= repetitions <= 4096
            and type(warmup) is int and 1 <= warmup <= 100,
            "registered CPU thread and sample budget required")
    model, source = original_material(archive)
    torch.set_num_threads(threads)
    before = {k: v.clone() for k, v in model.state_dict().items()}
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(174911)
        features = torch.randn(64, 384, dtype=torch.float32)
    begin = time.process_time_ns()
    packed = pack_gates(model)
    pack_cpu_ns = time.process_time_ns() - begin
    with torch.inference_mode():
        trial = torch.cat((features, features.clamp(-8, 8) * 4), 0)
        reference, candidate = model(trial), fused_logits(model, trial, packed)
        maximum = float((reference-candidate).abs().max())
        flips = int((reference.argmax(-1) != candidate.argmax(-1)).sum())
        require(maximum <= 1e-6 and flips == 0,
                "cannot fuse logits while changing classifications")
        for _ in range(warmup):
            model(features[:1]); fused_logits(model, features[:1], packed)
        measured = {"original": [], "fused": []}
        walls = {"original": [], "fused": []}
        for i in range(repetitions):
            row = features[i % len(features):i % len(features)+1]
            order = ("original", "fused") if i % 2 == 0 else ("fused", "original")
            for name in order:
                wall0, cpu0 = time.perf_counter_ns(), time.process_time_ns()
                if name == "original":
                    model(row)
                else:
                    fused_logits(model, row, packed)
                measured[name].append(time.process_time_ns()-cpu0)
                walls[name].append(time.perf_counter_ns()-wall0)
        for name, original in before.items():
            require(torch.equal(original, model.state_dict()[name]),
                    "frozen source Head was mutated by physical comparison")
    def quantiles(data):
        ordered = sorted(data)
        return {str(q): ordered[min(len(ordered)-1, math.ceil(q*len(ordered))-1)]
                for q in (0.5, 0.95, 0.99, 1.0)}
    result = {"schema": "hepta.fbsde.frozen-head-fusion-control.v1",
              "historical_zip_sha256": ZIP_SHA256,
              "historical_artifact_id": ARTIFACT_ID,
              "source_binding": source, "original_cpu_limit_ns": VIEW_LIMIT_NS,
              "torch_version": torch.__version__, "threads": threads,
              "fixed_vector_seed": 174911, "fixture_vectors_not_failed_source": True,
              "trained_original_head_materialized": True,
              "new_training_steps": 0, "new_pretrained_model_forwards": 0,
              "argmax_flips": flips, "maximum_logit_difference": maximum,
              "gate_pack_cpu_ns": pack_cpu_ns,
              "extra_packed_allocation_bytes": sum(x.numel()*x.element_size()
                                                    for x in packed),
              "process_peak_memory_delta_measured": False,
              "repetitions": repetitions, "warmup_each_arm": warmup,
              "cpu_quantiles_ns": {k: quantiles(v) for k,v in measured.items()},
              "wall_quantiles_ns": {k: quantiles(v) for k,v in walls.items()},
              "observed_budget_excesses": {k: sum(t > VIEW_LIMIT_NS for t in v)
                                           for k,v in measured.items()},
              "encoder_and_journal_cpu_not_measured": True,
              "original_failure_repaired": False,
              "budget_stability_established": False,
              "general_fbsde_solved": False,
              "production_promotion_permitted": False}
    output=Path(output)
    output.mkdir(parents=True, exist_ok=False)
    with (output/"report.json").open("x", encoding="utf-8") as handle:
        json.dump(result, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
    return result


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--threads",type=int,choices=(1,2),default=1)
    args=parser.parse_args()
    value=benchmark(args.archive,args.output,threads=args.threads)
    print(json.dumps({"argmax_flips":value["argmax_flips"],
                      "maximum_logit_difference":value["maximum_logit_difference"],
                      "production_promotion_permitted":False},sort_keys=True))
