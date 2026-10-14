"""Physical PyTorch SemanticMemoryCell experiments over externally admitted features.

Reuse Hepta's existing Head/fit and LocalEncoder machinery. This file does not
construct a fake HF model, download weights, select artifacts or claim promotion.
A candidate's held-out predictions are sealed before an independent scorer reads
ground truth. All mutation is confined to detached research copies.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import math

import torch
from torch import nn
from torch.nn import functional as F

from experiments.shared_stem_cell.execution import Head, fit, parameters, tensor_digest, measured
from amcn_core import RELATIONS, Refused, require, is_sha, digest, shadow_disposition

SCHEMA = "hepta.amcn.semantic-head.v1"
MAX_ROWS = 16384
MAX_WIDTH = 8192


@dataclass(frozen=True)
class Row:
    row_id: str
    source_root: str
    family: str
    split: str
    scope: str
    generation: str
    input_sha256: str

    def __post_init__(self):
        require(all(isinstance(v, str) and 0 < len(v) <= 256
                    for v in (self.row_id, self.source_root, self.family,
                              self.split, self.scope, self.generation)), "training row identity")
        require(self.split in ("train", "select", "future_a", "future_b", "retention"),
                "training row split")
        require(is_sha(self.input_sha256), "feature input binding")


class FeatureMatrix:
    """Frozen, physically shared tensor features; no label data or mutable cache."""
    def __init__(self, rows, features, *, encoder_sha256, scope, generation,
                 backend_profile, encoder_execution_receipt=None):
        require(is_sha(encoder_sha256), "encoder identity")
        require(backend_profile in ("local_hf_verified_externally", "mechanics_fixture"),
                "unregistered Encoder backend")
        require(isinstance(rows, (list, tuple)) and 2 <= len(rows) <= MAX_ROWS,
                "bounded feature rows")
        require(len({r.row_id for r in rows}) == len(rows)
                and all(isinstance(r, Row) and r.scope == scope and
                        r.generation == generation for r in rows), "foreign/duplicate features")
        require(isinstance(features, torch.Tensor) and features.dtype == torch.float32
                and features.device.type == "cpu" and features.ndim == 2
                and features.shape[0] == len(rows) and 1 <= features.shape[1] <= MAX_WIDTH,
                "CPU FP32 feature shape")
        require(bool(torch.isfinite(features).all()), "nonfinite features")
        # "verified_externally" is a declared provenance class, not an assertion
        # that this constructor independently authenticated the provider.
        if backend_profile == "local_hf_verified_externally":
            require(is_sha(encoder_execution_receipt), "missing original HF execution receipt")
        else:
            require(encoder_execution_receipt is None, "fixture cannot mint HF receipt")
        self.rows = tuple(rows)
        self.x = features.detach().clone().contiguous()
        self.encoder_sha256, self.scope, self.generation = encoder_sha256, scope, generation
        self.backend_profile = backend_profile
        self.encoder_execution_receipt = encoder_execution_receipt
        self.identity = digest({
            "encoder": encoder_sha256, "scope": scope, "generation": generation,
            "profile": backend_profile, "execution_receipt": encoder_execution_receipt,
            "rows": [(r.row_id, r.input_sha256, r.family, r.source_root, r.split) for r in rows],
            "tensors": tensor_digest(self.x),
        })

    def input_positions(self, target_split):
        return [i for i, r in enumerate(self.rows) if r.split == target_split]

    def train_labels(self, labels):
        require(isinstance(labels, dict), "TRAIN label map required")
        positions = self.input_positions("train")
        expected = {self.rows[i].row_id for i in positions}
        require(expected and set(labels) == expected, "nontraining label or missing train target")
        require(all(type(v) is int and v in (0, 1) for v in labels.values()),
                "binary evidence relevance labels")
        # Do not count correlation groups as independent trials.
        return positions, torch.tensor([labels[self.rows[i].row_id] for i in positions],
                                       dtype=torch.long)


def train_semantic(matrix, training_labels, *, seed=17, steps=48, kind="gated"):
    """Actual SGD/AdamW via existing Head.fit, same-init frozen no-learning control."""
    require(isinstance(matrix, FeatureMatrix), "frozen feature matrix required")
    require(kind in ("linear", "gated", "low_rank"), "bounded SemanticCell Head profile")
    require(type(steps) is int and 1 <= steps <= 1000, "training work bound")
    positions, labels = matrix.train_labels(training_labels)
    require(len(set(labels.tolist())) == 2, "both relevance classes required")
    train_families = {matrix.rows[i].family for i in positions}
    holdouts = [r for r in matrix.rows if r.split in ("future_a", "future_b")]
    require(all(r.family not in train_families for r in holdouts),
            "future-family leakage")
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        frozen = Head(matrix.x.shape[1], 2, kind=kind,
                      rank=min(8, matrix.x.shape[1])).eval()
    before_sha = parameters(frozen)["sha256"]
    trained, metrics = fit(frozen, matrix.x[positions], labels,
                           steps=steps, seed=seed, batch=min(16, len(positions)))
    require(parameters(frozen)["sha256"] == before_sha
            and parameters(trained)["sha256"] != before_sha,
            "frozen control changed or no actual learning")
    predictions = []
    with torch.no_grad():
        for i, row in enumerate(matrix.rows):
            # These are predictions only. No select/future/retention truth is opened.
            prediction = trained(matrix.x[i:i+1]).softmax(-1)[0, 1].item()
            baseline = frozen(matrix.x[i:i+1]).softmax(-1)[0, 1].item()
            require(math.isfinite(prediction) and math.isfinite(baseline), "invalid probabilities")
            predictions.append({"row_id": row.row_id, "split": row.split,
                                "family": row.family, "input_sha256": row.input_sha256,
                                "frozen_relevance": baseline, "trained_relevance": prediction})
    record = shadow_disposition(
        profile=SCHEMA, feature_digest=matrix.identity,
        encoder_sha256=matrix.encoder_sha256, backend_profile=matrix.backend_profile,
        frozen=parameters(frozen), trained=parameters(trained), work=metrics,
        prediction_digest=digest(predictions), train_source_groups=len(train_families),
        independent_future_accuracy=None, citation_entailment=None,
    )
    return {"frozen": frozen, "trained": trained, "predictions": predictions, "receipt": record}


def train_relation_router(graph, training_examples, *, steps=50, seed=17):
    """Learn edge-type routing coefficients ONLY; no new/deleted topology edges.

    TRAIN examples have exactly (relation, label, family). Neither validation nor
    future targets enter this optimizer. It is not a causal-edge truth validator.
    """
    from amcn_core import FrozenGraph
    require(isinstance(graph, FrozenGraph), "frozen HNMF projection required")
    require(isinstance(training_examples, list) and 4 <= len(training_examples) <= 4096,
            "bounded TRAIN edge examples")
    edge_set = {e.relation for e in graph.edges}
    features, labels, families = [], [], set()
    for row in training_examples:
        require(isinstance(row, dict) and set(row) == {"relation", "label", "family", "split"},
                "relation supervision")
        require(row["split"] == "train" and row["relation"] in edge_set
                and type(row["label"]) is int and row["label"] in (0, 1)
                and isinstance(row["family"], str) and row["family"], "invalid TRAIN edge row")
        features.append(RELATIONS.index(row["relation"]))
        labels.append(row["label"])
        families.add(row["family"])
    require(len(set(labels)) == 2, "edge classes")
    indices = torch.tensor(features, dtype=torch.long)
    y = torch.tensor(labels, dtype=torch.float32)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        # Six tiny scalars; graph connectivity is identical before and after.
        weights = nn.Parameter(torch.zeros(len(RELATIONS), dtype=torch.float32))
    optim = torch.optim.SGD([weights], lr=0.1)
    with measured() as measured_work:
        for _ in range(steps):
            optim.zero_grad(set_to_none=True)
            loss = F.binary_cross_entropy_with_logits(weights[indices], y)
            require(bool(torch.isfinite(loss)), "invalid relation loss")
            loss.backward()
            optim.step()
            with torch.no_grad():
                weights.clamp_(-8, 8)
    result = {relation: float(weights.detach()[idx]) for idx, relation in enumerate(RELATIONS)}
    return result, shadow_disposition(
        profile="hepta.amcn.fixed-topology-learned-route.v1",
        graph_sha256=graph.snapshot_digest, train_families=len(families),
        optimizer_steps=steps, candidate_weights_sha256=digest(result),
        topology_mutation=False, work=measured_work)


def candidate_fission_and_consolidation(parent, matrix, training_labels,
                                         train_branch, *, steps=20, seed=17):
    """True trainable child/teacher/student tensors on isolated candidate copies.

    The balanced group router reproduces parent logits on split initialization.
    This experiment reports ACTUAL parameter budgets and withholds qualification
    until the external same-budget unsplit control, retention and future evidence.
    """
    require(isinstance(matrix, FeatureMatrix) and isinstance(parent, Head),
            "real parent Head and feature matrix required")
    require(parent.kind in ("linear", "gated", "low_rank"), "unsupported parent architecture")
    indices, labels = matrix.train_labels(training_labels)
    train_ids = {matrix.rows[i].row_id for i in indices}
    require(isinstance(train_branch, dict) and set(train_branch) == train_ids
            and set(train_branch.values()) == {0, 1}
            and all(type(v) is int for v in train_branch.values()),
            "only TRAIN may define a two-sibling partition")
    require(type(steps) is int and 1 <= steps <= 512, "fission work")
    root_sha = parameters(parent)["sha256"]
    children = [deepcopy(parent).eval(), deepcopy(parent).eval()]
    # Parent-preserving soft mixture at boundary, before any specialization.
    with torch.no_grad():
        parent_logits = parent(matrix.x).detach()
        initial = (children[0](matrix.x) + children[1](matrix.x)) * 0.5
        initial_error = float((parent_logits - initial).abs().max())
    require(initial_error <= 2e-5, "fission initialization parity")
    trained_children, child_work = [], []
    for group in (0, 1):
        chosen = [i for i in indices if train_branch[matrix.rows[i].row_id] == group]
        require(len(chosen) >= 2, "too few sibling training samples")
        y = torch.tensor([training_labels[matrix.rows[i].row_id] for i in chosen],
                         dtype=torch.long)
        child, cost = fit(children[group], matrix.x[chosen], y,
                          steps=steps, seed=seed + group, batch=min(16, len(chosen)))
        trained_children.append(child)
        child_work.append(cost)
    teacher = lambda xx: (trained_children[0](xx) + trained_children[1](xx)) * 0.5
    student = deepcopy(parent).train()
    optimizer = torch.optim.AdamW(student.parameters(), lr=0.005, weight_decay=0.0)
    with torch.no_grad():
        teacher_logits = teacher(matrix.x[indices]).detach()
        parent_reference = parent(matrix.x[indices]).detach()
    with measured() as consolidation_work:
        for _ in range(steps):
            optimizer.zero_grad(set_to_none=True)
            new_logits = student(matrix.x[indices])
            # Source-label loss + teacher behavior + original retention reference.
            objective = (F.cross_entropy(new_logits, labels)
                         + F.kl_div(F.log_softmax(new_logits / 2, dim=-1),
                                    F.softmax(teacher_logits / 2, dim=-1),
                                    reduction="batchmean") * 4.0
                         + F.mse_loss(new_logits, parent_reference) * 0.1)
            require(bool(torch.isfinite(objective)), "nonfinite consolidation loss")
            objective.backward()
            nn.utils.clip_grad_norm_(student.parameters(), 1.0, error_if_nonfinite=True)
            optimizer.step()
    student.eval()
    require(parameters(parent)["sha256"] == root_sha, "parent mutated")
    # Candidate output withheld from any current-run selector.
    with torch.no_grad():
        teacher_probs = teacher(matrix.x).softmax(-1)[:, 1].tolist()
        student_probs = student(matrix.x).softmax(-1)[:, 1].tolist()
    predictions = [{"row_id": row.row_id, "family": row.family,
                    "split": row.split, "input_sha256": row.input_sha256,
                    "teacher_probability": teacher_probs[i],
                    "student_probability": student_probs[i]}
                   for i, row in enumerate(matrix.rows)]
    sizes = [parameters(c) for c in trained_children]
    return {"children": trained_children, "student": student, "predictions": predictions,
            "receipt": shadow_disposition(
                profile="hepta.amcn.candidate-fission-consolidation.v1",
                feature_sha256=matrix.identity, old_parent_sha256=root_sha,
                initialization_max_abs_error=initial_error,
                parent_parameters=parameters(parent), child_parameters=sizes,
                simultaneously_live_teacher_parameters=sum(x["parameters"] for x in sizes),
                student_parameters=parameters(student),
                child_training_work=child_work, consolidation_work=consolidation_work,
                partition_digest=digest(train_branch), prediction_sha256=digest(predictions),
                equal_parameter_budget_control_completed=False,
                independent_old_task_retention=False,
                trained_topology_promoted=False)}
