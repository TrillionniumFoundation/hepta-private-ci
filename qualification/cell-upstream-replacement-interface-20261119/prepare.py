"""Qualify a common A-only function interface with exact bytes and real native tests."""

import argparse
import ast
import copy
import importlib
import json
from pathlib import Path
import resource
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
codec = importlib.import_module("replacement_codec")

OLD_ROOT = Path("/home/qian-qi/work/hepta-upstream-current-policy-20261118-2e9b")
OLD_CODE = Path("/home/qian-qi/work/hepta-e1-matched-info-20261118-2e9b/source")
ARTIFACT = Path("/dev/shm/hepta-cell-experiments-v3-20261116-0c078a")
LAYOUT_ROOT = Path(
    "/home/qian-qi/work/hepta-upstream-layout-learning-20261118-2e9b-checkpoint2"
)
LEGACY_PROTOCOL_SHA256 = (
    "56071aea433cbf5e3b3c479e01ad39e3b025533030e6d4c57c68357163bdfc50"
)
MANIFESTS = {
    "P": (
        "/home/qian-qi/work/hepta-e2-current-credit-20261118-2e9b/retained/PARENT_MODEL.json",
        "4a9c82ab237a5d902db378d1987170c1608bdef40c5603731718f4202fff6c5d",
    ),
    "document_evidence": (
        str(LAYOUT_ROOT / "retained/document_evidence/manifest.json"),
        "82e4f88d542333b25d50f3bd71636b43103638a48d477542aa1e496519314251",
    ),
    "native_feedback": (
        str(LAYOUT_ROOT / "retained/native_feedback/manifest.json"),
        "a040d38216cff4a6bbde77cdf5e8f0d899e82407ced43f83002335914315dd3e",
    ),
}


def payload(body):
    if not body.endswith("\n"):
        raise ValueError("reference snippet must retain its original final newline")
    return "```python\n" + body + "```"


def prompt_for(task, binding):
    original = task["task"]["input"]
    marker = "\n\nProject: "
    if original.count(marker) != 1:
        raise ValueError("original task structure differs")
    context = "Project: " + original.split(marker, 1)[1]
    instructions = (
        "Repair this real upstream Python regression. Return exactly one closed Python code block, "
        "beginning with ```python and ending with ```, with no surrounding prose or extra blocks. "
        "Inside the block, return the COMPLETE replacement definition of "
        + binding["function"]
        + ", including its original signature and any decorators. Do not return JSON, a diff, tests, "
        "imports or an entire rewritten file. Only this function's body/docstring may change. "
        "Keep the signature and decorators identical. The adapter supplies the exact original old "
        "text and applies the generated replacement to the original revision; it never supplies "
        "any new repair code. Every attempt starts from that same original revision. "
        "No new external dependencies, test manipulation, process execution or network access are allowed."
    )
    if binding["optional_constant"]:
        instructions += (
            " You may also include at most one module-level "
            + binding["optional_constant"]
            + " = re.compile(<literal regex>) assignment in the same code block. "
            "The unchanged native validator checks this optional constant. Its insertion slot is "
            "immediately before the existing "
            + binding["constant_slot"]["insert_before_original_name"]
            + " assignment; the adapter does not invent its value. The original insertion anchor is:\n"
            + binding["constant_slot"]["anchor_old"]
        )
    instructions += (
        "\nOnly blank lines may surround or separate these permitted definitions. "
        "All original source, AST restrictions, read-only tests, isolated pytest command and timeouts remain in force.\n\n"
    )
    return instructions + context


def expect_reject(root, label, project, raw, rows):
    receipt = codec.verify(project, raw, root / label)
    if receipt["success"] or receipt["actual_native_child"]:
        raise ValueError(
            "negative admission control was not rejected before execution: " + label
        )
    rows.append(
        {
            "label": label,
            "project_id": project,
            "expected": "admission_reject_without_native_child",
            "observed": receipt,
            "verification_sha256": codec.sha(codec.canonical(receipt)),
        }
    )


def qualify(root, source_commit):
    output = root / "prepared"
    output.mkdir(exist_ok=False)
    control_root = root / "cpu-controls-1"
    control_root.mkdir(exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    native = codec.native_module()
    original_tasks = json.loads(codec.TASKS_PATH.read_bytes())
    if len(original_tasks) != 4:
        raise ValueError("exactly four bound A maintenance tasks required")
    legacy_raw = (OLD_ROOT / "prepared/PROTOCOL.json").read_bytes()
    if codec.sha(legacy_raw) != LEGACY_PROTOCOL_SHA256:
        raise ValueError("original common generation policy changed")
    legacy = json.loads(legacy_raw)
    expected_replays = native.read(native.MATERIAL_ROOT / "replay-1/RESULT.json")[
        "stages"
    ]
    tasks, controls, native_pairs, references, bindings = [], [], [], [], []
    codec.write(
        control_root / "STARTED.json",
        {
            "source_commit": source_commit,
            "started_at_ns": str(time.time_ns()),
            "codec_source_sha256": codec.sha(Path(codec.__file__).read_bytes()),
            "prepare_source_sha256": codec.sha(Path(__file__).read_bytes()),
            "planned_original_native_children": 8,
            "new_model_calls": 0,
            "new_training_updates": 0,
            "B3_material_read": False,
        },
    )
    for index, original_task in enumerate(original_tasks):
        project = original_task["project_id"]
        directory = control_root / str(index)
        directory.mkdir()
        before, binding = codec.source_binding(project)
        _, folder = native.source(project)
        after = (folder / "after" / binding["path"]).read_bytes()
        tree = ast.parse(after)
        fixed_function = codec.node_span(
            after.decode(), native.function(tree, binding["function"])
        )[2]
        extras = [
            row
            for row in tree.body
            if binding["optional_constant"]
            and native.constant_name(row) == binding["optional_constant"]
        ]
        if len(extras) > 1:
            raise ValueError("reference has duplicate optional constant")
        fixed_constant = (
            codec.node_span(after.decode(), extras[0])[2] if extras else None
        )
        body = fixed_function + ("\n" + fixed_constant if fixed_constant else "")
        reference = payload(body)
        action, conversion, regenerated_binding = codec.convert(project, reference)
        patched, admission = native.admit(project, action)
        if patched != after or binding != regenerated_binding:
            raise ValueError(
                "complete reference does not reproduce the exact original AFTER bytes"
            )
        codec.write(directory / "REFERENCE.txt", reference.encode())
        codec.write(directory / "REFERENCE_CONVERTED.json", action.encode())
        codec.write(directory / "REFERENCE_ADMISSION.json", admission)
        codec.write(directory / "BINDING.json", binding)
        # These are new real native children validating this new transport, not model calls.
        before_receipt = codec.verify(
            project, payload(binding["function_old"]), directory / "unchanged-before"
        )
        after_receipt = codec.verify(
            project, reference, directory / "upstream-reference"
        )
        for variant, receipt in (("before", before_receipt), ("after", after_receipt)):
            original = receipt.get("original_verification", {})
            expected = next(
                row
                for row in expected_replays
                if row["project_id"] == project and row["variant"] == variant
            )
            if (
                not receipt["actual_native_child"]
                or not original.get("same_original_case_set")
                or not original.get("sandbox_attestation_sha256")
            ):
                raise ValueError(
                    "new transport did not use the actual unchanged isolated native oracle"
                )
            for key in ("tests", "failures", "errors", "skipped"):
                if original.get(key) != expected.get(key):
                    raise ValueError(
                        "new transport changed original native outcome: "
                        + project
                        + ":"
                        + variant
                        + ":"
                        + key
                    )
            if original["timed_out"]:
                raise ValueError("new transport native oracle timed out")
        if before_receipt["success"] or not after_receipt["success"]:
            raise ValueError("unchanged-before/reference distinction failed")
        native_pairs.append(
            {"project_id": project, "before": before_receipt, "after": after_receipt}
        )
        negatives = {
            "prefix-prose": "Here is the fix:\n" + reference,
            "suffix-prose": reference + "\nDone.",
            "second-block": reference + "\n" + reference,
            "unclosed-fence": reference[:-3],
            "duplicate-function": payload(body + "\n" + fixed_function),
            "outside-statement": payload(body + "\nUNRELATED_SIDE_EFFECT = 1\n"),
            "top-level-import": payload("import os\n\n" + body),
            "wrong-function-name": payload(
                body.replace(
                    "def " + binding["function"] + "(", "def unrelated_function(", 1
                )
            ),
            "async-function": payload(
                body.replace(
                    "def " + binding["function"] + "(",
                    "async def " + binding["function"] + "(",
                    1,
                )
            ),
            "changed-decorator": payload("@staticmethod\n" + body),
            "syntax-error": payload("def " + binding["function"] + "(:\n    pass\n"),
            "oversized-output": "x" * (codec.MAXIMUM_RAW_BYTES + 1),
        }
        if fixed_constant:
            negatives["duplicate-constant"] = payload(body + "\n" + fixed_constant)
            negatives["nonliteral-constant"] = payload(
                fixed_function
                + "\n"
                + binding["optional_constant"]
                + " = re.compile(str(123))\n"
            )
        for label, raw in negatives.items():
            expect_reject(directory, label, project, raw, controls)
        for label, changed_bytes, changed_binding in (
            ("before-byte-tamper", before + b"\n", binding),
            ("allowed-path-tamper", before, {**binding, "path": "../outside.py"}),
        ):
            try:
                codec.action_from_bound_before(
                    project, reference, changed_bytes, changed_binding
                )
            except (ValueError, SyntaxError, TypeError, KeyError) as error:
                row = {
                    "label": label,
                    "project_id": project,
                    "expected": "bound_input_rejection",
                    "error_type": type(error).__name__,
                    "reason": str(error),
                    "actual_native_child": False,
                }
            else:
                raise ValueError(
                    "bound input negative control unexpectedly converted: " + label
                )
            codec.write(directory / (label + ".json"), row)
            controls.append(row)
        originals = {
            "original-unique-old": {"edits": [{"old": "\n", "new": "\n"}]},
            "original-overlap": {
                "edits": [
                    {"old": binding["function_old"], "new": fixed_function},
                    {"old": binding["function_old"], "new": fixed_function},
                ]
            },
        }
        before_tree = ast.parse(before)
        outside = next(
            row
            for row in before_tree.body
            if isinstance(row, (ast.Import, ast.ImportFrom))
            and before.decode().count(codec.node_span(before.decode(), row)[2]) == 1
        )
        outside_old = codec.node_span(before.decode(), outside)[2]
        originals["original-outside-ast"] = {
            "edits": [
                {"old": outside_old, "new": outside_old + "UNRELATED_SIDE_EFFECT = 1\n"}
            ]
        }
        for label, original_action in originals.items():
            receipt = native.verify(
                project, native.canonical(original_action).decode(), directory / label
            )
            if (
                receipt["success"]
                or receipt["actual_native_child"]
                or receipt["stage"] != "patch_admission"
            ):
                raise ValueError(
                    "unchanged strict native negative control failed: " + label
                )
            controls.append(
                {
                    "label": label,
                    "project_id": project,
                    "expected": "original_patch_admission_reject",
                    "observed": receipt,
                }
            )
        task = copy.deepcopy(original_task)
        prompt = prompt_for(original_task, binding)
        task.update(
            schema="hepta.upstream-replacement-A.v1",
            record_id="replacement-A-" + project.replace("/", "-"),
            task={"input": prompt, "messages": [{"role": "user", "content": prompt}]},
            prompt_sha256=codec.sha(prompt.encode()),
            original_A_task_sha256=codec.sha(codec.canonical(original_task)),
            source_binding_sha256=codec.sha(codec.canonical(binding)),
            format=codec.FORMAT,
            already_exposed_development=True,
            independent_confirmation_qualified=False,
        )
        tasks.append(task)
        bindings.append(binding)
        references.append(
            {
                "project_id": project,
                "payload": reference,
                "payload_sha256": codec.sha(reference.encode()),
                "exact_after_sha256": codec.sha(after),
                "conversion": conversion,
                "native_feedback": codec.feedback(after_receipt),
            }
        )
        print(
            json.dumps(
                {
                    "project": project,
                    "exact_after": True,
                    "before_failures": before_receipt["original_verification"][
                        "failures"
                    ],
                    "after_tests": after_receipt["original_verification"]["tests"],
                    "negative_controls_so_far": len(controls),
                    "new_model_calls": 0,
                }
            ),
            flush=True,
        )

    sys.path.insert(0, str(OLD_CODE / "scripts"))
    chat = importlib.import_module("cell_experiments.chat_protocol")
    probe = importlib.import_module("cell_experiments.causal_probe_v3")
    transformers = importlib.import_module("transformers")
    models = {}
    for name, (path, expected_sha) in MANIFESTS.items():
        raw = Path(path).read_bytes()
        if codec.sha(raw) != expected_sha:
            raise ValueError("frozen model manifest changed: " + name)
        manifest = json.loads(raw)
        models[name] = {
            "path": path,
            "file_sha256": expected_sha,
            "manifest_digest": codec.sha(codec.canonical(manifest)),
            "parameter_after": manifest["parameter_after"],
            "runtime": manifest["runtime"],
        }
    if not all(row["runtime"] == models["P"]["runtime"] for row in models.values()):
        raise ValueError("three model runtimes differ")
    runtime = models["P"]["runtime"]
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        str(probe._base(ARTIFACT, runtime["base_directory"])),
        local_files_only=True,
        trust_remote_code=False,
    )
    configuration = transformers.AutoConfig.from_pretrained(
        str(probe._base(ARTIFACT, runtime["base_directory"])),
        local_files_only=True,
        trust_remote_code=False,
    )
    if (
        chat.template_digest(tokenizer.get_chat_template())
        != runtime["chat_template_sha256"]
    ):
        raise ValueError("actual tokenizer template differs")
    if (
        int(configuration.max_position_embeddings)
        != legacy["native_max_position_embeddings"]
    ):
        raise ValueError("actual native context differs")
    token_rows = []
    for task, reference in zip(tasks, references):
        prompt = task["task"]["input"]
        rendered = chat.render_prompt(tokenizer, prompt, task["task"]["messages"])
        first = len(tokenizer.encode(rendered, add_special_tokens=False))
        reference_tokens = len(
            tokenizer.encode(reference["payload"], add_special_tokens=False)
        )
        second_messages = task["task"]["messages"] + [
            {"role": "assistant", "content": reference["payload"]},
            {"role": "tool", "content": reference["native_feedback"]},
        ]
        second_rendered = chat.render_prompt(tokenizer, prompt, second_messages)
        second = len(tokenizer.encode(second_rendered, add_special_tokens=False))
        if (
            max(first, second) > 8192
            or reference_tokens > 2048
            or max(first, second) + 2048 > int(configuration.max_position_embeddings)
        ):
            raise ValueError(
                "uniform full-context/output budget cannot express a reference"
            )
        task.update(
            input_tokens=first,
            rendered_input_sha256=codec.sha(rendered.encode()),
            codec_reference_output_tokens=reference_tokens,
        )
        token_rows.append(
            {
                "project_id": task["project_id"],
                "first_input_tokens": first,
                "reference_output_tokens": reference_tokens,
                "reference_feedback_second_input_tokens": second,
                "full_second_plus_output_reserve": second + 2048,
                "native_context": int(configuration.max_position_embeddings),
                "input_truncated": False,
            }
        )

    after_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {
        "status": "QUALIFIED_CPU_ONLY",
        "source_commit": source_commit,
        "exact_after_files": 4,
        "negative_controls": controls,
        "negative_control_count": len(controls),
        "actual_native_children": 8,
        "native_pairs": native_pairs,
        "token_preflight": token_rows,
        "new_model_calls": 0,
        "new_training_updates": 0,
        "B3_material_read": False,
        "wall_seconds": time.perf_counter() - started,
        "self_cpu_seconds": time.process_time() - cpu,
        "completed_children_cpu_seconds": after_usage.ru_utime
        + after_usage.ru_stime
        - usage.ru_utime
        - usage.ru_stime,
        "nested_native_windows_are_not_additive": True,
        "gpu_energy_joules": None,
        "host_energy_joules": None,
        "monetary_cost": None,
        "old_research_NoUpdate_unchanged": True,
    }
    result_sha = codec.write(control_root / "RESULT.json", result)
    task_sha = codec.write(output / "TASKS.json", tasks)
    binding_sha = codec.write(output / "BINDINGS.json", bindings)
    codec.write(output / "REFERENCES.json", references)
    generation = {
        key: legacy[key]
        for key in (
            "generation_config",
            "generation_config_sha256",
            "ancestral_generation_config_sha256",
            "native_max_position_embeddings",
            "maximum_input_tokens",
            "maximum_new_tokens",
        )
    }
    if (
        generation["maximum_input_tokens"] != 8192
        or generation["maximum_new_tokens"] != 2048
    ):
        raise ValueError("common generation caps changed")
    protocol = {
        "schema": "hepta.upstream-replacement-A.protocol.v1",
        "prepared_at_ns": str(time.time_ns()),
        "source_commit": source_commit,
        "format": codec.FORMAT,
        "codec_sha256": codec.sha(Path(codec.__file__).read_bytes()),
        "native_verifier_sha256": codec.NATIVE_SHA256,
        "original_A_task_file_sha256": codec.TASKS_SHA256,
        "original_source_inventory_sha256": codec.SOURCE_INVENTORY_SHA256,
        "original_common_generation_protocol_sha256": LEGACY_PROTOCOL_SHA256,
        "task_records_sha256": task_sha,
        "source_bindings_sha256": binding_sha,
        "cpu_controls_result_sha256": result_sha,
        "models": models,
        "planned_modes": ["P", "document_evidence", "native_feedback"],
        "planned_calls_per_mode": 8,
        "planned_total_model_calls": 24,
        "planned_training_updates": 0,
        "calls_per_task": 2,
        "common_prefix_extra_calls": 0,
        "actual_second_attempt_uses_own_first_answer_and_real_feedback": True,
        "B3_model_calls": 0,
        "B3_material_read_for_this_candidate": False,
        "evaluation_scope": "already-exposed A engineering mechanism diagnostic only",
        "primary_model_predeclared": "native_feedback",
        "strict_success": "unchanged original native verifier success, including exact original case set and sandbox attestation",
        "advance_rule": "diagnostic only; report admission/native first/final/recovery/regression and paired task differences for all three modes; retain previous NoUpdate; no adoption or independent confirmation qualification",
        "next_training_selection": "not authorized by this protocol; any new training requires separate prior freeze",
        "unknown_requests_not_replayed": True,
        "physical_compute_equal": False,
        "actual_costs_must_include_codec_native_load_failed_calls_and_output_caps": True,
        "all_contexts_checked_before_generation_without_truncation": True,
        "preserved_native_json_bytes_limit": 32768,
        "preserved_native_old_plus_new_characters_limit_per_edit": 16384,
        "preserved_native_edit_count_maximum": 8,
        "authenticated_users": 0,
        "native_adoption": False,
        "old_research_NoUpdate_unchanged": True,
        **generation,
    }
    protocol_sha = codec.write(output / "PROTOCOL.json", protocol)
    summary = {
        "status": result["status"],
        "source_commit": source_commit,
        "protocol_sha256": protocol_sha,
        "task_records_sha256": task_sha,
        "bindings_sha256": binding_sha,
        "cpu_controls_result_sha256": result_sha,
        "actual_native_children": 8,
        "negative_control_count": len(controls),
        "new_model_calls": 0,
        "token_preflight": token_rows,
        "planned_model_calls_not_yet_executed": 24,
    }
    codec.write(root / "PREPARED.json", summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    try:
        qualify(args.root, args.source_commit)
    except BaseException as error:
        codec.write(
            args.root / "FAILED.json",
            {
                "error_type": type(error).__name__,
                "error": str(error),
                "traceback": traceback.format_exc(),
                "source_commit": args.source_commit,
                "new_model_calls": 0,
                "outputs_retained": True,
            },
        )
        raise
