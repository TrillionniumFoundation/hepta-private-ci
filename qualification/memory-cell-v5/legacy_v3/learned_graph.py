"""Learn bounded typed layouts from actual candidate execution feedback.

Operation implementations and their port types are supplied capabilities. Edge
preferences are optimized from terminal correctness, not supplied target paths.
This is learned composition over a bounded catalog, not type invention.
"""

from dataclasses import asdict, dataclass
from collections import defaultdict
from pathlib import Path
import re
import time

import numpy as np

from .semantic_router import canonical, digest, strict_json


@dataclass(frozen=True)
class OperationSpec:
    name: str
    input_type: str
    output_type: str
    cell_type: str


@dataclass(frozen=True)
class TypedValue:
    kind: str
    value: object
    support: tuple[str, ...] = ()


@dataclass(frozen=True)
class GraphQuery:
    scope: str
    utterance: str
    handle: str
    as_of: str | None = None
    probe: object = None


class GraphExecutor:
    """Run real cell callbacks under one scoped, generation-bound catalog."""

    def __init__(
        self,
        specs,
        callbacks,
        *,
        scope,
        generation,
        max_hops=3,
        admission_check=None,
        artifact_bindings=None,
        source_frontier_digest=None,
    ):
        self.specs = {value.name: value for value in specs}
        if not 1 <= len(self.specs) <= 32 or len(self.specs) != len(specs):
            raise ValueError("invalid bounded operation catalog")
        if set(callbacks) != set(self.specs) or any(
            not callable(x) for x in callbacks.values()
        ):
            raise ValueError("operation implementation inventory mismatch")
        if type(generation) is not int or generation < 0 or not 1 <= max_hops <= 4:
            raise ValueError("invalid graph generation or depth")
        for spec in specs:
            if any(
                not isinstance(x, str) or not 1 <= len(x) <= 128
                for x in asdict(spec).values()
            ):
                raise ValueError("invalid operation port identity")
            if spec.name == "stop" or spec.name.startswith("start:"):
                raise ValueError("reserved graph operation name")
        self.callbacks = dict(callbacks)
        self.scope, self.generation, self.max_hops = scope, generation, max_hops
        if admission_check is not None and not callable(admission_check):
            raise ValueError("invalid graph admission callback")
        self.admission_check = admission_check
        self.artifact_bindings = dict(artifact_bindings or {})
        self.source_frontier_digest = source_frontier_digest

    def candidates(self, start_type):
        paths = []
        queue = [((), start_type)]
        while queue:
            path, current = queue.pop()
            for name, spec in sorted(self.specs.items()):
                if spec.input_type != current or name in path:
                    continue
                candidate = (*path, name)
                paths.append(candidate)
                if len(paths) > 4096:
                    raise ValueError("typed path search exceeds candidate bound")
                if len(candidate) < self.max_hops:
                    queue.append((candidate, spec.output_type))
        return tuple(sorted(paths))

    def run(
        self,
        path,
        initial,
        query,
        *,
        expected_generation,
        mode="connected",
        permutation=None,
    ):
        if query.scope != self.scope or expected_generation != self.generation:
            raise ValueError("scope or graph generation mismatch")
        if mode not in {"connected", "no_cross_cell_edges"}:
            raise ValueError("unknown graph execution mode")
        if not 1 <= len(path) <= self.max_hops or len(set(path)) != len(path):
            raise ValueError("invalid bounded acyclic path")
        if permutation is not None:
            if set(permutation) != set(self.specs) or set(permutation.values()) != set(
                self.specs
            ):
                raise ValueError("edge permutation is not a bijection")
            for before, after in permutation.items():
                a, b = self.specs[before], self.specs[after]
                if (a.input_type, a.output_type) != (b.input_type, b.output_type):
                    raise ValueError("edge permutation changes port types")
            path = tuple(permutation[x] for x in path)
        value, previous, trace = initial, None, []
        started = time.perf_counter()
        for name in path:
            if name not in self.specs:
                raise ValueError("path selects an unregistered operation")
            spec = self.specs[name]
            if value is None:
                break
            if value.kind != spec.input_type:
                raise ValueError("runtime edge type mismatch")
            if (
                mode == "no_cross_cell_edges"
                and previous is not None
                and previous.cell_type != spec.cell_type
            ):
                return None, {
                    "trace": trace,
                    "calls": len(trace),
                    "seconds": time.perf_counter() - started,
                    "disposition": "removed_cross_cell_edge",
                }
            if self.admission_check is not None:
                self.admission_check(
                    self.generation,
                    name,
                    self.artifact_bindings.get(name),
                    self.source_frontier_digest,
                )
            before = digest(canonical(asdict(value)))
            tick = time.perf_counter()
            value = self.callbacks[name](value, query)
            elapsed = time.perf_counter() - tick
            if value is not None and (
                not isinstance(value, TypedValue) or value.kind != spec.output_type
            ):
                raise ValueError("operation violated its declared output port")
            trace.append(
                {
                    "operation": name,
                    "cell_type": spec.cell_type,
                    "owner_checked": self.admission_check is not None,
                    "input_digest": before,
                    "output": None if value is None else asdict(value),
                    "seconds": elapsed,
                }
            )
            previous = spec
        return value, {
            "trace": trace,
            "calls": len(trace),
            "seconds": time.perf_counter() - started,
            "disposition": "completed" if value is not None else "cell_abstained",
        }


def typed_permutation(specs, seed):
    """Permute same-port operations without fixed points where possible."""
    groups = defaultdict(list)
    for spec in specs:
        groups[spec.input_type, spec.output_type].append(spec.name)
    rng = np.random.default_rng(seed)
    result = {}
    for names in groups.values():
        names = sorted(names)
        if len(names) > 1:
            rng.shuffle(names)
        for index, name in enumerate(names):
            result[name] = names[(index + 1) % len(names)]
    return result


def collect_feedback(executor, examples, *, partition, score_function=None):
    """Targets are compared outside callbacks; every attempted path is retained."""
    if partition not in {"train", "selection"}:
        raise ValueError("hidden examples cannot select or train graph structure")
    rows = []
    for example in examples:
        query_id, intent, initial, query, target = example
        for path in executor.candidates(initial.kind):
            value, receipt = executor.run(
                path, initial, query, expected_generation=executor.generation
            )
            correct = value is not None and value == target
            reward = (
                float(correct)
                if score_function is None
                else float(score_function(value, target))
            )
            if not np.isfinite(reward) or not 0 <= reward <= 1:
                raise ValueError("terminal grader must return a bounded scalar")
            rows.append(
                {
                    "query_id": query_id,
                    "partition": partition,
                    "intent": intent,
                    "start_type": initial.kind,
                    "path": list(path),
                    "terminal_exact": bool(correct),
                    "reward": reward,
                    "target": asdict(target),
                    "actual": None if value is None else asdict(value),
                    "execution": receipt,
                }
            )
    return rows


class LearnedGraph:
    """Intent-conditioned edge weights learned from terminal candidate rewards."""

    def __init__(self, specs, intents, start_types, *, max_hops=3, seed=0):
        self.specs, self.intents = tuple(specs), tuple(intents)
        self.start_types = tuple(start_types)
        self.max_hops, self.seed, self.steps = max_hops, seed, 0
        if (
            not 1 <= len(self.intents) <= 64
            or len(set(self.intents)) != len(self.intents)
            or not 1 <= len(self.start_types) <= 32
            or len(set(self.start_types)) != len(self.start_types)
            or any(
                not isinstance(x, str) or not 1 <= len(x) <= 128
                for x in (*self.intents, *self.start_types)
            )
        ):
            raise ValueError("unique supported graph intents required")
        dummy = {x.name: lambda value, query: None for x in self.specs}
        executor = GraphExecutor(
            self.specs, dummy, scope="enumeration", generation=0, max_hops=max_hops
        )
        self.paths = {kind: executor.candidates(kind) for kind in self.start_types}
        edges = set()
        for kind, paths in self.paths.items():
            if not paths:
                raise ValueError("graph start type has no valid operation")
            for path in paths:
                edges.update(self.path_edges(kind, path))
        self.edges = tuple(sorted(edges))
        self.weights = np.random.default_rng(seed).normal(
            0, 0.01, (len(self.intents), len(self.edges))
        )
        self.path_features = {}
        for kind, paths in self.paths.items():
            features = np.zeros((len(paths), len(self.edges)), dtype=np.float64)
            for row, path in enumerate(paths):
                for edge in self.path_edges(kind, path):
                    features[row, self.edges.index(edge)] += 1
            self.path_features[kind] = features

    def path_edges(self, kind, path):
        return (
            ("start:" + kind, path[0]),
            *zip(path[:-1], path[1:]),
            (path[-1], "stop"),
        )

    @property
    def parameter_bytes(self):
        return self.weights.nbytes

    def fit(
        self, feedback, *, steps=300, learning_rate=0.08, call_penalty=0.002, l2=0.001
    ):
        started = time.perf_counter()
        if type(steps) is not int or not 1 <= steps <= 100000:
            raise ValueError("invalid graph optimizer step count")
        if not 0 < learning_rate <= 1 or not 0 <= call_penalty < 1 or not 0 <= l2 <= 1:
            raise ValueError("invalid graph optimizer settings")
        grouped = defaultdict(list)
        for row in feedback:
            if row["partition"] != "train":
                raise ValueError("only training feedback may update graph weights")
            if row["intent"] not in self.intents or row["start_type"] not in self.paths:
                raise ValueError("feedback has unsupported graph intent or start")
            grouped[row["query_id"]].append(row)
        if not grouped:
            raise ValueError("empty graph training feedback")
        batches, unsupported = [], 0
        for rows in grouped.values():
            intent, kind = rows[0]["intent"], rows[0]["start_type"]
            by_path = {tuple(row["path"]): row for row in rows}
            if len(by_path) != len(rows) or set(by_path) != set(self.paths[kind]):
                raise ValueError("candidate feedback inventory is incomplete")
            if any(
                row["intent"] != intent or row["start_type"] != kind for row in rows
            ):
                raise ValueError("one training query has inconsistent intent metadata")
            rewards = np.asarray(
                [by_path[path]["reward"] for path in self.paths[kind]], dtype=np.float64
            )
            if not np.isfinite(rewards).all() or np.any((rewards < 0) | (rewards > 1)):
                raise ValueError("invalid terminal reward")
            unsupported += int(np.max(rewards) == 0)
            costs = np.asarray(
                [by_path[path]["execution"]["calls"] for path in self.paths[kind]]
            )
            batches.append(
                (
                    self.intents.index(intent),
                    self.path_features[kind],
                    rewards - call_penalty * costs,
                )
            )
        before = digest(self.weights.tobytes())
        mean, variance = np.zeros_like(self.weights), np.zeros_like(self.weights)
        for step in range(1, steps + 1):
            gradient = l2 * self.weights
            for intent, features, rewards in batches:
                logits = features @ self.weights[intent]
                probability = np.exp(logits - logits.max())
                probability /= probability.sum()
                advantage = rewards - probability @ rewards
                gradient[intent] -= ((probability * advantage) @ features) / len(
                    batches
                )
            mean = 0.9 * mean + 0.1 * gradient
            variance = 0.999 * variance + 0.001 * gradient * gradient
            self.weights -= (
                learning_rate
                * (mean / (1 - 0.9**step))
                / (np.sqrt(variance / (1 - 0.999**step)) + 1e-8)
            )
        self.steps += steps
        if not np.isfinite(self.weights).all():
            raise ValueError("graph optimizer produced nonfinite parameters")
        return {
            "optimizer": "Adam expected terminal reward over compatible paths",
            "queries": len(batches),
            "candidate_executions": len(feedback),
            "queries_with_no_positive_reward": unsupported,
            "steps": steps,
            "learning_rate": learning_rate,
            "call_penalty": call_penalty,
            "l2": l2,
            "parameter_bytes": self.parameter_bytes,
            "parameters_changed": before != digest(self.weights.tobytes()),
            "fit_seconds": time.perf_counter() - started,
            "all_candidate_execution_seconds": sum(
                row["execution"]["seconds"] for row in feedback
            ),
            "all_candidate_calls": sum(row["execution"]["calls"] for row in feedback),
            "target_paths_supplied": False,
            "operation_catalog_supplied": True,
        }

    def select(self, intent, start_type, *, maximum_hops=None):
        if intent not in self.intents or start_type not in self.paths:
            return None
        candidates = self.paths[start_type]
        scores = (
            self.path_features[start_type] @ self.weights[self.intents.index(intent)]
        )
        eligible = [
            i
            for i, path in enumerate(candidates)
            if maximum_hops is None or len(path) <= maximum_hops
        ]
        if not eligible:
            return None
        index = max(
            eligible,
            key=lambda i: (float(scores[i]), -len(candidates[i]), tuple(candidates[i])),
        )
        return candidates[index]

    def save(self, directory, *, source_commit, support_digest):
        if not re.fullmatch(r"[0-9a-f]{40}", source_commit) or not re.fullmatch(
            r"[0-9a-f]{64}", support_digest
        ):
            raise ValueError("invalid graph source binding")
        raw = self.weights.astype("<f8").tobytes()
        manifest = {
            "schema": "memory-cell-v3.learned-layout.v1",
            "specs": [asdict(x) for x in self.specs],
            "intents": list(self.intents),
            "start_types": list(self.start_types),
            "max_hops": self.max_hops,
            "seed": self.seed,
            "steps": self.steps,
            "edges": [list(edge) for edge in self.edges],
            "parameter_bytes": len(raw),
            "parameter_sha256": digest(raw),
            "source_commit": source_commit,
            "support_digest": support_digest,
        }
        manifest["manifest_sha256"] = digest(canonical(manifest))
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=False)
        (path / "weights.bin").write_bytes(raw)
        (path / "manifest.json").write_bytes(canonical(manifest) + b"\n")
        return manifest

    @classmethod
    def load(cls, directory, *, expected_manifest_digest=None):
        path = Path(directory)
        if (
            path.is_symlink()
            or not path.is_dir()
            or {x.name for x in path.iterdir()} != {"weights.bin", "manifest.json"}
        ):
            raise ValueError("invalid graph artifact directory")
        if any(
            (path / name).is_symlink() or not (path / name).is_file()
            for name in ("weights.bin", "manifest.json")
        ):
            raise ValueError("invalid graph artifact file")
        if (path / "manifest.json").stat().st_size > 1048576:
            raise ValueError("oversized graph manifest")
        manifest = strict_json((path / "manifest.json").read_bytes())
        required = {
            "schema",
            "specs",
            "intents",
            "start_types",
            "max_hops",
            "seed",
            "steps",
            "edges",
            "parameter_bytes",
            "parameter_sha256",
            "source_commit",
            "support_digest",
            "manifest_sha256",
        }
        if (
            not isinstance(manifest, dict)
            or set(manifest) != required
            or manifest["schema"] != "memory-cell-v3.learned-layout.v1"
        ):
            raise ValueError("unsupported graph artifact format")
        if (
            not isinstance(manifest["source_commit"], str)
            or not re.fullmatch(r"[0-9a-f]{40}", manifest["source_commit"])
            or not isinstance(manifest["support_digest"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", manifest["support_digest"])
            or type(manifest["seed"]) is not int
            or not 0 <= manifest["seed"] < 2**32
        ):
            raise ValueError("invalid graph source binding")
        body = {
            key: value for key, value in manifest.items() if key != "manifest_sha256"
        }
        if manifest["manifest_sha256"] != digest(canonical(body)) or (
            expected_manifest_digest is not None
            and manifest["manifest_sha256"] != expected_manifest_digest
        ):
            raise ValueError("graph manifest digest differs")
        model = cls(
            [OperationSpec(**x) for x in manifest["specs"]],
            manifest["intents"],
            manifest["start_types"],
            max_hops=manifest["max_hops"],
            seed=manifest["seed"],
        )
        if (
            manifest["edges"] != [list(x) for x in model.edges]
            or manifest["parameter_bytes"] != model.parameter_bytes
        ):
            raise ValueError("graph parameter inventory differs")
        if (path / "weights.bin").stat().st_size != model.parameter_bytes:
            raise ValueError("graph parameter size differs")
        raw = (path / "weights.bin").read_bytes()
        if digest(raw) != manifest["parameter_sha256"]:
            raise ValueError("graph parameter digest differs")
        model.weights = (
            np.frombuffer(raw, dtype="<f8").reshape(model.weights.shape).copy()
        )
        if (
            not np.isfinite(model.weights).all()
            or type(manifest["steps"]) is not int
            or manifest["steps"] < 0
        ):
            raise ValueError("invalid graph numeric state")
        model.steps = manifest["steps"]
        return model, manifest
