"""Audit completed fixed-prefix calls and retain exact original evidence; no inference or rescoring."""
import argparse, gzip, hashlib, io, json, os, sys, tarfile, time
from pathlib import Path

EXECUTION_SOURCE = "0d1e9d9e24f2f1d569585adb3a6203a9114f850d"
PROTOCOL_SHA = "b2894184e497663f52fc01cafe7b1d86e32c247248d339ded8b1ad75f62a5e1e"
CASES_SHA = "6b759706ee2970d824c864c1a6d7dc947e1cb75b2622af3dda6a60f11b28b1c9"
VERIFIER_SHA = "64fcc25e4ccf82f31c2549f5d4c1a5c4af1831c5bed4219c0aac2283b213a020"
MODES = ("NoUpdate", "all_observed", "verified_credit")
PREVIOUS = Path("/home/qian-qi/work/hepta-e2-current-credit-20261118-2e9b")

def raw_sha(raw):
    return hashlib.sha256(raw).hexdigest()

def sha(path):
    return raw_sha(path.read_bytes())

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()

def digest(value):
    return raw_sha(canonical(value))

def read(path):
    return json.loads(path.read_bytes())

def write(path, value):
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())

def main(root):
    started = time.perf_counter()
    deployment = read(root / "FINAL_DEPLOYMENT.json")
    assert deployment["source_commit"] == EXECUTION_SOURCE
    assert len(deployment["files"]) == 7
    for name, expected in deployment["files"].items():
        assert sha(root / "source" / name) == expected, name
    here = root / "source/qualification/cell-e2-fixed-prefix-20261118"
    assert sha(here / "prepared/PROTOCOL.json") == PROTOCOL_SHA
    assert sha(here / "prepared/CASES.json") == CASES_SHA
    protocol, cases = read(here / "prepared/PROTOCOL.json"), read(here / "prepared/CASES.json")
    assert digest(cases) == protocol["cases_digest"] and len(cases) == 11
    assert [row["kind"] for row in cases] == ["failure"] * 6 + ["success"] * 5
    assert sum(row["input_tokens"] for row in cases) == 5828
    assert sha(here / "run_prefix.py") == protocol["runner_sha256"]
    assert sha(here / "owner.py") == protocol["owner_sha256"]
    for name in ("PROTOCOL.json", "CASES.json", "PREPARATION.json"):
        assert (root / "prepared" / name).read_bytes() == (here / "prepared" / name).read_bytes()
    old_index_path = PREVIOUS / "export-complete-1/ARCHIVE_MANIFEST.json"
    assert sha(old_index_path) == protocol["source_index_sha256"]
    old_index = read(old_index_path)
    sys.path.insert(0, "/home/qian-qi/work/hepta-e1-matched-info-20261118-2e9b/source/scripts")
    from cell_experiments.protocol_v3 import feedback
    for case in cases:
        originals = {}
        for name, binding in case["source_bindings"].items():
            path = PREVIOUS / case["source_prefix"] / name
            assert old_index["files"][case["source_prefix"] + name] == binding
            assert sha(path) == binding["sha256"] and path.stat().st_size == binding["bytes"]
            originals[name] = read(path)
        attempt = str(case["historical_attempt"])
        past_request = originals["REQUEST-" + attempt + ".json"]
        past_output = originals["OUTPUT-" + attempt + ".json"]
        past_receipt = originals["VERIFICATION-" + attempt + ".json"]
        assert case["record"] == originals["ORIGINAL_RECORD.json"]
        assert case["historical_success"] is past_receipt["success"]
        expected_messages = past_request["task"]["messages"] + [
            {"role": "assistant", "content": past_output["answer"]},
            {"role": "tool", "content": feedback(past_receipt)}]
        assert case["request"] == {"record_id": case["record"]["record_id"],
            "task": {"input": case["record"]["task"]["input"], "messages": expected_messages}}
        assert digest(expected_messages) == case["prefix_messages_digest"]
    complete = read(root / "owned-run-1/COMPLETE.json")
    assert complete["status"] == "COMPLETE" and complete["actual_model_calls"] == 33
    assert complete["actual_verifier_calls"] == 33 and complete["new_training_updates"] == 0
    calls, costs, by_arm, exits, model_files = [], {}, {}, [], {}
    output_answers = {}
    for mode in MODES:
        model_path = (PREVIOUS / "retained/PARENT_MODEL.json" if mode == "NoUpdate" else
            PREVIOUS / "retained/training" / mode / "manifest.json")
        assert sha(model_path) == protocol["manifest_sha256"][mode]
        assert digest(read(model_path)) == protocol["model_digests"][mode]
        model_files["frozen-model-manifests/" + mode + ".json"] = model_path.read_bytes()
        folder = root / "output" / mode
        result, loaded = read(folder / "RESULT.json"), read(folder / "MODEL_LOADED.json")
        assert result["status"] == "COMPLETE" and result["source_commit"] == EXECUTION_SOURCE
        assert result["protocol_sha256"] == PROTOCOL_SHA
        assert loaded["model_digest"] == protocol["model_digests"][mode]
        assert loaded["generation_digest"] == protocol["generation_config_sha256"]
        assert not result["old_108_call_decision_changed"] and result["research_NoUpdate_retained"]
        assert not (folder / "FAILED.json").exists()
        rows = []
        for i, case in enumerate(cases):
            task = folder / str(i)
            request, output, receipt, row = [read(task / (name + ".json")) for name in
                ("REQUEST", "OUTPUT", "VERIFICATION", "RESULT")]
            assert request == case["request"]
            assert output["loaded_model_digest"] == protocol["model_digests"][mode]
            assert output["generation_config_sha256"] == protocol["generation_config_sha256"]
            assert output["messages_sha256"] == case["prefix_messages_digest"]
            assert output["rendered_input_sha256"] == case["rendered_input_sha256"]
            assert output["input_tokens"] == case["input_tokens"]
            assert output["input_sha256"] == raw_sha(request["task"]["input"].encode())
            assert output["max_new_tokens"] == protocol["maximum_new_tokens"] == 384
            assert output["output_tokens"] == len(output["output_token_ids"])
            assert 0 < output["output_tokens"] <= 384
            assert receipt["answer_sha256"] == raw_sha(output["answer"].encode())
            assert receipt["input_sha256"] == output["input_sha256"]
            assert receipt["parameters_sha256"] == digest(case["record"]["task"]["verifier"]["parameters"])
            assert receipt["verifier"] == ["repo_patch", "1"] and receipt["verifier_source_sha256"] == VERIFIER_SHA
            assert row["request_digest"] == digest(request) and row["output_digest"] == digest(output)
            assert row["verification_digest"] == digest(receipt)
            execution = receipt["result"]
            observed = execution.get("result", {})
            observations = observed.get("observations", [])
            control_count = case["record"]["protocol_reference_receipt"]["result"]["result"]["control_count"]
            strict_success = bool(execution.get("executed", False) and
                observed.get("original_passed") is True and
                observed.get("controls_rejected") == control_count and
                len(observations) == control_count + 1 and
                observations[0]["control"] == "original" and observations[0]["passed"] is True and
                all(item["passed"] is False for item in observations[1:]))
            assert receipt["success"] is strict_success
            assert row["success"] is strict_success and row["reason"] == execution["reason"]
            assert row["case_id"] == case["case_id"] and row["kind"] == case["kind"]
            assert row["cost"] == {key: output[key] for key in
                ("input_tokens", "output_tokens", "wall_seconds", "hit_output_limit")}
            assert output["started_at_ns"] > protocol["prepared_at_ns"]
            output_answers[(mode, case["case_id"])] = output["answer"]
            call = {"mode": mode, "case_id": case["case_id"], "kind": case["kind"],
                "historical_attempt": case["historical_attempt"], "success": strict_success,
                "reason": execution["reason"], "executed": execution.get("executed", False),
                "declared_control_count": control_count,
                "observed_subject_calls": sum(len(item["calls"]) for item in observations),
                "input_tokens": output["input_tokens"], "output_tokens": output["output_tokens"],
                "generation_wall_seconds": output["wall_seconds"], "hit_output_limit": output["hit_output_limit"],
                "verifier_wall_seconds": execution.get("wall_ns", 0) / 1e9,
                "answer_sha256": receipt["answer_sha256"], "original_files": {
                    name: {"sha256": sha(task / (name + ".json")),
                           "bytes": (task / (name + ".json")).stat().st_size}
                    for name in ("REQUEST", "OUTPUT", "VERIFICATION", "RESULT")}}
            calls.append(call)
            rows.append(row)
        assert rows == result["rows"]
        aggregate = {kind: {"cases": sum(row["kind"] == kind for row in rows),
            "successful": sum(row["kind"] == kind and row["success"] for row in rows)}
            for kind in ("failure", "success")}
        assert aggregate == result["by_kind"]
        assert result["cost"]["model_calls"] == result["cost"]["verifier_calls"] == 11
        for key in ("input_tokens", "output_tokens", "hit_output_limit"):
            assert result["cost"][key] == sum(row["cost"][key] for row in rows)
        by_arm[mode] = aggregate
        owned = root / "owned-run-1" / mode
        exit_record = read(owned / "EXIT.json")
        assert exit_record["wait_returncode"] == 0 and not exit_record["timed_out"]
        assert exit_record["stdout_sha256"] == sha(owned / "STDOUT.txt")
        assert exit_record["stderr_sha256"] == sha(owned / "STDERR.txt")
        exits.append(exit_record)
        costs[mode] = {**result["cost"], "load_wall_seconds": loaded["load_wall_seconds"],
            "owned_wall_seconds": exit_record["wall_seconds"],
            "owned_child_cpu_seconds": exit_record["completed_child_user_cpu_seconds"] +
                                       exit_record["completed_child_system_cpu_seconds"]}
    assert len(calls) == len(list((root / "output").glob("*/*/OUTPUT.json"))) == 33
    paired = []
    for case in cases:
        chosen = {mode: next(row for row in calls if row["mode"] == mode and row["case_id"] == case["case_id"])
                  for mode in MODES}
        paired.append({"case_id": case["case_id"], "kind": case["kind"],
            "success_by_mode": {mode: chosen[mode]["success"] for mode in MODES},
            "reason_by_mode": {mode: chosen[mode]["reason"] for mode in MODES},
            "all_observed_and_credit_same_answer_bytes":
                output_answers[("all_observed", case["case_id"])] == output_answers[("verified_credit", case["case_id"])]})
    paired_kinds = []
    for case in cases[6:]:
        task = case["case_id"].rsplit("/", 1)[0]
        paired_kinds.append({"task": task, "exact_answer_identity_across_failure_and_success_history": {
            mode: output_answers[(mode, task + "/failure")] == output_answers[(mode, task + "/success")]
            for mode in MODES}})
    prepare_exit = read(root / "owned-prepare-1/EXIT.json")
    assert prepare_exit["wait_returncode"] == 0
    assert prepare_exit["new_model_calls"] == prepare_exit["new_verifier_calls"] == 0
    report = {"schema": "hepta.current-policy-fixed-prefix-readout.v1", "status": "COMPLETE",
        "execution_source": EXECUTION_SOURCE, "protocol_sha256": PROTOCOL_SHA, "cases_sha256": CASES_SHA,
        "model_digests": protocol["model_digests"], "manifest_sha256": protocol["manifest_sha256"],
        "source_108_archive_sha256": protocol["source_archive_sha256"],
        "source_108_index_sha256": protocol["source_index_sha256"],
        "by_arm": by_arm, "paired_cases": paired, "paired_history_answer_identity": paired_kinds,
        "costs": costs, "calls": calls, "stage_exits": exits, "preparation_owned_exit": prepare_exit,
        "disjoint_model_stage_wall_seconds": sum(row["wall_seconds"] for row in exits),
        "disjoint_model_stage_child_cpu_seconds": sum(row["completed_child_user_cpu_seconds"] +
            row["completed_child_system_cpu_seconds"] for row in exits),
        "totals": {"model_calls": 33, "verifier_calls": 33, "new_training_updates": 0,
            "input_tokens": sum(row["input_tokens"] for row in calls),
            "output_tokens": sum(row["output_tokens"] for row in calls),
            "hit_output_limit": sum(row["hit_output_limit"] for row in calls),
            "format_rejections": sum(row["reason"] == "invalid_test_patch" for row in calls),
            "business_executions": sum(row["executed"] for row in calls),
            "observed_subject_calls": sum(row["observed_subject_calls"] for row in calls),
            "generation_wall_seconds": sum(row["generation_wall_seconds"] for row in calls),
            "verifier_wall_seconds": sum(row["verifier_wall_seconds"] for row in calls)},
        "descriptive_mechanism_only": True, "exposed_A_training_histories": True,
        "independent_users": 0, "new_independent_tasks": 0, "scientific_confirmation_qualified": False,
        "old_108_advancement_criterion_met": False, "old_108_decision_changed": False,
        "research_decision": "NoUpdate retained under the original completed 108-call preregistration",
        "native_adoption": False, "energy_joules": None, "full_system_cost_known": False,
        "nested_windows_are_not_additive": True, "new_calls_by_this_collector": 0,
        "original_scores_reexecuted_or_modified": False}
    files = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if "__pycache__" in path.parts or any(part.startswith("export-") for part in relative.parts):
            continue
        assert not path.is_symlink()
        if path.is_file():
            files[relative.as_posix()] = path.read_bytes()
    files.update(model_files)
    runtime_exits = {}
    for job in ("1a1ef5cfb42-ffbe-49d", "1a1ef5f1616-ffbe-4a3", "1a1ef5fa542-ffbe-4a4"):
        folder = Path("/home/qian-qi/.local/state/hepta-runtime-mac-worker/jobs") / job
        raw = (folder / "exit.json").read_bytes()
        exit_record, witness = json.loads(raw), read(folder / "exit.witness.json")
        assert exit_record["exit_code"] == 0 and not exit_record["timed_out"]
        assert exit_record["output_complete"] and exit_record["output_durable"]
        assert witness["exit_sha256"] == raw_sha(raw)
        runtime_exits[job] = {"exit_sha256": raw_sha(raw), "witness_sha256": sha(folder / "exit.witness.json"),
                             "exit_code": exit_record["exit_code"]}
        for name in ("exit.json", "exit.witness.json", "started.json", "child.json", "stdout.log", "stderr.log"):
            path = folder / name
            if path.exists():
                files["runtime-jobs/" + job + "/" + name] = path.read_bytes()
    report["runtime_exits"] = runtime_exits
    manifest = {"schema": "hepta.current-policy-fixed-prefix-originals.v1",
        "execution_source": EXECUTION_SOURCE, "protocol_sha256": PROTOCOL_SHA, "cases_sha256": CASES_SHA,
        "files": {name: {"sha256": raw_sha(raw), "bytes": len(raw)} for name, raw in files.items()},
        "actual_model_calls": 33, "actual_verifier_calls": 33, "new_training_updates": 0,
        "model_manifest_bytes_included": True, "adapter_and_base_bytes_duplicated": False,
        "trained_adapter_bytes_in_prior_archive_sha256": protocol["source_archive_sha256"],
        "postprocess_source_sha256": sha(Path(__file__)), "research_NoUpdate_retained": True,
        "scientific_confirmation_qualified": False, "native_adoption": False}
    raw_index = json.dumps(manifest, sort_keys=True, indent=2).encode() + b"\n"
    destination = root / "export-complete-1"
    destination.mkdir(exist_ok=False)
    archive = destination / "complete-originals.tar.gz"
    with archive.open("xb") as stream:
        with gzip.GzipFile(fileobj=stream, mode="wb", mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w") as tar:
                for name, raw in sorted({**files, "ARCHIVE_MANIFEST.json": raw_index}.items()):
                    info = tarfile.TarInfo(name)
                    info.size, info.mode = len(raw), 0o644
                    tar.addfile(info, io.BytesIO(raw))
        stream.flush()
        os.fsync(stream.fileno())
    (destination / "ARCHIVE_MANIFEST.json").write_bytes(raw_index)
    report.update({"index_sha256": raw_sha(raw_index), "archive_sha256": sha(archive),
        "archive_bytes": archive.stat().st_size, "verified_original_files": len(files),
        "postprocess_wall_seconds": time.perf_counter() - started})
    write(destination / "READOUT.json", report)
    export = {"archive": str(archive), "bytes": archive.stat().st_size, "sha256": sha(archive),
        "index_sha256": raw_sha(raw_index), "readout_sha256": sha(destination / "READOUT.json"),
        "members": len(files) + 1, "by_arm": by_arm, "totals": report["totals"],
        "research_NoUpdate_retained": True}
    write(destination / "EXPORT.json", export)
    print(json.dumps(export, sort_keys=True))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    main(parser.parse_args().root.resolve(strict=True))
