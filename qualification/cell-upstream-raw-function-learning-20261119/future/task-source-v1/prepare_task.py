"""Prepare shared future input without loading a model or running upstream code.

Selection uses only bound original material and reference qualification. The
same deterministic context recipe applies to every candidate and every arm.
"""

import argparse
import ast
import copy
import json
from pathlib import Path
import sys
import time
import traceback

import future_native as native

WORK = Path("/home/qian-qi/work/hepta-upstream-raw-function-learning-20261119-2e9b")
PARENT = Path(
    "/home/qian-qi/work/hepta-e2-current-credit-20261118-2e9b/retained/PARENT_MODEL.json"
)
PARENT_SHA = "4a9c82ab237a5d902db378d1987170c1608bdef40c5603731718f4202fff6c5d"
WEIGHTS_SHA = "237ae92fc94d6ae411671c671190314049ded5cdc0d5dae254d57c9d8bb67be6"
INVENTORY = WORK / "future-preparation-old-inventory-1/DEDUP_INVENTORY.json"
INVENTORY_SHA = "aa522307a3d06aba4ac355846cba05417c0a9dc06a88b834d618b414247c1d9a"
ARTIFACT = Path("/dev/shm/hepta-cell-experiments-v3-20261116-0c078a")
SOURCE = Path("/home/qian-qi/work/hepta-e1-matched-info-20261118-2e9b/source/scripts")
MAX_INPUT, MAX_OUTPUT, NATIVE_CONTEXT = 8192, 2048, 32768
SECOND_FEEDBACK_PLANNING_RESERVE = 2048
CHAT_WRAPPER_PLANNING_RESERVE = 256


def read(path, expected=None):
    raw = Path(path).read_bytes()
    if expected and native.sha(raw) != expected:
        raise ValueError("bound preparation input changed: " + str(path))
    return json.loads(raw)


def names(node):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return {
            row.asname or row.name.split(".")[0]
            for row in node.names
            if row.name != "*"
        }
    if isinstance(node, ast.Assign):
        return {
            part.id
            for target in node.targets
            for part in ast.walk(target)
            if isinstance(part, ast.Name)
        }
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return {node.target.id}
    return set()


def references(node):
    return {
        part.id
        for part in ast.walk(node)
        if isinstance(part, ast.Name) and isinstance(part.ctx, ast.Load)
    }


def closure(tree, initial):
    chosen = {id(node): node for node in initial}
    needed = set().union(*(references(node) for node in initial))
    while True:
        extra = [
            node
            for node in tree.body
            if id(node) not in chosen and names(node) & needed
        ]
        if not extra:
            break
        for node in extra:
            chosen[id(node)] = node
            needed |= references(node)
    return [node for node in tree.body if id(node) in chosen]


def exact_node(text, node):
    start = min(
        [
            node.lineno,
            *(decorator.lineno for decorator in getattr(node, "decorator_list", [])),
        ]
    )
    return "".join(text.splitlines(keepends=True)[start - 1 : node.end_lineno])


def source_context(spec, prior):
    text = prior.decode()
    tree = ast.parse(text)
    target = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == spec["function"]
    )
    selected = closure(tree, [target])
    root = Path(spec["_root"]) / "before"
    sections = []
    inventory = []
    context = [node for node in selected if node is not target]
    if context:
        sections.append(
            "Original same-module bindings and helper definitions (exact source):\n"
            + "\n".join(exact_node(text, node) for node in context)
        )
    package_root = root / spec["package_import_root"]
    relative = (
        Path(spec["source_path"]).relative_to(spec["package_import_root"])
        if spec["package_import_root"] != "."
        else Path(spec["source_path"])
    )
    current_package = relative.parent.parts
    package_name = spec["package_names"][0]
    seen = set()
    # One original project-import hop, then complete same-module dependency
    # closure. No imports execute; no transitive external library is expanded.
    for node in selected:
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level:
            if node.level > len(current_package):
                continue
            module_parts = (
                *current_package[: len(current_package) - node.level + 1],
                *(node.module or "").split("."),
            )
        elif node.module and node.module.split(".")[0] == package_name:
            module_parts = tuple(node.module.split("."))
        else:
            continue
        module_parts = tuple(part for part in module_parts if part)
        module = package_root.joinpath(*module_parts).with_suffix(".py")
        if not module.is_file():
            module = package_root.joinpath(*module_parts, "__init__.py")
        if not module.is_file() or module == root / spec["source_path"]:
            continue
        imported = {
            row.name
            for row in node.names
            if (row.asname or row.name) in references(target)
        }
        module_text = module.read_text()
        module_tree = ast.parse(module_text)
        initial = [part for part in module_tree.body if names(part) & imported]
        if not initial:
            continue
        key = (str(module.relative_to(root)), tuple(sorted(imported)))
        if key in seen:
            continue
        seen.add(key)
        shown = closure(module_tree, initial)
        sections.append(
            "Original project definitions from "
            + str(module.relative_to(root))
            + " (exact source):\n"
            + "\n".join(exact_node(module_text, part) for part in shown)
        )
        inventory.append(
            {
                "path": str(module.relative_to(root)),
                "file_sha256": native.sha(module.read_bytes()),
                "shown_node_AST_sha256s": [
                    native.sha(ast.dump(part, include_attributes=False).encode())
                    for part in shown
                ],
            }
        )
    return exact_node(text, target), "\n\n".join(sections), inventory


def test_context(spec):
    root = Path(spec["_root"])
    sections, inventory = [], []
    for selector in spec["test_selectors"]:
        relative = Path(spec["test_root"]) / selector
        after_path = root / "after-tests" / relative
        tree = ast.parse(after_path.read_bytes())
        prior = root / "before" / relative
        prior_fingerprints = (
            {
                ast.dump(node, include_attributes=False)
                for node in ast.parse(prior.read_bytes()).body
            }
            if prior.is_file()
            else set()
        )
        changed = [
            node
            for node in tree.body
            if ast.dump(node, include_attributes=False) not in prior_fingerprints
        ]
        initial = [
            node
            for node in changed
            if isinstance(
                node, (ast.FunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign)
            )
        ]
        shown = closure(tree, initial) if initial else list(tree.body)
        content = "\n\n".join(ast.unparse(node) for node in shown)
        sections.append(
            "Original test file "
            + str(relative)
            + " (AST-normalized complete changed definitions with binding closure; all parameters preserved):\n"
            + content
        )
        inventory.append(
            {
                "path": str(relative),
                "file_sha256": native.sha(after_path.read_bytes()),
                "changed_definition_count": len(initial),
                "fallback_complete_file": not bool(initial),
                "shown_node_AST_sha256s": [
                    native.sha(ast.dump(node, include_attributes=False).encode())
                    for node in shown
                ],
                "prompt_text_sha256": native.sha(content.encode()),
                "oracle_remains_entire_original_declared_file": True,
            }
        )
    return "\n\n".join(sections), inventory


def all_hashes(value):
    result = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if "sha256" in key.lower():
                if isinstance(item, str) and len(item) == 64:
                    result.add(item)
                elif isinstance(item, list):
                    result.update(
                        x for x in item if isinstance(x, str) and len(x) == 64
                    )
            result |= all_hashes(item)
    elif isinstance(value, list):
        for item in value:
            result |= all_hashes(item)
    return result


def tokenizer_and_chat(parent):
    base = ARTIFACT / parent["runtime"]["base_directory"]
    verified = []
    for row in parent["base_manifest"]["files"]:
        if row["path"] in {
            "tokenizer.json",
            "tokenizer_config.json",
            "merges.txt",
            "vocab.json",
            "config.json",
        }:
            raw = (base / row["path"]).read_bytes()
            if len(raw) != row["bytes"] or native.sha(raw) != row["sha256"]:
                raise ValueError("actual original tokenizer/config bytes changed")
            verified.append(row)
    if (
        len(verified) != 5
        or read(base / "config.json")["max_position_embeddings"] != NATIVE_CONTEXT
    ):
        raise ValueError("original tokenizer/native context is incomplete")
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(base, local_files_only=True)
    if (
        native.sha(tokenizer.chat_template.encode())
        != parent["runtime"]["chat_template_sha256"]
    ):
        raise ValueError("original chat template changed")
    sys.path.insert(0, str(SOURCE))
    from cell_experiments import chat_protocol

    # Match the original parent's actual source inventory, not a module with
    # the same import name from another checkout.
    path = Path(chat_protocol.__file__).resolve()
    if (
        path != SOURCE / "cell_experiments/chat_protocol.py"
        or native.sha(path.read_bytes())
        != parent["source_inventory"]["scripts/cell_experiments/chat_protocol.py"]
    ):
        raise ValueError("actual original chat protocol differs")
    return tokenizer, chat_protocol, verified


def prepare(qualified, output):
    weights = read(WORK / "WEIGHTS_FROZEN.json", WEIGHTS_SHA)
    if weights["status"] != "MATCHED_AND_WEIGHTS_FROZEN":
        raise ValueError("actual weights must already be frozen")
    parent = read(PARENT, PARENT_SHA)
    old = read(INVENTORY, INVENTORY_SHA)
    result = read(qualified / "RESULT.json")
    if result["status"] != "ORIGINAL_NATIVE_PAIR_PASSED":
        raise ValueError("original native reference has not qualified")
    intent = read(qualified / "INTENT.json")
    if int(intent["started_at_ns"]) <= int(weights["created_at_ns"]):
        raise ValueError(
            "future original-material qualification predates frozen weights"
        )
    spec = native.bound(qualified / "TASK_SPEC.json", result["task_spec_sha256"])
    before, after = native.before_oracle(spec)
    gate = native.load_module(
        "future_preparation_original_gate", native.ANCESTOR, native.ANCESTOR_SHA
    )
    codec = native.load_module(
        "future_preparation_original_codec", native.CODEC, native.CODEC_SHA
    )
    after_tree, before_tree = ast.parse(after), ast.parse(before)
    before_function = gate.function(before_tree, spec["function"])
    after_function = gate.function(after_tree, spec["function"])
    after_text = after.decode()
    reference_parts = [codec.node_span(after_text, after_function)[2]]
    if spec.get("optional_constant"):
        constants = [
            node
            for node in after_tree.body
            if gate.constant_name(node) == spec["optional_constant"]
        ]
        if len(constants) != 1:
            raise ValueError("reference optional constant is not unique")
        reference_parts.append(codec.node_span(after_text, constants[0])[2])
    reference = "```python\n" + "\n".join(reference_parts) + "```\n"
    actual, admission = native.convert(spec, reference)
    if actual != after:
        raise ValueError("shared codec does not reconstruct exact original AFTER bytes")
    native.write(output / "REFERENCE.txt", reference.encode())
    native.write(output / "REFERENCE_CONVERSION.json", admission)
    function_text, context, source_inventory = source_context(spec, before)
    tests, test_inventory = test_context(spec)
    intro = (
        "Repair this real upstream Python regression. Return exactly one closed Python code block, beginning with ```python and ending with ```, with no surrounding prose or extra blocks. Inside the block, return the COMPLETE replacement definition of "
        + spec["function"]
        + ", including its original signature and any decorators. Do not return JSON, a diff, tests, imports or an entire rewritten file. Only this function's body/docstring may change. Keep the signature and decorators identical. The adapter supplies the exact original old text and applies the generated replacement to the original revision; it never supplies any new repair code. Every attempt starts from that same original revision. No new external dependencies, test manipulation, process execution or network access are allowed.\nOnly blank lines may surround or separate these permitted definitions. All original source, AST restrictions, read-only tests, isolated pytest command and timeouts remain in force."
    )
    if spec.get("optional_constant"):
        intro += (
            "\nThe separately allowed original module literal constant is "
            + spec["optional_constant"]
            + "; if needed return its complete definition in the same code block. No other module statement is permitted."
        )
    prompt = (
        intro
        + "\n\nProject: "
        + spec["project_id"]
        + "\nAllowed file: "
        + spec["source_path"]
        + "\nOriginal file SHA256: "
        + spec["before_sha256"]
        + "\nThe tests and all other source remain immutable. Original package bindings are available.\n\nOriginal function (exact source):\n"
        + function_text
        + "\n\n"
        + context
        + "\n\n"
        + tests
    )
    source_ast = [
        native.sha(ast.dump(node, include_attributes=False).encode())
        for node in (before_function, after_function)
    ]
    fingerprints = {
        spec["before_sha256"],
        spec["after_sha256"],
        *source_ast,
        *(row["normalized_ast_sha256"] for row in spec["test_ast"]),
    }
    old_repositories = {
        row.get("canonical_repository", row.get("repository"))
        for row in old["repositories"]
    }
    if spec["project_id"] in old_repositories or fingerprints & all_hashes(old):
        raise ValueError(
            "task overlaps the frozen prior project/function/test inventory"
        )
    tokenizer, chat, tokenizer_files = tokenizer_and_chat(parent)

    def count(messages):
        rendered = chat.render_prompt(
            tokenizer, prompt, chat.inference_messages(prompt, messages)
        )
        ids = tokenizer(
            rendered, add_special_tokens=False, truncation=False, padding=False
        )["input_ids"]
        return {
            "tokens": len(ids),
            "rendered_sha256": native.sha(rendered.encode()),
            "token_ids_digest": native.sha(native.canonical(ids)),
            "rendered_bytes": len(rendered.encode()),
        }

    messages = [{"role": "user", "content": prompt}]
    first = count(messages)
    reference_tokens = len(
        tokenizer(reference, add_special_tokens=False, truncation=False, padding=False)[
            "input_ids"
        ]
    )
    seconds = []
    for side in ("before", "after"):
        receipt = copy.deepcopy(result[side])
        receipt["stage"] = "native_pytest"
        feedback = native.feedback(receipt)
        seconds.append(
            {
                "side": side,
                "feedback_sha256": native.sha(feedback.encode()),
                **count(
                    messages
                    + [
                        {"role": "assistant", "content": reference},
                        {"role": "tool", "content": feedback},
                    ]
                ),
            }
        )
    planning = (
        first["tokens"]
        + MAX_OUTPUT
        + SECOND_FEEDBACK_PLANNING_RESERVE
        + CHAT_WRAPPER_PLANNING_RESERVE
    )
    token_check = {
        "first": first,
        "complete_reference_second_contexts": seconds,
        "reference_output_tokens": reference_tokens,
        "planned_previous_answer_token_reserve": MAX_OUTPUT,
        "planned_feedback_token_reserve": SECOND_FEEDBACK_PLANNING_RESERVE,
        "planned_chat_wrapper_token_reserve": CHAT_WRAPPER_PLANNING_RESERVE,
        "planned_second_total": planning,
        "planning_reserve_is_not_a_proof_for_arbitrary_generated_text": True,
        "every_actual_complete_request_checked_before_generation": True,
        "maximum_input_tokens": MAX_INPUT,
        "maximum_output_tokens": MAX_OUTPUT,
        "native_max_position_embeddings": NATIVE_CONTEXT,
        "tokenizer_files": tokenizer_files,
        "truncations": 0,
        "model_weights_loaded": False,
        "model_calls": 0,
    }
    native.write(output / "TOKENIZER_PREFLIGHT.json", token_check)
    native.write(output / "PROMPT.txt", prompt.encode())
    if not (
        0 < reference_tokens <= MAX_OUTPUT
        and 0 < first["tokens"] <= MAX_INPUT
        and planning <= MAX_INPUT
        and all(row["tokens"] <= MAX_INPUT for row in seconds)
        and all(row["rendered_bytes"] <= 131072 for row in [first, *seconds])
    ):
        raise ValueError(
            "complete fixed context/reference plus shared planning reserves does not fit; no truncation permitted"
        )
    task = {
        "schema": "hepta.future-original-raw-function-task.v1",
        "project_id": spec["project_id"],
        "record_id": "future-raw-function-"
        + spec["project_id"].replace("/", "-")
        + ":"
        + spec["original_commit"],
        "source_path": spec["source_path"],
        "allowed_function": spec["function"],
        "optional_module_constant": spec.get("optional_constant"),
        "original_source_sha256": spec["before_sha256"],
        "original_after_sha256": spec["after_sha256"],
        "original_parent": spec["original_parent"],
        "original_commit": spec["original_commit"],
        "task_spec_path": str(qualified / "TASK_SPEC.json"),
        "task_spec_sha256": spec["_spec_sha256"],
        "native_pair_result_sha256": native.sha(
            (qualified / "RESULT.json").read_bytes()
        ),
        "expected_cases": result["expected_cases"],
        "task": {"input": prompt, "messages": messages},
        "source_context_inventory": source_inventory,
        "test_context_inventory": test_inventory,
        "complete_reference_output_sha256": native.sha(reference.encode()),
        "before_after_function_AST_sha256": source_ast,
        "old_inventory_sha256": INVENTORY_SHA,
        "training_allowed": False,
        "evaluation_allowed": True,
        "split": "confirmation",
        "origin_kind": "curated_development",
        "newly_selected_after_actual_weight_freeze": True,
        "weights_frozen_sha256": WEIGHTS_SHA,
        "no_model_output_used_for_selection": True,
        "authenticated_users": 0,
        "authenticated_independent_controller": False,
        "pretraining_contamination_eliminated": False,
        "license_review_required_before_panel_freeze": True,
    }
    native.write(output / "TASK.json", task)
    return {
        "status": "CODEC_CONTEXT_DEDUP_PASSED_PENDING_LICENSE",
        "project_id": spec["project_id"],
        "task_sha256": native.sha((output / "TASK.json").read_bytes()),
        "reference_tokens": reference_tokens,
        "first_tokens": first["tokens"],
        "planned_second_total": planning,
        "task_spec_sha256": spec["_spec_sha256"],
        "actual_new_model_calls": 0,
        "actual_new_native_children": 0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qualification-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    try:
        result = prepare(Path(args.qualification_root), output)
    except BaseException as error:
        result = {
            "status": "PREPARATION_REJECTED",
            "error_type": type(error).__name__,
            "reason": str(error),
            "traceback": traceback.format_exc(),
            "actual_new_model_calls": 0,
            "actual_new_native_children": 0,
        }
    result.update(
        wall_seconds=time.perf_counter() - started,
        self_cpu_seconds=time.process_time() - cpu,
        completed_at_ns=str(time.time_ns()),
        preparation_source_sha256=native.sha(Path(__file__).read_bytes()),
        native_source_sha256=native.sha(Path(native.__file__).read_bytes()),
    )
    native.write(output / "RESULT.json", result)
    print(
        json.dumps(
            {
                "path": str(output / "RESULT.json"),
                "sha256": native.sha((output / "RESULT.json").read_bytes()),
                "result": result,
            }
        ),
        flush=True,
    )
    raise SystemExit(
        0 if result["status"] == "CODEC_CONTEXT_DEDUP_PASSED_PENDING_LICENSE" else 1
    )


if __name__ == "__main__":
    main()
