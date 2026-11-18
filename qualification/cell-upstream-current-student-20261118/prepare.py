"""Freeze four A-only repair tasks and prove their oracle behavior in bwrap."""

import argparse
import ast
import difflib
import importlib.util
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parent))
import native_sandbox as native

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
    selected = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    assert len(selected) == len(names)
    needed = {
        node.id
        for chosen in selected
        for node in ast.walk(chosen)
        if isinstance(node, ast.Name)
    }
    needed.update(
        arg.arg
        for chosen in selected
        for arg in ast.walk(chosen)
        if isinstance(arg, ast.arg)
    )
    included = set(selected)
    for _ in range(5):
        additions = []
        for node in tree.body:
            if node in included:
                continue
            bindings = set()
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                bindings = {
                    alias.asname or alias.name.split(".")[0] for alias in node.names
                }
            elif isinstance(node, ast.FunctionDef):
                if node.name.startswith("test_"):
                    continue
                bindings = {node.name}
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.With)):
                bindings = {
                    entry.id
                    for entry in ast.walk(node)
                    if isinstance(entry, ast.Name) and isinstance(entry.ctx, ast.Store)
                }
            if bindings & needed:
                additions.append(node)
        if not additions:
            break
        included.update(additions)
        needed.update(
            entry.id
            for node in additions
            for entry in ast.walk(node)
            if isinstance(entry, ast.Name)
        )
    nodes = [node for node in tree.body if node in included]
    return "\n\n".join(ast.unparse(node) for node in nodes)


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
    output = root / "prepared"
    output.mkdir(exist_ok=False)
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
        tests_text = test_context(original_tests, row["selected_tests"]["names"])
        allowed = (
            "Only the body/docstring of "
            + name
            + " may change; its signature and decorators must stay identical."
        )
        if constant:
            allowed += (
                " You may also add one module-level "
                + constant
                + " = re.compile(<literal regex>) constant."
            )
        prompt = (
            "Repair this real upstream Python regression. Return only one JSON object, with no Markdown fences:\n"
            '{"edits":[{"old":"exact text from the original source file","new":"replacement text"}]}\n'
            "Use 1 to 8 non-overlapping edits. Every old string must occur exactly once in the ORIGINAL source file. "
            "All edits in every attempt apply to that original revision. Do not submit tests or an entire rewritten file. "
            "No imports, new external dependencies, test manipulation, process execution or network access are allowed. "
            + allowed
            + "\n\nProject: "
            + project
            + "\nAllowed file: "
            + path
            + "\nOriginal file SHA256: "
            + native.sha(before)
            + "\nThe tests and all other source remain immutable. Original package bindings are available.\n\n"
            "Original function (exact source):\n"
            + function_text
            + "\nSelected unchanged upstream tests and their needed bindings (AST-normalized; all parameter cases retained):\n"
            + tests_text
        )
        task = {
            "schema": "hepta.upstream-current-student-A.v1",
            "record_id": "upstream-A-" + project.replace("/", "-"),
            "project_id": project,
            "source_id": source["source_id"],
            "lineage_id": source["lineage_id"],
            "task_id": source["source_id"] + ":repair",
            "split": "train",
            "origin_kind": "curated_development",
            "task_wrapper_authored_for_this_experiment": True,
            "original_upstream_material": True,
            "independent_users": 0,
            "future_evaluation": False,
            "training_updates_in_this_stage": 0,
            "authorization": source["authorization"],
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
            for entry in native.read(native.MATERIAL_ROOT / "replay-1/RESULT.json")[
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
    sys.path.insert(0, str(OLD_CODE / "scripts"))
    from cell_experiments import chat_protocol, causal_probe_v3 as probe
    from transformers import AutoTokenizer, AutoConfig, GenerationConfig

    parent_path = PREVIOUS / "retained/PARENT_MODEL.json"
    credit_path = PREVIOUS / "retained/training/verified_credit/manifest.json"
    assert (
        native.sha(parent_path.read_bytes())
        == "4a9c82ab237a5d902db378d1987170c1608bdef40c5603731718f4202fff6c5d"
    )
    assert (
        native.sha(credit_path.read_bytes())
        == "88f93eaca8b88eeec3ff426eb26d2ee472de7d1cd2c9e3388dea6750c1391005"
    )
    parent, credit = native.read(parent_path), native.read(credit_path)
    assert parent["runtime"] == credit["runtime"]
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
        "schema": "hepta.upstream-current-student-protocol.v1",
        "stage": "four authorized A maintenance tasks; actual current student collection; no training",
        "builder_source_commit": commit,
        "prepared_at_ns": time.time_ns(),
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
            "C": "785bc1cea2996e33cfe02c9c51a5a3802c931b010060369fc659b47fde4440a1",
        },
        "manifest_sha256": {
            "P": native.sha(parent_path.read_bytes()),
            "C": native.sha(credit_path.read_bytes()),
        },
        "ancestral_generation_config_sha256": "e31715a80c7c2d6fb35843583b19931ec955723cba8366472ed48b461514e3eb",
        "generation_config_sha256": native.sha(native.canonical(generation.to_dict())),
        "generation_config": generation.to_dict(),
        "immutable_ancestral_runtime": parent["runtime"],
        "effective_runtime_override": {
            "max_input_tokens": 8192,
            "max_new_tokens": 2048,
        },
        "runtime_override_scope": "new common collection protocol, same verified weights; original model manifests and source gates are unchanged",
        "native_max_position_embeddings": native_context,
        "tokenizer_model_max_length": tokenizer.model_max_length,
        "complete_context_rule": "before every actual call require full rendered input <=8192 and full input +2048 output reserve <=actual native context; no truncation",
        "calls_per_model_task": 2,
        "maximum_new_tokens": 2048,
        "maximum_input_tokens": 8192,
        "student_calls": 16,
        "optional_existing_teacher_calls": 8,
        "total_model_call_cap": 24,
        "unknown_generation_requests_are_not_replayed": True,
        "second_call": "every task, even after success; original user -> actual own assistant output -> bound native feedback",
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
        "teacher_scope": "only the already authorized existing byte-bound 8080 service while idle; different hardware/active parameters/physical compute not matched",
        "cost_scope": "all attempted model and verifier calls, cold loads, failures and native subprocesses; CPU package counters are whole-host windows, not model-only energy; GPU/network/money remain unknown",
        "preparation": {
            "actual_native_children": 8,
            "actual_case_executions": 228,
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
    main(args.root, args.source_commit)
