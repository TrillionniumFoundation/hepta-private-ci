"""Compose existing shared Encoder and training entrypoints, research only.

No new loader, cache, trainer service or storage. The caller supplies an existing
SharedStemEngine and source-isolated FeatureRequests. Evaluation labels never
enter this runner: it accepts training labels and returns predictions only.
"""

from copy import deepcopy
import time

import torch

from development_tensors import parameter_digest
from shared_encoder_batch import FeatureRequest, SharedStemEngine


def train_shared_head_trial(engine, requests, training_labels, *, classes, head_kind,
                            parameter_budget, steps, seed, head_factory=None, fitter=None):
    """Return paired frozen/trained predictions without self-scoring.

    `training_labels` maps request IDs from the caller's TRAIN fold to labels.
    Canonical study.validate_dataset must run before constructing that mapping.
    Physical encoding is shared; hypothetical standalone costs are NOT imputed.
    """
    if not isinstance(engine, SharedStemEngine):
        raise ValueError("use the existing SharedStemEngine")
    if (not isinstance(requests, tuple) or not 1 <= len(requests) <= 4096
            or not isinstance(training_labels, dict) or not training_labels
            or type(classes) is not int or not 2 <= classes <= 128
            or type(parameter_budget) is not int or not 1 <= parameter_budget <= 262144
            or type(steps) is not int or not 1 <= steps <= 1000 or type(seed) is not int):
        raise ValueError("invalid bounded shared-head trial")
    # Validate the WHOLE trial, not only each microbatch, before any forward.
    seen, scopes, cells = set(), set(), set()
    for request in requests:
        if not isinstance(request, FeatureRequest):
            raise ValueError("invalid FeatureRequest")
        request.validate()
        if request.request_id in seen:
            raise ValueError("duplicate trial request")
        seen.add(request.request_id)
        cells.add(request.cell_id)
        scopes.add(request.cache_key()[:6] + (request.representation,))
    if len(scopes) != 1 or len(cells) > 64:
        raise ValueError("mixed scope/version or too many learning Cells")
    if (not set(training_labels) <= seen
            or any(type(label) is not int or not 0 <= label < classes for label in training_labels.values())
            or any(not any(r.cell_id == cell and r.request_id in training_labels for r in requests) for cell in cells)):
        raise ValueError("missing/invalid per-Cell training labels")
    if head_factory is None or fitter is None:
        from model_runner import build_head, train_head
        head_factory = build_head if head_factory is None else head_factory
        fitter = train_head if fitter is None else fitter
    observed, features = [], []
    total_values = 0
    start = time.perf_counter_ns()
    for offset in range(0, len(requests), 32):
        batch, vectors = engine.run(requests[offset:offset+32], return_features=True)
        total_values += sum(len(item.values) for item in vectors)
        if total_values > 4_194_304:
            raise ValueError("trial feature retention budget exceeded")
        observed.append(batch)
        features.extend(vectors)
    widths = {len(item.values) for item in features}
    if len(widths) != 1 or len(features) * next(iter(widths)) > 4_194_304:
        raise ValueError("heterogeneous or oversized training features")
    # Materialize ordinary tensors outside inference_mode for Head autograd.
    x = torch.tensor([item.values for item in features], dtype=torch.float32)
    frozen, trained, predictions, fit_ns = {}, {}, [], 0
    for index, cell in enumerate(sorted(cells)):
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed + index)
            head, count = head_factory(torch, x.shape[1], classes, head_kind, parameter_budget)
        actual_count = sum(p.numel() for p in head.parameters())
        if count != actual_count or count > parameter_budget:
            raise ValueError("unmatched physical Head parameter count")
        if any(not torch.isfinite(p).all() for p in head.parameters()):
            raise ValueError("invalid initial Head")
        frozen[cell] = deepcopy(head).eval().requires_grad_(False)
        candidate = deepcopy(head)
        train_rows = [i for i, r in enumerate(requests) if r.cell_id == cell and r.request_id in training_labels]
        labels = torch.tensor([training_labels[requests[i].request_id] for i in train_rows], dtype=torch.long)
        before = time.process_time_ns()
        fitter(torch, candidate, x[train_rows].clone(), labels, steps=steps, seed=seed + index)
        fit_ns += time.process_time_ns() - before
        candidate.eval()
        if any(not torch.isfinite(p).all() for p in candidate.parameters()):
            raise ValueError("invalid trained Head")
        trained[cell] = candidate
        evaluation = [i for i, r in enumerate(requests) if r.cell_id == cell and r.request_id not in training_labels]
        if not evaluation:
            continue
        with torch.no_grad():
            old, new = frozen[cell](x[evaluation]), candidate(x[evaluation])
        if old.shape != (len(evaluation), classes) or new.shape != old.shape or not torch.isfinite(new).all() or not torch.isfinite(old).all():
            raise ValueError("invalid paired prediction shape/value")
        for i, a, b in zip(evaluation, old.tolist(), new.tolist()):
            request = requests[i]
            predictions.append({"request_id": request.request_id, "cell_id": cell,
                                "input_digest": request.input_digest,
                                "frozen_logits": a, "trained_logits": b,
                                "trainable_parameters": count})
    report = {"source": "existing SharedStemEngine + existing Head fitter",
              "simulated_encoder": any(o.simulated for o in observed),
              "physical_encoder_calls": sum(o.backend_calls for o in observed),
              "physical_encoder_batch_widths": [w for o in observed for w in o.backend_batch_widths],
              "prior_cache_hits": sum(o.cache_hits for o in observed),
              "encoder_cpu_ns": sum(o.cpu_ns for o in observed),
              "training_cpu_ns": fit_ns, "total_wall_ns": time.perf_counter_ns() - start,
              "frozen_head_digests": {c: parameter_digest(h) for c, h in frozen.items()},
              "trained_head_digests": {c: parameter_digest(h) for c, h in trained.items()},
              "predictions": sorted(predictions, key=lambda r: r["request_id"]),
              "production_authorized": False}
    return frozen, trained, report
