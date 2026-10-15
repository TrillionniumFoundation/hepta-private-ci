"""Research-only shared-Stem weight/fanout accounting; no runtime or efficacy claim.

Counts model weights and *logical* encoder forward invocations under an exact
scope+generation+source+preprocessing cache identity. It does not measure
latency, training, activations, IO, energy, optimizer state or model quality.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Sequence

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_SCOPE = re.compile(r"[A-Za-z0-9_.:/-]{1,96}\Z")
_MAX_CELLS = 4096


@dataclass(frozen=True)
class FeatureIdentity:
    """Exact same input is reusable only in the SAME authorization scope.

    Values are caller-supplied assertions, not cryptographic attestations.
    The original owner must validate source, final-use and revocation first.
    """

    scope: str
    generation: int
    stem_sha256: str
    tokenizer_sha256: str
    normalizer_sha256: str
    source_sha256: str
    options_sha256: str

    def validate(self) -> None:
        if type(self.scope) is not str or not _SCOPE.fullmatch(self.scope):
            raise ValueError("invalid scope")
        if type(self.generation) is not int or not 0 <= self.generation <= (1 << 63) - 1:
            raise ValueError("invalid generation")
        for field in ("stem_sha256", "tokenizer_sha256", "normalizer_sha256", "source_sha256", "options_sha256"):
            value = getattr(self, field)
            if type(value) is not str or not _DIGEST.fullmatch(value):
                raise ValueError(f"missing or invalid {field}")


@dataclass(frozen=True)
class CellUse:
    cell_id: str
    identity: FeatureIdentity
    active: bool = True

    def validate(self) -> None:
        if type(self.cell_id) is not str or not _SCOPE.fullmatch(self.cell_id):
            raise ValueError("invalid Cell ID")
        if type(self.identity) is not FeatureIdentity:
            raise ValueError("exact FeatureIdentity required")
        self.identity.validate()
        if type(self.active) is not bool:
            raise ValueError("active must be boolean")


@dataclass(frozen=True)
class Profile:
    """Declared research geometry, not real process resident-set size."""

    legacy_encoder_params: int = 421_000_000
    compact_encoder_params: int = 97_000_000
    gated_head_params: int = 9_744
    weight_bytes: int = 4

    def validate(self) -> None:
        for name in ("legacy_encoder_params", "compact_encoder_params", "gated_head_params"):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= 10**10:
                raise ValueError(f"invalid {name}")
        if type(self.weight_bytes) is not int or self.weight_bytes not in (1, 2, 4, 8):
            raise ValueError("invalid declared weight byte width")


def estimate(uses: Sequence[CellUse], profile: Profile = Profile(), *,
             graph_nodes: int = 0, system2_solved_nodes: int = 0) -> dict:
    """Three-way weight comparison separates weight-sharing from Stem shrinkage.

    'unique_feature_forwards' is an *upper* achievable reuse count assuming
    all same-identity calls are bundled while valid. It is NOT a measurement:
    source authorization, cache lifetime and real scheduling can prevent reuse.
    A Cell with a different scope/generation cannot share a FeatureSnapshot.
    """
    profile.validate()
    if isinstance(uses, (str, bytes)) or not isinstance(uses, (list, tuple)):
        raise ValueError("bounded ordered Cell uses required")
    if not 1 <= len(uses) <= _MAX_CELLS:
        raise ValueError("Cell count outside declared bounded study")
    seen_ids = set()
    active = []
    for use in uses:
        if type(use) is not CellUse:
            raise ValueError("typed CellUse required")
        use.validate()
        if use.cell_id in seen_ids:
            raise ValueError("duplicate Cell ID in one batch")
        seen_ids.add(use.cell_id)
        if use.active:
            active.append(use.identity)
    if type(graph_nodes) is not int or not 0 <= graph_nodes <= 1_000_000:
        raise ValueError("invalid graph node count")
    if type(system2_solved_nodes) is not int or not 0 <= system2_solved_nodes <= graph_nodes:
        raise ValueError("invalid System 2 solve count")

    n = len(uses)
    a = len(active)
    unique_inputs = len(set(active))
    width = profile.weight_bytes
    heads = profile.gated_head_params * n * width
    copy_421m = profile.legacy_encoder_params * n * width
    share_421m = profile.legacy_encoder_params * width + heads
    share_97m = profile.compact_encoder_params * width + heads
    return {
        "schema": "hepta.research.shared-stem-cost-lower-bound.v1",
        "authority": "DENY_ALL",
        "measured": False,
        "encoder_invocation_counts_are_schedulable_hypotheses": True,
        "cells_total": n,
        "active_cell_uses": a,
        "hypothetical_best_reuse_distinct_scope_bound_stem_forwards": unique_inputs,
        "without_feature_reuse_stem_forwards": a,
        "saved_encoder_forwards_if_perfectly_coalesced": a - unique_inputs,
        "graph_nodes_declared": graph_nodes,
        "system2_solved_nodes_declared": system2_solved_nodes,
        "graph_nodes_not_solved": graph_nodes - system2_solved_nodes,
        "fp_weight_bytes_only": {
            "dedicated_421m_per_cell": copy_421m,
            "one_shared_421m_plus_heads": share_421m,
            "one_shared_97m_plus_heads": share_97m,
            "resident_cell_heads": heads,
        },
        "excluded_from_weight_accounting": [
            "activation_peak", "KV_or_token_cache", "optimizer_gradients_moments",
            "working_memory_and_checkpoints", "modality_towers", "bridge_projection",
            "concurrent_trainers", "dispatch_and_queue", "decoder_and_verifier",
        ],
        "not_proven": [
            "target_host_RSS_latency_or_energy", "identical_model_quality_or_capacity",
            "feature_final_use_authorization", "true_zero_copy_or_no_double_encoding",
            "learned_task_improvement", "FBSDE_global_regular_solution",
            "end_to_end_System2_cost_adjusted_advantage",
        ],
    }


def example(n: int = 4096, distinct_inputs: bool = False) -> dict:
    """A wholly HYPOTHETICAL n-Cell scenario, never observed model work."""
    if type(n) is not int or not 1 <= n <= _MAX_CELLS:
        raise ValueError("invalid example Cell count")
    uses = []
    for i in range(n):
        hx = lambda v: format(v, "064x")  # noqa: E731
        identity = FeatureIdentity("example_scope", 7, hx(1), hx(2), hx(3),
                                   hx(i + 100 if distinct_inputs else 100), hx(4))
        uses.append(CellUse(f"cell_{i}", identity))
    return estimate(uses)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cells", type=int, default=4096)
    parser.add_argument("--distinct-inputs", action="store_true")
    args = parser.parse_args()
    print(json.dumps(example(args.cells, args.distinct_inputs), sort_keys=True, indent=2))
