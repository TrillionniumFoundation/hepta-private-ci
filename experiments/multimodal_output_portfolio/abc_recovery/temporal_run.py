"""Prospectively gated fit/calibration/evaluation for actual AV stream restoration."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time
import traceback

from .temporal_codec import CommitSink, load_reference, observe_output
from .temporal_sources import digest, elapsed, save, save_json, usage
from .temporal_statistics import summarize
from .temporal_transport import (FEEDBACK, FIXED, FRAME_TICKS, fit_policy, loss,
                                 network_events, simulate)


MODULE = "experiments.multimodal_output_portfolio.abc_recovery.temporal_run"
CODE = ("temporal_run.py", "temporal_codec.py", "temporal_transport.py", "temporal_statistics.py",
        "temporal_sources.py", "temporal_tests.py")


def file_sha(path):
    return digest(Path(path).read_bytes())


def storage_gate(output, protocol):
    parent = Path(output).parent
    used = 0
    for path in parent.glob("causal-av-*"):
        used += path.stat().st_size if path.is_file() else sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
    capacity = protocol["serialization"]
    reserve = 32000000
    if used + reserve > capacity["maximum_artifact_bytes"]:
        raise RuntimeError("Registered causal AV artifact capacity would be exceeded; no evidence may be discarded")
    if shutil.disk_usage(parent).free < capacity["minimum_free_disk_bytes"] + reserve:
        raise RuntimeError("Insufficient reserved disk space for other active experiments")


def registered_sources(protocol, receipt, role):
    raw = {row["source_id"]: row for row in receipt["source_records"]}
    selected = []
    for source in protocol["sources"]:
        if source["role"] != role:
            continue
        known = raw[source["source_id"]]
        if any(known[key] != source[key] for key in ("speaker", "role", "video_sha256")):
            raise ValueError("Temporal source registration differs from the closed source receipt")
        selected.append({**known, **source})
    if [source["speaker"] for source in selected] != protocol["roles"][role]:
        raise ValueError("Source role census differs from the prospective split")
    return selected


def reference(source_root, source, output):
    inventory = Path(source_root) / "originals" / f"s{source['speaker']}" / "source-inventory.json"
    if file_sha(inventory) != source["source_inventory_sha256"]:
        raise ValueError("Original source inventory and actual PTS changed")
    return load_reference(source_root, source, output)


def frozen_fit(path, protocol_sha):
    model = json.loads(Path(path).read_bytes())
    if (model["protocol_sha256"] != protocol_sha or model["fit_role"] != "fit"
            or model["feedback_parameters"]["base_ms"] not in (80, 120, 160)
            or model["feedback_parameters"]["margin_ms"] not in (0, 40, 80)
            or model["fixed_comparison"] not in FIXED):
        raise ValueError("Fit policy is not compatible with the frozen protocol")
    if model["source_code_pins"]["temporal_transport.py"] != file_sha(Path(__file__).with_name("temporal_transport.py")):
        raise ValueError("Transport implementation changed after policy fitting")
    return model


def do_fit(args, protocol, receipt, pins):
    before = usage()
    sources = registered_sources(protocol, receipt, "fit")
    for source in sources:
        storage_gate(args.output, protocol)
        reference(args.source_root, source, args.output / "references" / f"s{source['speaker']}")
    result = fit_policy(sources)
    full = result.pop("full_candidate_records")
    with (args.output / "fit-candidates.jsonl.gz").open("xb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as stream:
            for record in full:
                stream.write((json.dumps(record, sort_keys=True) + "\n").encode())
    model = {"schema": "hepta.ndu-abc.causal-av-timeout-policy.v1", **result, "fit_role": "fit",
             "protocol_sha256": file_sha(args.protocol), "source_receipt_sha256": file_sha(args.source_receipt),
             "candidate_records_sha256": file_sha(args.output / "fit-candidates.jsonl.gz"),
             "source_code_pins": pins, "fit_cost": elapsed(before), "qualified": False,
             "finite_policy_search_not_audio_video_generator_training": True}
    model["parameter_sha256"] = digest(json.dumps({"feedback": model["feedback_parameters"],
        "fixed_comparison": model["fixed_comparison"], "risk_aversion_eta": 4.0}, sort_keys=True).encode())
    save_json(args.output / "policy.json", model)
    return {"fit_complete": True, "policy_sha256": file_sha(args.output / "policy.json"),
            "feedback_parameters": model["feedback_parameters"], "fixed_comparison": model["fixed_comparison"],
            "fit_source_groups": len(sources), "candidate_policies": len(full), "fit_cost": model["fit_cost"]}


def qualifying_case(ref, condition, output):
    before, sink = usage(), None
    try:
        sink = CommitSink(ref, output)
        for index in range(len(ref.frames)):
            sink.commit(index, {"video": index not in condition["drop_video"], "audio": index not in condition["drop_audio"]},
                        (index + 1) * FRAME_TICKS)
        path = sink.finish(condition["relative_audio_delay_ms"])
        result = observe_output(path, ref, sink.records, output)
        expected_video = (len(ref.frames) - len(condition["drop_video"])) / len(ref.frames)
        expected_audio = 1 - sum(len(ref.audio_slice(index)) for index in condition["drop_audio"]) / len(ref.audio)
        gate = (result["content_fidelity_passed"]
                and abs(result["signed_relative_audio_clock_offset_seconds"] - condition["relative_audio_delay_ms"] / 1000) <= .001
                and abs(result["source_delivery_video_fraction"] - expected_video) < 1e-12
                and abs(result["source_delivery_audio_fraction"] - expected_audio) < 1e-12
                and result["video_frames"] == 75 and result["audio_samples_per_channel"] == 131328)
        sink.cleanup(verified=gate)
        return {"passed": gate, "readback_sha256": file_sha(output / "readback.json"),
                "actual_file_bytes": result["actual_file_bytes"], "signed_clock_seconds": result["signed_relative_audio_clock_offset_seconds"],
                "video_coverage": result["source_delivery_video_fraction"], "audio_coverage": result["source_delivery_audio_fraction"],
                "valid_alignment_coverage": result["valid_alignment_coverage"], "content_fidelity": result["content_fidelity_passed"],
                "cost": elapsed(before)}
    except BaseException as error:
        if sink:
            sink.cleanup(verified=False)
        Path(output).mkdir(parents=True, exist_ok=True)
        failure = {"passed": False, "error": f"{type(error).__name__}: {error}",
                   "traceback": traceback.format_exc(), "cost": elapsed(before)}
        save_json(output / "failure.json", failure)
        return failure


def do_qualification(args, protocol, receipt, pins):
    model = frozen_fit(args.fit, file_sha(args.protocol))
    model_sha = file_sha(args.fit)
    sources = registered_sources(protocol, receipt, "calibration")
    rows = []
    for source in sources:
        storage_gate(args.output, protocol)
        ref = reference(args.source_root, source, args.output / "references" / f"s{source['speaker']}")
        for condition in protocol["qualification"]["conditions"]:
            storage_gate(args.output, protocol)
            result = qualifying_case(ref, condition, args.output / "cases" / f"s{source['speaker']}" / condition["name"])
            rows.append({"speaker": source["speaker"], "source_id": source["source_id"],
                         "condition": condition["name"], **result})
            print(f"qualification {len(rows)}/35 speaker={source['speaker']} condition={condition['name']} pass={result['passed']}", flush=True)
    passed = len(rows) == 35 and all(row["passed"] for row in rows) and file_sha(args.fit) == model_sha
    result = {"schema": "hepta.ndu-abc.causal-av-clock-qualification.v1", "qualified": passed,
              "protocol_sha256": file_sha(args.protocol), "policy_sha256": model_sha,
              "source_code_pins": pins, "speaker_groups": [source["speaker"] for source in sources],
              "conditions_per_speaker": 7, "actual_census": len(rows), "passed_cases": sum(row["passed"] for row in rows),
              "policy_parameters_unchanged": file_sha(args.fit) == model_sha, "rows": rows,
              "independent_lip_sync_qualified": False, "native_joint_generator_training_established": False,
              "qualification_meaning": "Actual lossless payload, delivery coverage and container-clock readback only"}
    save_json(args.output / "qualification.json", result)
    return {"qualified": passed, "qualification_sha256": file_sha(args.output / "qualification.json"),
            "actual_census": len(rows), "passed_cases": result["passed_cases"], "policy_sha256": model_sha}


def evaluation_case(ref, events, policy, parameters, output):
    before, sink, simulation = usage(), None, None
    try:
        sink = CommitSink(ref, output)
        simulation = simulate(events, policy, parameters, commit=sink.commit)
        save_json(output / "simulation.json", simulation)
        path = sink.finish()
        observed = observe_output(path, ref, sink.records, output)
        sink.cleanup()
        cost = elapsed(before)
        value = loss(observed["source_delivery_video_fraction"], observed["source_delivery_audio_fraction"],
                     observed["valid_alignment_clock_error_seconds"], simulation["mean_simulated_delivery_latency_seconds"],
                     observed["valid_alignment_coverage"])
        return {"completed_and_fidelity_passed": True, "loss": value,
                "q_video": observed["source_delivery_video_fraction"], "q_audio": observed["source_delivery_audio_fraction"],
                "joint_delivery_completion": observed["joint_delivery_completion"],
                "valid_alignment_coverage": observed["valid_alignment_coverage"],
                "valid_clock_error_seconds": observed["valid_alignment_clock_error_seconds"],
                "simulated_delivery_latency_seconds": simulation["simulated_delivery_latency_seconds"],
                "service_wall_seconds": cost["wall_seconds"], "service_cpu_seconds": cost["cpu_seconds"] + cost["child_cpu_seconds"],
                "policy_wall_seconds": simulation["actual_cost"]["policy_wall_seconds"],
                "policy_cpu_seconds": simulation["actual_cost"]["policy_cpu_seconds"],
                "actual_file_sha256": observed["actual_file_sha256"], "readback_sha256": file_sha(output / "readback.json")}
    except BaseException as error:
        if sink:
            sink.cleanup(verified=False)
        cost = elapsed(before)
        result = {"completed_and_fidelity_passed": False, "loss": 1.0, "q_video": 0.0, "q_audio": 0.0,
                  "joint_delivery_completion": 0.0, "valid_alignment_coverage": 0.0, "valid_clock_error_seconds": None,
                  "service_wall_seconds": cost["wall_seconds"], "service_cpu_seconds": cost["cpu_seconds"] + cost["child_cpu_seconds"],
                  "error": f"{type(error).__name__}: {error}", "traceback": traceback.format_exc()}
        Path(output).mkdir(parents=True, exist_ok=True)
        save_json(output / "failure.json", result)
        return result


def do_evaluation(args, protocol, receipt, pins):
    model = frozen_fit(args.fit, file_sha(args.protocol))
    qualified = json.loads(Path(args.qualification).read_bytes())
    release = json.loads(Path(args.eval_release).read_bytes())
    required = {"protocol_sha256": file_sha(args.protocol), "policy_sha256": file_sha(args.fit),
                "qualification_sha256": file_sha(args.qualification)}
    if (not qualified["qualified"] or qualified["protocol_sha256"] != required["protocol_sha256"]
            or qualified["policy_sha256"] != required["policy_sha256"]
            or any(release.get(key) != value for key, value in required.items())
            or release.get("authorized_by") != "root" or not release.get("AB_mechanism_result_sha256")):
        raise ValueError("Evaluation requires matching qualification and explicit root release after A/B mechanism results")
    if any(qualified["source_code_pins"][name] != pins[name] for name in ("temporal_codec.py", "temporal_transport.py")):
        raise ValueError("Qualified temporal codec or transport implementation changed")
    save_json(args.output / "eval-release.json", release)
    rows, blocked = [], None
    for source in registered_sources(protocol, receipt, "evaluation"):
        ref, source_error = None, blocked
        if blocked is None:
            try:
                storage_gate(args.output, protocol)
                ref = reference(args.source_root, source, args.output / "references" / f"s{source['speaker']}")
            except Exception as error:
                source_error = f"Source setup failed: {type(error).__name__}: {error}"
        for scenario, seed in enumerate(source["scenario_seeds"]):
            events = network_events(seed, scenario)
            parent = args.output / "episodes" / f"s{source['speaker']}" / f"scenario-{scenario}"
            parent.mkdir(parents=True, exist_ok=False)
            save_json(parent / "environment-private-events.json", {"seed": seed, "events": events, "passed_to_policy": False})
            order = sorted(FIXED + (FEEDBACK,), key=lambda policy: hashlib.sha256(
                f"hepta-causal-av-order-v1|{source['source_id']}|{scenario}|{policy}".encode()).hexdigest())
            for policy in order:
                if source_error is None and blocked is None:
                    try:
                        storage_gate(args.output, protocol)
                    except Exception as error:
                        blocked = f"Remaining registered cases not executed: {type(error).__name__}: {error}"
                if source_error is not None or blocked is not None:
                    result = {"completed_and_fidelity_passed": False, "loss": 1.0,
                              "q_video": 0.0, "q_audio": 0.0, "joint_delivery_completion": 0.0,
                              "valid_alignment_coverage": 0.0, "valid_clock_error_seconds": None,
                              "unexecuted": True, "error": blocked or source_error}
                else:
                    result = evaluation_case(ref, events, policy, model["feedback_parameters"] if policy == FEEDBACK else None, parent / policy)
                row = {"speaker": source["speaker"], "source_id": source["source_id"], "scenario": scenario, "policy": policy, **result}
                rows.append(row)
                save_json(parent / (policy + ".json"), row)
                print(f"evaluation {len(rows)}/192 speaker={source['speaker']} scenario={scenario} policy={policy} complete={result['completed_and_fidelity_passed']}", flush=True)
    result = summarize(rows, protocol["roles"]["evaluation"], model["fixed_comparison"])
    result.update(protocol_sha256=file_sha(args.protocol), policy_sha256=file_sha(args.fit), source_code_pins=pins)
    save_json(args.output / "evaluation.json", result)
    return result


def worker(args):
    before = usage()
    if not args.output.name.startswith("causal-av-"):
        raise ValueError("Causal AV runs must use the shared budget's causal-av- prefix")
    args.output.mkdir(parents=True, exist_ok=False)
    try:
        protocol = json.loads(args.protocol.read_bytes())
        receipt = json.loads(args.source_receipt.read_bytes())
        if file_sha(args.source_receipt) != protocol["source_receipt_sha256"]:
            raise ValueError("Source receipt differs from the frozen causal AV protocol")
        if file_sha(args.source_root / "selected-source-manifest.json") != protocol["source_selection_sha256"]:
            raise ValueError("Source selection differs from prospective registration")
        pins = {}
        for name in CODE:
            pins[name] = save(args.output / name, Path(__file__).with_name(name).read_bytes())
        save(args.output / "protocol.json", args.protocol.read_bytes())
        save_json(args.output / "registration.json", {"phase": args.phase, "protocol_sha256": file_sha(args.protocol),
                  "source_receipt_sha256": file_sha(args.source_receipt), "source_code_pins": pins,
                  "fit_sha256": file_sha(args.fit) if args.fit else None,
                  "qualification_sha256": file_sha(args.qualification) if args.qualification else None,
                  "real_media_simulated_network": True, "evaluation_authorization_required": True})
        function = {"fit": do_fit, "qualify": do_qualification, "evaluate": do_evaluation}[args.phase]
        result = function(args, protocol, receipt, pins)
        result.update(phase=args.phase, whole_worker_cost=elapsed(before),
                      source_code_unchanged=all(file_sha(Path(__file__).with_name(name)) == value for name, value in pins.items()))
        save_json(args.output / "summary.json", result)
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0 if result.get("qualified", True) and result["source_code_unchanged"] else 1
    except BaseException as error:
        save_json(args.output / "failure.json", {"phase": args.phase, "error": f"{type(error).__name__}: {error}",
                  "traceback": traceback.format_exc(), "cost": elapsed(before)})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("fit", "qualify", "evaluate"), required=True)
    for name in ("protocol", "source-receipt", "source-root", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("fit", "qualification", "eval-release"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    if args.phase in ("qualify", "evaluate") and not args.fit:
        parser.error("Qualification/evaluation require a frozen --fit policy")
    if args.phase == "evaluate" and (not args.qualification or not args.eval_release):
        parser.error("Evaluation requires --qualification and --eval-release")
    if args.worker:
        sys.exit(worker(args))
    if args.output.exists():
        raise FileExistsError("Temporal run directories cannot be overwritten")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    before, usage_before = time.monotonic(), resource.getrusage(resource.RUSAGE_CHILDREN)
    command = [sys.executable, "-m", MODULE, *sys.argv[1:], "--worker"]
    with args.output.with_suffix(".process.log").open("x") as stream:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            stream.write(line)
            stream.flush()
            print(line, end="", flush=True)
        returncode = process.wait()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    save_json(args.output.with_suffix(".process.json"), {"argv": command, "returncode": returncode,
              "whole_child_process_wall_seconds": time.monotonic() - before,
              "whole_child_process_cpu_seconds": after.ru_utime + after.ru_stime - usage_before.ru_utime - usage_before.ru_stime,
              "child_maximum_rss_bytes": after.ru_maxrss * 1024})
    sys.exit(returncode)


if __name__ == "__main__":
    main()
