"""Pinned historical physical Head execution; no new Encoder/training/labels.

The input is a previously completed public Actions archive. This replay only
measures CPU Head execution over repeated, originally frozen mmBERT features.
It is NOT total Hepta latency, fresh model generation, energy measurement or
evidence for changing the selected model. No task labels enter the comparison.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import time
from zipfile import ZipFile

import torch
from torch import nn
from torch.nn import functional as F
from safetensors.torch import load

from experiments.shared_stem_cell import postseal_historical_audit as audit

ORIGINAL_SHA = "05b6ec4b33a7563ea368f7d5be212ad1dbf1220bbccb9195ac900ac5adde34a6"
FEATURE = "hepta-public-study/execution/frozen-features/"
COMPONENTS = {
    "bank0": "hepta-public-study/execution/heads/gated/cell-0/learned/",
    "bank1": "hepta-public-study/execution/heads/gated/cell-1/learned/",
    "shared": "hepta-consolidation/heads/supervised/",
    "correction": "hepta-consolidation/ridge-heads/residual_corrected/cell-1/",
}


def require(ok, reason):
    if not ok:
        raise audit.AuditError(reason)


class Head(nn.Module):
    """Exactly the existing unmodified gated/linear research Head arithmetic."""

    def __init__(self, width, kind, rank=8):
        super().__init__()
        require(kind in {"gated", "linear"} and width in {384, 386}, "closed architecture")
        self.kind = kind
        self.base = nn.Linear(width, 4)
        if kind == "gated":
            self.down = nn.Linear(width, rank)
            self.up = nn.Linear(rank, 4, bias=False)
            self.gate = nn.Linear(width, 4)

    def forward(self, x):
        logits = self.base(x)
        if self.kind == "gated":
            logits = (logits + self.up(torch.tanh(self.down(x)))
                      * torch.sigmoid(self.gate(x)))
        return logits


def load_material(archive, name):
    prefix = COMPONENTS[name]
    mraw = archive.read(prefix + "manifest.json")
    manifest = audit.strict_json(mraw)
    raw = archive.read(prefix + "weights.safetensors")
    require(len(raw) <= 2 * 1024 * 1024 and
            len(raw) == manifest.get("weights_bytes") and
            hashlib.sha256(raw).hexdigest() == manifest.get("weights_sha256") and
            manifest.get("production_accepted") is False,
            "model material SHA/size or status mismatch")
    architecture = manifest.get("architecture")
    expected = {"bank0": (384, "gated", 6192),
                "bank1": (384, "gated", 6192),
                "shared": (386, "gated", 6224),
                "correction": (384, "linear", 1540)}
    width, kind, n = expected[name]
    require(type(architecture) is dict and architecture.get("width") == width
            and architecture.get("kind") == kind
            and architecture.get("classes") == 4
            and architecture.get("rank") == (1 if kind == "linear" else 8),
            "unexpected trained Head geometry")
    tensors = load(raw)
    with torch.random.fork_rng(devices=[]):
        model = Head(width, kind)
    model.load_state_dict(tensors, strict=True)
    model = model.cpu().float().eval().requires_grad_(False)
    parameters = sum(p.numel() for p in model.parameters())
    require(parameters == n and manifest["parameters"]["parameters"] == n and
            manifest["parameters"]["parameter_bytes"] == 4 * n and
            all(torch.isfinite(v).all() for v in model.state_dict().values()),
            "actual tensor count or values mismatch")
    return model, {"manifest_sha256": hashlib.sha256(mraw).hexdigest(),
                   "weights_sha256": hashlib.sha256(raw).hexdigest(),
                   "parameters": parameters, "parameter_bytes": 4 * parameters,
                   "stem_sha256": manifest["binding"]["stem_sha256"],
                   "dataset_sha256": manifest["binding"]["dataset_sha256"],
                   "scope": manifest["binding"]["scope"]}


@torch.no_grad()
def execute(models, x, routes, arm):
    require(isinstance(x, torch.Tensor) and x.dtype == torch.float32
            and x.ndim == 2 and x.shape[1] == 384 and
            2 <= len(x) <= 4096 and isinstance(routes, torch.Tensor)
            and routes.dtype == torch.long and routes.shape == (len(x),)
            and bool(((routes == 0) | (routes == 1)).all())
            and bool(torch.isfinite(x).all()), "finite bounded same-scope Head workload")
    if arm == "bank":
        output = torch.empty(len(x), 4)
        for cell in (0, 1):
            indices = (routes == cell).nonzero(as_tuple=False).flatten()
            if len(indices):
                output[indices] = models[f"bank{cell}"](x[indices])
    elif arm in ("shared", "sparse_corrected"):
        combined = torch.cat([x, F.one_hot(routes, num_classes=2).float()], dim=1)
        output = models["shared"](combined)
        if arm == "sparse_corrected":
            correction_rows = (routes == 1).nonzero(as_tuple=False).flatten()
            if len(correction_rows):
                output[correction_rows] += models["correction"](x[correction_rows])
    else:
        raise audit.AuditError("unregistered physical comparator arm")
    require(bool(torch.isfinite(output).all()), "nonfinite physical Head result")
    return output


def study(archive_path, output, *, sha256, repetitions=301, warmup=30):
    require(type(repetitions) is int and 5 <= repetitions <= 1001 and
            type(warmup) is int and 1 <= warmup <= 100,
            "fixed bounded Head microbenchmark budget")
    archive_path = Path(archive_path)
    require(sha256 == ORIGINAL_SHA and
            hashlib.sha256(archive_path.read_bytes()).hexdigest() == ORIGINAL_SHA,
            "externally pinned historical model archive required")
    with ZipFile(archive_path) as z:
        require(z.testzip() is None, "corrupt original archive")
        models = {}
        identities = {}
        for name in COMPONENTS:
            models[name], identities[name] = load_material(z, name)
        common = {(v["stem_sha256"], v["dataset_sha256"], v["scope"])
                  for v in identities.values()}
        require(len(common) == 1, "mixed Stem/Scope/dataset candidate material")
        mraw = z.read(FEATURE + "manifest.json")
        manifest = audit.strict_json(mraw)
        frozen = z.read(FEATURE + "features.safetensors")
        require(manifest.get("simulated_encoder") is False
                and manifest.get("contains_labels") is False
                and manifest.get("production_accepted") is False
                and len(frozen) == manifest.get("file_bytes")
                and hashlib.sha256(frozen).hexdigest() == manifest.get("file_sha256"),
                "physical frozen-pretrained feature provenance mismatch")
        x = load(frozen)["features"].clone().contiguous()
        require(list(x.shape) == [128, 384] and x.dtype == torch.float32
                and bool(torch.isfinite(x).all()),
                "unexpected frozen pretrained feature shape")
        rows = manifest["rows"]
        require(len(rows) == len(x) and
                set(row["cell"] for row in rows) == {0, 1} and
                all(row["scope"] == next(iter(common))[2] for row in rows),
                "mixed scope/Cell feature identities")
        routes = torch.tensor([row["cell"] for row in rows], dtype=torch.long)
    # Reusing original examples is explicit; these are NOT 512 independent tasks.
    torch.set_num_threads(1)
    x = x.repeat(4, 1)
    routes = routes.repeat(4)
    names = ("bank", "shared", "sparse_corrected")
    before = {n: {k: v.detach().clone() for k, v in models[n].state_dict().items()}
              for n in models}
    for _ in range(warmup):
        for name in names:
            execute(models, x, routes, name)
    samples = {n: [] for n in names}
    digests = {}
    for step in range(repetitions):
        for name in names[step % 3:] + names[:step % 3]:
            start = time.perf_counter_ns()
            output_values = execute(models, x, routes, name)
            samples[name].append(time.perf_counter_ns() - start)
            digest = hashlib.sha256(output_values.contiguous().numpy().tobytes()).hexdigest()
            if name in digests:
                require(digests[name] == digest, "same-arm Head logits drift")
            digests[name] = digest
    require(all(torch.equal(v, models[n].state_dict()[k])
                for n, state in before.items() for k, v in state.items()),
            "historical Head weights changed under supposedly frozen inference")
    def percentile(values, p):
        return sorted(values)[max(0, math.ceil(len(values) * p) - 1)]
    report = {
        "schema": "hepta.historical-physical-head-portfolio.v1",
        "source_historical_zip_sha256": ORIGINAL_SHA,
        "frozen_feature_manifest_sha256": hashlib.sha256(mraw).hexdigest(),
        "model_components": identities,
        "input_rows": len(x), "underlying_original_rows": 128,
        "new_encoder_forward_calls": 0, "new_training_steps": 0,
        "same_repeated_feature_rows_not_independent": True,
        "head_invocations_per_batch": {"bank": 2, "shared": 1, "sparse_corrected": 2},
        "candidate_head_parameters": {"bank": 12384, "shared": 6224,
                                      "sparse_corrected": 7764},
        "warmup": warmup, "iterations": repetitions,
        "host": platform.platform(), "torch": torch.__version__, "threads": 1,
        "candidate_logit_sha256": digests,
        "samples_ns": samples,
        "quantiles_ns": {
            name: {f"p{p}": percentile(values, p / 100)
                   for p in (50, 95, 99)} for name, values in samples.items()},
        "peak_rss_per_arm_bytes": None, "energy_joules": None,
        "encoder_and_generation_work_measured": False,
        "independent_evaluation": False, "production_accepted": False,
    }
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    with (output / "result.json").open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = study(args.archive, args.output, sha256=args.sha256)
    print(json.dumps({"quantiles_ns": result["quantiles_ns"],
                      "production_accepted": False}, sort_keys=True))


if __name__ == "__main__":
    main()
