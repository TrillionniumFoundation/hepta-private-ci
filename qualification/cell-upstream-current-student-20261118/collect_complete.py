"""Audit all 24 frozen calls and retain complete owned raw evidence without replay."""

import collections
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import time

ROOT = Path("/home/qian-qi/work/hepta-upstream-current-policy-20261118-2e9b")
MATERIAL = Path("/home/qian-qi/work/hepta-e5-upstream-20261118-2e9b")
PREVIOUS = Path("/home/qian-qi/work/hepta-e2-current-credit-20261118-2e9b")
OLD_CODE = Path("/home/qian-qi/work/hepta-e1-matched-info-20261118-2e9b/source")
SOURCE = "dfc4e24ba68fa983f4dbdaca1de6c2d54a4df950"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = value if isinstance(value, bytes) else canonical(value) + b"\n"
    with path.open("xb") as stream:
        stream.write(raw)
    return sha(raw)


def digest(value):
    return sha(canonical(value))


def classified(receipt):
    if receipt["stage"] == "native_pytest":
        return "native_pass" if receipt["success"] else "native_business_failure"
    if receipt.get("error_type") == "JSONDecodeError":
        return "invalid_JSON"
    reason = receipt.get("reason", "")
    if reason == "old text must occur exactly once in the original file":
        return "original_text_mismatch"
    if reason == "each edit needs only old and new":
        return "invalid_edit_schema"
    if reason.startswith("new external name"):
        return "restricted_name"
    return "other_admission_rejection"


def pair(rows):
    assert len(rows) == 2
    first, last = (row["success"] for row in rows)
    return {
        "first": first,
        "final": last,
        "any_success": first or last,
        "recovery": not first and last,
        "regression": first and not last,
    }


def audit_native(folder, receipt, task):
    if not receipt["actual_native_child"]:
        return
    actual = read(folder / "RESULT.json")
    assert actual["success"] == receipt["success"]
    assert receipt["original_test_sha256"] == task["original_tests_sha256"]
    assert receipt["same_original_case_set"]
    assert (
        sha((folder / "sandbox-output/SANDBOX_ATTESTATION.json").read_bytes())
        == receipt["sandbox_attestation_sha256"]
    )
    assert (
        sha((folder / "sandbox-output/junit.xml").read_bytes())
        == receipt["junit_sha256"]
    )
    assert sha((folder / "STDOUT.txt").read_bytes()) == receipt["stdout_sha256"]
    assert sha((folder / "STDERR.txt").read_bytes()) == receipt["stderr_sha256"]
    assert sha((folder / "CASE.json").read_bytes()) == receipt["case_sha256"]
    expected = bool(
        receipt["actual_wait_returncode"] == 0
        and not receipt["timed_out"]
        and receipt["failures"] == receipt["errors"] == receipt["skipped"] == 0
    )
    assert receipt["success"] == expected


def main():
    started, cpu = time.perf_counter(), time.process_time()
    out = ROOT / "export-complete-1"
    out.mkdir(exist_ok=False)
    tasks = read(ROOT / "prepared/TASKS.json")
    protocol = read(ROOT / "prepared/PROTOCOL.json")
    assert len(tasks) == 4
    assert (
        sha((ROOT / "prepared/TASKS.json").read_bytes())
        == "b30229f6fe886a0d23151b3e761592e3e11eeb333bdaf7e79c606eb6f85a08de"
    )
    assert (
        sha((ROOT / "prepared/PROTOCOL.json").read_bytes())
        == "56071aea433cbf5e3b3c479e01ad39e3b025533030e6d4c57c68357163bdfc50"
    )
    assert (
        sha((ROOT / "execution-code/native_sandbox.py").read_bytes())
        == protocol["native_verifier_sha256"]
    )
    calls, pairs, models = [], {}, {}
    for mode in ("P", "C"):
        result = read(ROOT / "results" / mode / "RESULT.json")
        assert (
            result["status"] == "COMPLETE"
            and result["source_commit"] == SOURCE
            and result["actual_model_calls"] == 8
        )
        loaded = read(ROOT / "results" / mode / "MODEL_LOADED.json")
        models[mode] = loaded
        mode_pairs = []
        for index, task in enumerate(tasks):
            folder = ROOT / "results" / mode / str(index)
            assert read(folder / "ORIGINAL_TASK.json") == task
            expected = task["task"]["messages"]
            rows = []
            previous = None
            for attempt in range(2):
                request = read(folder / ("REQUEST-" + str(attempt) + ".json"))
                output = read(folder / ("OUTPUT-" + str(attempt) + ".json"))
                receipt = read(folder / ("VERIFICATION-" + str(attempt) + ".json"))
                feedback = read(folder / ("FEEDBACK-" + str(attempt) + ".json"))
                assert request["task"]["messages"] == expected
                assert request["task"]["input"] == task["task"]["input"]
                assert output["messages_sha256"] == digest(expected)
                assert (
                    output["generation_config_sha256"]
                    == protocol["generation_config_sha256"]
                )
                assert (
                    output["loaded_model_manifest_digest"]
                    == protocol["model_digests"][mode]
                )
                assert (
                    output["original_manifest_unchanged"]
                    and not output["input_truncated"]
                )
                assert output["maximum_new_tokens"] == 2048
                assert (
                    output["input_tokens"] <= 8192
                    and output["input_tokens"] + 2048
                    <= output["native_max_position_embeddings"]
                )
                assert output["output_tokens"] == len(output["output_token_ids"])
                assert receipt["answer_sha256"] == sha(output["answer"].encode())
                assert (
                    read(folder / ("verify-" + str(attempt)) / "VERIFICATION.json")
                    == receipt
                )
                assert feedback["verification_digest"] == digest(receipt)
                summary = result["rows"][index * 2 + attempt]
                assert summary["request_sha256"] == digest(request)
                assert summary["output_sha256"] == digest(output)
                assert summary["verification_sha256"] == digest(receipt)
                assert summary["success"] == receipt["success"]
                assert (
                    folder / ("GENERATION_STARTED-" + str(attempt) + ".json")
                ).exists()
                audit_native(
                    folder / ("verify-" + str(attempt)) / "native", receipt, task
                )
                row = {
                    **summary,
                    "mode": mode,
                    "failure_category": classified(receipt),
                    "reason": receipt.get("reason"),
                    "answer_sha256": receipt["answer_sha256"],
                    "same_answer_as_previous": attempt > 0
                    and output["answer"] == previous,
                    "original_output_file_sha256": sha(
                        (folder / ("OUTPUT-" + str(attempt) + ".json")).read_bytes()
                    ),
                    "original_receipt_file_sha256": sha(
                        (
                            folder / ("VERIFICATION-" + str(attempt) + ".json")
                        ).read_bytes()
                    ),
                }
                calls.append(row)
                rows.append(row)
                previous = output["answer"]
                expected = [
                    *expected,
                    {"role": "assistant", "content": output["answer"]},
                    {"role": "tool", "content": feedback["content"]},
                ]
            actual_pair = pair(rows)
            assert read(folder / "PAIR.json") == actual_pair
            mode_pairs.append({"project_id": task["project_id"], **actual_pair})
        assert result["input_tokens"] == sum(
            row["input_tokens"] for row in calls if row["mode"] == mode
        )
        assert result["output_tokens"] == sum(
            row["output_tokens"] for row in calls if row["mode"] == mode
        )
        pairs[mode] = mode_pairs
    teacher = ROOT / "retained-teacher"
    freeze = read(teacher / "TEACHER_FREEZE.json")
    assert (
        sha((teacher / "TEACHER_FREEZE.json").read_bytes())
        == "c9e7b72fb1bd196b32bb7022d6743054e234e1b7de1f08233e93939e3ff33094"
    )
    models["T2"] = {
        key: freeze[key]
        for key in (
            "server",
            "weight_identity",
            "native_context",
            "chat_template_sha256",
            "request_parameters",
            "internal_research_license_scope_only",
            "physical_compute_matched",
        )
    }
    teacher_pairs = []
    for index, task in enumerate(tasks):
        expected = task["task"]["messages"]
        rows = []
        previous = None
        for attempt, stage in enumerate(("first", "second")):
            request = read(teacher / stage / ("REQUEST-" + str(index) + ".json"))
            output = read(teacher / stage / ("OUTPUT-" + str(index) + ".json"))
            raw = read(teacher / stage / ("RAW_RESPONSE-" + str(index) + ".json"))
            post = read(teacher / stage / ("POSTFLIGHT-" + str(index) + ".json"))
            verified = ROOT / ("teacher-verification-" + stage + "-1")
            records = read(verified / (stage.upper() + "_VERIFICATIONS.json"))
            record = records[index]
            receipt = record["verification"]
            assert request["logical_messages"] == expected
            assert request["payload"]["messages"] == [
                {
                    "role": "user" if x["role"] == "tool" else x["role"],
                    "content": ("Tool observation:\n" if x["role"] == "tool" else "")
                    + x["content"],
                }
                for x in expected
            ]
            assert (
                output["request_digest"]
                == digest(request["payload"])
                == raw["request_digest"]
            )
            assert raw["raw_response"] == output["raw_response"]
            assert output["logical_messages_digest"] == digest(expected)
            assert sha(output["answer"].encode()) == receipt["answer_sha256"]
            assert record["verification_digest"] == digest(receipt)
            assert record["feedback_digest"] == sha(record["feedback"].encode())
            assert read(verified / str(index) / "VERIFICATION.json") == receipt
            assert sha(
                (verified / ("ORIGINAL_OUTPUT-" + str(index) + ".json")).read_bytes()
            ) == sha(
                (teacher / stage / ("OUTPUT-" + str(index) + ".json")).read_bytes()
            )
            assert request["input_tokenization"]["tokens"] == len(
                request["input_tokenization"]["raw"]["tokens"]
            )
            usage = output["usage"]
            assert (
                abs(usage["prompt_tokens"] - request["input_tokenization"]["tokens"])
                <= 1
            )
            assert (
                usage["prompt_tokens"] <= 8192
                and usage["prompt_tokens"] + 2048 <= freeze["native_context"]
            )
            assert post["actual_prompt_tokens"] == usage["prompt_tokens"]
            assert (
                not output["input_truncated"]
                and request["output_reserve"]
                == request["payload"]["max_tokens"]
                == 2048
            )
            assert (
                teacher / stage / ("GENERATION_STARTED-" + str(index) + ".json")
            ).exists()
            audit_native(verified / str(index) / "native", receipt, task)
            row = {
                "mode": "T2",
                "project_id": task["project_id"],
                "task_id": task["task_id"],
                "source_id": task["source_id"],
                "attempt": attempt,
                "success": receipt["success"],
                "stage": receipt["stage"],
                "failure_category": classified(receipt),
                "reason": receipt.get("reason"),
                "input_tokens": usage["prompt_tokens"],
                "output_tokens": usage["completion_tokens"],
                "generation_wall_seconds": output["wall_seconds"],
                "verifier_wall_seconds": receipt.get(
                    "verification_wall_seconds", receipt["wall_seconds"]
                ),
                "actual_native_child": receipt["actual_native_child"],
                "hit_output_limit": output["raw_response"]["choices"][0][
                    "finish_reason"
                ]
                == "length",
                "answer_sha256": receipt["answer_sha256"],
                "same_answer_as_previous": attempt > 0 and output["answer"] == previous,
                "native_tests": receipt.get("tests", 0),
                "native_failures": receipt.get("failures", 0),
                "native_errors": receipt.get("errors", 0),
                "native_case_timeouts": sum(
                    "Timeout" in ((x["failure"] or "") + (x["error"] or ""))
                    for x in receipt.get("cases", [])
                ),
                "request_sha256": sha(
                    (teacher / stage / ("REQUEST-" + str(index) + ".json")).read_bytes()
                ),
                "output_sha256": sha(
                    (teacher / stage / ("OUTPUT-" + str(index) + ".json")).read_bytes()
                ),
                "verification_sha256": sha(
                    (verified / str(index) / "VERIFICATION.json").read_bytes()
                ),
            }
            calls.append(row)
            rows.append(row)
            previous = output["answer"]
            expected = [
                *expected,
                {"role": "assistant", "content": output["answer"]},
                {"role": "tool", "content": record["feedback"]},
            ]
        teacher_pairs.append({"project_id": task["project_id"], **pair(rows)})
    pairs["T2"] = teacher_pairs
    assert len(calls) == 24
    assert len(list((ROOT / "results").glob("*/*/GENERATION_STARTED-*.json"))) == 16
    assert len(list(teacher.glob("*/GENERATION_STARTED-*.json"))) == 8
    aggregates = {}
    for mode, mode_pairs in pairs.items():
        rows = [row for row in calls if row["mode"] == mode]
        aggregates[mode] = {
            key: sum(row[key] for row in mode_pairs)
            for key in ("first", "final", "any_success", "recovery", "regression")
        }
        aggregates[mode].update(
            tasks=4,
            recovery_opportunities=sum(not row["first"] for row in mode_pairs),
            preservation_opportunities=sum(row["first"] for row in mode_pairs),
            actual_model_calls=len(rows),
            actual_verifier_calls=len(rows),
            actual_native_children=sum(row["actual_native_child"] for row in rows),
            input_tokens=sum(row["input_tokens"] for row in rows),
            output_tokens=sum(row["output_tokens"] for row in rows),
            generation_wall_seconds=sum(row["generation_wall_seconds"] for row in rows),
            verifier_wall_seconds=sum(row["verifier_wall_seconds"] for row in rows),
            output_caps_hit=sum(row["hit_output_limit"] for row in rows),
            failure_categories=dict(
                collections.Counter(row["failure_category"] for row in rows)
            ),
            unchanged_second_answers=sum(
                row["same_answer_as_previous"] for row in rows
            ),
        )
    owner = read(ROOT / "owned-students-1/COMPLETE.json")
    assert owner["actual_student_model_calls"] == 16 and all(
        x["wait_returncode"] == 0 and not x["timed_out"] for x in owner["stage_exits"]
    )
    preflight = read(ROOT / "preparation-1/prepared/SANDBOX_PREFLIGHT.json")
    assert len(preflight) == 4 and all(
        not row["before"]["success"] and row["after"]["success"] for row in preflight
    )
    summary = {
        "schema": "hepta.upstream-current-student-readout.v1",
        "status": "COMPLETE_24_REAL_CALLS_NO_NEW_TRAINING",
        "source_commit": SOURCE,
        "teacher_freeze_commit": "9cfa4995c5d08aa0af00cdda6ef1fa67e49b6d1e",
        "protocol_sha256": sha((ROOT / "prepared/PROTOCOL.json").read_bytes()),
        "generation_config_sha256": protocol["generation_config_sha256"],
        "ancestral_generation_config_sha256": protocol[
            "ancestral_generation_config_sha256"
        ],
        "actual_model_calls": 24,
        "actual_verifier_calls": 24,
        "actual_native_children": sum(x["actual_native_child"] for x in calls),
        "actual_native_cases": sum(x.get("native_tests", 0) for x in calls),
        "preflight_native_children": 8,
        "preflight_native_cases": sum(
            row[side]["tests"] for row in preflight for side in ("before", "after")
        ),
        "new_training_updates": 0,
        "aggregates": aggregates,
        "pairs": pairs,
        "models": models,
        "first_task_information_identical": True,
        "adaptive_feedback_is_own_actual_observation": True,
        "complete_context_checked_before_every_call": True,
        "input_truncation_count": 0,
        "uniform_input_cap": 8192,
        "uniform_output_cap": 2048,
        "physical_compute_matched_across_teacher_and_students": False,
        "independent_maintainer_lineages": 4,
        "authenticated_users": 0,
        "scientific_independent_confirmation": False,
        "native_adoption": False,
        "research_NoUpdate_retained": True,
        "multiteacher_mutual_complementarity_demonstrated": False,
        "whole_host_cpu_package_energy": owner["whole_host_cpu_package_energy"],
        "energy_scope": owner["energy_scope"],
        "student_owner_wall_seconds": owner["owner_wall_seconds"],
        "student_stage_exits": owner["stage_exits"],
        "teacher_stage_owner_wall_seconds": {
            stage: read(teacher / (stage.upper() + "_COMPLETE.json"))["wall_seconds"]
            for stage in ("first", "second")
        },
        "native_cpu_counter_scope": "Reported RUSAGE_CHILDREN deltas are the observed reaped-child counter only; sandbox descendant CPU accounting is not established, and this is not full-system compute.",
        "gpu_energy_joules": None,
        "teacher_host_energy_joules": None,
        "network_energy_joules": None,
        "monetary_cost": None,
        "full_system_cost_known": False,
        "nested_windows_are_not_additive": True,
        "historical_public_sources_not_future_eval": True,
        "pretraining_contamination_excluded": False,
        "teacher_software_model_license_conflict_retained": True,
        "teacher_internal_research_only": True,
        "collection_owns_no_service_configuration_change": True,
        "collector_new_model_calls": 0,
        "collector_new_verifier_calls": 0,
    }
    write(out / "CALLS.json", calls)
    write(out / "READOUT.json", summary)
    dependencies = ROOT / "retained-dependencies"
    dependencies.mkdir(exist_ok=False)
    ppath = PREVIOUS / "retained/PARENT_MODEL.json"
    cpath = PREVIOUS / "retained/training/verified_credit/manifest.json"
    for label, path, expected in (
        ("P", ppath, protocol["manifest_sha256"]["P"]),
        ("C", cpath, protocol["manifest_sha256"]["C"]),
    ):
        raw = path.read_bytes()
        assert sha(raw) == expected
        write(dependencies / (label + "_MANIFEST.json"), raw)
    parent = read(ppath)
    credit = read(cpath)
    closure = []
    for relative, expected in parent["source_inventory"].items():
        src = OLD_CODE / relative
        raw = src.read_bytes()
        assert sha(raw) == expected
        write(dependencies / "old-code" / relative, raw)
        closure.append(
            {"path": "old-code/" + relative, "sha256": expected, "bytes": len(raw)}
        )
    candidate = PREVIOUS / "source/qualification/cell-current-policy-credit-20261118"
    for relative, expected in credit["candidate_files"].items():
        raw = (candidate / relative).read_bytes()
        assert sha(raw) == expected
        write(dependencies / "credit-code" / relative, raw)
        closure.append(
            {"path": "credit-code/" + relative, "sha256": expected, "bytes": len(raw)}
        )
    write(dependencies / "SOURCE_CLOSURE.json", closure)
    write(
        dependencies / "UPSTREAM_SOURCES.json", (MATERIAL / "SOURCES.json").read_bytes()
    )
    write(
        dependencies / "UPSTREAM_REPLAY_RESULT.json",
        (MATERIAL / "replay-1/RESULT.json").read_bytes(),
    )
    write(
        dependencies / "PRIOR_ARTIFACTS.json",
        {
            "upstream_complete_archive_sha256": "998d989c99834dfd70058bcee4e3ea8f38cea00dbeb36dc7481c51501c1ed9f7",
            "upstream_complete_archive_pr": 6715,
            "P_adapter_previous_evidence_pr": 6699,
            "P_previous_complete_archive_sha256": "bb42d6353d4865c92790948473dcacedd626d160dd2e50cf2e94f7a66f258476",
            "C_adapter_previous_evidence_pr": 6707,
            "C_previous_complete_archive_sha256": "95beda262721a747aeb3180b7d7f37a245735870b3ee0c8c58e80e45857b9bb6",
            "weights_retrained_or_modified_here": False,
            "model_bytes_not_duplicated_in_this_collection": True,
        },
    )
    # Every owned original is retained, including earlier engineering/probe failures.
    items = []
    for path in sorted(ROOT.rglob("*")):
        rel = path.relative_to(ROOT)
        if (
            not path.is_file()
            or "__pycache__" in rel.parts
            or rel.parts[0].startswith("export-")
        ):
            continue
        assert not path.is_symlink() and path.stat().st_nlink == 1
        raw = path.read_bytes()
        items.append((rel.as_posix(), raw))
    for name in ("CALLS.json", "READOUT.json"):
        items.append(("readout/" + name, (out / name).read_bytes()))
    index = {
        "schema": "hepta.complete-owned-original-index.v1",
        "source_commit": SOURCE,
        "files": [
            {"path": name, "bytes": len(raw), "sha256": sha(raw)} for name, raw in items
        ],
        "actual_model_calls": 24,
        "actual_verifier_calls": 24,
        "prior_dependencies_are_explicitly_external": True,
    }
    index_raw = canonical(index) + b"\n"
    write(out / "INDEX.json", index_raw)
    archive = out / "complete-originals.tar.gz"
    with (
        archive.open("xb") as stream,
        gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w") as tar,
    ):
        for name, raw in items + [("INDEX.json", index_raw)]:
            entry = tarfile.TarInfo(name)
            entry.size = len(raw)
            entry.mode = 0o600
            entry.mtime = 0
            tar.addfile(entry, io.BytesIO(raw))
    archive_bytes = archive.read_bytes()
    manifest = {
        "archive": str(archive),
        "sha256": sha(archive_bytes),
        "bytes": len(archive_bytes),
        "original_files": len(items),
        "tar_members": len(items) + 1,
        "index_sha256": sha(index_raw),
        "readout_sha256": sha((out / "READOUT.json").read_bytes()),
        "calls_sha256": sha((out / "CALLS.json").read_bytes()),
        "collector_sha256": sha(Path(__file__).read_bytes()),
        "collector_wall_seconds": time.perf_counter() - started,
        "collector_self_cpu_seconds": time.process_time() - cpu,
        "new_model_calls": 0,
        "new_native_verifier_calls": 0,
    }
    write(out / "ARCHIVE_MANIFEST.json", manifest)
    print(
        json.dumps(
            {"status": "COMPLETE", "aggregates": aggregates, "manifest": manifest}
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
