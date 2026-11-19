"""Reconcile completed original calls and native receipts; run no new model or tests."""

import argparse
import copy
import hashlib
import importlib
import json
from pathlib import Path
import sys
import time
import xml.etree.ElementTree as ET


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


def write(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def audit(root, terminal_path, output):
    output.mkdir(exist_ok=False)
    read_inputs = {}

    def raw(path):
        path = Path(path)
        data = path.read_bytes()
        row = {"path": str(path), "bytes": len(data), "sha256": sha(data)}
        if str(path) in read_inputs and read_inputs[str(path)] != row:
            raise ValueError("original evidence changed while read: " + str(path))
        read_inputs[str(path)] = row
        return data

    def read(path):
        return json.loads(raw(path))

    terminal = read(terminal_path)
    terminal = json.loads(terminal["content"][0]["text"])
    if not (
        terminal["status"]["state"] == "exited"
        and terminal["status"]["exit_code"] == 0
        and terminal["status"]["output_complete"]
    ):
        raise ValueError(
            "authoritative original owner terminal is not successful and complete"
        )
    deployment = read(root / "DEPLOYMENT.json")
    protocol_raw = raw(root / "prepared/PROTOCOL.json")
    if sha(protocol_raw) != deployment["protocol_sha256"]:
        raise ValueError("published protocol differs")
    protocol = json.loads(protocol_raw)
    task_raw = raw(root / "prepared/TASKS.json")
    binding_raw = raw(root / "prepared/BINDINGS.json")
    if (
        sha(task_raw) != protocol["task_records_sha256"]
        or sha(binding_raw) != protocol["source_bindings_sha256"]
    ):
        raise ValueError("task or binding bytes changed")
    tasks, bindings = json.loads(task_raw), json.loads(binding_raw)
    cpu_raw = raw(deployment["cpu_qualification_result_path"])
    if sha(cpu_raw) != protocol["cpu_controls_result_sha256"]:
        raise ValueError("CPU reference qualification changed")
    qualification = json.loads(cpu_raw)
    reference_cases = {
        row["project_id"]: [
            case["name"] for case in row["after"]["original_verification"]["cases"]
        ]
        for row in qualification["native_pairs"]
    }
    source = Path(deployment["source_directory"])
    for name, digest in deployment["candidate_files"].items():
        if sha(raw(source / name)) != digest:
            raise ValueError("execution source changed")
    for path, digest in deployment["external_source_files"].items():
        if sha(raw(path)) != digest:
            raise ValueError("original loader/verifier source changed")
    sys.path.insert(0, str(source))
    runner = importlib.import_module("run_replacement")
    codec = runner.codec
    if Path(runner.__file__).resolve() != (source / "run_replacement.py").resolve():
        raise ValueError("wrong source imported for read-only reconciliation")
    _, layout, _ = runner.environment()
    transformers = importlib.import_module("transformers")
    chat = importlib.import_module("cell_experiments.chat_protocol")
    runtime = protocol["models"]["P"]["runtime"]
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        str(layout.probe._base(runner.ARTIFACT, runtime["base_directory"])),
        local_files_only=True,
        trust_remote_code=False,
    )
    if (
        chat.template_digest(tokenizer.get_chat_template())
        != runtime["chat_template_sha256"]
    ):
        raise ValueError("tokenizer template changed")
    owner = read(root / "owned-evaluation-1/COMPLETE.json")
    if (
        owner["status"] != "COMPLETE"
        or owner["actual_model_calls"] != 24
        or owner["source_commit"] != deployment["source_commit"]
    ):
        raise ValueError("original owner did not finish exactly the prescribed scope")
    if len(owner["stage_exits"]) != 3 or any(
        row["wait_returncode"] != 0 or row["timed_out"] for row in owner["stage_exits"]
    ):
        raise ValueError("a model stage has a real failure/timeout")

    def audit_native(directory, original, task, action, binding):
        native_dir = directory / "original-verifier/native"
        saved_original = read(directory / "original-verifier/VERIFICATION.json")
        if original != saved_original:
            raise ValueError("wrapper does not preserve the original verifier receipt")
        if original["answer_sha256"] != sha(action.encode()):
            raise ValueError("original verifier used different converted action bytes")
        if not original["actual_native_child"]:
            if (
                original["stage"] != "patch_admission"
                or native_dir.exists()
                or original["success"]
            ):
                raise ValueError("original admission failure was misreported")
            return {
                "actual_native_child": False,
                "reason": original["reason"],
                "original_stage": original["stage"],
            }
        admission = read(directory / "original-verifier/ADMISSION.json")
        actual = read(native_dir / "RESULT.json")
        for key, value in actual.items():
            if original.get(key) != value:
                raise ValueError("original native result field differs: " + key)
        case = read(native_dir / "CASE.json")
        intent = read(native_dir / "INTENT.json")
        read(native_dir / "STARTED.json")
        if actual["case_sha256"] != sha(canonical(case) + b"\n"):
            raise ValueError("native case bytes differ")
        for name, key in (
            ("STDOUT.txt", "stdout_sha256"),
            ("STDERR.txt", "stderr_sha256"),
        ):
            if sha(raw(native_dir / name)) != actual[key]:
                raise ValueError("original native output bytes changed")
        patched = raw(native_dir / "PATCHED_SOURCE.py")
        before, checked_binding = codec.source_binding(task["project_id"])
        if checked_binding != binding:
            raise ValueError("source binding changed during patch reconstruction")
        original_text = before.decode()
        replacements = []
        for edit in json.loads(action)["edits"]:
            if original_text.count(edit["old"]) != 1:
                raise ValueError("executed original old text was not unique")
            start = original_text.index(edit["old"])
            replacements.append((start, start + len(edit["old"]), edit["new"]))
        rebuilt = original_text
        for start, end, new in sorted(replacements, reverse=True):
            rebuilt = rebuilt[:start] + new + rebuilt[end:]
        if rebuilt.encode() != patched:
            raise ValueError(
                "native child source differs from the exact converted model action"
            )
        if (
            sha(patched) != admission["patched_source_sha256"]
            or sha(patched) != case["source_sha256"]
            or sha(patched) != actual["patched_source_sha256"]
        ):
            raise ValueError("different candidate source was executed")
        if (
            case["test_sha256"] != task["original_tests_sha256"]
            or actual["original_test_sha256"] != task["original_tests_sha256"]
        ):
            raise ValueError("original immutable tests differ")
        if (
            case["source_path"] != task["source_path"]
            or case["project_id"] != task["project_id"]
        ):
            raise ValueError("native task identity changed")
        if (
            admission["original_source_sha256"] != binding["original_source_sha256"]
            or admission["test_files_modified"]
            or admission["oracle_files_modified"]
        ):
            raise ValueError("native admission changed immutable inputs")
        if (
            intent["native_verifier_source_sha256"]
            != protocol["native_verifier_sha256"]
            or intent["timeout_seconds"] != 120
        ):
            raise ValueError("native source or timeout changed")
        required = (
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
            "--clearenv",
            "--cap-drop",
        )
        if intent["argv"][0] != "/usr/bin/bwrap" or not all(
            item in intent["argv"] for item in required
        ):
            raise ValueError("original real sandbox invocation differs")
        attest_path = native_dir / "sandbox-output/SANDBOX_ATTESTATION.json"
        attested = False
        if attest_path.exists():
            attestation_raw = raw(attest_path)
            attestation = json.loads(attestation_raw)
            if sha(attestation_raw) != actual["sandbox_attestation_sha256"]:
                raise ValueError("native sandbox attestation bytes differ")
            attested = (
                attestation["net_namespace"] != case["host_net_namespace"]
                and attestation["pid_namespace"] != case["host_pid_namespace"]
                and attestation["network_interfaces"] == [[1, "lo"]]
                and not attestation["host_canary_visible"]
                and attestation["tests_readonly"]
                and attestation["dependencies_readonly"]
                and attestation["package_readonly"]
                and int(attestation["effective_capabilities"], 16) == 0
                and attestation["test_sha256"] == case["test_sha256"]
                and attestation["source_sha256"] == case["source_sha256"]
            )
            if not attested:
                raise ValueError("actual native attestation failed")
        junit_path = native_dir / "sandbox-output/junit.xml"
        case_rows, counts = [], {}
        if junit_path.exists():
            junit_raw = raw(junit_path)
            if sha(junit_raw) != actual["junit_sha256"]:
                raise ValueError("native JUnit bytes differ")
            nodes = list(ET.fromstring(junit_raw).iter("testcase"))
            counts = {
                "tests": len(nodes),
                "failures": sum(row.find("failure") is not None for row in nodes),
                "errors": sum(row.find("error") is not None for row in nodes),
                "skipped": sum(row.find("skipped") is not None for row in nodes),
            }
            case_rows = [
                {
                    "name": row.attrib["name"],
                    "failure": None
                    if row.find("failure") is None
                    else row.find("failure").attrib.get("message"),
                    "error": None
                    if row.find("error") is None
                    else row.find("error").attrib.get("message"),
                }
                for row in nodes
            ]
            if actual["cases"] != case_rows or any(
                actual.get(key) != value for key, value in counts.items()
            ):
                raise ValueError("native case summary differs from original XML")
        same_cases = [row["name"] for row in case_rows] == reference_cases[
            task["project_id"]
        ]
        strict_success = bool(
            actual["actual_wait_returncode"] == 0
            and not actual["timed_out"]
            and same_cases
            and counts.get("failures")
            == counts.get("errors")
            == counts.get("skipped")
            == 0
            and attested
        )
        if (
            strict_success != actual["success"]
            or same_cases != actual["same_original_case_set"]
        ):
            raise ValueError(
                "original native success does not match real exit/XML/case set/attestation"
            )
        return {
            "actual_native_child": True,
            "strict_success_recomputed": strict_success,
            "actual_wait_returncode": actual["actual_wait_returncode"],
            "timed_out": actual["timed_out"],
            "same_original_case_set": same_cases,
            "sandbox_attested": attested,
            "counts": counts,
            "failure_cases": [
                row for row in case_rows if row["failure"] or row["error"]
            ],
        }

    calls, paired, models, first_requests = [], [], {}, {}
    codec_reconstructions = 0
    for mode in protocol["planned_modes"]:
        result_dir = root / "results" / mode
        identity = protocol["models"][mode]
        if sha(raw(identity["path"])) != identity["file_sha256"]:
            raise ValueError("model manifest original changed")
        loaded = read(result_dir / "MODEL_LOADED.json")
        result = read(result_dir / "RESULT.json")
        if (
            loaded["model_manifest_digest"] != identity["manifest_digest"]
            or loaded["actual_parameter_digest_verified_by_original_loader"]
            != identity["parameter_after"]
        ):
            raise ValueError("actual cold-loaded model identity differs")
        if (
            loaded["generation_config_sha256"] != protocol["generation_config_sha256"]
            or loaded["cuda_memory_fraction"] != 0.70
            or not loaded["all_parameters_frozen"]
        ):
            raise ValueError("actual common generation/frozen-parameter policy differs")
        stage_exit = read(root / "owned-evaluation-1" / mode / "EXIT.json")
        if stage_exit not in owner["stage_exits"] or stage_exit["wait_returncode"] != 0:
            raise ValueError("actual mode child did not finish")
        for name, key in (
            ("STDOUT.txt", "stdout_sha256"),
            ("STDERR.txt", "stderr_sha256"),
        ):
            if sha(raw(root / "owned-evaluation-1" / mode / name)) != stage_exit[key]:
                raise ValueError("original mode output bytes changed")
        mode_pairs = []
        for index, (task, binding) in enumerate(zip(tasks, bindings)):
            folder = result_dir / str(index)
            if read(folder / "ORIGINAL_TASK.json") != task:
                raise ValueError("actual task differs from frozen common panel")
            messages = copy.deepcopy(task["task"]["messages"])
            outcomes = []
            for attempt in range(2):
                request = read(folder / ("REQUEST-" + str(attempt) + ".json"))
                produced = read(folder / ("OUTPUT-" + str(attempt) + ".json"))
                receipt = read(folder / ("VERIFICATION-" + str(attempt) + ".json"))
                feedback = read(folder / ("FEEDBACK-" + str(attempt) + ".json"))
                generation = read(
                    folder / ("GENERATION_STARTED-" + str(attempt) + ".json")
                )
                if request != {
                    "record_id": task["record_id"],
                    "task": {"input": task["task"]["input"], "messages": messages},
                }:
                    raise ValueError(
                        "actual current-policy prefix differs from own real first answer/feedback"
                    )
                rendered = chat.render_prompt(
                    tokenizer, task["task"]["input"], messages
                )
                input_count = len(tokenizer.encode(rendered, add_special_tokens=False))
                if (
                    produced["loaded_model_manifest_digest"]
                    != identity["manifest_digest"]
                    or produced["generation_config_sha256"]
                    != protocol["generation_config_sha256"]
                    or produced["effective_policy_digest"]
                    != loaded["effective_policy_digest"]
                    or produced["rendered_input_sha256"] != sha(rendered.encode())
                    or produced["messages_sha256"] != sha(canonical(messages))
                    or produced["input_sha256"] != sha(task["task"]["input"].encode())
                    or produced["input_tokens"] != input_count
                    or produced["output_tokens"] != len(produced["output_token_ids"])
                    or tokenizer.decode(
                        produced["output_token_ids"],
                        skip_special_tokens=True,
                        clean_up_tokenization_spaces=False,
                    )
                    != produced["answer"]
                    or produced["input_truncated"]
                ):
                    raise ValueError(
                        "actual request/token/model/generation binding differs"
                    )
                if not (
                    input_count <= 8192
                    and produced["output_tokens"] <= 2048
                    and input_count + 2048 <= 32768
                ):
                    raise ValueError(
                        "actual complete context or output exceeded the frozen budget"
                    )
                if (
                    generation["input_tokens"] != input_count
                    or generation["effective_policy_digest"]
                    != loaded["effective_policy_digest"]
                    or int(generation["started_at_ns"])
                    <= int(deployment["prepared_at_ns"])
                ):
                    raise ValueError(
                        "generation entry lacks the frozen policy or occurred before deployment"
                    )
                if attempt == 0:
                    key = task["project_id"]
                    if key in first_requests and first_requests[key] != request:
                        raise ValueError("models received different first requests")
                    first_requests[key] = request
                verify_dir = folder / ("verify-" + str(attempt))
                if (
                    raw(verify_dir / "RAW_ANSWER.txt") != produced["answer"].encode()
                    or read(verify_dir / "VERIFICATION.json") != receipt
                ):
                    raise ValueError("raw output or actual wrapper receipt differs")
                if (
                    receipt["raw_answer_sha256"] != sha(produced["answer"].encode())
                    or receipt["wrapper_source_sha256"] != protocol["codec_sha256"]
                    or receipt["original_verifier_sha256"]
                    != protocol["native_verifier_sha256"]
                ):
                    raise ValueError("raw/wrapper/native source binding differs")
                native_audit = None
                try:
                    action, conversion, actual_binding = codec.convert(
                        task["project_id"], produced["answer"]
                    )
                    codec_reconstructions += 1
                except (ValueError, SyntaxError, TypeError, KeyError) as error:
                    if (
                        receipt["stage"] != "replacement_admission"
                        or receipt["actual_native_child"]
                        or receipt["success"]
                        or receipt["reason"] != str(error)
                    ):
                        raise ValueError(
                            "pure codec reconstruction differs from original rejection"
                        ) from error
                else:
                    if (
                        raw(verify_dir / "CONVERTED_ACTION.json") != action.encode()
                        or read(verify_dir / "CONVERSION.json") != conversion
                        or read(verify_dir / "BINDING.json") != actual_binding
                        or actual_binding != binding
                    ):
                        raise ValueError(
                            "actual converted action or trusted BEFORE binding differs"
                        )
                    if receipt["converted_action_sha256"] != sha(
                        action.encode()
                    ) or receipt["conversion_sha256"] != sha(canonical(conversion)):
                        raise ValueError("raw-to-original-action linkage differs")
                    original = receipt["original_verification"]
                    if (
                        receipt["original_verification_sha256"]
                        != sha(canonical(original))
                        or receipt["success"] != original["success"]
                    ):
                        raise ValueError("wrapper changed original success or receipt")
                    native_audit = audit_native(
                        verify_dir, original, task, action, binding
                    )
                if feedback["content"] != codec.feedback(receipt) or feedback[
                    "verification_digest"
                ] != sha(canonical(receipt)):
                    raise ValueError("observed feedback differs from the real receipt")
                row = {
                    "mode": mode,
                    "task_index": index,
                    "project_id": task["project_id"],
                    "attempt": attempt,
                    "success": receipt["success"],
                    "stage": receipt["stage"],
                    "actual_native_child": receipt["actual_native_child"],
                    "input_tokens": input_count,
                    "output_tokens": produced["output_tokens"],
                    "output_cap_hit": produced["hit_output_limit"],
                    "generation_wall_seconds": produced["wall_seconds"],
                    "codec_and_verifier_wall_seconds": receipt["wall_seconds"],
                    "reason": receipt.get("reason")
                    or receipt.get("original_verification", {}).get("reason"),
                    "native_audit": native_audit,
                    "original_directory": str(folder),
                    "raw_answer_sha256": receipt["raw_answer_sha256"],
                    "converted_action_sha256": receipt["converted_action_sha256"],
                }
                calls.append(row)
                outcomes.append(receipt["success"])
                messages += [
                    {"role": "assistant", "content": produced["answer"]},
                    {"role": "tool", "content": feedback["content"]},
                ]
            pair = {
                "project_id": task["project_id"],
                "first": outcomes[0],
                "final": outcomes[1],
                "any_success": any(outcomes),
                "recovery": not outcomes[0] and outcomes[1],
                "recovery_opportunity": not outcomes[0],
                "regression": outcomes[0] and not outcomes[1],
                "preservation_opportunity": outcomes[0],
            }
            if read(folder / "PAIR.json") != pair:
                raise ValueError("stored paired outcome differs from real receipts")
            mode_pairs.append(pair)
            paired.append({"mode": mode, **pair})
        model_calls = [row for row in calls if row["mode"] == mode]
        counts = {
            key: sum(pair[key] for pair in mode_pairs)
            for key in (
                "first",
                "final",
                "any_success",
                "recovery",
                "recovery_opportunity",
                "regression",
                "preservation_opportunity",
            )
        }
        if (
            result["summary"] != counts
            or result["actual_model_calls"] != len(model_calls)
            or len(model_calls) != 8
        ):
            raise ValueError("original mode totals differ from complete receipts")
        models[mode] = {
            "model_manifest_digest": identity["manifest_digest"],
            "parameter_after": identity["parameter_after"],
            "actual_model_calls": 8,
            "native_children": sum(row["actual_native_child"] for row in model_calls),
            "stage_counts": {
                stage: sum(row["stage"] == stage for row in model_calls)
                for stage in sorted({row["stage"] for row in model_calls})
            },
            "scores": counts,
            "input_tokens": sum(row["input_tokens"] for row in model_calls),
            "output_tokens": sum(row["output_tokens"] for row in model_calls),
            "output_caps_hit": sum(row["output_cap_hit"] for row in model_calls),
            "original_stage_cost": result["cost"],
            "original_owner_stage_exit": stage_exit,
        }

    if (
        len(calls) != 24
        or sum(model["actual_model_calls"] for model in models.values()) != 24
    ):
        raise ValueError("incomplete original 24-call scope")
    energies = []
    for path in sorted(
        (root / "owned-evaluation-1").glob("ENERGY-*.json"),
        key=lambda path: int(path.stem.split("-")[-1]),
    ):
        energies.append(read(path))
    if len(energies) != owner["energy_samples"]:
        raise ValueError("original energy sample count differs")
    recomputed_energy = []
    for index in (0, 1):
        rows = [row["domains"][index] for row in energies]
        if (
            len(rows) >= 2
            and all(row.get("exit_code") == 0 for row in rows)
            and len({row["boot_id"] for row in energies}) == 1
            and len({row["max_energy_range_uj"] for row in rows}) == 1
        ):
            maximum = rows[0]["max_energy_range_uj"]
            deltas = [
                (right["energy_uj"] - left["energy_uj"]) % maximum
                for left, right in zip(rows, rows[1:])
            ]
            recomputed_energy.append(
                {
                    "domain_name": rows[0]["domain_name"],
                    "host_window_joules": sum(deltas) / 1e6,
                    "modular_deltas_uj": deltas,
                    "samples": len(rows),
                    "no_multiple_wraps_between_samples_assumption": True,
                }
            )
    if recomputed_energy != owner["whole_host_cpu_package_energy"]:
        raise ValueError("whole-host energy summary differs from original samples")
    costs = {
        "schema": "hepta.replacement-original-cost.v1",
        "actual_new_generations": 24,
        "actual_inference_native_children": sum(
            row["actual_native_child"] for row in calls
        ),
        "prior_cpu_qualification_native_children": qualification[
            "actual_native_children"
        ],
        "prior_cpu_qualification_source_commit": qualification["source_commit"],
        "prior_cpu_qualification_result_sha256": protocol["cpu_controls_result_sha256"],
        "model_stage_wall_seconds": sum(
            row["wall_seconds"] for row in owner["stage_exits"]
        ),
        "owner_wall_seconds": owner["owner_wall_seconds"],
        "observed_model_stage_child_cpu_seconds_including_energy_reads": sum(
            row["observed_child_cpu_seconds_including_energy_reads"]
            for row in owner["stage_exits"]
        ),
        "input_tokens": sum(row["input_tokens"] for row in calls),
        "output_tokens": sum(row["output_tokens"] for row in calls),
        "output_caps_hit": sum(row["output_cap_hit"] for row in calls),
        "nested_generation_wall_seconds": sum(
            row["generation_wall_seconds"] for row in calls
        ),
        "nested_codec_native_wall_seconds": sum(
            row["codec_and_verifier_wall_seconds"] for row in calls
        ),
        "nested_windows_not_added_to_stage_totals": True,
        "whole_host_cpu_package_energy": recomputed_energy,
        "energy_scope": owner["energy_scope"],
        "gpu_energy_joules": None,
        "network_energy_joules": None,
        "monetary_cost": None,
        "unmeasured_engineering_import_preflight_format_archive_and_controller_costs_known": False,
        "earlier_56_call_training_and_evaluation_costs_not_recounted_here": True,
        "full_system_cost_known": False,
    }
    readout = {
        "schema": "hepta.replacement-A-readout.v1",
        "status": "COMPLETE_ORIGINAL_24_RECONCILED",
        "execution_source_commit": deployment["source_commit"],
        "protocol_sha256": deployment["protocol_sha256"],
        "created_at_ns": str(time.time_ns()),
        "scope": "already-exposed A engineering diagnostic; no new independent confirmation",
        "primary_model_predeclared": "native_feedback",
        "models": models,
        "actual_model_calls": 24,
        "actual_native_children": costs["actual_inference_native_children"],
        "same_first_requests_and_original_business_oracle": True,
        "actual_own_first_response_and_real_feedback_checked": True,
        "hash_and_token_decode_checks_passed": True,
        "native_success_recomputed_from_original_exit_XML_case_set_and_attestation": True,
        "new_readout_model_calls": 0,
        "new_readout_native_children": 0,
        "pure_codec_reconstructions": codec_reconstructions,
        "new_training_updates": 0,
        "B3_model_calls": 0,
        "old_research_NoUpdate_unchanged": True,
        "decision": "DIAGNOSTIC_ONLY_KEEP_PREVIOUS_NOUPDATE",
        "independent_confirmation_qualified": False,
        "native_adoption": False,
        "authenticated_users": 0,
        "limits": [
            "A was already exposed and used in earlier training",
            "the interface and prompts differ from the original JSON experiment, so old scores are not replaced",
            "equal caps and calls do not imply equal physical compute or actual token cost",
            "this run adds no retrieval arm, new training, teacher complementarity, source-growth curve or owner adoption",
        ],
    }
    write(output / "CALLS.json", calls)
    write(output / "PAIRED_TASKS.json", paired)
    write(output / "COST_LEDGER.json", costs)
    write(output / "READOUT.json", readout)
    write(
        output / "INPUT_INDEX.json",
        sorted(read_inputs.values(), key=lambda row: row["path"]),
    )
    print(
        json.dumps(
            {
                "readout_sha256": sha((output / "READOUT.json").read_bytes()),
                "cost_ledger_sha256": sha((output / "COST_LEDGER.json").read_bytes()),
                "models": models,
                "actual_native_children": readout["actual_native_children"],
                "new_readout_model_calls": 0,
                "new_readout_native_children": 0,
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--owner-terminal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit(args.root, args.owner_terminal, args.output)
