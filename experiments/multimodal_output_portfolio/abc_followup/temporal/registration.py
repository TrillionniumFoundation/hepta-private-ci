"""Freeze all final hypotheses and executable identities before final outputs."""

import argparse
import json
from pathlib import Path
import time

from experiments.multimodal_output_portfolio.abc_next.temporal.audit import sha256, write_json
from .analysis import BOOTSTRAPS, BOOTSTRAP_SEED, PRIMARY_CONFIDENCE
from .qualification import GATES
from .state import GAMMA, PRICE, PRICE_GRID, SEEDS
from .value import FIT


CORE = ("tasks.py", "state.py", "episodes.py", "value.py", "run.py", "score.py",
        "analysis.py", "qualification.py", "registration.py")
REUSED = ("audit.py", "speech.py", "external.py", "stream.py", "facts.py")


def code_hashes():
    root = Path(__file__).parent
    old = root.parents[1] / "abc_next" / "temporal"
    result = {f"new/{name}": sha256(root / name) for name in CORE}
    result.update({f"reused/{name}": sha256(old / name) for name in REUSED})
    return result


def verify(protocol_path, policy_path):
    if protocol_path is None or policy_path is None:
        raise ValueError("Frozen protocol and policy are required")
    protocol = json.loads(Path(protocol_path).read_text())
    if protocol["code_hashes"] != code_hashes():
        raise ValueError("Final executable source changed after freeze")
    if protocol["policy_sha256"] != sha256(policy_path):
        raise ValueError("Frozen selected policy changed")
    qualifier = Path(protocol["qualification_result_path"])
    if sha256(qualifier) != protocol["qualification_result_sha256"]:
        raise ValueError("Qualification evidence changed")
    result = json.loads(qualifier.read_text())
    if not result["passed"] or result["gates"] != GATES or result["protocol_sha256"] != protocol["qualification_protocol_sha256"]:
        raise ValueError("Frozen independent observer gate did not pass")
    if protocol["gamma"] != GAMMA or protocol["price"] != PRICE or protocol["fit_config"] != FIT:
        raise ValueError("Risk/cost/training profile changed")
    source = Path(protocol["source_manifest_path"])
    if sha256(source) != protocol["source_manifest_sha256"]:
        raise ValueError("Source partition changed")
    return protocol


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policies", type=Path, required=True)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    policy = json.loads(args.policies.read_text())
    result = json.loads(args.qualification.read_text())
    qualification_protocol = json.loads((args.freeze / "qualification_protocol.json").read_text())
    if not result["passed"] or policy.get("selection_sources") != 16 or policy["fit_sources"] != 32:
        raise ValueError("Complete fit, selection and observer qualification required")
    protocol = {"schema": "hepta.abc4.temporal-final-protocol.v1",
                "registered_unix_ns": time.time_ns(), "code_hashes": code_hashes(),
                "policy_sha256": sha256(args.policies), "fit_config": FIT,
                "qualification_result_path": str(args.qualification.resolve()),
                "qualification_result_sha256": sha256(args.qualification),
                "qualification_protocol_sha256": sha256(args.freeze / "qualification_protocol.json"),
                "tts_online_assets_sha256": qualification_protocol["assets_sha256"],
                "external_assets_sha256": qualification_protocol["external_assets_sha256"],
                "source_manifest_path": str((args.freeze / "sources.json").resolve()),
                "source_manifest_sha256": sha256(args.freeze / "sources.json"),
                "gamma": GAMMA, "price": PRICE, "price_grid": PRICE_GRID,
                "value_clock_origins": "Q1 after second gate; Q2 backup exp(gamma*price*(tau1-tau0))*min(mean_OOF_Q1); initial-only and final outcomes use complete request T",
                "state": "82 public features: initial words, full shared posterior, actual committed-prefix ASR categories, uncertainty/history summaries; no source ID, target or unreleased cue",
                "price_unit": "research utility per actual online wall-second; not externally calibrated economic value",
                "utility": ".6*(text_fact_accuracy+audio_fact_accuracy)/2+.2*nonmissing_agreement+.2*joint_exact_success",
                "net_utility": "utility minus price times actual same-request wall seconds",
                "source_groups": 64, "templates": 2, "scenarios": 2, "requests": 768,
                "policies": ["selection-selected constant two-stage query route", "learned initial-only route ensemble", "learned two-gate feedback ensemble"],
                "selected_fixed_route": policy["selected_fixed_route"], "critic_seeds": SEEDS,
                "selected_feedback_variant": policy["selected_feedback_variant"],
                "selection_candidates": "four constant routes, one initial-only ensemble, full-prefix-observer feedback, cue-only feedback;448actual serial selection requests; choose fixed and feedback separately using only Vosk primary-price CE",
                "cue_only_mask": "previous_audio_fact fully replaced with missing before features; elapsed not a feature; training inter-gate cost subtracts measured prefix-probe component; final actually omits that operation",
                "primary_family": ["priced_CE(feedback)-priced_CE(selected_fixed)>0",
                                   "priced_CE(feedback)-priced_CE(initial_only)>0",
                                   "success_probability(feedback)-success_probability(selected_fixed)>=0"],
                "strict_success_margin": 0., "primary_confidence": PRIMARY_CONFIDENCE,
                "bootstrap": {"draws": BOOTSTRAPS, "seed": BOOTSTRAP_SEED,
                              "resample": "underlying fact groups, preserving all templates/scenarios/policies",
                              "primary_family_size": 3, "price_grid_family_size": 10,
                              "price_grid_individual_confidence": .995,
                              "finite_sample_coverage_guarantee": False},
                "break_even_scan": {"start": 0., "stop": .2, "points": 41,
                                    "references": "fixed at primary-price selection; no per-price reselection"},
                "generation": "all selected requests serial, counterbalanced policy order, fresh actual source/output TTS, no sleep or precomputed waveform lookup",
                "acquisition": "private source owner pre-samples noisy facts; action releases a real new spoken cue via synthesis/persist/unrestricted Vosk; no hidden truth returned",
                "causal_scope": "controlled delayed sensor evidence, not an external live sensor; same public fusion operator in all controls",
                "quality_cost_identity": "only independently observed actual outputs of those same serial requests",
                "offline_scoring": "after all generation closes; reuse target-free Whisper transcription only for exact complete-WAV hash, recalculate metrics for each target",
                "cost_scope": "owner construction, neutral prefix, actual cue production/persistence/ASR, policy decisions, both output commits, WAV serialization/readback; excludes model load and terminal measurement ASR, all separately reported",
                "failure_rule": "retain complete fixed census and all failures; no policy/price/threshold/source/observer changes after final freeze",
                "claims_excluded": ["all-modal foundation model", "acoustic model training", "natural voice/template population", "global conditional optimum", "production native admission", "externally priced economic benefit"]}
    write_json(args.output, protocol)
    verify(args.output, args.policies)
    print(json.dumps({"protocol_sha256": sha256(args.output), "code_hashes": protocol["code_hashes"]}), flush=True)


if __name__ == "__main__":
    main()
