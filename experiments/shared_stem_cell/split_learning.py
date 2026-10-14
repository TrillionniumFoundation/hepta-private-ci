"""Training-only routing and a function-preserving unsplit capacity control.

Small research operators for the EXISTING split trial. No new Cell owner,
objective, live topology mutation or production model-selection authority.
"""
from copy import deepcopy

import torch
from torch import nn

from experiments.shared_stem_cell.execution import Head, InputError, integer, measured, tensor_digest

# Offline FP32 train-only centroid routing, NOT the native Q24 Neuron z<=512 profile.
# 768 is the largest preregistered E1 candidate hidden width. Allocation remains
# independently capped to 32 MiB and route centroids to two copies.
MAX_OFFLINE_ROUTING_WIDTH = 768


def checked_features(x, width=None):
    if (not isinstance(x, torch.Tensor) or x.device.type != "cpu" or x.dtype != torch.float32
            or x.ndim != 2 or not 1 <= len(x) <= 16384 or not 1 <= x.shape[1] <= MAX_OFFLINE_ROUTING_WIDTH
            or x.numel() * x.element_size() > 32 * 1024**2
            or (width is not None and x.shape[1] != width) or not bool(torch.isfinite(x).all())
            or bool((x.abs() > 1e6).any())):
        raise InputError("bounded finite CPU routing features required")


class TrainingPartition:
    """Two-centroid Lloyd routing fitted ONLY to supplied training features.

    Deterministic first/farthest initialization; ties choose the first centroid.
    It is a bounded heuristic, not an optimal topology or semantic partition.
    Owns centroid copies, accepts no labels and never updates at inference.
    """
    def __init__(self, centers):
        checked_features(centers)
        if len(centers) != 2:
            raise InputError("two routing centroids required")
        self.centers = centers.detach().clone()

    @torch.no_grad()
    def assign(self, x):
        checked_features(x, self.centers.shape[1])
        # Only n x 2 extra distances, not n x 2 x width materialization.
        distance = x.square().sum(1, keepdim=True) - 2 * x @ self.centers.T
        distance += self.centers.square().sum(1)
        if not bool(torch.isfinite(distance).all()):
            raise InputError("nonfinite routing distance")
        return distance.argmin(1)

    @classmethod
    @torch.no_grad()
    def fit(cls, train, *, iterations=16):
        checked_features(train)
        integer(iterations, 1, 64, "routing iterations")
        with measured() as cost:
            x = train.detach().clone()
            furthest = (x - x[0]).square().sum(1).argmax()
            result = cls(torch.stack((x[0], x[furthest])))
            previous = None
            for step in range(iterations):
                routes = result.assign(x)
                if previous is not None and torch.equal(previous, routes):
                    break
                previous = routes.clone()
                centers = result.centers.clone()
                for index in range(2):
                    members = x[routes == index]
                    if len(members):
                        centers[index] = members.mean(0)
                result = cls(centers)
            counts = torch.bincount(result.assign(x), minlength=2).tolist()
        return result, {**cost, "iterations": step + 1, "train_rows": len(train),
            "train_feature_sha256": tensor_digest(train), "centers": result.centers.tolist(),
            "centroid_sha256": tensor_digest(result.centers),
            "centroid_bytes": result.centers.numel() * result.centers.element_size(),
            "training_route_counts": counts, "empty_child": min(counts) == 0,
            "labels_consumed": False, "inference_updates": 0, "global_optimum": False}

    @torch.no_grad()
    def append_route(self, x):
        return torch.cat((x.detach(), self.assign(x).float().unsqueeze(1)), dim=1)


class InheritedUnsplit(nn.Module):
    """Parent plus initially-zero nonlinear residual, within split's parameter cap.

    Both parent and residual train. Unlike a fresh MLP it retains parent knowledge,
    but unlike RoutedSplit it has one unsplit computation and no expert dispatch.
    """
    def __init__(self, parent, parameter_cap):
        super().__init__()
        if type(parent) is not Head or parent.kind != "linear":
            raise InputError("existing linear parent required")
        width, classes = parent.base.in_features, parent.base.out_features
        count = sum(p.numel() for p in parent.parameters())
        hidden = (parameter_cap - count - classes) // (width + classes + 1)
        if hidden < 1:
            raise InputError("inherited unsplit residual does not fit parameter cap")
        self.parent = deepcopy(parent)
        self.residual = nn.Sequential(nn.Linear(width, hidden), nn.Tanh(), nn.Linear(hidden, classes))
        nn.init.zeros_(self.residual[-1].weight)
        nn.init.zeros_(self.residual[-1].bias)

    def forward(self, x):
        return self.parent(x) + self.residual(x)
