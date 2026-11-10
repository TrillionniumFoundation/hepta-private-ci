"""Experimental 1+2+7 Cell enrollment and update-scope gate.

This gate checks declared identities, frozen component pins, learning scope and
read-only candidate evidence. It neither loads model bytes nor authenticates
host evidence, performs a native cutover, or authorizes an effect or adoption.
Native Bundle/owner/evaluation checks are always additional obligations.
"""

from dataclasses import dataclass, fields
import math
import re


LINEAGES = frozenset({"PERC", "MEM", "PRED", "CTRL", "VERIFY", "ACT", "LEARN"})
KERNELS = frozenset({"shared_semantic", "stateful_temporal", "deterministic"})
SCOPES = {
    "shared_semantic": frozenset({"heads", "cell_adapter_and_heads"}),
    "stateful_temporal": frozenset({"kernel_and_heads"}),
    "deterministic": frozenset(),
}
ALLOWED_CHANGES = {
    "heads": frozenset({"heads"}),
    "cell_adapter_and_heads": frozenset({"heads", "cell_adapter"}),
    "kernel_and_heads": frozenset({"base", "heads"}),
}
COST_AXES = frozenset({
    "training_cpu_seconds", "evaluation_cpu_seconds", "inference_cpu_seconds",
    "recovery_cpu_seconds", "accelerator_seconds", "resident_byte_seconds",
    "transport_bytes", "provider_charges",
})
_TOKEN = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")


class LineagePolicyError(ValueError):
    """A proposed cell registration or candidate violates the frozen scope."""


def _token(value, name):
    if type(value) is not str or not _TOKEN.fullmatch(value):
        raise LineagePolicyError(f"invalid {name} stable identifier")


def _digest(value, name):
    if type(value) is not str or not _HEX.fullmatch(value) or value == "0" * 64:
        raise LineagePolicyError(f"invalid {name} SHA256")


@dataclass(frozen=True)
class ComponentPins:
    """One complete existing CellBundleComponentsV1 field inventory.

    This records *claims* about actual artifacts. Full native bundle decoding,
    bytes, numeric compatibility and any ABI signature are not inferred here.
    """

    base: str
    heads: str
    composition: str
    encoder: str
    tokenizer: str
    normalizer: str
    calibration: str
    numeric_profile: str
    output_schema: str
    state_schema: str
    state_semantics: str
    organ_adapter: str | None = None
    cell_adapter: str | None = None

    def __post_init__(self):
        for f in fields(self):
            value = getattr(self, f.name)
            if value is not None:
                _digest(value, f.name)
            elif f.name not in {"organ_adapter", "cell_adapter"}:
                raise LineagePolicyError(f"missing required component: {f.name}")

    def changed(self, other):
        if not isinstance(other, ComponentPins):
            raise LineagePolicyError("candidate has no complete component inventory")
        return frozenset(
            f.name for f in fields(self)
            if getattr(self, f.name) != getattr(other, f.name)
        )

    @property
    def shared_feature_identity(self):
        return (
            self.base, self.organ_adapter, self.encoder, self.tokenizer,
            self.normalizer, self.composition, self.numeric_profile,
        )


@dataclass(frozen=True)
class CellEnrollment:
    lineage: str
    kernel: str
    principal_id: str
    agent_id: str
    cell_id: str
    run_id: str
    state_owner: str
    bundle_digest: str
    generation: int
    components: ComponentPins
    data_scope: str
    feature_share_group: str | None = None
    feature_abi: str | None = None
    trainable_scope: str | None = None
    max_training_steps: int = 0
    evaluation_profile: str | None = None
    update_rule: str | None = None

    def __post_init__(self):
        if self.lineage not in LINEAGES or self.kernel not in KERNELS:
            raise LineagePolicyError("unknown lineage or kernel")
        for key in ("principal_id", "agent_id", "cell_id", "run_id", "state_owner", "data_scope"):
            _token(getattr(self, key), key)
        _digest(self.bundle_digest, "bundle")
        if type(self.generation) is not int or not 1 <= self.generation < 2**64:
            raise LineagePolicyError("invalid positive generation")
        if not isinstance(self.components, ComponentPins):
            raise LineagePolicyError("complete component pins required")
        if self.feature_share_group is not None:
            _token(self.feature_share_group, "feature_share_group")
            if self.kernel != "shared_semantic":
                raise LineagePolicyError("only semantic features may share this frozen pool")
            # A shared runtime feature pool needs an explicit frozen interface
            # identity in addition to matching model/encoder/numeric pins.
            _digest(self.feature_abi, "feature_abi")
        elif self.feature_abi is not None:
            raise LineagePolicyError("unshared Cell cannot claim a pooled feature ABI")
        if self.trainable_scope not in SCOPES[self.kernel] and self.trainable_scope is not None:
            raise LineagePolicyError("kernel cannot train the requested fields")
        if self.lineage == "LEARN" and (
            self.kernel != "deterministic" or self.trainable_scope is not None
        ):
            raise LineagePolicyError("LEARN orchestrates original owners; not another optimizer")
        if self.trainable_scope is None:
            if (
                type(self.max_training_steps) is not int
                or self.max_training_steps != 0
                or self.evaluation_profile is not None
                or self.update_rule is not None
            ):
                raise LineagePolicyError("frozen cell cannot carry a trainable policy")
        else:
            if (
                type(self.max_training_steps) is not int
                or not 1 <= self.max_training_steps <= 1024
            ):
                raise LineagePolicyError("trainable cell needs a bounded step budget")
            _digest(self.evaluation_profile, "evaluation_profile")
            _digest(self.update_rule, "update_rule")

    @property
    def partition(self):
        return (self.principal_id, self.agent_id, self.cell_id, self.run_id)


@dataclass(frozen=True)
class CellRoster:
    """A frozen experimental enrollment roster, not a production registry."""

    cells: tuple[CellEnrollment, ...]
    max_trainable_instances: int = 3

    def __post_init__(self):
        if (
            type(self.max_trainable_instances) is not int
            or not 1 <= self.max_trainable_instances <= 3
            or type(self.cells) is not tuple
            or not 1 <= len(self.cells) <= 128
            or not all(isinstance(c, CellEnrollment) for c in self.cells)
        ):
            raise LineagePolicyError("invalid bounded experimental roster")
        if {c.lineage for c in self.cells} != LINEAGES:
            raise LineagePolicyError("all seven responsibilities must be represented")
        if len({c.partition for c in self.cells}) != len(self.cells):
            raise LineagePolicyError("duplicate Cell state partition")
        if sum(c.trainable_scope is not None for c in self.cells) > self.max_trainable_instances:
            raise LineagePolicyError("too many simultaneously trainable instances")
        groups = {}
        for cell in self.cells:
            if cell.feature_share_group is not None:
                # Shared model residency is not cross-principal/agent authorization.
                identity = (
                    cell.principal_id, cell.agent_id, cell.state_owner, cell.data_scope,
                    cell.components.shared_feature_identity, cell.feature_abi,
                )
                old = groups.setdefault(cell.feature_share_group, identity)
                if old != identity:
                    raise LineagePolicyError("feature group mixes owner or frozen bindings")

    def cell(self, partition):
        matches = [c for c in self.cells if c.partition == partition]
        if len(matches) != 1:
            raise LineagePolicyError("unknown or ambiguous Cell partition")
        return matches[0]


@dataclass(frozen=True)
class UpdateEvidence:
    partition: tuple[str, str, str, str]
    source_bundle: str
    candidate_bundle: str
    candidate_generation: int
    candidate_components: ComponentPins
    training_source: str
    dataset_digest: str
    update_rule: str
    evaluation_profile: str
    evaluation_receipt_digest: str | None
    completed_training_steps: int
    costs: dict[str, float | int | None]


@dataclass(frozen=True)
class UpdateReview:
    status: str
    reasons: tuple[str, ...]
    native_validation_required: bool = True
    independent_evaluator_required: bool = True
    adoption_authorized: bool = False


def review_update(roster: CellRoster, evidence: UpdateEvidence) -> UpdateReview:
    """Fail closed on semantic scope; never confer installation authority.

    Complete declared costs produce REVIEW_ONLY, not ACCEPTED/Adopt. Missing
    measured axes produce HOLD. The original evaluator must authenticate its own
    execution; a digest here cannot establish that provenance.
    """
    if not isinstance(evidence, UpdateEvidence):
        raise LineagePolicyError("invalid update evidence type")
    cell = roster.cell(evidence.partition)
    if cell.trainable_scope is None:
        raise LineagePolicyError("frozen cell cannot request a neural update")
    for key in (
        "source_bundle", "candidate_bundle", "training_source", "dataset_digest",
        "update_rule", "evaluation_profile",
    ):
        _digest(getattr(evidence, key), key)
    if (
        evidence.source_bundle != cell.bundle_digest
        or evidence.training_source != evidence.source_bundle
        or evidence.candidate_bundle == evidence.source_bundle
        or evidence.update_rule != cell.update_rule
        or evidence.evaluation_profile != cell.evaluation_profile
        or type(evidence.candidate_generation) is not int
        or not 1 <= evidence.candidate_generation < 2**64
        or evidence.candidate_generation != cell.generation + 1
    ):
        raise LineagePolicyError("candidate violates frozen lineage or evaluation binding")
    if (
        type(evidence.completed_training_steps) is not int
        or not 1 <= evidence.completed_training_steps <= cell.max_training_steps
    ):
        raise LineagePolicyError("actual training steps exceed the frozen budget")
    changed = cell.components.changed(evidence.candidate_components)
    if not changed or not changed <= ALLOWED_CHANGES[cell.trainable_scope]:
        raise LineagePolicyError("candidate changes frozen or absent parameter fields")
    if type(evidence.costs) is not dict or set(evidence.costs) != COST_AXES:
        raise LineagePolicyError("all eight real-cost axes must be retained")
    missing = []
    for axis in sorted(COST_AXES):
        value = evidence.costs[axis]
        if value is None:
            missing.append(axis)
        elif type(value) not in (float, int) or not math.isfinite(value) or value < 0:
            raise LineagePolicyError(f"invalid measured cost: {axis}")
    if evidence.evaluation_receipt_digest is None:
        missing.append("original_signed_evaluation")
    else:
        _digest(evidence.evaluation_receipt_digest, "evaluation_receipt")
    return UpdateReview(
        status="HOLD" if missing else "REVIEW_ONLY",
        reasons=tuple(sorted(missing)) if missing else (
            "native original-bundle byte validation pending",
            "independent signed evaluator provenance pending",
            "old-task retention and measured net-benefit pending",
        ),
    )
