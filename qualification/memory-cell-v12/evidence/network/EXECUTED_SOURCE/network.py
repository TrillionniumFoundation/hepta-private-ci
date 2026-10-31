"""V12 research networks: genuine learned routing and executed cell lifecycle.

The owner in this module is an experimental snapshot, not Rust admission. Source
selection is measured separately from parametric content storage. Internal model
weights, routing weights, and retained checkpoints are all charged explicitly.
"""

import hashlib
import json
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.special import expit, softmax

from learned import MLP, features, train_mlp


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def tokens(text):
    words = re.findall(r"[^\W_]+", text.lower())
    return words + [text[i:i + 2] for i in range(len(text) - 1)
                    if "\u4e00" <= text[i] <= "\u9fff" and "\u4e00" <= text[i + 1] <= "\u9fff"]


def active_mask(records, phase):
    """Resolve latest available versions without letting model scores authorize them."""
    latest = {}
    for i, record in enumerate(records):
        if int(record.get("available_phase", 0)) <= phase:
            source = (record.get("path", record["source_id"]), record.get("heading", record["id"]))
            current = latest.get(source)
            if current is None or int(record["version"]) > int(records[current]["version"]):
                latest[source] = i
            elif int(record["version"]) == int(records[current]["version"]) and current != i:
                raise ValueError("ambiguous source version")
    mask = np.zeros(len(records), dtype=bool)
    for i in latest.values():
        row = records[i]
        mask[i] = not row.get("revoked", False) and phase < row.get("withdrawn_phase", float("inf"))
    return mask


class Retrieval:
    """Full visible-text BM25 or fixed-feature nearest source control."""

    def __init__(self, records, mask, mode="bm25", dimension=256):
        started = time.perf_counter()
        self.indices = np.flatnonzero(mask)
        self.size, self.mode = len(records), mode
        self.docs = [records[i]["text"] for i in self.indices]
        self.vectors = features(self.docs, dimension=dimension)
        self.bags = [dict(Counter(tokens(doc))) for doc in self.docs]
        self.lengths = np.array([sum(bag.values()) for bag in self.bags], dtype=float)
        self.average_length = max(1., float(self.lengths.mean()))
        frequency = {}
        for bag in self.bags:
            for word in bag:
                frequency[word] = frequency.get(word, 0) + 1
        self.idf = {word: np.log1p((len(self.docs) - n + .5) / (n + .5))
                    for word, n in frequency.items()}
        self.fit_seconds = time.perf_counter() - started
        self.index_bytes = int(self.vectors.nbytes + len(json.dumps(self.bags).encode())
                               + len(json.dumps(self.idf).encode()) + self.lengths.nbytes)

    def scores(self, texts, x):
        if self.mode == "dense":
            local = np.maximum(x @ self.vectors.T, 0)
        else:
            local = np.zeros((len(texts), len(self.indices)), dtype=np.float32)
            denominator = 1.2 * (.25 + .75 * self.lengths / self.average_length)
            for q, text in enumerate(texts):
                for word in set(tokens(text)):
                    counts = np.array([bag.get(word, 0) for bag in self.bags])
                    local[q] += self.idf.get(word, 0) * counts * 2.2 / (counts + denominator)
            local = local / (1 + local)
        result = np.zeros((len(texts), self.size), dtype=np.float32)
        result[:, self.indices] = local
        return result


@dataclass
class Cell:
    name: str
    kind: str
    model: object
    allowed: list
    dependencies: list
    receipts: list = field(default_factory=list)
    sleeping: dict | None = None
    calls: int = 0

    def scores(self, x, width):
        if self.model is None:
            raise RuntimeError("sleeping cell cannot execute")
        self.calls += len(x)
        score = expit(self.model.predict(x))
        result = np.zeros((len(x), width), dtype=np.float32)
        result[:, self.allowed] = score[:, self.allowed]
        return result

    def export(self):
        return dict(name=self.name, kind=self.kind, allowed=self.allowed,
                    dependencies=self.dependencies, receipts=self.receipts,
                    model=self.model.export(include_optimizer=True) if self.model is not None else None,
                    sleeping=self.sleeping)

    @classmethod
    def restore(cls, state):
        state = dict(state)
        state["model"] = MLP.from_export(state["model"]) if state["model"] is not None else None
        return cls(**state)

    def sleep(self, path):
        if self.model is None:
            raise ValueError("already asleep")
        value = self.model.export(include_optimizer=True)
        write_json(path, value)
        self.sleeping = dict(path=str(Path(path).resolve()), digest=digest(value),
                             bytes=Path(path).stat().st_size)
        self.model = None

    def wake(self):
        if self.model is not None or self.sleeping is None:
            raise ValueError("no sleeping checkpoint")
        value = json.loads(Path(self.sleeping["path"]).read_text())
        if digest(value) != self.sleeping["digest"]:
            raise ValueError("sleep checkpoint changed")
        self.model = MLP.from_export(value)


class Network:
    def __init__(self, cells, width, top_k=None, router=None):
        if not cells or len({c.name for c in cells}) != len(cells):
            raise ValueError("network needs uniquely named cells")
        self.cells, self.width = cells, width
        self.top_k = len(cells) if top_k is None else top_k
        self.router = router
        self.router_receipt = {}

    def fit_router(self, x, targets, ridge=1.):
        """Fit query-to-expert utility on disclosed past outcomes, never query type."""
        started, cpu = time.perf_counter(), time.process_time()
        outcomes = np.column_stack([np.sum(cell.scores(x, self.width) * targets, axis=1)
                                    / np.maximum(targets.sum(axis=1), 1) for cell in self.cells])
        design = np.column_stack([x, np.ones(len(x))]).astype(np.float64)
        prior = np.zeros((design.shape[1], len(self.cells)))
        self.router = np.linalg.solve(design.T @ design + ridge * np.eye(design.shape[1]),
                                      design.T @ outcomes).astype(np.float32)
        self.router_receipt = dict(examples=len(x), historical_cell_reads=len(x) * len(self.cells),
                                   parameter_change_l2=float(np.linalg.norm(self.router - prior)),
                                   target="mean probability assigned by each actual expert to historical required sources",
                                   target_digest=digest(outcomes.tolist()),
                                   wall_seconds=time.perf_counter() - started,
                                   cpu_seconds=time.process_time() - cpu)

    def scores(self, x, mask):
        awake = [i for i, cell in enumerate(self.cells) if cell.model is not None]
        if not awake:
            return np.zeros((len(x), self.width), dtype=np.float32), [[] for _ in x]
        utilities = (np.column_stack([x, np.ones(len(x))]) @ self.router
                     if self.router is not None else np.zeros((len(x), len(self.cells))))
        unavailable = list(set(range(len(self.cells))) - set(awake))
        utilities[:, unavailable] = -np.inf
        chosen = np.argsort(-utilities, axis=1, kind="stable")[:, :min(self.top_k, len(awake))]
        weights = softmax(np.take_along_axis(utilities, chosen, axis=1), axis=1)
        result = np.zeros((len(x), self.width), dtype=np.float32)
        for i, cell in enumerate(self.cells):
            rows, positions = np.where(chosen == i)
            if len(rows):
                result[rows] += cell.scores(x[rows], self.width) * weights[rows, positions, None]
        result[:, ~mask] = 0
        return result, [[self.cells[i].name for i in row] for row in chosen]

    def export(self):
        return dict(cells=[cell.export() for cell in self.cells], width=self.width,
                    top_k=self.top_k, router=None if self.router is None else self.router.tolist(),
                    router_receipt=self.router_receipt)

    @classmethod
    def restore(cls, state):
        router = None if state["router"] is None else np.array(state["router"], dtype=np.float32)
        obj = cls([Cell.restore(cell) for cell in state["cells"]], state["width"], state["top_k"], router)
        obj.router_receipt = state["router_receipt"]
        return obj

    def resource(self):
        arrays = [a for cell in self.cells if cell.model is not None for a in cell.model.arrays.values()]
        receipts = {digest(r): r for cell in self.cells for r in cell.receipts}.values()
        return dict(active_cells=sum(cell.model is not None for cell in self.cells),
                    parameter_bytes=sum(a.nbytes for a in arrays),
                    router_bytes=0 if self.router is None else self.router.nbytes,
                    presentations=sum(r.get("sample_presentations", 0) for r in receipts),
                    fit_wall_seconds=sum(r.get("fit_wall_seconds", 0) for r in receipts),
                    fit_cpu_seconds=sum(r.get("fit_cpu_seconds", 0) for r in receipts),
                    optimizer_bytes=sum(sum(v.nbytes for m in cell.model.optimizer["moments"].values()
                                            for v in m.values()) for cell in self.cells
                                        if cell.model is not None and cell.model.optimizer is not None),
                    serialized_bytes=len(json.dumps(self.export()).encode()),
                    source_dependencies=len(set(s for cell in self.cells for s in cell.dependencies)))


def fit_cell(name, kind, x, y, allowed, dependencies, *, hidden, steps, seed, initial=None):
    arguments = dict(hidden=hidden, steps=steps, seed=seed)
    if initial is not None:
        arguments["initial"] = initial
    model = train_mlp(x, y, **arguments)
    return Cell(name, kind, model, list(map(int, allowed)), sorted(set(dependencies)), [model.receipt])


def select(scores, mask, threshold, limit=3):
    choices = []
    for row in scores:
        order = np.argsort(-row, kind="stable")
        valid = [int(i) for i in order if mask[i] and row[i] > 0][:limit]
        choices.append(valid if valid and row[valid[0]] >= threshold else [])
    return choices


def rewards(choices, targets):
    return np.array([float(set(target).issubset(choice)) if target else float(not choice)
                     for choice, target in zip(choices, targets, strict=True)])


def calibrate(scores, mask, targets, limit=3):
    if not len(targets):
        raise ValueError("calibration must use actual past labels")
    initial = select(scores, mask, 0., limit)
    confidence = np.array([row.max() if choice else -1. for row, choice in zip(scores, initial, strict=True)])
    thresholds = np.unique(np.r_[0., confidence[confidence >= 0],
                                  np.nextafter(confidence[confidence >= 0], np.inf), 1.000001])
    covered = np.array([bool(target) and set(target).issubset(choice)
                        for target, choice in zip(targets, initial, strict=True)])
    best = None
    known = np.array([bool(target) for target in targets])
    for threshold in thresholds:
        accepted = confidence >= threshold
        value = np.where(known, covered & accepted, ~accepted).astype(float)
        groups = [value[known], value[~known]]
        balanced = float(np.mean([group.mean() for group in groups if len(group)]))
        key = (balanced, threshold)
        if best is None or key > best[0]:
            best = (key, float(threshold))
    return best[1]


def lower_gain(candidate, reference, candidate_cost, reference_cost, z=3.2):
    difference = np.asarray(candidate, dtype=float) - np.asarray(reference, dtype=float)
    if len(difference) < 2:
        return dict(mean=None, lower=None, admitted=False)
    gain = float(difference.mean()) - candidate_cost + reference_cost
    lower = gain - z * float(difference.std(ddof=1)) / np.sqrt(len(difference))
    return dict(mean=gain, lower=float(lower), admitted=bool(lower > .005))
