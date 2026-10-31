"""Render the major detailed report from already frozen aggregate analysis."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from .audit import sha256


def number(value, digits=4):
    return f"{value:.{digits}f}"


def interval(contrast):
    result = contrast["net_ce"]
    return f"{result['gain']:+.4f} [{result['interval'][0]:+.4f}, {result['interval'][1]:+.4f}]"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preliminary-policy", type=Path, required=True)
    parser.add_argument("--timing-raw", type=Path, required=True)
    parser.add_argument("--timing-audit", type=Path, required=True)
    parser.add_argument("--chronology", type=Path, required=True)
    parser.add_argument("--process-receipt", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.summary.read_text())
    if args.output.exists():
        raise FileExistsError(args.output)
    external, online = data["summaries"]["external"], data["summaries"]["online"]
    contrasts = data["contrasts"]["external"]
    shared = contrasts["shared_state_effect"]["primary_positive_gate_passed"]
    feedback = contrasts["learned_feedback_increment"]["primary_positive_gate_passed"]
    lines = ["# C-next: genuine text/speech continuation with delayed shared semantics", "",
             "## Result and scope", "",
             "The complete frozen experiment generated new text and speech through a fixed pretrained "
             "Piper acoustic backend, measured terminal audio with an external Whisper observer, and "
             "retained actual generation, observation, serialization and training costs. It executed "
             "64 held-out fact combinations, four public-noise scenarios per combination, and five "
             "actual continuation paths per case. The 1,280 paths are repeated potential outcomes "
             "within 64 fact groups, not 1,280 independent samples. There is one template family and one voice.", "",
             f"The registered shared-state contrast **{'passed' if shared else 'did not pass'}** its positive-evidence gate: "
             f"external-observer net-CE gain {interval(contrasts['shared_state_effect'])} "
             "(nominal 97.5% crossed fact/seed interval). "
             f"The learned-feedback contrast against the fit-selected fixed policy **{'passed' if feedback else 'did not pass'}**: "
             f"{interval(contrasts['learned_feedback_increment'])}. A nonpositive lower interval endpoint "
             "does not become a successful feedback claim because the execution pipeline worked.", "",
             "This closes the artifact-realization gap left by the earlier transport-only C witness: "
             "the new waveform bytes come from actual pretrained neural synthesis of the current "
             "shared-state text, rather than replay of a source recording. It does not establish "
             "end-to-end acoustic/text co-training, general language generation, an audiovisual model, "
             "continuous-time Merton control, or an optimal native multimodal portfolio.", "",
             "## Registered design and identities", "",
             "| Artifact | SHA-256 |", "|---|---|",
             f"| Final evaluation protocol | `{data['final_protocol_sha256']}` |",
             f"| Active 15-critic policy bundle | `{data['policies_sha256']}` |",
             f"| Aggregate `SUMMARY.json` | `{sha256(args.summary)}` |", "",
             "The source-role manifest and qualification/final protocols are in `freeze-v1/`. "
             "The final protocol pins the generator, both observers, parsing, public-state/action "
             "interfaces, trained policy identities, statistical implementation, two primary contrasts, "
             "all secondary analyses, candidate census and timing design before evaluation begins. "
             "No evaluation group selected a template, observer, threshold, controller hyperparameter or fixed policy.", "",
             "The 128 unique number/color/direction combinations were frozen into 16 development, "
             "32 fit, 16 qualification and 64 evaluation groups. Vocabulary and templates are shared "
             "across roles. Fact-group intervals therefore condition on one fixed construction and "
             "voice; they do not represent independent natural-source, lexical-family, template or voice replication.", "",
             "Only the action-value interface is trained here: a 24-unit tanh hidden layer with "
             "four positive softplus outputs (floor 0.001), regressing `exp(-2 × net utility)`. "
             "Initial-only, feedback and probe-masked variants use five fixed seeds each "
             "(17, 29, 43, 59, 71), 1,200 Adam steps, learning rate 0.01 and weight regularization "
             "0.001. The 32 fit groups supplied 128 actual contexts and 512 actual candidate paths. "
             f"Their Vosk-based risk selected `{data['fit_selected_fixed_action']}` as the fixed comparator. "
             "Whisper was not run on fit data. The categorical fusion operator, text templates and "
             "pretrained acoustic weights are fixed; this is conditional-value training, not new "
             "joint text/acoustic generator training.", "",
             "### Actual causal sequence", "",
             "The semantic source is a controlled noisy-fact environment. Its owner pre-samples "
             "both initial and later cues when constructing the episode; the initial-only feature "
             "adapter ignores all later fields, and the executor releases them after the actual "
             "draft observation. This is a tested nonanticipating information interface, not acquisition "
             "of a new live sensor signal. The new synthesized waveform and draft ASR are real operations.", "",
             "1. An initial-only gate sees only initial public features. The episode owner alone "
             "uses hidden facts to sample declared noisy cues.",
             "2. The generator actually synthesizes a neutral prefix and commits its text and PCM "
             "with durable writes before any later observation is released.",
             "3. A fresh, uncommitted draft is synthesized from the initial shared semantic state. "
             "Vosk observes the actual audio without a custom grammar, intended text or target.",
             "4. Later public evidence and the draft observation become available. Feedback decisions "
             "are durably recorded before any future candidate waveform or terminal quality score exists.",
             "5. Each candidate forks the already committed prefix, then synthesizes and commits "
             "two future chunks. Exact text/PCM spans and final wave bytes are checked against the original prefix.",
             "6. Independent Whisper measures the complete final WAV offline. Its scores never "
             "enter policy features, critic fitting, best-fixed selection or hyperparameters.", "",
             "The four lawful generator actions are keep/fuse × normal/slow. Fixed and initial-only "
             "gates have the same fusion operator, lawful fresh evidence, action family and generation "
             "budget. Initial-only means the action gate, not denial of later conditioning inside "
             "a selected fusion operator. The fifth path requests fuse but clamps the shared state. "
             "It pays the same declared fuse penalty, isolating content propagation from an artificial cost advantage.", "",
             "The strong public reference enumerates all eight correctness masks under the declared "
             "factorized posterior and the same gamma-2 exponential-risk objective, while assuming "
             "perfect acoustic intelligibility. It is not asserted to be optimal for actual recognition "
             "errors or for a finite held-out subset. The realized full-information oracle is computed "
             "only after all real candidates exist and remains an offline diagnostic upper bound.", "",
             "### Frozen utility and statistical unit", "",
             "Utility is `0.6 × (text fact accuracy + audio fact accuracy)/2 + 0.2 × nonmissing "
             "fact agreement + 0.2 × joint exact success`. Net utility subtracts 0.02 for fuse "
             "(also for the clamp) and 0.01 for slow synthesis. These fixed proxy penalties do not "
             "stand for measured milliseconds, CPU, money, energy or a deployment cost price.", "",
             "Completion requires physically complete output and all three unambiguous facts in both "
             "text and independently decoded speech. Incorrect but complete content can satisfy "
             "completion and must fail exact task success. Silence and truncated outputs cannot "
             "pass merely because a file is present. ASR-measured task success is an imperfect "
             "external content metric, not a human listening score.", "",
             "The five critic seeds are crossed with 64 fact groups; all four scenarios and policy "
             "replays stay within their fact group. CE is evaluated within each trained seed and "
             "then averaged across seeds. The two registered primary contrasts use nominal 97.5% "
             "paired percentile intervals with 4,000 common bootstrap draws. All other intervals are "
             "descriptive 95% intervals. Few-seed coverage is not guaranteed, and finite-scenario CE "
             "is not claimed to be an unbiased population-risk estimate.", "",
             "## Independent observer qualification", "",
             "| Frozen observer | Speed | Fact accuracy | Exact success |", "|---|---|---:|---:|"]
    for key, row in data["qualification"]["summary"].items():
        observer, speed = key.split("_")
        lines.append(f"| {observer} | {speed} | {row['fact_accuracy']:.4f} | {row['exact']:.4f} |")
    lines += ["", "All predeclared qualification gates passed on the 16 qualification groups. "
              "External fact/exact thresholds were 0.90/0.75 at both speeds; online thresholds were "
              "0.85/0.65. Intentionally wrong numbers failed exact success, and actual silent/truncated "
              "PCM failed semantic completion. Repeated silent controls are not independent "
              "population-level false-positive-rate evidence. The actual `south → self` and "
              "`four → for` errors were retained. No homophone-to-target repair was added.", "",
              "Whisper and Vosk have separate weights and different recognizer implementations. "
              "Their possible pretraining-corpus overlap is unknown, and their recognition errors "
              "are not assumed statistically independent. Target-independent normalization of digits "
              "1–8 into words was frozen before qualification. Neither observer received a target "
              "prompt, candidate-fact list, hotwords or custom vocabulary grammar.", "",
              "## Held-out external quality", "",
              "| Policy | Net CE | Exact success | Required completion | Text facts | Speech facts | Agreement |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    quality_order = ("fixed/keep_normal", "fixed/fuse_normal", "fixed/keep_slow", "fixed/fuse_slow", "fixed/best_fit",
                     "initial_only", "feedback_no_probe", "feedback", "public/assumed_prior_reference",
                     "mechanism/clamped_fuse", "oracle_offline")
    for name in quality_order:
        row = external[name]
        m = row["metrics"]
        lines.append(f"| {name} | {row['net_utility']['joint_ce']:.4f} | {m['joint_task_success']:.4f} | "
                     f"{m['required_semantic_completion']:.4f} | {m['text_fact_accuracy']:.4f} | "
                     f"{m['audio_fact_accuracy']:.4f} | {m['fact_agreement']:.4f} |")
    feedback_metric = external["feedback"]["metrics"]
    fixed_metric = external["fixed/best_fit"]["metrics"]
    gross_delta = feedback_metric["utility"] - fixed_metric["utility"]
    penalty_delta = ((feedback_metric["utility"] - feedback_metric["net_utility"]) -
                     (fixed_metric["utility"] - fixed_metric["net_utility"]))
    lines += ["", f"For feedback versus the fit-selected fixed policy, the mean gross-utility change "
              f"is `{gross_delta:+.6f}`, and the mean declared proxy-penalty change is `{penalty_delta:+.6f}` "
              "(negative means a smaller penalty). This separates observed content changes from "
              "the chosen proxy pricing. These mean differences are not an additive decomposition "
              "of the nonlinear CE contrast, and a lower proxy penalty is not a measured CPU saving."]
    lines += ["", "The oracle row selects a realized outcome after scoring every candidate and cannot "
              "be implemented by the online controller. Fixed policies are repeated along the seed "
              "axis only to preserve paired comparisons; those repeats add no information. A learned "
              "gain over one globally fixed action alone would not demonstrate that real generated-state "
              "feedback is needed; the initial-only and draft-masked diagnostics remain explicit.", "",
              "All 1,280 paths physically completed both text and nonempty speech and passed exact "
              "committed-span readback. The table's required *semantic* completion additionally "
              "requires recovery of all three facts by the external audio observer; its failures "
              "do not mean that the waveform file or speech modality was absent.", "",
              "| Registered/descriptive contrast | Net-CE gain [interval] | Exact-success difference (percentage points) |",
              "|---|---:|---:|"]
    for name in ("shared_state_effect", "learned_feedback_increment", "initial_gate_increment", "probe_increment",
                 "declared_prior_reference", "oracle_vs_fixed", "oracle_vs_feedback"):
        row = contrasts[name]
        lines.append(f"| {name} | {interval(row)} | {row['success']['gain_percentage_points']:+.2f} |")
    lines += ["", "### Mean and tail loss", "",
              "These are descriptive empirical losses `1 - utility`, before proxy action costs. "
              "CVaR uses the worst 10% with exact fractional boundary mass. Values below are "
              "per-seed output-distribution statistics averaged over seeds, not a relabelled "
              "population tail certificate.", "",
              "| Policy | Mean loss | P95 loss | Worst-10% CVaR |", "|---|---:|---:|---:|"]
    for name in ("fixed/best_fit", "initial_only", "feedback", "feedback_no_probe", "public/assumed_prior_reference", "oracle_offline"):
        tail = external[name]["loss_tails"]["output_level"]["mean_across_seed_summaries"]
        lines.append(f"| {name} | {tail['mean']:.4f} | {tail['p95']:.4f} | {tail['cvar']:.4f} |")
    lines += ["", "## Observer transfer and value diagnostics", "",
              f"Vosk and external Whisper disagreed on parsed audio facts on "
              f"{data['observer_disagreement']['paths']} of 1,280 actual candidate paths "
              f"({100 * data['observer_disagreement']['fraction']:.2f}%). This is a descriptive "
              "path count; repeated facts/actions do not make it an independent-sample estimate.", "",
              "| Policy | External net CE | Online-Vosk net CE |", "|---|---:|---:|"]
    for name in ("fixed/best_fit", "initial_only", "feedback", "feedback_no_probe", "public/assumed_prior_reference"):
        lines.append(f"| {name} | {external[name]['net_utility']['joint_ce']:.4f} | {online[name]['net_utility']['joint_ce']:.4f} |")
    lines += ["", "| Value interface | Observer target | Realized-target MSE | Mean predicted Z minus realized Z |",
              "|---|---|---:|---:|"]
    for observer, rows in data["positive_value_prediction_diagnostics"].items():
        for mode, row in rows.items():
            lines.append(f"| {mode} | {observer} | {row['realized_target_mse']:.6f} | {row['mean_prediction_minus_realized_target']:+.6f} |")
    if data["external_text_audio_disagreement_examples"]:
        lines += ["", "The following are the first retained examples of text versus external audio-observer "
                  "disagreement, not a selection of favorable cases. They distinguish measurement "
                  "disagreement from a semantically wrong but faithfully spoken shared state.", "",
                  "| Action | Actually committed text | External transcription of actual WAV |", "|---|---|---|"]
        for row in data["external_text_audio_disagreement_examples"][:4]:
            text = row["committed_text"].replace("\n", " ").strip()
            lines.append(f"| {row['action']} | {text} | {row['external_transcript']} |")
    lines += ["", "These diagnostics compare a predicted conditional positive value with one actual "
              "exponential-utility outcome per candidate. They include irreducible outcome variation "
              "and are not direct measurements of the true conditional expectation, a calibration "
              "bound, or a hidden-information oracle. Whisper targets are evaluation-only; the "
              "critics were fitted to Vosk targets on the 32 fit groups.", "",
              "## Real compute and latency", "",
              f"The evaluation executed {data['census']['actual_tts_api_calls']:,} synthesis API requests, "
              f"yielding {data['census']['distinct_final_wave_hashes']} distinct complete-WAV hashes. "
              "Duplicate hashes are expected under deterministic synthesis of the same facts; every "
              "candidate still performed its real synthesis call. An API request can contain multiple "
              "sentence-level acoustic forwards, so the request count is not an acoustic forward-pass count.", "",
              "Evaluation used two spawned processes with static source-index-parity assignment; "
              "all scenarios for a fact stayed on one logical worker. Each worker was bound to one "
              "CPU and used single-thread ONNX/Whisper plus OMP/BLAS limits. Vosk's default native "
              "threading was also bounded by one-CPU affinity. The final selected-policy timing "
              "study ran sequentially on one CPU. Global wall time is one monotonic elapsed clock; "
              "per-case wall sums are occupancy and are not added to form global elapsed time.", "",
              "| Stage | Actual wall seconds | Actual process/child CPU seconds |", "|---|---:|---:|"]
    preliminary = json.loads(args.preliminary_policy.read_text())
    for label, clocks in (("Observer qualification", data["qualification"]),):
        lines.append(f"| {label} | {clocks['wall_ns_before_report']/1e9:.3f} | {clocks['cpu_ns_before_report']/1e9:.3f} |")
    for label, clocks in (("Fit data: 128 cases / 512 real paths", data["fit_run"]["whole_process_before_report"]),
                          ("Evaluation: all 1,280 real paths", data["evaluation_run"]["whole_process_before_report"])):
        lines.append(f"| {label} | {clocks['wall_ns']/1e9:.3f} | {clocks['cpu_ns']/1e9:.3f} |")
    final_fit = data["value_fit_cost"]
    lines.append(f"| Critic fitting, both identical-weight builds | "
                 f"{(preliminary['wall_ns_before_report']+final_fit['wall_ns_before_report'])/1e9:.3f} | "
                 f"{(preliminary['cpu_ns_before_report']+final_fit['cpu_ns_before_report'])/1e9:.3f} |")
    for observer, clocks in data["offline_terminal_asr_total_cost"].items():
        lines.append(f"| Terminal {observer} scoring, sum across workers (included above) | {clocks['wall_ns']/1e9:.3f} | {clocks['cpu_ns']/1e9:.3f} |")
    timing = data["timing"]
    if timing:
        process_receipt = json.loads(args.process_receipt.read_text())
        if process_receipt["child_exit_code"] != 0 or process_receipt["primary_protocol_sha256"] != data["final_protocol_sha256"]:
            raise ValueError("Outer timing process did not complete the frozen experiment")
        raw_timing = json.loads(args.timing_raw.read_text())
        timing_audit = json.loads(args.timing_audit.read_text())
        if raw_timing["summary"] != timing["summary"] or len(raw_timing["rows"]) != 256:
            raise ValueError("Timing evidence does not match the aggregate report")
        if timing_audit["timing_report_sha256"] != sha256(args.timing_raw):
            raise ValueError("Timing post-audit refers to different evidence")
        matching_waves = sum(row["identical_wave_to_quality_matrix"] for row in raw_timing["rows"])
        lines.append(f"| Timing-run fresh-process generator/online-observer load (included in timing-run total) | "
                     f"{timing['backend_load']['wall_ns']/1e9:.3f} | {timing['backend_load']['cpu_ns']/1e9:.3f} |")
        lines.append(f"| Full timing child process, separately pinned outer wrapper (includes internal run) | "
                     f"{process_receipt['full_child_wall_ns']/1e9:.3f} | {process_receipt['full_child_cpu_ns']/1e9:.3f} |")
        lines.append(f"| Dedicated selected-policy timing, 256 executions | {timing['run_wall_ns_before_report']/1e9:.3f} | {timing['run_cpu_ns_before_report']/1e9:.3f} |")
        lines += ["", "| Selected policy | Wall mean / P50 / P95 ms | CPU mean / P50 / P95 ms | First durable output P50 ms | Audio duration P50 s |",
                  "|---|---:|---:|---:|---:|"]
        for name, row in timing["summary"].items():
            fmt = lambda values: " / ".join(f"{values[key]:.2f}" for key in ("mean", "p50", "p95"))
            lines.append(f"| {name} | {fmt(row['wall_ms'])} | {fmt(row['cpu_ms'])} | "
                         f"{row['first_durable_output_ms']['p50']:.2f} | {row['audio_duration_seconds']['p50']:.3f} |")
        lines += ["", f"Timing host load averages began at `{timing['load_average_start']}` and ended at "
                  f"`{timing['load_average_end']}`; measured process affinity was `{timing['cpu_affinity']}`. "
                  "This is a shared container, not an isolated deployment benchmark. All rounds and "
                  "outliers were retained. Timing repeats added zero independent quality samples. "
                  f"Exact final-WAV hashes matched their corresponding quality-matrix outputs on {matching_waves}/256 "
                  f"timing executions; raw timing report SHA-256 is `{sha256(args.timing_raw)}`."]
        lines += ["", f"The independent stdlib-only outer wrapper recorded full child-process launch "
                  f"through exit, with peak child RSS `{process_receipt['child_peak_rss_kib']}` KiB "
                  f"({process_receipt['child_peak_rss_kib']/1024:.2f} MiB). It includes Python startup/import, "
                  "CLI/freeze checks, all model loads, all sequential episodes, measurement receipts "
                  "and final report serialization. It excludes the outer wrapper's own startup/preparation "
                  "and receipt write, later post-audit/rescoring, other host work and actual audio-device "
                  f"playback. `TIMING_PROCESS_RECEIPT.json` SHA-256 is `{sha256(args.process_receipt)}`; "
                  f"its pre-timing launch plan is `{process_receipt['measurement_plan_sha256']}`. "
                  "The wrapper, child source, executable, command vector and explicit thread environment "
                  "were pinned before timing; the frozen timing implementation was not changed."]
        lines += ["", f"The separate closing audit independently recomputed all 256 media identities: "
                  f"stored audio-identity flag false count `{timing_audit['stored_wave_flag_false_count']}`, "
                  f"actual audio mismatches `{timing_audit['actual_wave_identity_false_count']}`, and "
                  f"actual text mismatches `{timing_audit['actual_text_identity_false_count']}`. "
                  f"`TIMING_AUDIT.json` records this audit (SHA-256 `{sha256(args.timing_audit)}`)."]
        if timing_audit["main_quality_transfer_by_exact_identity_valid_for_all"]:
            lines += ["", "Every timed artifact has the exact text and audio bytes of its corresponding "
                      "quality-matrix output, so the frozen content measurement applies to those identical outputs."]
        else:
            lines += ["", f"{timing_audit['changed_media_independently_rescored']} changed timing outputs were "
                      "separately decoded by the already frozen Whisper observer. Main-matrix quality was "
                      "not assigned to those different artifacts. Their separate measurements are retained "
                      "in the closing audit and do not replace or enlarge the primary evaluation."]
    lines += ["", "The per-execution latency table uses already loaded models; model loading is separately "
              "reported and included in the timing-run total. Fresh-process model construction does not "
              "imply cold filesystem, OS or hardware caches after the preceding study. The actual online timer includes prefix TTS/commit, draft TTS, online Vosk, the "
              "selected gate, both new future chunks, durable writes, final WAV serialization and "
              "exact readback. Final content ASR is offline and separately charged. The endpoint is "
              "a durable complete WAV/text artifact, not speaker playback or network delivery. "
              "Both policies pay the common draft/probe; a deployment-specialized fixed policy "
              "could omit unused probing and be cheaper. That optimization was not measured.", "",
              "Timing covers the first 16 predeclared evaluation fact groups, all four scenarios, "
              "two counterbalanced rounds, and two policies: 128 executions per policy. Feedback "
              "uses the prospectively chosen seed 17, not a post-result seed selection. Main quality "
              "summaries average five critic seeds over all 64 groups, so the narrower timing sample "
              "is not presented as a five-seed latency estimate or a matched full-cohort economic "
              "dominance test.", "",
              "The timing-run clock begins after CLI parsing, frozen-input verification, affinity "
              "configuration and output-directory creation; it includes model/policy loading, matrix "
              "index reads and every selected episode, and ends before final report serialization. "
              "The per-episode measurement-only timing receipt is written after its episode timer "
              "stops but remains inside the run clock. The evaluation runner begins its clock after "
              "CLI parsing, includes both spawned workers' startup, and records parent plus terminated "
              "worker CPU. Parent Python/import startup and final report writing are outside these "
              "code-defined internal clocks. The separate outer receipt adds full child-process "
              "launch/import/exit coverage; neither measurement resets filesystem/hardware caches "
              "or measures full machine energy consumption.", "",
              "The compact `component_cost_ms` arrays are aligned on five policy seeds. Fixed/clamp "
              "measurements repeat on that axis; their `sum` and `n_rows` fields are not unique actual "
              "executions or total measured resource use. The main total-cost figures above use the "
              "evaluation's single global elapsed clock and actual parent-plus-child CPU. "
              "`matrix_total_case_cost.wall_ns` is summed worker occupancy, not global elapsed time.", "",
              f"For independent cost reconciliation, preliminary critic bundle `{sha256(args.preliminary_policy)}` "
              f"recorded {preliminary['wall_ns_before_report']/1e9:.9f} s wall and "
              f"{preliminary['cpu_ns_before_report']/1e9:.9f} s CPU. The active bundle "
              f"`{data['policies_sha256']}` recorded {final_fit['wall_ns_before_report']/1e9:.9f} s wall "
              f"and {final_fit['cpu_ns_before_report']/1e9:.9f} s CPU. `SUMMARY.json.value_fit_cost` "
              "contains the active build only; the two-build total above additionally includes the "
              "preserved preliminary build. These are actual critic-fitting clocks, not acoustic "
              "generator training costs.", "",
              "Fit-data generation and both critic builds are included above. The second build "
              "kept exactly the same learned arrays and fit-selected fixed action after the public "
              "analytic baseline was made explicitly risk-sensitive; both builds' actual costs are "
              "counted. Public-model download, development/qualification and model loads are preparation "
              "costs, not free pretrained-model training. The original training cost of Piper and "
              "Whisper is unknown to this experiment. No claim that measured control benefits cover "
              "a deployment's economic or full foundational-model training costs is made.", "",
              "## Integrity checks and remaining claims", "",
              "All eight targeted unit/invariant checks passed before the evaluation freeze. Real "
              "development streaming and two-process execution were also exercised before evaluation. "
              "The final analysis verified the complete registered census, exact original prefix "
              "and committed spans, actual ASR input hashes, decisions matching frozen public models, "
              "and prefix/release/decision ordering under the frozen decision-before-generation executor. Qualification failures "
              "and actual recognition errors were preserved rather than corrected using hidden facts.", "",
              "The positive claims are bounded by the registered numerical gates above. Actual "
              "new speech, delayed shared-state propagation, independent terminal observation and "
              "cost-accounted executable control are now directly testable. A learned-feedback "
              "advantage must stand on its own primary and ablation results; the existence of a "
              "large hindsight oracle gap does not make it attainable from public observations.", "",
              "Outstanding scientific scope includes learned generative text rather than templates, "
              "joint acoustic/semantic generator training, multiple online decisions with delayed "
              "temporal dependencies, fresh natural sources and voices, human perceptual validation, "
              "missing-input multimodal robustness, video and audiovisual synchronization, and native "
              "admission/proposal integration of this specific speech backend. This Python output "
              "journal is not presented as the native admitted-tick journal/proposal chain. A genuine "
              "global-portfolio optimality or foundation-model superiority claim remains beyond this experiment.", "",
              "## Reproduction and retained evidence", "",
              "`README.md` documents the runnable sequence, public primary sources, models, licenses, "
              "frozen interfaces and dependencies. `SUMMARY.json` is the full compact aggregate evidence, "
              "including every fixed action, all registered contrasts, observer disagreement examples, "
              "per-seed risk results, tail summaries and cost accounting. `freeze-v1/` preserves the "
              "small source-role and protocol artifacts. Source code and this detailed report are the "
              "publication deliverable. Generated waves, raw fit/evaluation rows, downloaded model "
              "weights and critic checkpoints remain outside Git as requested.", ""]
    chronology = json.loads(args.chronology.read_text())
    lines += ["## Freeze and Git publication chronology", "",
              "This was a **local prospective freeze**, not a claim that the protocol was publicly "
              "committed to Git before testing. The source/protocol Git publication began after "
              "evaluation had already started. Local artifact timestamps below are filesystem "
              "mtime observations from the actual written records; they are not an independent "
              "external timestamping certificate.", "",
              "| Event | Recorded time |", "|---|---|"]
    timeline = [(event["event"], event["timestamp_utc"]) for event in chronology["events"]]
    timeline += [("First local source commit", chronology["local_source_commit_first"]["committer_timestamp"]),
                 ("Last local source/protocol commit", chronology["local_source_commit_last"]["committer_timestamp"])]
    for label, stamp in sorted(timeline, key=lambda row: datetime.fromisoformat(row[1])):
        lines.append(f"| {label} | `{datetime.fromisoformat(stamp).astimezone(timezone.utc).isoformat()}` |")
    lines += ["",
              f"The six local source stages run from `{chronology['local_source_commit_first']['sha']}` "
              f"through `{chronology['local_source_commit_last']['sha']}`. The parent verified remote "
              f"source publication through `{chronology['remote_source_tip_verified_by_parent']}`. "
              "Exact remote-server publication time was not independently sampled by this child. "
              "`PUBLICATION_CHRONOLOGY.json` preserves these identities and the distinction between "
              "the local freeze and later Git publication.", "",
              f"The original v1 full-process timing wrapper and launch plan were subsequently published "
              f"through remote `{chronology['original_v1_timing_measurement_source_remote_tip_verified_by_parent']}` "
              "before timing execution began. That wrapper rejected its launch after observing nonzero "
              "cumulative `RUSAGE_CHILDREN` values, before `Popen` and before any timing output existed. "
              "The origin of those prior cumulative counters was not directly established. "
              "`TIMING_WRAPPER_PREFLIGHT_FAILURE.json` preserves the failure without counting it as "
              "a discarded timing execution.", "",
              "The non-CORE wrapper was corrected to use `os.wait4` for the exact new child PID, "
              "with `Popen.returncode` assigned from its exit status. The unchanged timing child then "
              f"ran under locally pre-pinned v2 wrapper `{chronology['executed_measurement_wrapper_v2_sha256']}` "
              f"and plan `{chronology['executed_measurement_plan_v2_sha256']}`. We do not assert that "
              "the corrected v2 source was publicly published before that actual child launch. "
              "Neither this metrology correction nor the earlier v1 publication makes the original "
              "primary-quality run a publicly preregistered Git test.", ""]
    args.output.write_text("\n".join(lines))
    print(json.dumps({"report": str(args.output), "report_sha256": sha256(args.output),
                      "shared_state_gate": shared, "feedback_gate": feedback}))


if __name__ == "__main__":
    main()
