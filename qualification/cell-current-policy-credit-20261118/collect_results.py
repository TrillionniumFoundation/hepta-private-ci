"""Bind completed original calls, preserve all trained bytes, and archive evidence."""
import argparse, gzip, hashlib, io, json, os, sys, tarfile, time
from pathlib import Path

TRAINING_SOURCE = "6a7696b0c0c5a0a2ba0fb52160aabb191850b2d3"
EVALUATION_SOURCE = "048014f8634059b65b24f49da7f00d5b1bb85737"
PARENT = "430f4051d47672d121a5d790aca0e489804b0d8419c101e3c1171b3d17157786"
PARENT_PARAMETERS = "e5da16c3256c27f06f42ecac69880ce8802a0eb3a87c05830d11c09477aa817f"
OLD_PANELS_SHA = "273b26af219c7294edcc3b9f9186c53a1de464eff9c31d07d4bef6ee77aae818"

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
    old = Path("/home/qian-qi/work/hepta-e1-matched-info-20261118-2e9b/source")
    sys.path.insert(0, str(old / "scripts"))
    from cell_experiments.protocol_v3 import feedback
    retained = root / "retained"
    freeze, weights = read(retained / "FREEZE.json"), read(retained / "WEIGHTS_FROZEN.json")
    assert freeze["code_commit"] == TRAINING_SOURCE
    assert freeze["parent_model_digest"] == PARENT and freeze["parent_parameter_sha256"] == PARENT_PARAMETERS
    assert weights["status"] == "MATCHED_AND_WEIGHTS_FROZEN" and weights["freeze_digest"] == digest(freeze)
    assert weights["B2_material_read_before_weights_frozen"] is False
    fits, shapes = {}, {}
    for mode in ("all_observed", "verified_credit"):
        folder = retained / "training" / mode
        manifest, fit = read(folder / "manifest.json"), read(folder / "TRAINING.json")
        initial = read(folder / "INITIALIZATION.json")
        steps = [json.loads(line) for line in (folder / "STEPS.jsonl").read_bytes().splitlines()]
        groups = read(folder / "ENCODED_GROUPS.json")
        assert fit["status"] == "COMPLETE" and fit["steps"] == len(steps) == 64
        assert digest(manifest) == fit["model_digest"] == weights["arms"][mode]["model_digest"]
        assert sha(folder / "manifest.json") == weights["arms"][mode]["manifest_sha256"]
        assert digest(groups) == manifest["encoded_groups_digest"] == fit["encoded_groups_digest"]
        assert manifest["parameter_before"] == initial["parameter_before"] == PARENT_PARAMETERS
        assert initial["optimizer_state_entries"] == 0 and initial["resumed_existing_adapter"]
        assert not initial["new_lora_initialization"]
        assert manifest["parameter_after"] != manifest["parameter_before"]
        assert all(row["success"] for row in read(folder / "REFERENCE_RECHECKS.json"))
        for expected in manifest["adapter_files"]:
            path = folder / "adapter" / expected["path"]
            assert path.stat().st_size == expected["bytes"] and sha(path) == expected["sha256"]
        keys = ("step", "task_id", "group", "input_group_digest", "model_forwards",
                "model_backwards", "head_positions", "input_tokens", "padded_positions")
        shapes[mode] = [{key: row[key] for key in keys} for row in steps]
        assert shapes[mode] == weights["arms"][mode]["step_shapes"]
        fits[mode] = {"model_digest": fit["model_digest"], "manifest_sha256": sha(folder / "manifest.json"),
            "parameter_before": manifest["parameter_before"], "parameter_after": manifest["parameter_after"],
            "cost": fit["cost"], "adapter_files": manifest["adapter_files"], "steps": len(steps)}
    assert shapes["all_observed"] == shapes["verified_credit"]
    evaluation = retained / "evaluation"
    ef = read(evaluation / "FREEZE.json")
    assert ef["evaluation_code_commit"] == EVALUATION_SOURCE
    assert ef["weights_frozen_digest"] == digest(weights)
    assert ef["weights_frozen_file_sha256"] == sha(retained / "WEIGHTS_FROZEN.json")
    assert ef["original_panels_sha256"] == OLD_PANELS_SHA
    assert sha(evaluation / "PANELS.json") == ef["panels_sha256"]
    b2 = root / "eval-source/qualification/cell-blind-panel-b2-20261118"
    release, b2panel = read(b2 / "RELEASE.json"), read(b2 / "PANEL.json")
    assert release["weights_frozen_sha256"] == sha(retained / "WEIGHTS_FROZEN.json")
    assert release["weights_created_at_ns"] == weights["created_at_ns"] < release["released_at_ns"]
    assert release["original_commitment_sha256"] == sha(b2 / "COMMITMENT.json") == ef["B2_commitment_sha256"]
    assert sha(b2 / "prepared/records.jsonl") == ef["B2_records_sha256"]
    for mode in ("all_observed", "verified_credit"):
        assert release["weight_manifests"][mode]["manifest_sha256"] == sha(retained / "training" / mode / "manifest.json")
    panels = read(evaluation / "PANELS.json")
    assert {key: len(rows) for key, rows in panels.items()} == {
        "A_retention": 6, "B_exposed_development": 6, "B2_blind_future": 6}
    arms, calls, costs, generations = {}, [], {}, []
    for mode in ("NoUpdate", "all_observed", "verified_credit"):
        folder = evaluation / mode
        result, loaded = read(folder / "RESULT.json"), read(folder / "MODEL_LOADED.json")
        assert result["status"] == "COMPLETE" and result["freeze_digest"] == digest(ef)
        assert loaded["model_digest"] == ef["models"][mode]
        generations.append(loaded["generation_digest"])
        arms[mode] = {}
        for panel, records in panels.items():
            outcomes = []
            for i, record in enumerate(records):
                task = folder / panel / str(i)
                assert read(task / "ORIGINAL_RECORD.json") == record
                row = read(task / "RESULT.json")
                history = [{"role": "user", "content": record["task"]["input"]}]
                assert record["task"].get("messages", history) == history
                successes = []
                for attempt in range(2):
                    request, output, receipt = [read(task / (name + "-" + str(attempt) + ".json"))
                                                for name in ("REQUEST", "OUTPUT", "VERIFICATION")]
                    assert request["task"]["messages"] == history
                    assert output["messages_sha256"] == digest(history)
                    assert output["loaded_model_digest"] == ef["models"][mode]
                    assert output["generation_config_sha256"] == loaded["generation_digest"]
                    assert output["max_new_tokens"] == 384 and 0 < output["input_tokens"] <= 4096
                    assert 0 < output["output_tokens"] <= 384
                    assert receipt["answer_sha256"] == raw_sha(output["answer"].encode())
                    assert receipt["verifier_source_sha256"] == "64fcc25e4ccf82f31c2549f5d4c1a5c4af1831c5bed4219c0aac2283b213a020"
                    assert receipt == row["steps"][attempt]["verification"]
                    assert digest(request) == row["steps"][attempt]["request_digest"]
                    assert digest(output) == row["steps"][attempt]["output_digest"]
                    successes.append(receipt["success"])
                    calls.append({"mode": mode, "panel": panel, "task_id": record["task_id"],
                        "attempt": attempt, "success": receipt["success"], "reason": receipt["result"]["reason"],
                        "executed": receipt["result"].get("executed", False),
                        "input_tokens": output["input_tokens"], "output_tokens": output["output_tokens"],
                        "wall_seconds": output["wall_seconds"], "hit_output_limit": output["hit_output_limit"],
                        "request_sha256": sha(task / ("REQUEST-" + str(attempt) + ".json")),
                        "output_sha256": sha(task / ("OUTPUT-" + str(attempt) + ".json")),
                        "verification_sha256": sha(task / ("VERIFICATION-" + str(attempt) + ".json"))})
                    history = history + [{"role": "assistant", "content": output["answer"]},
                                         {"role": "tool", "content": feedback(receipt)}]
                first, last = successes
                expected = {"first": first, "last": last, "selected": first or last,
                            "recovered": not first and last, "regressed": first and not last}
                assert all(row[key] == value for key, value in expected.items())
                outcomes.append(expected)
            aggregate = {"tasks": len(records), **{key: sum(row[key] for row in outcomes)
                for key in ("first", "last", "selected", "recovered", "regressed")}}
            assert aggregate == result["by_panel"][panel]
            arms[mode][panel] = aggregate
        costs[mode] = {**result["cost"], "load_wall_seconds": loaded["load_wall_seconds"]}
    assert len(set(generations)) == 1
    assert len(calls) == len(list(evaluation.glob("*/*/*/OUTPUT-*.json"))) == ef["planned_model_calls"] == 108
    stage_exits = []
    for owner, stages in (("owned-train-1", ("freeze", "train-all_observed", "train-verified_credit", "audit")),
                          ("owned-evaluation-1", ("freeze", "NoUpdate", "all_observed", "verified_credit"))):
        assert read(root / owner / "COMPLETE.json")["status"] == "COMPLETE"
        for stage in stages:
            folder = root / owner / stage
            row = read(folder / "EXIT.json")
            assert row["wait_returncode"] == 0 and not row["timed_out"]
            assert row["stdout_sha256"] == sha(folder / "STDOUT.txt")
            assert row["stderr_sha256"] == sha(folder / "STDERR.txt")
            stage_exits.append({"owner": owner, **row})
    control, treatment = arms["all_observed"]["A_retention"], arms["verified_credit"]["A_retention"]
    criterion = (treatment["regressed"] < control["regressed"] and
                 treatment["recovered"] >= control["recovered"] and treatment["last"] >= control["last"])
    report = {"schema": "hepta.current-policy-credit-readout.v1", "status": "COMPLETE",
        "training_source": TRAINING_SOURCE, "evaluation_source": EVALUATION_SOURCE,
        "freeze_sha256": sha(retained / "FREEZE.json"),
        "weights_frozen_sha256": sha(retained / "WEIGHTS_FROZEN.json"),
        "evaluation_freeze_sha256": sha(evaluation / "FREEZE.json"),
        "training": fits, "matched_work_verified": True, "by_arm": arms, "calls": calls,
        "evaluation_costs": costs, "stage_exits": stage_exits,
        "disjoint_stage_wall_seconds": sum(row["wall_seconds"] for row in stage_exits),
        "disjoint_stage_child_cpu_seconds": sum(row["completed_child_user_cpu_seconds"] +
            row["completed_child_system_cpu_seconds"] for row in stage_exits),
        "A_only_preregistered_advancement_criterion_met": criterion,
        "research_decision": "NoUpdate retained; report mechanism and external-task results without native promotion",
        "criterion": "strictly fewer A regressions, no fewer A recoveries or final successes versus all_observed",
        "new_model_calls": 108, "training_updates": 128, "new_verifier_calls_owned_stages": 138,
        "prior_corpus_correction_verifier_calls": 6,
        "B2_prior_curator_reference_verifier_calls": b2panel["reference_verifier_calls"],
        "B2_prior_curator_tautology_verifier_calls": b2panel["tautology_verifier_calls"],
        "parent_training_ancestry": "one retained previous 64-step all_actions fit; not repeated or charged twice",
        "old_B_is_repeated_development": True, "B2_used_for_training_or_selection": False,
        "B2_release_sha256": sha(b2 / "RELEASE.json"), "B2_released_after_exact_weights_frozen": True,
        "B2_maintainer_groups": b2panel["maintainer_groups"], "B2_repositories": b2panel["repositories"],
        "B2_blinding_scope": "operational separation of agents in shared workspace, not authenticated independent custody",
        "B2_prepared_by_separate_executor": True, "independent_authenticated_evaluator": False,
        "independent_users": 0, "pretraining_overlap_known": False,
        "energy_joules": None, "full_system_cost_known": False,
        "scientific_confirmation_qualified": False, "native_adoption": False,
        "nested_windows_are_not_additive": True, "scoring_reexecuted_or_modified": False,
        "prelaunch_tool_validation_error": "first deployment rejected relative executable python3 before a job existed; corrected absolute executable, zero model calls"}
    files = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if "__pycache__" in path.parts or any(part.startswith("export-") for part in relative.parts):
            continue
        assert not path.is_symlink()
        if path.is_file():
            files[relative.as_posix()] = path.read_bytes()
    jobs = ("1a1ef30a56c-ffbe-428", "1a1ef401640-ffbe-455", "1a1ef2feb92-ffbe-426",
            "1a1ef3f91dc-ffbe-453", "1a1ef42eecd-ffbe-45d")
    for job in jobs:
        folder = Path("/home/qian-qi/.local/state/hepta-runtime-mac-worker/jobs") / job
        raw = (folder / "exit.json").read_bytes()
        exit_record, witness = json.loads(raw), read(folder / "exit.witness.json")
        assert exit_record["exit_code"] == 0 and not exit_record["timed_out"]
        assert exit_record["output_complete"] and exit_record["output_durable"]
        assert witness["exit_sha256"] == raw_sha(raw)
        for name in ("exit.json", "exit.witness.json", "started.json", "child.json", "stdout.log", "stderr.log"):
            path = folder / name
            if path.exists():
                files["runtime-jobs/" + job + "/" + name] = path.read_bytes()
    manifest = {"schema": "hepta.current-policy-credit-complete-originals.v1",
        "training_source": TRAINING_SOURCE, "evaluation_source": EVALUATION_SOURCE,
        "files": {name: {"sha256": raw_sha(raw), "bytes": len(raw)} for name, raw in files.items()},
        "new_model_calls": 108, "new_training_updates": 128, "both_trained_adapters_included": True,
        "base_model_bytes_included": False, "base_identity": "retained parent manifests and pinned pre-existing base files",
        "weights_frozen_sha256": sha(retained / "WEIGHTS_FROZEN.json"),
        "postprocess_source_sha256": sha(Path(__file__)),
        "scientific_confirmation_qualified": False, "native_adoption": False, "full_system_cost_known": False}
    raw_index = json.dumps(manifest, sort_keys=True, indent=2).encode() + b"\n"
    destination = root / "export-complete-1"
    destination.mkdir(exist_ok=False)
    archive = destination / "complete-originals.tar.gz"
    with archive.open("xb") as stream:
        with gzip.GzipFile(fileobj=stream, mode="wb", mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w") as tar:
                for name, raw in sorted(files.items()):
                    info = tarfile.TarInfo(name)
                    info.size, info.mode = len(raw), 0o644
                    tar.addfile(info, io.BytesIO(raw))
                info = tarfile.TarInfo("ARCHIVE_MANIFEST.json")
                info.size, info.mode = len(raw_index), 0o644
                tar.addfile(info, io.BytesIO(raw_index))
        stream.flush()
        os.fsync(stream.fileno())
    (destination / "ARCHIVE_MANIFEST.json").write_bytes(raw_index)
    report["index_sha256"] = raw_sha(raw_index)
    report["archive_sha256"] = sha(archive)
    report["archive_bytes"] = archive.stat().st_size
    report["verified_original_files"] = len(files)
    report["postprocess_wall_seconds"] = time.perf_counter() - started
    write(destination / "READOUT.json", report)
    result = {"archive": str(archive), "bytes": archive.stat().st_size, "sha256": sha(archive),
              "index_sha256": raw_sha(raw_index), "members": len(files) + 1,
              "readout": str(destination / "READOUT.json"), "readout_sha256": sha(destination / "READOUT.json"),
              "trained_adapters_included": True, "by_arm": arms,
              "A_only_preregistered_advancement_criterion_met": criterion}
    write(destination / "EXPORT.json", result)
    print(json.dumps(result, sort_keys=True))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    main(parser.parse_args().root.resolve(strict=True))
