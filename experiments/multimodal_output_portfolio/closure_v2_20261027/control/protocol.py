"""Predeclared semantic feedback study; no production authority is inferred."""

from pathlib import Path

from ...continuation_20261027.control.client import digest, sha, write


PROTOCOL = {
    "schema": "hepta.ndu.semantic-owner-continuation.v1",
    "baseline_commit": "fb9281e4a7ccfc4034281ed6310adea7e50f4474",
    "generator": "seed-17-joint_uniform-selected.pt",
    "generator_sha256": "508931a0cb780d413bc39de83b8de91aeab68b33cfe1b384f176cb8e8f004ee6",
    "native_binary_sha256": "ba5fc96e8139e652fd1d7ae0f9713b66ccd879b12e190e4dcc93bca43426143b",
    "native_owner_source_sha256": "4d56cc99d0edb1018734aebf70dc715de8df7846a2a9c4f2edb4230a0fc87faf",
    "task": "Actual neural digit-pair image/caption delivery followed by scalar preference feedback and delayed order correction",
    "task_scope": "Constructed two-option preference task on genuine MNIST pixels; no general-language or natural AV claim",
    "conditions": ["clean", "occlusion", "missing", "heavy_noise"],
    "arms": ["native_numeric", "native_zero", "native_permuted", "history", "linear_memory"],
    "fit_pairs": 256,
    "validation_pairs": 128,
    "qualification_pairs": 128,
    "readout_examples": 96,
    "gamma": 2.0,
    "seed": 2702791,
    "readout_ridge": 1e-8,
    "critic_shrinkage_candidates": [0, 8, 32, 128, 512],
    "bootstrap_replicates": 5000,
    "interval": 0.975,
    "bootstrap_seed": 2702793,
    "native_kernel_charge": 0.0001,
    "generator_call_charge": 0.01,
    "delivery_charge": 0.002,
    "refused_proposal_charge": 0.005,
    "feedback": {
        "positive": "Actual delivered caption has the preferred ordered pair and correct relation",
        "negative": "Actual delivered caption has exactly the opposite ordered pair and its correct relation",
        "zero": "Caption does not express either candidate unambiguously",
        "private_truth_access": "External feedback/scoring service only; downstream inference receives the scalar after delivery",
    },
    "semantic_success": "Both actual caption digits/relation and independent audit image digits equal the preferred pair",
    "readout_target": "exp(-gamma*initial_utility) - exp(-gamma*(alternate_utility-extra_generator_and_delivery_charge))",
    "future_model": "Empirical joint law of actual fit deliveries, semantic feedback and alternate outputs; validation-only pooling selection",
    "qualification_contexts": "Balanced assignment of one corruption, expiry (6 or 7) and media budget (1 or 2) to each source pair",
    "cold_resume": "After the actual feedback tick, close and terminate process; recover journal/witness/event ledger in a new process before hold and decision",
    "same_information_history_superiority_required": False,
    "semantic_gain_gate": "Paired source-pair 97.5% lower bound for strict semantic success and net utility versus zero is positive",
    "history_equivalence_gate": "Native and same-information history actions and final output bytes are identical",
    "actual_alignment_gate": "Every realized feedback/hold/decision numeric state matches its pre-delivery native future branch; all admissions/refusals agree",
    "semantic_ece_threshold": 0.03,
    "semantic_false_acceptance_threshold": 0.004999,
    "semantic_acceptance_confidence": 0.75,
    "minimum_semantic_coverage": 0.20,
    "semantic_qualification_scope": "Report point metrics and source-pair uncertainty; not a replacement production qualification",
    "native_authority": "DENY_ALL",
    "production_authorization": False,
    "threads": 1,
}


def preserve_sources(directory):
    directory = Path(directory)
    directory.mkdir()
    records = {}
    for source in Path(__file__).resolve().parent.glob("*.py"):
        target = directory / source.name
        target.write_bytes(source.read_bytes())
        records[source.name] = sha(target)
    return records
