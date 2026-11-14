"""Shared semantic inference through the durable experimental Cell owner.

Persistent state, retrieval view and total budget belong to CellOwner. Only the
small local head is copied into each invocation; the pool retains the shared
provider. Retrieval results enter an encoder only when explicitly put in inputs.
"""

from dataclasses import replace

import numpy as np

from .bundle import Bundle, validate_local_update
from .lifecycle import CellError, ComponentIdentity, StepResult
from .semantic import SemanticCell, SemanticTrainingError, _digest


IMPLEMENTATION = "shared-semantic-v1"
STATE_KEYS = {"cell_id", "bundle_digest", "partition", "steps", "observations"}


def semantic_components(cell):
    """Bind the exact provider, local shape/objective and owner-state semantics."""
    binding, head = cell.binding, cell.head
    return dict(
        base=binding.base,
        heads=head.digest,
        composition=_digest(
            "semantic-composition-v1", binding.model, *(a.shape for a in head.arrays)
        ),
        encoder=binding.encoder,
        tokenizer=binding.tokenizer,
        normalizer=_digest("normalizer-is-part-of-the-bound-encoder-v1"),
        calibration=_digest("no-post-head-calibration-v1"),
        numeric_profile=binding.numeric_profile,
        output_schema=_digest(
            "semantic-output-v1",
            cell.objective.kind,
            cell.objective.output_dim,
            cell.objective.target_name,
        ),
        state_schema=_digest("semantic-owner-state-v1", *sorted(STATE_KEYS)),
        state_semantics=_digest("owner-bound-counters-reset-on-bundle-change-v1"),
        organ_adapter=binding.domain,
        cell_adapter=None,
    )


def semantic_bundle(cell, artifact_id, generation=1):
    bundle = Bundle(artifact_id, generation, semantic_components(cell))
    bundle.canonical_bytes()
    return bundle


class SemanticComponent:
    """An immutable inference configuration and explicit candidate producer."""

    def __init__(self, pool, cell, bundle):
        if not isinstance(bundle, Bundle) or bundle.components != semantic_components(
            cell
        ):
            raise CellError(
                "bundle does not bind this semantic provider/head/objective"
            )
        pool._resolve(cell)
        self._pool = pool
        self._cell = SemanticCell(
            cell.cell_id, cell.binding, cell.head, cell.objective, cell.budget
        )
        self._bundle = Bundle(**bundle.record())
        self._identity = ComponentIdentity(IMPLEMENTATION, self._bundle.digest())

    @property
    def identity(self):
        if (
            self._bundle.components != semantic_components(self._cell)
            or self._bundle.digest() != self._identity.bundle_digest
        ):
            raise CellError("semantic component changed after admission")
        return self._identity

    @property
    def bundle(self):
        return Bundle(**self._bundle.record())

    def initial_state(self):
        return dict(
            cell_id=self._cell.cell_id,
            bundle_digest=self.identity.bundle_digest,
            partition=None,
            steps=0,
            observations=0,
        )

    def _invocation_cell(self, budget=None):
        # Persistent charging is performed by the owner. This budget bounds one
        # invocation's input/local arrays, while provider resource limits remain
        # the provider host's responsibility.
        local = self._cell.budget
        if budget is not None:
            local = replace(
                local,
                max_input_bytes=min(local.max_input_bytes, budget.max_input_bytes),
                max_total_items=local.max_items,
            )
        return SemanticCell(
            self._cell.cell_id,
            self._cell.binding,
            self._cell.head,
            self._cell.objective,
            local,
        )

    def step(self, payload, state, context):
        identity = self.identity
        if (
            context.identity != identity
            or context.partition.cell_id != self._cell.cell_id
        ):
            raise CellError("semantic component identity or owner cell differs")
        if (
            not isinstance(state, dict)
            or set(state) != STATE_KEYS
            or state["cell_id"] != self._cell.cell_id
            or state["bundle_digest"] != identity.bundle_digest
            or state["partition"] not in (None, context.partition.digest)
            or any(
                type(state[k]) is not int or not 0 <= state[k] < 2**63
                for k in ("steps", "observations")
            )
        ):
            raise CellError("state belongs to another owner/bundle or is malformed")
        if (
            not isinstance(payload, dict)
            or set(payload) != {"inputs"}
            or not isinstance(payload["inputs"], list)
        ):
            raise CellError("semantic input must contain one explicit inputs list")
        if not 1 <= len(payload["inputs"]) <= self._cell.budget.max_items:
            raise CellError("semantic input count exceeds the local envelope")
        inputs = [
            np.asarray(value, dtype=np.float64) if isinstance(value, list) else value
            for value in payload["inputs"]
        ]
        cell = self._invocation_cell(context.budget)
        backend, _, _, input_bytes, _ = self._pool._prepare(cell, inputs)
        # These units measure admitted input bytes and local feature/head slots.
        # They do not estimate opaque LLM FLOPs or remote-server memory.
        units = input_bytes + len(inputs) * (
            backend.feature_dim + sum(a.size for a in cell.head.arrays)
        )
        if units > context.budget.max_work_units:
            raise CellError("semantic local work exceeds the reserved owner budget")
        outputs, measurements = self._pool.predict_batch([(cell, inputs)])
        measured = dict(
            measurements[0],
            binding=list(measurements[0]["binding"]),
            work_unit_scope="input bytes plus local feature/head slots; excludes encoder FLOPs",
        )
        new_state = dict(
            state,
            partition=context.partition.digest,
            steps=state["steps"] + 1,
            observations=state["observations"] + len(inputs),
        )
        return StepResult(
            dict(logits=outputs[0].tolist(), measurement=measured),
            new_state,
            int(units),
        )

    def propose(
        self,
        inputs,
        targets,
        *,
        artifact_id,
        evaluation_profile,
        steps=1,
        learning_rate=0.01,
    ):
        """Return (candidate component, measured training candidate); never adopt."""
        source = self.bundle
        try:
            candidate = self._pool.train_candidate(
                self._invocation_cell(),
                inputs,
                targets,
                steps=steps,
                learning_rate=learning_rate,
            )
        except SemanticTrainingError as error:
            error.receipt["source_bundle_digest"] = source.digest()
            raise
        if (
            candidate.source_digest != self._cell.digest
            or candidate.binding != self._cell.binding
        ):
            raise CellError("training candidate no longer names the source component")
        target = SemanticCell(
            candidate.cell_id,
            candidate.binding,
            candidate.head,
            candidate.objective,
            self._cell.budget,
        )
        bundle = source.successor(
            artifact_id,
            semantic_components(target),
            candidate.dataset_digest,
            _digest(
                "local-head-sgd-v1", steps, learning_rate, self._cell.objective.kind
            ),
            evaluation_profile,
        )
        validate_local_update("shared_semantic", source, bundle)
        candidate.training_receipt.update(
            source_bundle_digest=source.digest(),
            candidate_bundle_digest=bundle.digest(),
        )
        return SemanticComponent(self._pool, target, bundle), candidate
