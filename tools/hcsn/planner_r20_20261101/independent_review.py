"""Independent standard-library source, recovery and resource-record review."""

import argparse
import gzip
import hashlib
import itertools
import json
import os
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def signed(body):
    result = dict(body)
    digest = result.pop("sha256")
    assert hashlib.sha256(encoded(result)).hexdigest() == digest
    return result


def source():
    manifest = json.loads((HERE / "SOURCE_MANIFEST.json").read_text())
    assert sha(HERE / "SOURCE_MANIFEST.json") == "a5bfa4585170b2650e7cf56c15c587d8bc3ae94a0df26b0def7993b6b42f69a2"
    assert all(sha(ROOT / name) == digest for name, digest in manifest["files"].items())
    remote = json.loads((HERE / "INDEPENDENT_REMOTE_BINDINGS.json").read_text())
    for entry in remote["files"]:
        raw = (HERE / entry["path"]).read_bytes()
        assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == entry["git_blob_sha1"]
    inputs = json.loads((HERE / "FROZEN_TRAINING_INPUTS.json").read_text())
    for entry in inputs["files"]:
        raw = (ROOT / entry["path"]).read_bytes()
        assert len(raw) == entry["bytes"] and sha(ROOT / entry["path"]) == entry["sha256"]
        assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == entry["git_blob_sha1"]
    return dict(passed=True, frozen_source_files=len(manifest["files"]), remote_blobs=len(remote["files"]),
                exact_training_archives=len(inputs["files"]), manifest_sha256=sha(HERE / "SOURCE_MANIFEST.json"))


def recovery():
    identities = source()
    folder = HERE / "recovery_confirmation_01"
    summary = json.loads((folder / "SUMMARY.json").read_text())
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    training = ROOT / "tools/hcsn/addressed_decision_r15_20261101/run_01/training/151101.json.gz"
    law = json.loads(gzip.decompress(training.read_bytes()))["calibration"]["models"]["hx"]["payload"]
    modes = ("baseline", "r18", "r19", "r20")
    hashes = {str(p.relative_to(folder)): sha(p) for p in folder.rglob("*") if p.is_file()}
    checks, action_counts = 0, {}
    semantic_fields = lambda row: {k: v for k, v in row.items() if k not in
        ("cpu_seconds", "wall_seconds", "checkpoint_io_cpu_seconds")}
    for mode, representation in itertools.product(modes, protocol["representations"]):
        group = folder / (mode + "_" + representation)
        reference = json.loads((group / "reference/OUTPUT.json").read_text())
        inp = json.loads((group / "reference/INPUT.json").read_text())
        assert inp["law"] == law and inp["seed"] == 2000999101 and inp["domain"] == "ood"
        assert inp["variant"] == mode and inp["representation"] == representation
        assert json.loads((group / "reference/PROCESS.json").read_text())["exit_code"] == 0
        assert reference["fsync_calls"] == ["file", "directory"] * 6
        target = reference["result"]
        assert len(target["queries"]) == 6 and len(target["checkpoint_receipts"]) == 6
        actions = [a["action"] for q in target["queries"] for a in q["actions"]]
        action_counts[group.name] = {name: actions.count(name) for name in ("READ", "WAIT", "REFRESH")}
        for completed in range(6):
            lost = group / ("lost_query_" + str(completed))
            resumed = group / ("resume_query_" + str(completed))
            request = json.loads((lost / "INPUT.json").read_text())
            assert request["law"] == law and request["stop_after_query"] == completed and request["die_before_reply"]
            assert request["variant"] == mode and request["representation"] == representation
            assert json.loads((lost / "PROCESS.json").read_text())["exit_code"] == -9
            assert not (lost / "OUTPUT.json").exists()
            payload = json.loads((lost / "state.json").read_text())
            body = signed(payload)
            memory = signed(payload["memory"])
            assert body["schema"] == "hcsn-r20-query-checkpoint-v1"
            assert body["completed_query"] == completed and len(body["history"]) == completed + 1
            assert body["model"] == law["identity"] and body["world"] == target["world"]
            assert body["representation"] == representation and body["seed"] == 2000999101
            assert payload["memory"]["sha256"] == target["queries"][completed]["checkpoint_sha256"]
            assert memory["model"] == law["identity"] and abs(memory["clock"] - target["queries"][completed]["deadline"]) < 1e-10
            for index, public in enumerate(body["history"]):
                expected = {k: v for k, v in target["queries"][index].items() if k not in ("target", "reward", "utility")}
                assert public == expected and not {"target", "reward", "utility"}.intersection(public)
                assert body["receipts"][index] == dict(query=index, file_fsyncs=1, directory_fsyncs=1,
                                                       memory_sha256=expected["checkpoint_sha256"])
                checks += 3
            reply = json.loads((resumed / "OUTPUT.json").read_text())
            resume_input = json.loads((resumed / "INPUT.json").read_text())
            assert resume_input["law"] == law and resume_input["resume_path"] == str(lost / "state.json").replace(str(ROOT) + "/", "")
            assert json.loads((resumed / "PROCESS.json").read_text())["exit_code"] == 0
            assert semantic_fields(reply["result"]) == semantic_fields(target)
            assert reply["fsync_calls"] == ["file", "directory"] * (5 - completed)
            if completed == 5:
                assert not (resumed / "state.json").exists()
            else:
                final = json.loads((resumed / "state.json").read_text())
                signed(final)
                assert final["completed_query"] == 5 and final["history"] == [
                    {k: v for k, v in q.items() if k not in ("target", "reward", "utility")} for q in target["queries"]]
            checks += 18
    for expected_phase in ("file_fsync", "replace", "directory_fsync"):
        group = folder / ("atomic_" + expected_phase)
        request = json.loads((group / "killed/INPUT.json").read_text())
        assert request["persist_phase"] == expected_phase
        assert json.loads((group / "killed/PROCESS.json").read_text())["exit_code"] == -9
        assert not (group / "killed/OUTPUT.json").exists()
        recorded = next(row for row in summary["atomic_windows"] if row["phase"] == expected_phase)
        assert signed(recorded["recovered"])["value"] == (1 if expected_phase == "file_fsync" else 2)
        assert signed(json.loads((group / "state.json").read_text()))["value"] == 3
        checks += 6
    process_files = list(folder.rglob("PROCESS.json"))
    assert len(process_files) == 107 == summary["process_count"]
    assert len(summary["cases"]) == 48 and summary["lost_reply_cases"] == 48 and summary["passed"]
    assert {json.loads(p.read_text())["exit_code"] for p in process_files} == {0, -9}
    receipt = json.loads((folder / "PROCESS_RECEIPT.json").read_text())
    assert receipt["exit_code"] == 0
    return dict(passed=True, checks=checks, source=identities, files_sha256=hashes,
                processes=107, lost_reply_cases=48, atomic_windows=3, reference_action_counts=action_counts,
                complete_child_family_cpu_seconds=receipt["complete_child_family_cpu_seconds"],
                scope="Independent standard-library raw replay and checksum/history/model/source binding. Fsync syscall probes call real os.fsync; lost-process calls additionally rely on frozen source. One HX episode per representation/variant, READ only; no WAIT/REFRESH, mid-query external effect, power-loss or multiwriter qualification.")


def resources():
    identities = source()
    folder = HERE / "confirmation_01"
    summary = json.loads((folder / "SUMMARY.json").read_text())
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    modes = ("baseline", "r18", "r19", "r20")
    wanted = set(itertools.product(protocol["fits"], protocol["models"], protocol["representations"]))
    found, worlds, costs, hashes, checks, calculated = set(), set(), {m: 0. for m in modes}, {}, 0, []
    for path in sorted(folder.glob("*.json.gz")):
        hashes[path.name] = sha(path)
        data = json.loads(gzip.decompress(path.read_bytes()))
        group, rows = data["group"], data["records"]
        key = group["fit"], group["model"], group["representation"]
        assert key in wanted and key not in found
        found.add(key)
        assert len(rows) == protocol["uses_per_fit_group"] == group["uses"]
        cpu, wall = dict(group["preparation"]), {m: 0. for m in modes}
        for index, row in enumerate(rows):
            assert row["index"] == index and row["seed"] == protocol["namespace"] * 10**10 + group["fit"] * 10**4 + index
            assert row["order"] == list(modes[index % 4:] + modes[:index % 4])
            worlds.add((row["seed"], row["world"]))
            reference = row["modes"]["baseline"]["semantic"]
            for mode in modes:
                record = row["modes"][mode]
                body = record["semantic"]
                assert hashlib.sha256(encoded(body)).hexdigest() == record["semantic_sha256"] and body == reference
                assert body["seed"] == row["seed"] and body["world"] == row["world"]
                assert len(body["queries"]) == 6 and len(body["checkpoint_receipts"]) == 6
                for q, receipt in zip(body["queries"], body["checkpoint_receipts"], strict=True):
                    assert receipt == dict(query=q["query"], file_fsyncs=1, directory_fsyncs=1, memory_sha256=q["checkpoint_sha256"])
                    slots, fee = 0, 0.
                    for action in q["actions"]:
                        consumed = 2 if action["action"] == "REFRESH" else 1
                        slots += consumed
                        fee += .003 * consumed * q["dt"]
                        fee += {"READ": .025, "WAIT": 0., "REFRESH": .07}[action["action"]] * q["price_scale"]
                        assert action["step"] == slots
                    assert abs(fee - q["fee"]) <= 1e-14
                    assert q["reward"] == int(q["answer"] == q["target"])
                    assert abs(q["utility"] - q["reward"] + q["fee"]) <= 1e-14
                    assert abs(q["submitted_after"] - slots * q["dt"]) <= 1e-14
                    checks += 5
                for name in ("fee", "utility", "reward"):
                    assert abs(sum(q[name] for q in body["queries"]) / 6 - body[name]) <= 1e-14
                    checks += 1
                cpu[mode] += record["cpu_seconds"]
                wall[mode] += record["wall_seconds"]
                checks += 3
            checks += 2
        for mode in modes:
            assert abs(cpu[mode] - group["cpu_with_preparation"][mode]) < 1e-10
            assert abs(wall[mode] - group["actor_wall_seconds"][mode]) < 1e-10
            assert abs(len(rows) / wall[mode] - group["actor_episodes_per_second"][mode]) < 1e-10
            memory = group["memory"][mode]
            assert len(memory["peaks"]) == 8 and max(memory["peaks"]) == memory["maximum"]
            assert abs(sum(memory["peaks"]) / 8 - memory["mean"]) < 1e-10
            costs[mode] += cpu[mode]
            checks += 5
        ratios = dict(baseline=cpu["r20"] / cpu["baseline"], r18=cpu["r20"] / cpu["r18"],
                      r19=cpu["r20"] / cpu["r19"], peak=group["memory"]["r20"]["maximum"] / group["memory"]["r18"]["maximum"])
        for suffix, name in (("baseline_cpu", "baseline"), ("r18_cpu", "r18"), ("r19_cpu", "r19"), ("r18_peak", "peak")):
            assert abs(ratios[name] - group["r20_" + suffix + "_ratio"]) < 1e-12
        calculated.append(dict(fit=key[0], model=key[1], representation=key[2], ratios=ratios))
    assert found == wanted and len(worlds) == 512
    assert summary["timed_executions"] == 12288 and summary["memory_executions"] == 1536
    old_gate = all(g["ratios"]["baseline"] <= .90 for g in calculated)
    joint = all(g["ratios"]["r18"] <= 1. and g["ratios"]["peak"] <= .90 for g in calculated)
    assert summary["original_cpu_gate"] == old_gate and summary["joint_cpu_memory_gate"] == joint
    savings = costs["baseline"] - costs["r20"]
    old = json.loads((HERE.parent / "planner_fastpath_r18_20261101/COST_LEDGER.json").read_text())["nonoverlapping_measured_child_cpu_lower_bound"]
    previous = json.loads((HERE.parent / "planner_r19_20261101/COST_LEDGER.json").read_text())["r19_recorded_cpu_lower_bound"]
    assert old == protocol["historical_r18_investment_cpu_seconds"] and previous == protocol["historical_r19_investment_cpu_seconds"]
    assert abs(savings - summary["actual_actor_cpu_savings"]) < 1e-10
    assert abs(old + previous - summary["historical_investment_cpu_floor"]) < 1e-10
    assert abs(savings - old - previous - summary["savings_minus_historical_floor"]) < 1e-10
    assert summary["full_investment_gate"] == (False if savings <= old + previous else None)
    assert summary["mismatches"] == 0 and not summary["production_activation"]
    return dict(passed=True, checks=checks, source=identities, raw_sha256=hashes, groups=calculated,
                original_cpu_gate=old_gate, joint_cpu_memory_gate=joint,
                original_cpu_failures=[g for g in calculated if g["ratios"]["baseline"] > .90],
                joint_failures=[g for g in calculated if g["ratios"]["r18"] > 1. or g["ratios"]["peak"] > .90],
                actual_actor_cpu_with_preparation=costs, actual_actor_cpu_savings=savings,
                historical_investment_floor=old + previous, savings_minus_floor=savings - old - previous,
                unique_worlds=512, fitted_seeds=8, uses_per_fit_group=64,
                scope="Independent standard-library record reconstruction. Every fit/group gate retained; no pooled override. Memory peaks use eight warmed calls/variant/group. No hidden-world resimulation or unmeasured 1000-use, GPU, energy or production claim.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("source", "recovery", "resources"))
    args = parser.parse_args()
    os.sched_setaffinity(0, {1})
    started = time.process_time()
    result = {"source": source, "recovery": recovery, "resources": resources}[args.phase]()
    result["review_cpu_seconds_after_imports"] = time.process_time() - started
    result["reviewer_source_sha256"] = sha(Path(__file__))
    with (HERE / ("INDEPENDENT_" + args.phase.upper() + "_REVIEW.json")).open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
