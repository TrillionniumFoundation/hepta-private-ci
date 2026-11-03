"""Research-only artifact lineage, revocation and structural selection.

This registry does not train tensors or prove erasure. Clean retraining must be
performed by the caller from an untainted initialization and source set. Owner
source validity and real evaluation observations remain external inputs.
"""

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
import os
from pathlib import Path
from types import MappingProxyType


class LifecycleError(ValueError):
    pass


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    scope: str
    parameter_digest: str
    sources: tuple[str, ...]
    parents: tuple[str, ...] = ()
    generation: int = 1

    def __post_init__(self):
        if not self.artifact_id or not self.scope or self.generation < 1:
            raise LifecycleError("invalid artifact identity")
        if len(self.parameter_digest) != 64 or any(
            c not in "0123456789abcdef" for c in self.parameter_digest
        ):
            raise LifecycleError("invalid parameter digest")
        for group in (self.sources, self.parents):
            if (
                not isinstance(group, tuple)
                or group != tuple(sorted(set(group)))
                or any(not x for x in group)
            ):
                raise LifecycleError("lineage must contain sorted unique identifiers")


@dataclass(frozen=True)
class Selection:
    artifact_id: str
    revision: int


class MemoryRegistry:
    """Single-owner research state; immutable records and CAS-selected slots."""

    def __init__(self):
        self._records = {}
        self._selections = {}
        self._revoked_sources = set()
        self._corrections = {}
        self._effective_sources = {}

    @property
    def records(self):
        return MappingProxyType(self._records)

    @property
    def selections(self):
        return MappingProxyType(self._selections)

    @property
    def revoked_sources(self):
        return frozenset(self._revoked_sources)

    @property
    def corrections(self):
        return MappingProxyType(self._corrections)

    def register(self, record: ArtifactRecord):
        existing = self.records.get(record.artifact_id)
        if existing is not None:
            if existing != record:
                raise LifecycleError("artifact identity conflict")
            if not self.usable(record.artifact_id):
                raise LifecycleError("artifact revoked")
            return
        sources = set(record.sources)
        parent_generations = []
        for parent_id in record.parents:
            if parent_id not in self.records or not self.usable(parent_id):
                raise LifecycleError("unknown or revoked parent")
            parent = self.records[parent_id]
            if parent.scope != record.scope:
                raise LifecycleError("parent scope mismatch")
            sources.update(self._effective_sources[parent_id])
            parent_generations.append(parent.generation)
        expected = max(parent_generations, default=0) + 1
        if record.generation != expected:
            raise LifecycleError("artifact generation is not exact successor")
        if sources & self.revoked_sources:
            raise LifecycleError("revoked training source")
        self._records[record.artifact_id] = record
        self._effective_sources[record.artifact_id] = frozenset(sources)

    def usable(self, artifact_id):
        return artifact_id in self.records and not (
            self._effective_sources[artifact_id] & self.revoked_sources
        )

    def adopt(self, slot, artifact_id, *, expected_revision):
        previous = self.selections.get(slot)
        actual = previous.revision if previous else 0
        if actual != expected_revision:
            raise LifecycleError("selection CAS conflict")
        if not self.usable(artifact_id):
            raise LifecycleError("artifact unavailable")
        if (
            previous
            and self.records[previous.artifact_id].scope
            != self.records[artifact_id].scope
        ):
            raise LifecycleError("slot scope mismatch")
        successor = Selection(artifact_id, actual + 1)
        self._selections[slot] = successor
        return successor

    def resolve(self, slot, *, scope):
        selected = self.selections.get(slot)
        if selected is None or not self.usable(selected.artifact_id):
            raise LifecycleError("selected artifact unavailable")
        record = self.records[selected.artifact_id]
        if record.scope != scope:
            raise LifecycleError("read scope mismatch")
        return record

    def revoke_source(self, source_id):
        if not isinstance(source_id, str) or not source_id:
            raise LifecycleError("invalid source revision")
        self._revoked_sources.add(source_id)
        return tuple(sorted(key for key in self.records if not self.usable(key)))

    def correct_source(self, old_revision, new_revision):
        if (
            not new_revision
            or old_revision == new_revision
            or new_revision in self.revoked_sources
        ):
            raise LifecycleError("invalid correction revision")
        if (
            old_revision in self.corrections
            and self.corrections[old_revision] != new_revision
        ):
            raise LifecycleError("correction identity conflict")
        self._corrections[old_revision] = new_revision
        return self.revoke_source(old_revision)

    def save(self, path):
        payload = {
            "schema": "hepta.memory-cell-research.registry.v1",
            "records": [
                asdict(r)
                for r in sorted(
                    self.records.values(), key=lambda r: (r.generation, r.artifact_id)
                )
            ],
            "selections": {
                key: asdict(value) for key, value in sorted(self.selections.items())
            },
            "revoked_sources": sorted(self.revoked_sources),
            "corrections": dict(self.corrections),
        }
        envelope = {
            "payload": payload,
            "sha256": sha256(_canonical(payload)).hexdigest(),
        }
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        with temporary.open("wb") as handle:
            handle.write(_canonical(envelope))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    @classmethod
    def load(cls, path, *, current_revoked_sources: Iterable[str]):
        """Reopen with the owner's current frontier, including on backup restore."""
        try:
            envelope = json.loads(Path(path).read_text())
            if set(envelope) != {"payload", "sha256"}:
                raise LifecycleError("invalid registry envelope")
            payload = envelope["payload"]
            if sha256(_canonical(payload)).hexdigest() != envelope["sha256"]:
                raise LifecycleError("registry digest mismatch")
            if set(payload) != {
                "schema",
                "records",
                "selections",
                "revoked_sources",
                "corrections",
            }:
                raise LifecycleError("invalid registry fields")
            if payload["schema"] != "hepta.memory-cell-research.registry.v1":
                raise LifecycleError("unknown registry schema")
            result = cls()
            for raw in payload["records"]:
                result.register(
                    ArtifactRecord(
                        **{
                            **raw,
                            "sources": tuple(raw["sources"]),
                            "parents": tuple(raw["parents"]),
                        }
                    )
                )
            for slot, raw in payload["selections"].items():
                selection = Selection(**raw)
                if (
                    selection.artifact_id not in result.records
                    or not isinstance(selection.revision, int)
                    or selection.revision < 1
                ):
                    raise LifecycleError("invalid persisted selection")
                result._selections[slot] = selection
            for source in set(payload["revoked_sources"]) | set(
                current_revoked_sources
            ):
                result.revoke_source(source)
            result._corrections = payload["corrections"]
            for old, new in result.corrections.items():
                if old not in result.revoked_sources or not new or new == old:
                    raise LifecycleError("invalid persisted correction")
            return result
        except (TypeError, KeyError, json.JSONDecodeError) as error:
            raise LifecycleError("malformed registry") from error


@dataclass(frozen=True)
class SplitPlan:
    children: tuple[tuple[str, tuple[str, ...]], ...]
    selection_ids: tuple[str, ...]
    test_ids: tuple[str, ...]


def plan_split(training_ids, selection_ids, test_ids, assignments):
    """Partition training examples only; selection and future tests stay separate."""
    partitions = [tuple(training_ids), tuple(selection_ids), tuple(test_ids)]
    groups = [set(values) for values in partitions]
    if any(len(group) != len(values) for group, values in zip(groups, partitions)):
        raise LifecycleError("duplicate experiment example")
    if any(not group for group in groups) or any(
        groups[i] & groups[j] for i in range(3) for j in range(i)
    ):
        raise LifecycleError("empty or overlapping experiment partitions")
    if set(assignments) != groups[0] or len(set(assignments.values())) < 2:
        raise LifecycleError(
            "split must assign every training example to at least two children"
        )
    if any(not isinstance(child, str) or not child for child in assignments.values()):
        raise LifecycleError("invalid child identity")
    children = tuple(
        (
            name,
            tuple(sorted(key for key, group in assignments.items() if group == name)),
        )
        for name in sorted(set(assignments.values()))
    )
    return SplitPlan(children, tuple(sorted(groups[1])), tuple(sorted(groups[2])))


@dataclass(frozen=True)
class CandidateMetrics:
    candidate_id: str
    operation: str
    risk: float
    retained_risk: float
    parameter_bytes: int
    training_seconds: float
    read_seconds: float


@dataclass(frozen=True)
class StructureDecision:
    selected_id: str
    accepted: bool
    estimated_gain: float
    rejected: tuple[tuple[str, str], ...]


def choose_structure(
    candidates,
    *,
    byte_price=0.0,
    training_price=0.0,
    read_price=0.0,
    max_retention_regression=0.0,
    min_gain=0.0,
):
    """Select from measured selection-window results, never manufacture efficacy.

    Risk, retention and cost observations must be supplied by the experiment runner.
    This function makes no confidence-interval or production acceptance claim.
    """
    candidates = tuple(candidates)
    coefficients = (
        byte_price,
        training_price,
        read_price,
        max_retention_regression,
        min_gain,
    )
    if any(not math.isfinite(v) or v < 0 for v in coefficients):
        raise LifecycleError("invalid selection coefficients")
    if len({c.candidate_id for c in candidates}) != len(candidates):
        raise LifecycleError("duplicate candidate")
    baselines = [c for c in candidates if c.operation == "no_change"]
    if len(baselines) != 1:
        raise LifecycleError("exactly one no-change candidate required")
    for c in candidates:
        if c.operation not in {"no_change", "split", "merge", "grow", "update"}:
            raise LifecycleError("unknown structure operation")
        values = (
            c.risk,
            c.retained_risk,
            c.parameter_bytes,
            c.training_seconds,
            c.read_seconds,
        )
        if any(not math.isfinite(v) or v < 0 for v in values):
            raise LifecycleError("invalid candidate observations")
    baseline = baselines[0]

    def cost(c):
        return (
            c.risk
            + byte_price * c.parameter_bytes
            + training_price * c.training_seconds
            + read_price * c.read_seconds
        )

    best, gain, rejected = baseline, 0.0, []
    for candidate in sorted(candidates, key=lambda c: c.candidate_id):
        if candidate == baseline:
            continue
        improvement = cost(baseline) - cost(candidate)
        if candidate.retained_risk > baseline.retained_risk + max_retention_regression:
            rejected.append((candidate.candidate_id, "retention_regression"))
        elif improvement <= min_gain:
            rejected.append((candidate.candidate_id, "insufficient_net_gain"))
        elif improvement > gain:
            best, gain = candidate, improvement
    return StructureDecision(best.candidate_id, best != baseline, gain, tuple(rejected))
