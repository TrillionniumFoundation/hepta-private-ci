"""Prepare four source-separated B3 repair tasks; zero model calls or updates."""

import argparse
import copy
import traceback
import ast
import difflib
import importlib.util
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parent))
import b3_native as native

OLD_CODE = Path("/home/qian-qi/work/hepta-e1-matched-info-20261118-2e9b/source")
ARTIFACT = Path("/dev/shm/hepta-cell-experiments-v3-20261116-0c078a")
PREVIOUS = Path("/home/qian-qi/work/hepta-e2-current-credit-20261118-2e9b")


def snippet(raw, node):
    lines = raw.decode().splitlines(keepends=True)
    start = min(
        [
            node.lineno,
            *[decorator.lineno for decorator in getattr(node, "decorator_list", [])],
        ]
    )
    return "".join(lines[start - 1 : node.end_lineno])


def test_context(raw, names):
    tree = ast.parse(raw)
    selected, class_rows = [], {}
    for name in names:
        parts = name.split("::")
        parent = tree
        if len(parts) == 2:
            matches = [
                node for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == parts[0]
            ]
            assert len(matches) == 1, "original test class must be unique"
            parent = matches[0]
        assert len(parts) in (1, 2)
        matches = [
            node for node in parent.body
            if isinstance(node, ast.FunctionDef) and node.name == parts[-1]
        ]
        assert len(matches) == 1, "selected original test must be unique"
        if parent is tree:
            selected.append(matches[0])
        else:
            class_rows.setdefault(parent, []).append(matches[0])
    for node, children in class_rows.items():
        chosen = copy.deepcopy(node)
        chosen.body = copy.deepcopy(children)
        selected.append(chosen)
    needed = {
        node.id for chosen in selected for node in ast.walk(chosen)
        if isinstance(node, ast.Name)
    }
    included = set(selected)
    for _ in range(8):
        additions = []
        for node in tree.body:
            if node in included or node in class_rows:
                continue
            bindings = set()
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                bindings = {alias.asname or alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                if node.name.startswith("test_") or node.name.startswith("Test"):
                    continue
                bindings = {node.name}
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.With)):
                bindings = {
                    item.id for item in ast.walk(node)
                    if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store)
                }
            if bindings & needed:
                additions.append(node)
        if not additions:
            break
        included.update(additions)
        needed.update(
            item.id for node in additions for item in ast.walk(node)
            if isinstance(item, ast.Name)
        )
    nodes = [node for node in tree.body if node in included]
    nodes.extend(node for node in selected if node not in tree.body)
    return "\n\n".join(ast.unparse(node) for node in nodes)


def supporting_context(project, raw, constant):
    tree = ast.parse(raw)
    nodes = []
    if constant:
        nodes.extend(node for node in tree.body if native.constant_name(node) == constant)
    if project == "python-semver/python-semver":
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Version")
        nodes.extend(
            node for node in cls.body
            if native.constant_name(node) == "_PRERELEASE_IDENTIFIER"
        )
        nodes.append(native.function(tree, "Version._validate_identifiers"))
    return "\n".join(snippet(raw, node) for node in nodes)


BEHAVIOR = {
    "pypa/packaging": "Parse arbitrary equality versions in comma-separated requirement specifier sets, retaining the original token spelling and accepting the unchanged whitespace/marker cases.",
    "python-semver/python-semver": "When requesting prerelease, validate a nonempty token as literal SemVer identifiers and match its token family literally. Retain original None/empty token behavior and ignore this token for major/minor/patch requests.",
    "mahmoud/boltons": "Split Unicode line endings including U+2028 and U+2029 without consuming ordinary following digits or spaces; preserve the original iterator interface and indent behavior.",
    "python-hyper/h11": "Reject a Content-Length value with more than 20 decimal digits through the original LocalProtocolError path, while preserving original header normalization and all other validation.",
}


def negative_controls(root):
    output = root / "admission-negative-controls"
    output.mkdir()
    specs = [
        ("invalid_json", "pypa/packaging", "{", "Expecting"),
        ("old_text_mismatch", "pypa/packaging",
         native.canonical({"edits": [{"old": "HEPTA_B3_ABSENT_2e9b", "new": ""}]}).decode(),
         "old text must occur exactly once"),
    ]
    for name, project, mode, expected in [
        ("outside_body_import", "pypa/packaging", "import", "outside the permitted body"),
        ("method_signature_change", "python-semver/python-semver", "signature", "signature"),
        ("constant_type_change", "python-hyper/h11", "integer", "bounded integer literal"),
        ("regex_flag_change", "mahmoud/boltons", "flags", "original flags"),
    ]:
        row, folder = native.source(project)
        path, fn_name, constant = native.TARGETS[project]
        before = (folder / "before" / path).read_bytes()
        tree = ast.parse(before)
        if mode == "import":
            fn = native.function(tree, fn_name)
            old = snippet(before, fn)
            new = "import os\n\n" + old
        elif mode == "signature":
            old = snippet(before, native.function(tree, fn_name))
            assert old.count("def next_version(") == 1
            new = old.replace("def next_version(", "def next_version_changed(", 1)
            # Changing the declared method is a concrete function-boundary rejection.
            expected = "exactly one permitted concrete function"
        elif mode == "integer":
            fn = native.function(tree, fn_name)
            old = snippet(before, fn)
            new = 'CONTENT_LENGTH_MAX_DIGITS = "20"\n\n' + old
        else:
            node = next(node for node in tree.body if native.constant_name(node) == constant)
            old = snippet(before, node)
            call = copy.deepcopy(node.value)
            if len(call.args) > 1:
                call.args[1] = ast.Constant(0)
                if ast.dump(call.args[1]) == ast.dump(node.value.args[1]):
                    call.args[1] = ast.Constant(1)
            else:
                call.args.append(ast.Constant(0))
            changed = copy.deepcopy(node)
            changed.value = call
            new = ast.unparse(changed) + "\n"
        specs.append((name, project, native.canonical({"edits": [{"old": old, "new": new}]}).decode(), expected))
    rows = []
    for name, project, answer, expected in specs:
        directory = output / name
        receipt = native.verify(project, answer, directory)
        ok = (
            receipt["stage"] == "patch_admission"
            and receipt["success"] is False
            and receipt["actual_native_child"] is False
            and expected in receipt["reason"]
        )
        rows.append({
            "name": name, "project_id": project, "expected_reason_substring": expected,
            "passed": ok, "receipt": receipt,
            "receipt_sha256": native.sha((directory / "VERIFICATION.json").read_bytes()),
        })
    native.write(root / "prepared" / "NEGATIVE_CONTROLS.json", rows)
    assert all(row["passed"] for row in rows), "negative admission boundary mismatch"
    return rows


def oracle_action(before, after):
    old, new = (
        before.decode().splitlines(keepends=True),
        after.decode().splitlines(keepends=True),
    )
    edits = []
    for group in difflib.SequenceMatcher(
        a=old, b=new, autojunk=False
    ).get_grouped_opcodes(3):
        edits.append(
            {
                "old": "".join(old[group[0][1] : group[-1][2]]),
                "new": "".join(new[group[0][3] : group[-1][4]]),
            }
        )
    return native.canonical({"edits": edits}).decode()


def main(root, commit):
    started = time.perf_counter()
    root.mkdir(parents=True, exist_ok=False)
    output = root / "prepared"
    output.mkdir(exist_ok=False)
    canary = b"hepta-b3-isolation-canary-20261118-2e9b\n"
    if native.HOST_CANARY.exists():
        assert native.HOST_CANARY.read_bytes() == canary
    else:
        native.write(native.HOST_CANARY, canary)
    assert native.sha(native.REPLAY_RESULT.read_bytes()) == native.REPLAY_SHA
    sources = json.loads((native.MATERIAL_ROOT / "SOURCES.json").read_bytes())[
        "sources"
    ]
    tasks, before_after = [], []
    for index, source in enumerate(sources):
        project = source["project_id"]
        row, folder = native.source(project)
        path, name, constant = native.TARGETS[project]
        before, after = [
            (folder / variant / path).read_bytes() for variant in ("before", "after")
        ]
        original_tests = (folder / "after" / row["selected_tests"]["path"]).read_bytes()
        fn = native.function(ast.parse(before), name)
        function_text = snippet(before, fn)
        support_text = supporting_context(project, before, constant)
        tests_text = test_context(original_tests, row["selected_tests"]["names"])
        allowed = (
            "Only the body/docstring of "
            + name
            + " may change; its signature and decorators must stay identical."
        )
        if project == "mahmoud/boltons":
            allowed += " You may also change the existing _line_ending_re literal regex (at most 256 characters); retain its original re.compile flags."
        elif project == "python-hyper/h11":
            allowed += " You may also add one module-level CONTENT_LENGTH_MAX_DIGITS integer constant between 1 and 4096. Existing overload declarations must stay identical."
        prompt = (
            "Repair this real upstream Python regression. Return only one JSON object, with no Markdown fences:\n"
            '{"edits":[{"old":"exact text from the original source file","new":"replacement text"}]}\n'
            "Use 1 to 8 non-overlapping edits. Every old string must occur exactly once in the ORIGINAL source file. "
            "All edits in every attempt apply to that original revision. Do not submit tests or an entire rewritten file. "
            "No imports, new external dependencies, test manipulation, process execution or network access are allowed. "
            + allowed
            + "\nRequired behavior: " + BEHAVIOR[project]
            + "\n\nProject: "
            + project
            + "\nAllowed file: "
            + path
            + "\nOriginal file SHA256: "
            + native.sha(before)
            + "\nThe tests and all other source remain immutable. Original package bindings are available.\n\n"
            "Original function (exact source):\n"
            + function_text
            + "\nOriginal supporting bindings (read-only except any explicitly allowed constant):\n"
            + support_text
            + "\nSelected unchanged upstream tests and their needed bindings (AST-normalized; all parameter cases retained):\n"
            + tests_text
        )
        task = {
            "schema": "hepta.upstream-operational-B3.v1",
            "record_id": "upstream-B3-" + project.replace("/", "-"),
            "project_id": project,
            "source_id": source["source_id"],
            "lineage_id": source["lineage_id"],
            "task_id": source["source_id"] + ":repair",
            "split": "eval",
            "origin_kind": "source_separated_operational_holdout",
            "task_wrapper_authored_for_this_experiment": True,
            "original_upstream_material": True,
            "independent_users": 0,
            "future_evaluation": True,
            "training_updates_in_this_stage": 0,
            "authorization": source.get("authorization", {"basis": "retained original upstream open-source license", "license": source.get("license"), "authenticated_owner": False}),
            "original_source_sha256": native.sha(before),
            "original_tests_sha256": native.sha(original_tests),
            "source_path": path,
            "allowed_function": name,
            "optional_module_constant": constant,
            "task": {
                "input": prompt,
                "messages": [{"role": "user", "content": prompt}],
            },
            "prompt_sha256": native.sha(prompt.encode()),
        }
        tasks.append(task)
        action = oracle_action(before, after)
        patched, admission = native.admit(project, action)
        assert patched == after, "oracle patch must reproduce exact upstream fixed file"
        folder_out = root / "sandbox-preflight" / str(index)
        folder_out.mkdir(parents=True, exist_ok=False)
        native.write(folder_out / "ORACLE_ACTION.json", json.loads(action))
        native.write(folder_out / "ORACLE_ADMISSION.json", admission)
        results = [
            native.run_native(project, folder_out / "before", label="original_before"),
            native.run_native(
                project, folder_out / "after", patched, label="original_upstream_fix"
            ),
        ]
        expected = [
            entry
            for entry in native.read(native.REPLAY_RESULT)[
                "stages"
            ]
            if entry["project_id"] == project
        ]
        assert all(
            actual["same_original_case_set"]
            and actual["sandbox_attestation_sha256"]
            and actual.get("errors") == 0
            and not actual["timed_out"]
            for actual in results
        )
        assert [entry["failures"] for entry in results] == [
            entry["failures"] for entry in expected
        ]
        assert not results[0]["success"] and results[1]["success"]
        before_after.append(
            {"project_id": project, "before": results[0], "after": results[1]}
        )
        print(
            json.dumps(
                {
                    "project": project,
                    "before_failed": results[0]["failures"],
                    "after_passed": results[1]["tests"],
                    "real_sandbox": True,
                }
            ),
            flush=True,
        )
    negatives = negative_controls(root)
    parent_path = PREVIOUS / "retained/PARENT_MODEL.json"
    assert native.sha(parent_path.read_bytes()) == "4a9c82ab237a5d902db378d1987170c1608bdef40c5603731718f4202fff6c5d"
    parent = native.read(parent_path)
    for relative, expected_sha in parent["source_inventory"].items():
        candidate = OLD_CODE / relative
        assert native.sha(candidate.read_bytes()) == expected_sha, relative
    sys.path.insert(0, str(OLD_CODE / "scripts"))
    from cell_experiments import chat_protocol, causal_probe_v3 as probe
    from transformers import AutoTokenizer, AutoConfig, GenerationConfig

    base = probe._base(ARTIFACT, parent["runtime"]["base_directory"])
    checked_base_files = []
    for item in parent["base_manifest"]["files"]:
        if item["path"] == "model.safetensors":
            continue
        raw = (base / item["path"]).read_bytes()
        assert len(raw) == item["bytes"] and native.sha(raw) == item["sha256"], item["path"]
        checked_base_files.append(item)
    tokenizer = AutoTokenizer.from_pretrained(
        str(probe._base(ARTIFACT, parent["runtime"]["base_directory"])),
        local_files_only=True,
        trust_remote_code=False,
    )
    assert (
        chat_protocol.template_digest(tokenizer.get_chat_template())
        == parent["runtime"]["chat_template_sha256"]
    )
    configuration = AutoConfig.from_pretrained(
        str(probe._base(ARTIFACT, parent["runtime"]["base_directory"])),
        local_files_only=True,
        trust_remote_code=False,
    )
    native_context = int(configuration.max_position_embeddings)
    assert native_context >= 8192 + 2048, (
        "native position capacity below complete uniform input/output window"
    )
    generation = GenerationConfig(
        **dict(parent["runtime"]["generation"], max_new_tokens=2048)
    )
    for index, task in enumerate(tasks):
        reference = native.canonical(
            native.read(root / "sandbox-preflight" / str(index) / "ORACLE_ACTION.json")
        ).decode()
        reference_tokens = len(tokenizer.encode(reference, add_special_tokens=False))
        assert reference_tokens <= 2048, (
            "uniform patch output cap cannot express an original fix"
        )
        task.update(
            codec_reference_output_tokens=reference_tokens,
            old_384_token_codec_fits=reference_tokens <= 384,
        )
        rendered = chat_protocol.render_prompt(
            tokenizer, task["task"]["input"], task["task"]["messages"]
        )
        tokens = tokenizer.encode(rendered, add_special_tokens=False)
        task.update(
            input_tokens=len(tokens),
            rendered_input_sha256=native.sha(rendered.encode()),
            input_token_ids_digest=native.sha(native.canonical(tokens)),
        )
        assert len(tokens) <= 5120, (
            "first input must reserve 3072 tokens for actual action and bounded feedback without truncation"
        )
    native.write(output / "TASKS.json", tasks)
    native.write(output / "SANDBOX_PREFLIGHT.json", before_after)
    protocol = {
        "schema": "hepta.upstream-B3-preparation.v1",
        "stage": "four source-separated B3 maintenance tasks; original sandbox controls and CPU tokenizer preparation; zero generation or training",
        "builder_source_commit": commit,
        "prepared_at_ns": str(time.time_ns()),
        "native_verifier_sha256": native.sha(Path(native.__file__).read_bytes()),
        "builder_sha256": native.sha(Path(__file__).read_bytes()),
        "source_inventory_sha256": native.SOURCES_SHA,
        "task_records_sha256": native.sha((output / "TASKS.json").read_bytes()),
        "sandbox_preflight_sha256": native.sha(
            (output / "SANDBOX_PREFLIGHT.json").read_bytes()
        ),
        "tasks": [
            {
                "record_id": row["record_id"],
                "project_id": row["project_id"],
                "prompt_sha256": row["prompt_sha256"],
                "input_tokens": row["input_tokens"],
                "codec_reference_output_tokens": row["codec_reference_output_tokens"],
                "old_384_token_codec_fits": row["old_384_token_codec_fits"],
            }
            for row in tasks
        ],
        "model_digests": {
            "P": "430f4051d47672d121a5d790aca0e489804b0d8419c101e3c1171b3d17157786",
        },
        "manifest_sha256": {
            "P": native.sha(parent_path.read_bytes()),
        },
        "ancestral_generation_config_sha256": "e31715a80c7c2d6fb35843583b19931ec955723cba8366472ed48b461514e3eb",
        "generation_config_sha256": native.sha(native.canonical(generation.to_dict())),
        "generation_config": generation.to_dict(),
        "immutable_ancestral_runtime": parent["runtime"],
        "effective_runtime_override": {
            "max_input_tokens": 8192,
            "max_new_tokens": 2048,
        },
        "runtime_override_scope": "matches the prior A collection input/output policy; tokenizer only here; later generation requires its separate prospective model and evaluation freeze",
        "native_max_position_embeddings": native_context,
        "tokenizer_model_max_length": tokenizer.model_max_length,
        "complete_context_rule": "before every actual call require full rendered input <=8192 and full input +2048 output reserve <=actual native context; no truncation",
        "calls_per_model_task": 0,
        "maximum_new_tokens": 2048,
        "maximum_input_tokens": 8192,
        "student_calls": 0,
        "optional_existing_teacher_calls": 0,
        "total_model_call_cap": 0,
        "unknown_generation_requests_are_not_replayed": True,
        "second_call": "not executed in preparation; later study must freeze its own complete interaction protocol",
        "scoring": "strict raw JSON edits, immutable original tests, identical per-case3s/child120s; no fence stripping or output repair",
        "selection_metrics": [
            "first_success",
            "final_success",
            "any_success",
            "fail_to_pass",
            "pass_to_fail",
        ],
        "new_model_training_updates": 0,
        "native_adoption": False,
        "research_NoUpdate_retained": True,
        "independent_confirmation_qualified": False,
        "authenticated_users": 0,
        "teacher_scope": "no teacher service contacted in B3 preparation",
        "cost_scope": "actual preparation native children and CPU tokenizer; no model weights loaded, no model calls; physical energy/network/money unknown",
        "base_tokenizer_files_checked": checked_base_files,
        "source_module_inventory_checked": parent["source_inventory"],
        "negative_controls_sha256": native.sha((output / "NEGATIVE_CONTROLS.json").read_bytes()),
        "admission_negative_controls": len(negatives),
        "independent_source_project_count": 4,
        "independent_controller_custody_certified": False,
        "pretraining_contamination_excluded": False,
        "training_agent_task_release": "only after exact new weights and training manifests are frozen; shared-host operational separation, not certified custody",
        "preparation": {
            "actual_native_children": 8,
            "actual_case_executions": sum(item[variant]["tests"] for item in before_after for variant in ("before", "after")),
            "new_model_calls": 0,
            "new_training_updates": 0,
            "wall_seconds": time.perf_counter() - started,
        },
    }
    native.write(output / "PROTOCOL.json", protocol)
    print(
        json.dumps(
            {
                "status": "PREPARED",
                "tasks": len(tasks),
                "input_tokens": [row["input_tokens"] for row in tasks],
                "protocol_sha256": native.sha((output / "PROTOCOL.json").read_bytes()),
                "tasks_sha256": native.sha((output / "TASKS.json").read_bytes()),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    owner_started_ns = str(time.time_ns())
    owner_started = time.perf_counter()
    try:
        main(args.root, args.source_commit)
    except Exception as error:
        result = {
            "status": "FAILED", "source_commit": args.source_commit,
            "started_at_ns": owner_started_ns, "finished_at_ns": str(time.time_ns()),
            "wall_seconds": time.perf_counter() - owner_started,
            "error_type": type(error).__name__, "error": str(error),
            "traceback": traceback.format_exc(),
            "model_calls": 0, "training_updates": 0,
            "partial_originals_retained": True,
        }
        if args.root.is_dir() and not (args.root / "OWNER_RESULT.json").exists():
            native.write(args.root / "OWNER_RESULT.json", result)
        print(json.dumps(result), flush=True)
        raise
    else:
        native.write(args.root / "OWNER_RESULT.json", {
            "status": "PREPARED", "source_commit": args.source_commit,
            "started_at_ns": owner_started_ns, "finished_at_ns": str(time.time_ns()),
            "wall_seconds": time.perf_counter() - owner_started,
            "protocol_sha256": native.sha((args.root / "prepared/PROTOCOL.json").read_bytes()),
            "tasks_sha256": native.sha((args.root / "prepared/TASKS.json").read_bytes()),
            "model_calls": 0, "training_updates": 0,
        })
