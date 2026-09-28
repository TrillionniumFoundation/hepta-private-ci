"""Single canonical status projection for ``control.engineering``.

The checked-in status records source facts and open gates without embedding a
self-referential commit. CI may bind the same projection to an exact commit/tree
and attach retained evidence digests. Status is descriptive and grants no
runtime, merge, deployment, promotion, release, or acceptance authority.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Mapping

from .capacity_policy import EngineeringCapacityDecision
from .control_plane import EngineeringError, semantic_digest
from .release_qualification import ReleaseQualificationDecision

_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_SCHEMA = "hepta.control-engineering-status.v1"


@dataclass(frozen=True)
class ControlEngineeringStatus:
    schema: str
    module: str
    source_commit: str
    source_tree: str
    source_bound: bool
    native_source_implemented: bool
    product_composed: bool
    exact_source_qualified: bool
    synthetic_merge_qualified: bool
    post_merge_main_qualified: bool
    quality_gate_qualified: bool
    independent_review_accepted: bool
    external_controls_verified: bool
    deployment_observed: bool
    rollback_rehearsed: bool
    operator_accepted: bool
    production_implementation: bool
    deployment_ready: bool
    release_evidence_complete: bool
    capacity_state: str
    implementation_blockers: tuple[str, ...]
    deployment_blockers: tuple[str, ...]
    evidence: tuple[tuple[str, str], ...]
    status_digest: str
    runtime_authority: bool = False
    merge_authority: bool = False
    deployment_authority: bool = False
    promotion_authority: bool = False
    release_authority: bool = False


def _checked_optional_sha(value: str, label: str) -> str:
    if value == "":
        return value
    if not isinstance(value, str) or _SHA1.fullmatch(value) is None:
        raise EngineeringError("invalid_status_" + label)
    return value


def _normalized_evidence(values: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    if not isinstance(values, Mapping):
        raise EngineeringError("status_evidence_required")
    rows: list[tuple[str, str]] = []
    for key, value in values.items():
        if not isinstance(key, str) or not key or not isinstance(value, str):
            raise EngineeringError("status_evidence_invalid")
        if value and (
            len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise EngineeringError("status_evidence_invalid")
        rows.append((key, value))
    return tuple(sorted(rows))


def build_status(
    release: ReleaseQualificationDecision,
    capacity: EngineeringCapacityDecision,
    *,
    source_commit: str = "",
    source_tree: str = "",
    source_bound: bool = False,
    native_source_implemented: bool = True,
    product_composed: bool = True,
    exact_source_qualified: bool = False,
    synthetic_merge_qualified: bool = False,
    post_merge_main_qualified: bool = False,
    quality_gate_qualified: bool = False,
    independent_review_accepted: bool = False,
    external_controls_verified: bool = False,
    deployment_observed: bool = False,
    rollback_rehearsed: bool = False,
    operator_accepted: bool = False,
    evidence: Mapping[str, str] | None = None,
) -> ControlEngineeringStatus:
    if not isinstance(release, ReleaseQualificationDecision):
        raise EngineeringError("status_release_decision_required")
    if not isinstance(capacity, EngineeringCapacityDecision):
        raise EngineeringError("status_capacity_decision_required")
    source_commit = _checked_optional_sha(source_commit, "source_commit")
    source_tree = _checked_optional_sha(source_tree, "source_tree")
    if bool(source_commit) != bool(source_tree):
        raise EngineeringError("status_source_identity_incomplete")
    if source_bound is True and not source_commit:
        raise EngineeringError("status_source_binding_missing")
    evidence_rows = _normalized_evidence({} if evidence is None else evidence)
    implementation_ready = (
        native_source_implemented is True
        and product_composed is True
        and exact_source_qualified is True
        and synthetic_merge_qualified is True
        and post_merge_main_qualified is True
        and quality_gate_qualified is True
        and release.repository_implementation_qualified is True
        and not capacity.blockers
    )
    deployment_ready = (
        implementation_ready
        and independent_review_accepted is True
        and external_controls_verified is True
        and deployment_observed is True
        and rollback_rehearsed is True
        and operator_accepted is True
        and release.deployment_qualified is True
    )
    body: dict[str, object] = {
        "schema": _SCHEMA,
        "module": "control.engineering",
        "sourceCommit": source_commit,
        "sourceTree": source_tree,
        "sourceBound": source_bound,
        "nativeSourceImplemented": native_source_implemented,
        "productComposed": product_composed,
        "exactSourceQualified": exact_source_qualified,
        "syntheticMergeQualified": synthetic_merge_qualified,
        "postMergeMainQualified": post_merge_main_qualified,
        "qualityGateQualified": quality_gate_qualified,
        "independentReviewAccepted": independent_review_accepted,
        "externalControlsVerified": external_controls_verified,
        "deploymentObserved": deployment_observed,
        "rollbackRehearsed": rollback_rehearsed,
        "operatorAccepted": operator_accepted,
        "productionImplementation": implementation_ready,
        "deploymentReady": deployment_ready,
        "releaseEvidenceComplete": release.release_evidence_complete,
        "capacityState": capacity.state,
        "implementationBlockers": release.implementation_blockers,
        "deploymentBlockers": release.deployment_blockers,
        "evidence": evidence_rows,
        "runtimeAuthority": False,
        "mergeAuthority": False,
        "deploymentAuthority": False,
        "promotionAuthority": False,
        "releaseAuthority": False,
    }
    return ControlEngineeringStatus(
        _SCHEMA,
        "control.engineering",
        source_commit,
        source_tree,
        source_bound,
        native_source_implemented,
        product_composed,
        exact_source_qualified,
        synthetic_merge_qualified,
        post_merge_main_qualified,
        quality_gate_qualified,
        independent_review_accepted,
        external_controls_verified,
        deployment_observed,
        rollback_rehearsed,
        operator_accepted,
        implementation_ready,
        deployment_ready,
        release.release_evidence_complete,
        capacity.state,
        release.implementation_blockers,
        release.deployment_blockers,
        evidence_rows,
        semantic_digest(body),
    )


def status_json(status: ControlEngineeringStatus) -> str:
    if not isinstance(status, ControlEngineeringStatus):
        raise EngineeringError("control_engineering_status_required")
    return json.dumps(asdict(status), indent=2, sort_keys=True) + "\n"


def write_status(path: str | Path, status: ControlEngineeringStatus) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=target.name + ".",
        dir=str(target.parent),
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(status_json(status))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def verify_status_digest(status: ControlEngineeringStatus) -> None:
    value = asdict(status)
    supplied = value.pop("status_digest")
    body = {
        "schema": value.pop("schema"),
        "module": value.pop("module"),
        "sourceCommit": value.pop("source_commit"),
        "sourceTree": value.pop("source_tree"),
        "sourceBound": value.pop("source_bound"),
        "nativeSourceImplemented": value.pop("native_source_implemented"),
        "productComposed": value.pop("product_composed"),
        "exactSourceQualified": value.pop("exact_source_qualified"),
        "syntheticMergeQualified": value.pop("synthetic_merge_qualified"),
        "postMergeMainQualified": value.pop("post_merge_main_qualified"),
        "qualityGateQualified": value.pop("quality_gate_qualified"),
        "independentReviewAccepted": value.pop("independent_review_accepted"),
        "externalControlsVerified": value.pop("external_controls_verified"),
        "deploymentObserved": value.pop("deployment_observed"),
        "rollbackRehearsed": value.pop("rollback_rehearsed"),
        "operatorAccepted": value.pop("operator_accepted"),
        "productionImplementation": value.pop("production_implementation"),
        "deploymentReady": value.pop("deployment_ready"),
        "releaseEvidenceComplete": value.pop("release_evidence_complete"),
        "capacityState": value.pop("capacity_state"),
        "implementationBlockers": tuple(value.pop("implementation_blockers")),
        "deploymentBlockers": tuple(value.pop("deployment_blockers")),
        "evidence": tuple(tuple(item) for item in value.pop("evidence")),
        "runtimeAuthority": value.pop("runtime_authority"),
        "mergeAuthority": value.pop("merge_authority"),
        "deploymentAuthority": value.pop("deployment_authority"),
        "promotionAuthority": value.pop("promotion_authority"),
        "releaseAuthority": value.pop("release_authority"),
    }
    if value or semantic_digest(body) != supplied:
        raise EngineeringError("control_engineering_status_digest_mismatch")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    raw = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise EngineeringError("status_input_invalid")
    status = ControlEngineeringStatus(**raw)
    verify_status_digest(status)
    write_status(args.output, status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
