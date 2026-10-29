"""Four equal-parameter structures with a common frozen task head.

This module does not import evaluation labels. Routing sees the same explicit
entity address in every arm; language addressing is measured in a separate
experiment. A serial graph starts as the same function as the parent.
"""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from tensor_cell import TensorCell


ARMS = ("dynamic", "fixed_experts", "monolith", "fixed_graph")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


class Structure(nn.Module):
    """Own private adapters and one shared, frozen head, with auditable routing."""

    def __init__(self, parent, arm):
        super().__init__()
        if arm not in ARMS:
            raise ValueError("unknown structure arm")
        parent.freeze_head()
        self.arm = arm
        self.head = parent.head
        self.routes = np.arange(8, dtype=np.int64) % 2
        self.route_history = []
        self.parent_sha = parent.parameter_digest()
        if arm == "monolith":
            self.cells = nn.ModuleList([parent.expand_rank(2 * parent.config.rank, "monolith")])
        else:
            first = parent.fork(f"{arm}-0")
            if arm == "fixed_graph":
                second = TensorCell(replace(parent.config, cell_id=f"{arm}-1"),
                                    parent.base_encoder_sha, parent.source_ids, head=parent.head)
            else:
                second = parent.fork(f"{arm}-1")
            self.cells = nn.ModuleList([first, second])

    def forward(self, features, entities):
        if self.arm == "monolith":
            return self.cells[0](features)
        if self.arm == "fixed_graph":
            value = features
            for cell in self.cells:
                value = value + (value @ cell.A.T) @ cell.B.T
            return self.head(value)
        routes = torch.as_tensor(self.routes, dtype=torch.long)[entities]
        result = torch.empty((len(features), self.head.out_features), dtype=features.dtype)
        for index, cell in enumerate(self.cells):
            selected = routes == index
            if selected.any():
                result[selected] = cell(features[selected])
        return result

    def counts(self):
        return {"total": sum(p.numel() for p in self.parameters()),
                "trainable": sum(p.numel() for p in self.parameters() if p.requires_grad)}

    def propose_routes(self, features, targets, entities):
        """Training-only gradient partition; never use held outcomes to select."""
        if self.arm != "dynamic":
            return {"gradient_rows": 0, "wall_seconds": 0.0, "cpu_seconds": 0.0}
        began, cpu = time.perf_counter(), time.process_time()
        # Select on the common current function before repartitioning. Existing
        # expert identity is retained; routing changes are recorded as costs.
        gradients = []
        for entity in range(8):
            selected = entities == entity
            index = int(self.routes[entity])
            cell = self.cells[index]
            loss = F.binary_cross_entropy_with_logits(cell(features[selected]), targets[selected])
            values = torch.autograd.grad(loss, (cell.A, cell.B))
            vector = torch.cat([x.reshape(-1) for x in values]).detach().numpy()
            gradients.append(vector / max(float(np.linalg.norm(vector)), 1e-12))
        points = np.asarray(gradients)
        distances = ((points[:, None] - points[None, :]) ** 2).sum(2)
        a, b = np.unravel_index(distances.argmax(), distances.shape)
        centers = points[[a, b]].copy()
        routes = self.routes.copy()
        reason = "converged"
        for _ in range(32):
            proposal = ((points[:, None] - centers[None, :]) ** 2).sum(2).argmin(1)
            if len(set(proposal.tolist())) != 2:
                reason = "degenerate: retain previous routes"
                break
            if np.array_equal(proposal, routes):
                break
            routes = proposal
            centers = np.asarray([points[routes == k].mean(0) for k in range(2)])
        # Cluster labels are arbitrary; choose the permutation that moves the
        # fewest entities. This uses addresses, never answers or held examples.
        if np.count_nonzero(1 - routes != self.routes) < np.count_nonzero(routes != self.routes):
            routes = 1 - routes
        receipt = {"method": "normalized training gradients; deterministic two-means",
                   "before": self.routes.tolist(), "after": routes.tolist(),
                   "moved_entities": int(np.count_nonzero(routes != self.routes)),
                   "gradient_sha256": digest(points.astype("<f4").tobytes()),
                   "gradient_rows": len(features), "reason": reason,
                   "wall_seconds": time.perf_counter() - began,
                   "cpu_seconds": time.process_time() - cpu}
        self.routes = routes
        self.route_history.append(receipt)
        return receipt

    def save(self, root):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=False)
        models = []
        for index, cell in enumerate(self.cells):
            models.append(cell.save(root / f"cell-{index}"))
        manifest = {"schema": "hepta.structure-stream.v1", "arm": self.arm,
                    "routes": self.routes.tolist(), "parent_sha256": self.parent_sha,
                    "parameter_counts": self.counts(), "cells": models}
        (root / "structure.json").write_bytes(canonical(manifest))
        return {"manifest_sha256": digest(canonical(manifest)),
                "serialized_bytes": sum(p.stat().st_size for p in root.rglob("*") if p.is_file())}

    @classmethod
    def load(cls, root, encoder_sha):
        root = Path(root)
        manifest = json.loads((root / "structure.json").read_bytes())
        if manifest["schema"] != "hepta.structure-stream.v1" or manifest["arm"] not in ARMS:
            raise ValueError("invalid structure manifest")
        count = 1 if manifest["arm"] == "monolith" else 2
        cells = []
        for index in range(count):
            cells.append(TensorCell.load(root / f"cell-{index}", encoder_sha,
                                        shared_head=cells[0].head if cells else None))
        instance = cls.__new__(cls)
        nn.Module.__init__(instance)
        instance.arm = manifest["arm"]
        instance.head = cells[0].head
        instance.cells = nn.ModuleList(cells)
        routes = manifest["routes"]
        if len(routes) != 8 or any(type(x) is not int or x not in (0, 1) for x in routes):
            raise ValueError("invalid structure routing")
        instance.routes = np.asarray(routes, dtype=np.int64)
        instance.parent_sha = manifest["parent_sha256"]
        instance.route_history = []
        if instance.counts() != manifest["parameter_counts"]:
            raise ValueError("parameter count differs after restore")
        return instance


def fit(structure, features, targets, entities, *, seed, steps, batch_size,
        learning_rate, cpu_budget_seconds=None, budget_started=None):
    """Record every minibatch; CPU budget includes the caller's selector cost."""
    started, cpu = time.perf_counter(), time.process_time()
    if budget_started is None:
        budget_started = cpu
    optimizer = torch.optim.Adam([p for p in structure.parameters() if p.requires_grad], lr=learning_rate)
    generator = torch.Generator().manual_seed(seed)
    schedule = hashlib.sha256()
    completed, losses = 0, []
    for _ in range(steps):
        if cpu_budget_seconds is not None and time.process_time() - budget_started >= cpu_budget_seconds:
            break
        rows = torch.randint(len(features), (batch_size,), generator=generator)
        schedule.update(rows.numpy().astype("<i8").tobytes())
        optimizer.zero_grad(set_to_none=True)
        loss = F.binary_cross_entropy_with_logits(structure(features[rows], entities[rows]), targets[rows])
        if not torch.isfinite(loss):
            raise FloatingPointError("nonfinite loss")
        loss.backward()
        optimizer.step()
        completed += 1
        if completed == 1 or completed % 100 == 0:
            losses.append([completed, float(loss.detach())])
    return {"steps": completed, "batch_size": batch_size,
            "sample_presentations": completed * batch_size,
            "sample_schedule_sha256": schedule.hexdigest(), "loss_samples": losses,
            "optimizer_reset_each_phase": True,
            "cpu_budget_seconds": cpu_budget_seconds,
            "selector_and_fit_cpu_seconds": time.process_time() - budget_started,
            "fit_cpu_seconds": time.process_time() - cpu,
            "fit_wall_seconds": time.perf_counter() - started}
