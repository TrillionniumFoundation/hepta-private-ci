"""Final evaluation registration after qualification and fit, before 64 sources."""

import argparse
import json
from pathlib import Path

from .policy import FIT_CONFIG, SEEDS
from .audit import sha256, source_hashes, write_json


CORE = ("audit.py", "facts.py", "speech.py", "external.py", "stream.py", "episodes.py", "policy.py",
        "registration.py", "analysis.py", "timing.py", "parallel_matrix.py")


def verify_final_freeze(path, freeze, policies, qualification):
    protocol = json.loads(Path(path).read_text())
    if source_hashes(CORE) != protocol["source_hashes"]:
        raise ValueError("Evaluation code changed after final registration")
    for artifact, expected in ((Path(freeze) / "sources.json", protocol["source_manifest_sha256"]),
                               (Path(freeze) / "qualification_protocol.json", protocol["qualification_protocol_sha256"]),
                               (policies, protocol["policies_sha256"]),
                               (qualification, protocol["qualification_sha256"])):
        if sha256(artifact) != expected:
            raise ValueError("A frozen evaluation artifact changed")
    stats_path = Path(__file__).parents[2] / "abc_recovery" / "statistics.py"
    if sha256(stats_path) != protocol["statistics_sha256"]:
        raise ValueError("Frozen crossed-bootstrap implementation changed")
    return protocol


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("freeze", "policies", "qualification", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    qual = json.loads(args.qualification.read_text())
    policy = json.loads(args.policies.read_text())
    if not qual["passed"] or policy["config"] != FIT_CONFIG or policy["fit_source_groups"] != 32:
        raise ValueError("Qualification or fixed fit design incomplete")
    protocol = {"schema": "hepta.abc3.text-speech-evaluation.v1",
                "source_manifest_sha256": sha256(args.freeze / "sources.json"),
                "qualification_sha256": sha256(args.qualification),
                "qualification_protocol_sha256": sha256(args.freeze / "qualification_protocol.json"),
                "policies_sha256": sha256(args.policies), "source_hashes": source_hashes(CORE),
                "statistics_sha256": sha256(Path(__file__).parents[2] / "abc_recovery" / "statistics.py"),
                "census": {"role": "evaluation", "fact_groups": 64, "scenarios_per_group": 4,
                           "real_generator_actions": 4, "shared_clamp_actions": 1, "value_training_seeds": SEEDS},
                "execution": {"runner": "parallel_matrix", "workers": 2, "start_method": "spawn",
                              "case_assignment": "source index modulo 2; all scenarios in increasing order on that logical shard",
                              "worker_affinity": "last two CPUs in sorted permitted affinity; one distinct CPU per logical shard",
                              "engine_limits": "Piper ONNX intra/inter threads 1; Whisper CPU threads/workers 1; OMP/BLAS 1; Vosk library default additionally bounded by one-CPU process affinity",
                              "randomness": "public source/scenario hash seed frozen in facts.py; Piper noise_scale/noise_w_scale 0; Whisper temperature 0 beam 5; fixed Vosk decoding; five frozen critic seeds"},
                "primary_observer": "frozen offline Whisper tiny.en; zero controller/fit/fixed-selection access",
                "secondary_observer": "online Vosk, including its actual errors; used in fit labels only",
                "primary_comparisons": [
                    {"name": "shared_state_effect", "candidate": "fixed/fuse_normal", "reference": "mechanism/clamped_fuse"},
                    {"name": "learned_feedback_increment", "candidate": "feedback", "reference": "fixed/best_fit"}],
                "primary_metric": "net_utility", "primary_estimand": "joint_ce", "gamma": 2.0,
                "confidence": .975, "bootstrap_replicates": 4000, "bootstrap_seed": 2026102503,
                "primary_positive_gate": "nominal paired interval lower endpoint > 0; do not reinterpret a failure as success",
                "secondary": ["feedback vs initial-only gate", "feedback vs draft-masked feedback",
                              "feedback vs declared-prior reference", "all four fixed actions",
                              "realized-target positive-value MSE/bias for online and external observers; not conditional-value ground truth",
                              "offline all-information realized oracle; diagnostic only"],
                "secondary_confidence": .95,
                "feedback_claim_boundary": "A gain versus a single best-fixed action alone is not evidence of necessity of online feedback; initial-only and draft-masked contrasts remain explicit, descriptive diagnostics",
                "independent_unit": "unique number/color/direction tuple; all scenarios, actions, policy seeds and replays grouped",
                "shared_vocabulary_and_templates": "no independent template/voice/source-domain inference; one controlled task family",
                "statistical_scope": "crossed seed/fact percentile bootstrap, nominal few-seed coverage, no guaranteed population coverage",
                "utility": ".6*(text_fact_accuracy+external_audio_fact_accuracy)/2 + .2*nonmissing_fact_agreement + .2*joint_exact_success",
                "net_cost": ".02 for semantic fuse (including clamped intervention) + .01 for slow acoustic action",
                "cost_scope": "declared proxy action penalties are not measured CPU, milliseconds, money, or a demonstrated deployment price",
                "online_cost_components": ["actual prefix TTS and immutable commit", "internal draft TTS", "unrestricted online Vosk",
                                           "all public policy decisions", "two newly synthesized future chunks", "fsync and exact output readback"],
                "offline_cost_components": ["terminal Vosk measurement", "terminal independent Whisper", "all executed alternative paths", "conditional critic fit"],
                "latency": "matrix component sums labelled as such; separate sequential selected-policy run measures actual end-to-end wall/CPU",
                "timing_design": {"groups": "first 16 frozen evaluation groups", "scenarios": [0, 1, 2, 3],
                                  "policies": ["fixed/best_fit", "feedback/17"], "rounds": 2,
                                  "process_affinity": "single last CPU in sorted permitted affinity; same engine limits as an evaluation worker",
                                  "order": "alternate by group+scenario+round; no outlier deletion",
                                  "quality": "unchanged models and decisions; timing repetitions never increase scientific N"},
                "generation_boundary": "fixed pretrained Piper neural acoustic synthesis; template text decoder; learned shared-state action critic only",
                "delayed_effect": "neutral text/audio prefix committed before real draft/probe and fresh evidence; shared revision changes only later two committed chunks",
                "strong_baseline_information": "all fuse actions, including fixed/open-loop, receive identical lawful fresh cue and same operator; initial-only means action gate only",
                "media_scope": "genuine text and fresh speech, no video, no audiovisual alignment or end-to-end acoustic co-training claim",
                "nonanticipation": "initial decisions before draft; feedback decisions fsynced before future candidate audio and offline scoring",
                "stop_rule": "complete full census; preserve errors; no post-evaluation template/threshold/controller/observer changes"}
    write_json(args.output, protocol)
    print(json.dumps({"final_protocol_sha256": sha256(args.output), "best_fixed_action": policy["best_fixed_action"],
                      "policies_sha256": protocol["policies_sha256"]}))


if __name__ == "__main__":
    main()
