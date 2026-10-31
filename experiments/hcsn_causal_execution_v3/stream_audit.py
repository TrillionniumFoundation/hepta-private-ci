"""Independent raw-record audit; imports neither runner analysis nor scoring."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


PACKAGE = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def locate(recorded):
    marker = "/experiments/hcsn_causal_execution_v3/"
    return PACKAGE / str(recorded).split(marker, 1)[1]


def check_trace(row, descriptor, payload, policy):
    previous = [1 / len(row["probability"])] * len(row["probability"])
    acquired, times, latest, clocks = [], [], {}, {}
    headers = descriptor["headers"]
    for index, event in enumerate(row["trace"]):
        header = headers[index]
        assert (event["index"], event["time"], event["modality"]) == (index, header["time"], header["modality"])
        assert event["before"] == previous
        if not header["available"]:
            expected = "WAIT"
        elif policy["kind"] == "all":
            expected = "READ"
        elif policy["kind"] == "periodic":
            expected = "READ" if round(header["time"] / policy["period_seconds"]) % 2 == 0 else "WAIT"
        else:
            expected = "STOP" if len(acquired) >= policy["minimum_reads"] and max(previous) >= policy["threshold"] else "READ"
        assert event["action"] == expected and event["payload_read"] == (expected == "READ")
        probability = np.asarray(event["after"])
        assert np.isfinite(probability).all() and np.all(probability >= 0) and abs(probability.sum() - 1) < 1e-12
        if expected == "READ":
            kind = str(header["modality"])
            value = np.zeros(40, np.float32)
            value[:16] = payload[index]
            if kind in latest:
                value[16:32] = payload[index].astype(float) - latest[kind]
            latest[kind], clocks[kind] = payload[index].astype(float), header["time"]
            value[32 + int(kind)] = value[34 + int(kind)] = 1
            for channel in latest:
                value[36 + int(channel)], value[38 + int(channel)] = header["time"] - clocks[channel], 1
            acquired.append(value.tolist())
            times.append(header["time"])
        else:
            assert event["after"] == previous
        if expected == "STOP":
            assert index == len(row["trace"]) - 1
        previous = event["after"]
    assert len(row["trace"]) == len(headers) or row["trace"][-1]["action"] == "STOP"
    assert previous == row["probability"]
    assert row["encoder_calls"] == row["payload_reads"] == len(acquired)
    assert row["logical_payload_bytes"] == 64 * len(acquired)
    return acquired, times


def audit(output):
    output = Path(output)
    plan, summary, selection = (read(output / name) for name in ("PROTOCOL.json", "SUMMARY.json", "SELECTION_COMPLETE.json"))
    assert all(sha(PACKAGE / name) == value for name, value in plan["sources"].items())
    assert all(sha(locate(row["path"])) == row["sha256"] for row in plan["models"].values())
    assert plan["policy_order"][0] == "all"
    stores, trajectories, actions, recovered_count, result_count = {}, {}, 0, 0, 0
    for manifest_path in sorted((output / "stores").glob("*/*/MANIFEST.json")):
        manifest = read(manifest_path)
        for record in manifest["rows"]:
            path = locate(record["directory"])
            descriptor = read(path / "headers.json")
            blob = (path / "payload.bin").read_bytes()
            assert sha(path / "payload.bin") == descriptor["payload_sha256"] == record["payload_sha256"]
            payload = np.frombuffer(blob, dtype="<f4").reshape(-1, 16)
            assert len(payload) == len(descriptor["headers"]) == record["events"]
            assert all(hashlib.sha256(row.tobytes()).hexdigest() == identity for row, identity in zip(payload, descriptor["payload_hashes"], strict=True))
            stores[(manifest_path.parent.parent.name, manifest_path.parent.name, record["sample_id"])] = record, descriptor, payload
    result_paths = sorted((output / "validation").glob("*/*/RESULT.json")) + sorted((output / "test").glob("*/RESULT.json"))
    for path in result_paths:
        result = read(path)
        task, split = result["task"], result["split"]
        assert result["model_sha256"] == plan["models"][task]["sha256"]
        for row in result["rows"]:
            record, descriptor, payload = stores[(split, task, row["sample_id"])]
            assert row["label"] == record["label"] and row["actor"] == record["actor"]
            accepted, times = check_trace(row, descriptor, payload, plan["policies"][result["policy_name"]])
            trajectories[(str(path.parent), row["sample_id"])] = accepted, times
            actions += len(row["trace"])
        p = np.array([row["probability"] for row in result["rows"]])
        y = np.array([row["label"] for row in result["rows"]])
        assert len(y) == result["examples"] and abs((p.argmax(1) == y).mean() - result["accuracy"]) < 1e-12
        assert abs(-np.log(np.maximum(p[np.arange(len(y)), y], 1e-15)).mean() - result["ce"]) < 1e-12
        assert sum(row["encoder_calls"] for row in result["rows"]) == result["encoder_calls"]
        assert sum(row["logical_payload_bytes"] for row in result["rows"]) == result["logical_payload_bytes"]
        result_count += 1
    details = {}
    for task in plan["tasks"]:
        candidates = [read(output / "validation" / task / name / "RESULT.json") for name in plan["policy_order"]]
        baseline = candidates[0]
        eligible = [row for row in candidates if row["accuracy"] >= baseline["accuracy"] and row["ce"] <= baseline["ce"] + plan["validation_ce_tolerance"]]
        chosen = min(eligible, key=lambda row: row["encoder_calls"])
        assert chosen["policy_name"] == selection[task]["policy_name"]
        for key, value in (("validation_accuracy", chosen["accuracy"]), ("validation_ce", chosen["ce"]), ("encoder_calls", chosen["encoder_calls"])):
            assert selection[task][key] == value
        repeats = [(path.parent, read(path)) for path in sorted((output / "test").glob(f"test_{task}_*/RESULT.json"))]
        for side, policy_name in (("baseline", "all"), ("selected", chosen["policy_name"])):
            matching = [(path, row) for path, row in repeats if row["policy_name"] == policy_name]
            reported = summary["tasks"][task][side]
            assert len(matching) == reported["timing_repeats"] == plan["timing_repeats"] * (2 if chosen["policy_name"] == "all" else 1)
            durations = [r["episode_wall_seconds"] for _, row in matching for r in row["rows"]]
            receipts = [read(output / "meter" / (path.name + ".json")) for path, _ in matching]
            assert abs(np.median(durations) * 1000 - reported["episode_latency_p50_ms"]) < 1e-10
            assert abs(np.quantile(durations, .95) * 1000 - reported["episode_latency_p95_ms"]) < 1e-10
            assert [row["cpu_seconds"] for row in receipts] == reported["repeat_worker_cpu_seconds"]
            assert np.median([row["cpu_seconds"] for row in receipts]) == reported["median_worker_cpu_seconds"]
            assert np.median([row["wall_seconds"] for row in receipts]) == reported["median_worker_wall_seconds"]
            reference = matching[0][1]
            assert all([(r["trace"], r["probability"]) for r in row["rows"]] == [(r["trace"], r["probability"]) for r in reference["rows"]] for _, row in matching)
        with np.load(PACKAGE / "results/av_probe" / task / "test_normal.npz", allow_pickle=False) as old:
            error = float(np.max(np.abs(np.array([r["probability"] for r in reference["rows"]]) - old["probabilities"])))
            assert error <= 1e-12
        recovery_dir = output / "test" / ("recovery_" + task + "_" + chosen["policy_name"])
        recovery = read(recovery_dir / "RESULT.json")
        for index, (row, expected) in enumerate(zip(recovery["rows"], reference["rows"], strict=True)):
            assert all(row[key] == expected[key] for key in ("sample_id", "trace", "probability", "encoder_calls", "logical_payload_bytes"))
            checkpoint_path = recovery_dir / f"sample{index:03}.checkpoint.json"
            checkpoint, resumed = read(checkpoint_path), read(recovery_dir / f"sample{index:03}.resumed.json")
            assert checkpoint["encoder_identity"] == plan["models"][task]["sha256"]
            assert sha(locate(checkpoint["source_directory"]) / "headers.json") == checkpoint["header_sha256"]
            assert checkpoint["state"]["trace"] == row["trace"][:plan["recovery_after_headers"]]
            accepted, times = trajectories[(str(recovery_dir), row["sample_id"])]
            assert resumed["state"]["rows"] == accepted and resumed["state"]["times"] == times
            assert resumed["state"]["trace"] == row["trace"] and resumed["state"]["probabilities"] == row["probability"]
            assert checkpoint["state"]["rows"] == accepted[:checkpoint["payload_reads"]]
            assert resumed["payload_reads"] == row["encoder_calls"] and resumed["payload_bytes"] == row["logical_payload_bytes"]
            assert row["recovery"]["serialization"]["bytes"] == row["recovery"]["restore"]["bytes"] == checkpoint_path.stat().st_size
            recovered_count += 1
        details[task] = dict(selected_policy=chosen["policy_name"], eligible_policies=[r["policy_name"] for r in eligible],
                            repeated_runs=len(repeats), recovered_episodes=len(recovery["rows"]), baseline_probability_max_error=error)
    meters = {path.stem: read(path) for path in (output / "meter").glob("*.json")}
    assert len(meters) == 26 and meters == summary["process_receipts"] and "STUDY_PROCESS_RECEIPT" not in meters
    assert all(row["returncode"] == 0 and sha(output / "meter" / (name + ".log")) == row["log_sha256"] for name, row in meters.items())
    assert abs(sum(row["cpu_seconds"] for row in meters.values()) - summary["metered_worker_cpu_seconds"]) < 1e-10
    assert abs(sum(row["wall_seconds"] for row in meters.values()) - summary["metered_worker_wall_seconds"]) < 1e-10
    outer = read(output.parent / "STUDY_PROCESS_RECEIPT.json")
    assert outer["returncode"] == 0 and outer["cpu_seconds"] >= summary["metered_worker_cpu_seconds"]
    assert sha(output.parent / "STUDY_PROCESS_RECEIPT.log") == outer["log_sha256"]
    return dict(all_passed=True, auditor_sha256=sha(__file__), protocol_sha256=sha(output / "PROTOCOL.json"),
        tasks=details, result_files=result_count, action_records=actions, restart_episodes=recovered_count,
        worker_receipts=len(meters), inner_worker_cpu_seconds=summary["metered_worker_cpu_seconds"],
        outer_study_cpu_seconds=outer["cpu_seconds"], enclosing_receipt_excluded_from_inner_sum=True,
        limitations="Offline trace/data/integrity/score audit; process receipts are observed records, not hardware attestations. No sensor/network/energy or fresh-actor claim.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--study", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.study)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(result, indent=2))
