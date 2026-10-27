"""Independent complete selected-path media/feedback/score audit."""

import argparse
import json
from pathlib import Path
import time

from feedback_evidence import MediaIndex, ObserverArithmetic
from runtime_audit_support import file_sha, open_profile, records, require, verify_unchanged
from runtime_media_context import cases_for, load_context, unchanged_observers
from runtime_media_trace import SelectedTraceAudit


def expected_resources(summary):
    episodes, deliveries = summary["episodes"], summary["logical_media_deliveries"]
    result = {"encoder_examples": episodes, "encoder_batches": episodes,
        "transition_examples": deliveries, "transition_batches": deliveries,
        "decoder_examples": deliveries, "decoder_batches": deliveries,
        "public_feature_observer_digit_examples": 2 * summary["public_events_rebuilt"],
        "media_logical_deliveries_read_back": deliveries,
        "simulated_feedback_packets": summary.get("feedback_packets_rebuilt", 0),
        "reward_outcome_observer_digit_examples": 2 * episodes, "audit_outcome_observer_digit_examples": 2 * episodes,
        "unchosen_continuations_executed": 0,
        "physical_media_records": summary["physical_media_records"], "physical_media_bytes": summary["physical_media_bytes"]}
    for name in ("native_tick_calls", "selection_rows", "selection_batches", "select_wall_ns", "select_python_cpu_ns", "native_ns"):
        result[name] = summary[name]
    return result


def join_native(receipt, profile, freeze_sha, summaries):
    require(receipt["passed"] is True and receipt["profile"] == profile and receipt["freeze_sha256"] == freeze_sha and
            receipt["generator_forward_calls"] == receipt["observer_forward_calls"] == 0 and
            receipt["discrepancies"] == 0, "Native replay did not verify this selected profile/freeze")
    require(set(receipt["seeds"]) == {str(item["seed"]) for item in summaries}, "Native replay seed coverage differs")
    for item in summaries:
        replay = receipt["seeds"][str(item["seed"])]
        require(replay["inputs"] == {key: value for key, value in item["inputs"].items() if key != "rows_sha256" and key != "media_sha256"} and
                replay["decision_coverage_sha256"] == item["decision_coverage_sha256"] and
                replay["verification_native_ticks"] == item["native_tick_calls"],
                "Actual-media and native replay input/history/action coverage differs")
        for arm in ("native", "reset_native"):
            native, media = replay["per_arm"][arm], item["per_arm"][arm]
            require(native["sessions"] == media["episodes"] and native["decisions"] == media["decisions"] and
                    native["ticks"] == 2 * media["decisions"] and
                    all(native.get(f"round_{stage}_decisions", 0) == media.get(f"round_{stage}_decisions", 0) for stage in range(3)),
                    "Native/media episode or decision-stage coverage differs")


def execute(run, profile, source, freeze, assets, native_audit=None):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    bundle = open_profile(run, profile, source, freeze)
    corpus, observers, fingerprints, asset_identity = load_context(assets, source, ["runtime_audit"], bundle["protocol"])
    arithmetic, summaries = ObserverArithmetic(observers), []
    for item in bundle["seeds"]:
        require(item["complete"]["observer_parameter_sha256"] == fingerprints, "Selected observer differs from the actual pinned observer")
        cases, groups, panel_sha = cases_for(corpus, "runtime_audit", item["seed"], bundle["protocol"])
        trace = SelectedTraceAudit(MediaIndex(item["selected"] / "media.h3m"), arithmetic, item["policies"], cases, groups,
                                   item["seed"], profile)
        for row, _ in records(item["selected"] / "events.jsonl.gz"):
            trace.process(row)
        summary = trace.finish(row for row, _ in records(item["selected"] / "rows.jsonl.gz"))
        require(expected_resources(summary) == item["complete"]["resources"], "Actual selected media/decision cost ledger differs")
        summaries.append({"seed": item["seed"], "source_panel_sha256": panel_sha, **summary,
            "inputs": {"parent_complete_sha256": item["input_sha256"]["parent_complete"],
                "selected_complete_sha256": item["input_sha256"]["selected_complete"],
                "events_sha256": item["input_sha256"]["events.jsonl.gz"], "rows_sha256": item["input_sha256"]["rows.jsonl.gz"],
                "media_sha256": item["input_sha256"]["media.h3m"], "readouts_sha256": item["input_sha256"]["readouts"],
                "fit_complete_sha256": item["input_sha256"]["fit_complete"]}})
        print(json.dumps({"seed": item["seed"], "profile": profile, "status": "pass", "episodes": summary["episodes"],
                          "logical_media_deliveries": summary["logical_media_deliveries"]}), flush=True)
    native_sha = None
    if native_audit is not None:
        native_sha = file_sha(native_audit)
        join_native(json.loads(Path(native_audit).read_text()), profile, bundle["freeze_sha256"], summaries)
        require(file_sha(native_audit) == native_sha, "Native replay receipt changed during media join")
    unchanged_observers(observers, fingerprints)
    verify_unchanged(bundle)
    return {"schema": "hepta.field-bridge.v3.independent-selected-media.1", "status": "pass", "passed": True,
        "profile": profile, "seeds": summaries, "protocol_sha256": bundle["protocol_sha256"],
        "freeze_sha256": bundle["freeze_sha256"], "source_manifest_sha256": bundle["protocol"]["source_manifest_sha256"],
        "original_assets": asset_identity, "observer_parameter_sha256": fingerprints,
        "exact_media_event_feedback_score_discrepancies": 0,
        "native_replay_receipt_sha256": native_sha,
        "native_replay_required_for_acceptance": True, "native_replay_joined": native_sha is not None,
        "generator_forward_calls": 0, "native_tick_calls": 0,
        "verification_observer_digit_forwards": arithmetic.calls, "logical_observer_image_pairs": arithmetic.logical_images,
        "additional_verification_only": True, "new_independent_observations": 0,
        "verification_wall_ns": time.perf_counter_ns() - started, "verification_cpu_ns": time.process_time_ns() - cpu,
        "scope": "All selected actual bytes, public events, partial feedback, causal action chronology, fixed/current/history heads, both terminal scores and exact work counts; native arithmetic requires the matching separate replay",
        "public_logits_scope": "Exact retained H3M bytes and public softmax are checked; neural decoder logits are not regenerated",
        "reviewer_source_files": {name: file_sha(Path(__file__).with_name(name)) for name in
            ("runtime_media_audit.py", "runtime_media_trace.py", "runtime_bank_media_audit.py", "runtime_media_context.py",
             "runtime_audit_support.py", "feedback_evidence.py")}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "source", "freeze", "assets", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--profile", required=True, choices=("frozen", "ordinary", "field"))
    parser.add_argument("--native-audit")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    require(not output.is_relative_to((Path(args.run) / "runtime").resolve()) and not output.exists(),
            "Audit output must be new and outside immutable runtime evidence")
    result = execute(args.run, args.profile, args.source, args.freeze, args.assets, args.native_audit)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"passed": True, "profile": args.profile, "native_replay_joined": result["native_replay_joined"],
                      "receipt_sha256": file_sha(output)}))
