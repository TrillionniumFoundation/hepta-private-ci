"""Versioned development contract; no reinterpretation of the frozen v1/v2 runs."""

from dataclasses import dataclass
import hashlib
from pathlib import Path

from ..contract import digest
from ..runtime import make_profile as parent_profile, TARIFF, HORIZON, INITIAL_BUDGET


@dataclass(frozen=True)
class Profile:
    parent: object
    implementation: tuple
    horizon: int = HORIZON
    initial_budget: float = INITIAL_BUDGET
    audio_rate: int = 2048
    frame_ms: int = 120

    @property
    def ndu(self):
        return self.parent.ndu

    def to_dict(self):
        return {"schema": "hepta.joint-generation.initial-stop.v3", "parent": self.parent.to_dict(),
                "source": dict(self.implementation), "horizon": self.horizon,
                "initial_budget": self.initial_budget, "initial_stop_legal": True,
                "audio_rate": self.audio_rate, "frame_ms": self.frame_ms,
                "tariff": TARIFF, "clock": "measured_process_cpu_and_wall",
                "prefix": "immutable_state_budget_named_rng_and_already_charged_events",
                "randomness": "actor_seed; emission_seed_xor_0x5eed1234; conditional_sampling",
                "commitment": "buffered_bundle; native_stream_profile_is_separate",
                "risk": "finite_horizon_population_entropic_CE_gamma2; not_general_NDU",
                "verification": "public_consistency_proxy; not_independent_new_evidence",
                "cost_boundary": "encode_identity_checks_control_transition_codec_observer_audit_draft_and_seal",
                "final_seal_cost": "included_in_training_return; final_sidecar_is_outer_run_overhead",
                "physical_hard_budget_guarantee": False,
                "capability": "development_only_no_natural_or_global_optimum_claim"}

    @property
    def digest(self):
        return digest(self.to_dict())


def make_profile(dataset="mechanism", *, audio_rate=2048, frame_ms=120):
    directory = Path(__file__).parent
    sources = tuple((name, hashlib.sha256((directory / name).read_bytes()).hexdigest())
                    for name in ("model.py", "runtime.py", "profile.py"))
    return Profile(parent_profile(dataset, audio_rate=audio_rate, frame_ms=frame_ms),
                   sources, audio_rate=audio_rate, frame_ms=frame_ms)
