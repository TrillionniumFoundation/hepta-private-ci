"""AMCN read-only source/parameter lineage revalidation (SHADOW only).

A trained Head, split child or consolidated student is contaminated if any
contributing original source has been revoked, rewritten or is missing. Never
claim a small-model weight was unlearned: invalidate the ENTIRE artifact and its
transitive dependents pending independently authorized retraining/selection.
This is not a cognitive.store writer, Artifact Selector or complete deletion.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from amcn_core import digest, is_sha, require, shadow_disposition

MAX_ARTIFACTS = 4096
MAX_SOURCE_WITNESSES = 512
MAX_PARENTS = 32
PROFILE = "hepta.amcn.source-parameter-revocation.v1"
KINDS = frozenset({"semantic_head", "relation_router", "split_child",
                   "consolidation_student", "multimodal_connector"})


@dataclass(frozen=True)
class SourceWitness:
    evidence_id: str
    source_root: str
    scope: str
    generation: str
    revision: int
    content_sha256: str
    revoked: bool = False

    def __post_init__(self):
        require(all(isinstance(x, str) and 0 < len(x) <= 256 for x in
                    (self.evidence_id, self.source_root, self.scope,
                     self.generation)), "source identity")
        require(type(self.revision) is int and self.revision > 0,
                "positive source revision required")
        require(is_sha(self.content_sha256) and type(self.revoked) is bool,
                "source digest/revocation state")

    def immutable_key(self):
        return (self.evidence_id, self.source_root, self.scope,
                self.generation, self.revision, self.content_sha256)


@dataclass(frozen=True)
class CellGeneration:
    artifact_id: str
    kind: str
    scope: str
    generation: str
    stem_sha256: str
    head_sha256: str
    parent_artifacts: tuple[str, ...]
    source_witnesses: tuple[SourceWitness, ...]
    manifest_sha256: str

    def __post_init__(self):
        require(is_sha(self.artifact_id) and self.kind in KINDS
                and is_sha(self.stem_sha256) and is_sha(self.head_sha256),
                "artifact/model identity")
        require(all(isinstance(x, str) and 0 < len(x) <= 256
                    for x in (self.scope, self.generation)), "artifact scope")
        require(isinstance(self.parent_artifacts, tuple)
                and len(self.parent_artifacts) <= MAX_PARENTS
                and all(is_sha(x) for x in self.parent_artifacts)
                and len(set(self.parent_artifacts)) == len(self.parent_artifacts)
                and self.artifact_id not in self.parent_artifacts,
                "parents must be unique and noncyclic")
        require(isinstance(self.source_witnesses, tuple)
                and 1 <= len(self.source_witnesses) <= MAX_SOURCE_WITNESSES
                and all(isinstance(x, SourceWitness) and not x.revoked
                        and x.scope == self.scope
                        and x.generation == self.generation
                        for x in self.source_witnesses),
                "training witnesses must be complete, same-scope and live")
        ids = [s.evidence_id for s in self.source_witnesses]
        require(len(set(ids)) == len(ids), "duplicated source in training manifest")
        # Exact immutable manifest bytes, not a mutable pointer to a cell slot.
        require(self.manifest_sha256 == digest(self.manifest_fields()),
                "training manifest contents drift")

    def manifest_fields(self):
        return {
            "artifact_id": self.artifact_id, "kind": self.kind,
            "scope": self.scope, "generation": self.generation,
            "stem_sha256": self.stem_sha256, "head_sha256": self.head_sha256,
            "parents": list(self.parent_artifacts),
            "sources": sorted(x.immutable_key() for x in self.source_witnesses),
        }


def freeze_generation(artifact_id, kind, scope, generation, stem_sha256,
                      head_sha256, parents, sources):
    """Form a bound *research* artifact manifest; never activate it."""
    parents = tuple(parents)
    sources = tuple(sources)
    fields = {
        "artifact_id": artifact_id, "kind": kind, "scope": scope,
        "generation": generation, "stem_sha256": stem_sha256,
        "head_sha256": head_sha256, "parents": list(parents),
        "sources": sorted(x.immutable_key() for x in sources),
    }
    return CellGeneration(artifact_id, kind, scope, generation,
                          stem_sha256, head_sha256, parents, sources,
                          digest(fields))


def revocation_census(artifacts, current_sources, *, scope, generation,
                      externally_pinned_frontier_sha256, old_quarantined=()):
    """Fail closed on missing revision and all downstream artifact descendants.

    Operator pins only attest to bytes. This cannot authenticate independent
    ownership, same-principal host semantics or deletion from model weights.
    """
    require(isinstance(artifacts, (list, tuple))
            and 1 <= len(artifacts) <= MAX_ARTIFACTS,
            "bounded artifact graph required")
    require(isinstance(current_sources, (list, tuple))
            and len(current_sources) <= MAX_ARTIFACTS * MAX_SOURCE_WITNESSES,
            "bounded authoritative snapshot required")
    require(is_sha(externally_pinned_frontier_sha256),
            "current source frontier MUST have an out-of-band SHA pin")
    require(all(isinstance(x, CellGeneration) for x in artifacts)
            and len({x.artifact_id for x in artifacts}) == len(artifacts),
            "duplicated or malformed frozen artifacts")
    require(all(isinstance(s, SourceWitness)
                and s.scope == scope and s.generation == generation
                for s in current_sources), "foreign current source")
    require(len({s.evidence_id for s in current_sources}) == len(current_sources),
            "ambiguous current source revision")
    require(all(a.scope == scope and a.generation == generation
                for a in artifacts), "cross-scope artifact replay")
    current = {s.evidence_id: s for s in current_sources}
    frozen_frontier = digest(sorted(s.immutable_key() + (s.revoked,)
                                   for s in current_sources))
    require(frozen_frontier == externally_pinned_frontier_sha256,
            "source frontier changed after external pin")
    ids = {a.artifact_id: a for a in artifacts}
    require(isinstance(old_quarantined, (tuple, list, set, frozenset))
            and all(is_sha(s) and s in ids for s in old_quarantined),
            "old quarantines require complete existing artifact IDs")
    parents = defaultdict(list)
    for artifact in artifacts:
        for parent in artifact.parent_artifacts:
            require(parent in ids, "missing artifact ancestor")
            parents[parent].append(artifact.artifact_id)
            predecessor = ids[parent]
            require((predecessor.stem_sha256 == artifact.stem_sha256
                     and predecessor.scope == artifact.scope
                     and predecessor.generation == artifact.generation),
                    "cross-stem/cross-scope irreversible lineage")
            # Consolidation/split may add sources but cannot silently drop an
            # ancestor's material and still claim deletion provenance intact.
            inherited = {s.immutable_key() for s in predecessor.source_witnesses}
            descendants = {s.immutable_key() for s in artifact.source_witnesses}
            require(inherited <= descendants, "student dropped inherited source ancestry")
    # Do not implicitly trust order, and reject nonlocal cycles even if each
    # item has no self-parent.
    incoming = {a.artifact_id: len(a.parent_artifacts) for a in artifacts}
    queue = deque(sorted(x for x in incoming if incoming[x] == 0))
    visited = 0
    while queue:
        at = queue.popleft()
        visited += 1
        for descendant in sorted(parents[at]):
            incoming[descendant] -= 1
            if incoming[descendant] == 0:
                queue.append(descendant)
    require(visited == len(artifacts), "artifact graph contains lineage cycle")

    direct_reasons = {}
    for artifact in artifacts:
        reasons = []
        for witness in artifact.source_witnesses:
            live = current.get(witness.evidence_id)
            if live is None:
                reasons.append("missing")
            elif live.revoked:
                reasons.append("revoked")
            elif live.immutable_key() != witness.immutable_key():
                reasons.append("revised_or_replaced")
        if artifact.artifact_id in old_quarantined:
            reasons.append("previously_quarantined")
        if reasons:
            direct_reasons[artifact.artifact_id] = sorted(set(reasons))
    quarantined = set(direct_reasons)
    queue = deque(sorted(quarantined))
    while queue:
        for child in parents[queue.popleft()]:
            if child not in quarantined:
                quarantined.add(child)
                queue.append(child)
    quarantine_rows = []
    for aid in sorted(quarantined):
        direct = direct_reasons.get(aid)
        quarantine_rows.append({
            "artifact_id": aid, "reason": "source_invalid_or_previous_quarantine"
            if direct else "ancestor_source_invalid",
            "direct_reasons": direct or [],
        })
    return shadow_disposition(
        profile=PROFILE, source_frontier_sha256=frozen_frontier,
        artifact_manifest_sha256=digest(sorted(a.manifest_sha256 for a in artifacts)),
        artifact_count=len(artifacts), authoritative_source_count=len(current),
        directly_invalid=len(direct_reasons),
        quarantined_artifact_ids=sorted(quarantined),
        quarantine_reasons=quarantine_rows,
        unaffected_artifact_ids=sorted(set(ids) - quarantined),
        all_quarantines_persisted_by_owner=False,
        parameter_unlearning_performed=False,
        final_source_deletion_verified=False,
        safe_to_reactivate_previous_artifact=False,
        production_head_activation_allowed=False,
        independent_selector_accepted=False,
    )
