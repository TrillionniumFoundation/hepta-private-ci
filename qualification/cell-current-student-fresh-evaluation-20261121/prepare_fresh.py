"""Ordered original-material qualification and tokenizer-only task preparation.

The original static inspector, exact replacement codec and native executable
remain byte-bound. This owner creates only a new evaluation population.
"""

import argparse
import ast
import copy
import hashlib
import json
from pathlib import Path
import sys
import time

import acquire_fresh as acquisition
import fresh_contract as c
import run_fresh as runtime

CONTEXT_SHA = "cf3e7d0e207b5553618d6eee436b2550d6205c76151b655296c4e193d1a7fbbc"


def locations(selection, index, ordinal):
    c.require(type(index) is int and 0 <= index < 8 and type(ordinal) is int and 0 <= ordinal < 4,
              "declared material slot required")
    owner = Path(selection["owner_root"])
    project = c.REPOSITORIES[index]
    return owner, owner / "scans" / f"{index:02d}-{project.replace('/', '--')}", owner / "materials" / f"{index:02d}" / str(ordinal)


def tree_inventory(commands, prefix, revision):
    raw = commands.run(prefix + ["ls-tree", "-rzl", revision])
    rows = [row for row in raw.split(b"\0") if row]
    c.require(len(rows) <= 20000, "complete original tree exceeds entry cap")
    files, total = {}, 0
    for row in rows:
        description, name = row.split(b"\t", 1)
        mode, kind, blob, size = description.decode().split()
        path, count = name.decode(), int(size)
        c.require(mode in ("100644", "100755") and kind == "blob" and 0 <= count <= 1024**2,
                  "nonregular or oversized original tree blob")
        relative = Path(path)
        c.require(not relative.is_absolute() and ".." not in relative.parts, "unsafe original Git path")
        files[path] = {"blob": blob, "bytes": count}
        total += count
    c.require(total <= c.CAPS["archive_bytes"], "complete tree exceeds material archive cap")
    return files


def materialize(deployment, index, ordinal, scan_sha256):
    selection, excluded, _, _, _ = acquisition.release(deployment)
    acquisition.preceding_sources(selection, excluded, index)
    owner, scanned_root, output = locations(selection, index, ordinal)
    scanned = c.read_bound({"path": str(scanned_root / "RESULT.json"), "sha256": scan_sha256})
    schedule = c.ordered_potentials(scanned)
    c.require(ordinal < len(schedule) and scanned["canonical_repository"] == c.REPOSITORIES[index], "ordered source potential missing")
    if ordinal:
        previous = json.loads((output.parent / str(ordinal - 1) / "FINAL.json").read_bytes())
        c.require(previous["status"] in ("REFUSED", "FAILED_NO_RETRY"), "previous material must finish before proceeding")
    position = schedule[ordinal]
    slots = c.Slots(selection, excluded)
    slots.claim("material", (index, ordinal), {"scan_sha256": scan_sha256, "position": position})
    output.mkdir(parents=True, exist_ok=False)
    c.write_new(output / "ATTEMPT.json", {"project_id": c.REPOSITORIES[index], "position": list(position),
                "scan_sha256": scan_sha256, "selection_digest": c.digest(selection), "automatic_retry": False})
    phase, dispatched = "compatibility", []
    try:
        commands = acquisition.GitCommands(output, owner, index)
        prefix = ["git", "--git-dir", str(scanned_root / "upstream.git")]
        commit = scanned["commits"][position[0]]
        tree_inventory(commands, prefix, commit["parent"])
        after = tree_inventory(commands, prefix, commit["commit"])
        configurations = {name: commands.run(prefix + ["show", commit["commit"] + ":" + name])
                          for name in ("pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini") if name in after}
        acquisition.compatibility(after, commit["original_changed_test_paths"], configurations)
        c.write_new(output / "COMPATIBILITY.json", {"status": "SUPPORTED_ORIGINAL_CONFIGURATION_AND_LAYOUT",
                    "configuration_sha256s": {name: hashlib.sha256(raw).hexdigest() for name, raw in configurations.items()},
                    "tests_filtered_or_modified": False, "original_runtime_semantics_changed": False})
        phase = "original_materializer"
        native = runtime.native_adapter(deployment)
        c.write_new(output / "NATIVE_ENVIRONMENT.json", native.environment_scope_receipt)
        c.require("future_native" not in sys.modules or Path(sys.modules["future_native"].__file__).resolve() == Path(native.__file__).resolve(),
                  "native import identity already occupied")
        sys.modules["future_native"] = native
        original = runtime.module("fresh_original_materializer", deployment["materializer_source"], acquisition.MATERIALIZER_SHA)
        original.git = lambda root, destination, args: commands.run(["git", "--git-dir=" + str(root / "upstream.git"), *args])
        original_native = native.run_native

        def paid_native(spec, destination, candidate=None, label="candidate", expected_cases=None):
            side = ("before", "after")[len(dispatched)] if len(dispatched) < 2 else None
            c.require(label == ("original_parent" if side == "before" else "exact_reference_function") and side is not None,
                      "unexpected original qualification dispatch")
            slots.claim("qualification_native", (index, ordinal, side), {"task_spec_sha256": spec["_spec_sha256"]})
            dispatched.append(side)
            try:
                result = original_native(spec, destination, candidate, label, expected_cases)
            except BaseException:
                c.write_new(owner / "ACQUISITION_UNCERTAIN.json", {"material": str(output), "side": side,
                            "reason": "original native call did not return its waited receipt", "automatic_retry": False})
                raise
            acquisition.budget(acquisition.retained_bytes(owner) <= c.CAPS["owner_material_bytes"], "owner material cap exceeded")
            return result

        native.run_native = paid_native
        old_argv = sys.argv
        sys.argv = ["fresh-bound-materializer", "--repository-root", str(scanned_root), "--commit-index", str(position[0]),
                    "--source-index", str(position[1]), "--output", str(output / "native-material")]
        if c.REPOSITORIES[index] in deployment.get("dependency_bundles", {}):
            dependency = deployment["dependency_bundles"][c.REPOSITORIES[index]]
            c.read_bound(dependency)
            sys.argv += ["--dependency-bundle", dependency["path"], "--dependency-sha256", dependency["sha256"]]
        try:
            original.main()
        finally:
            sys.argv, native.run_native = old_argv, original_native
        pair_path = output / "native-material/RESULT.json"
        pair = json.loads(pair_path.read_bytes())
        receipt = {"status": "NATIVE_PAIR_READY_FOR_PREPARATION" if pair["status"] == "ORIGINAL_NATIVE_PAIR_PASSED" else "REFUSED",
                   "native_pair": {"path": str(pair_path), "sha256": c.sha(pair_path)}, "native_dispatches": dispatched,
                   "automatic_retry": False, "model_calls": 0}
        c.write_new(output / "MATERIALIZED.json", receipt)
        if receipt["status"] == "REFUSED":
            c.write_new(output / "FINAL.json", receipt)
        return receipt
    except BaseException as error:
        receipt = {"status": "REFUSED" if phase == "compatibility" and isinstance(error, ValueError) else "FAILED_NO_RETRY",
                   "phase": phase, "error_type": type(error).__name__, "error": str(error),
                   "native_dispatch_upper_bound": len(dispatched), "actual_native_completion_may_be_unknown": bool(dispatched),
                   "automatic_retry": False, "model_calls": 0}
        c.write_new(output / "FINAL.json", receipt)
        raise


def prepare(deployment, index, ordinal, license_binding):
    selection, excluded, publication, _, assets = acquisition.release(deployment)
    _, comparison, bundle, engine, manifests = assets
    _, scanned_root, root = locations(selection, index, ordinal)
    materialized = json.loads((root / "MATERIALIZED.json").read_bytes())
    c.require(materialized["status"] == "NATIVE_PAIR_READY_FOR_PREPARATION", "new original pair is not ready")
    output = root / "prepared"
    output.mkdir(exist_ok=False)
    try:
        native = runtime.native_adapter(deployment)
        sys.modules["future_native"] = native
        context = runtime.module("fresh_original_context", deployment["context_source"], CONTEXT_SHA)
        pair = c.read_bound(materialized["native_pair"])
        spec_path = root / "native-material/TASK_SPEC.json"
        spec = native.bound(spec_path, pair["task_spec_sha256"])
        before, after = native.before_oracle(spec)
        gate = native.load_module("fresh_prepare_gate", native.ANCESTOR, native.ANCESTOR_SHA)
        codec = native.load_module("fresh_prepare_codec", native.CODEC, native.CODEC_SHA)
        trees = [ast.parse(raw) for raw in (before, after)]
        functions = [gate.function(tree, spec["function"]) for tree in trees]
        after_text = after.decode()
        pieces = [codec.node_span(after_text, functions[1])[2]]
        if spec.get("optional_constant"):
            constants = [node for node in trees[1].body if gate.constant_name(node) == spec["optional_constant"]]
            c.require(len(constants) == 1, "one original optional constant required")
            pieces.append(codec.node_span(after_text, constants[0])[2])
        reference = "```python\n" + "\n".join(pieces) + "```\n"
        rebuilt, conversion = native.convert(spec, reference)
        c.require(rebuilt == after, "complete original reference must reconstruct exact AFTER bytes")
        (output / "REFERENCE.txt").write_bytes(reference.encode())
        c.write_new(output / "REFERENCE_CONVERSION.json", conversion)
        function, source_context, source_inventory = context.source_context(spec, before)
        tests, test_inventory = context.test_context(spec)
        prompt = ("Repair this original upstream Python regression. Return exactly one closed Python code block with no surrounding prose. "
                  "Return the COMPLETE replacement definition of " + spec["function"] + ", preserving its original signature and decorators. "
                  "Only that function body/docstring may change. Do not return a diff, JSON, tests, imports, or an entire file. "
                  "No external dependencies, process execution, network access, or test manipulation are allowed. "
                  "The exact original source, AST restrictions, read-only tests and native timeouts remain in force.\n")
        if spec.get("optional_constant"):
            prompt += "The only separately allowed module literal constant is " + spec["optional_constant"] + "; return its complete definition if needed.\n"
        prompt += ("\nProject: " + spec["project_id"] + "\nAllowed file: " + spec["source_path"] + "\nOriginal SHA256: "
                   + spec["before_sha256"] + "\n\nOriginal function:\n" + function + "\n\n" + source_context + "\n\n" + tests)
        attempt = json.loads((root / "ATTEMPT.json").read_bytes())
        scanned = c.read_bound({"path": str(scanned_root / "RESULT.json"), "sha256": attempt["scan_sha256"]})
        record = {"schema": "hepta.current-student-fresh-task.v1", "record_id": "fresh-" + spec["project_id"] + ":" + spec["original_commit"],
                  "project_id": spec["project_id"], "source_group": "github-owner:" + spec["project_id"].split("/")[0].casefold(),
                  "repository_metadata": deployment["repository_metadata"][spec["project_id"]], "source_position": attempt["position"],
                  "weights_digest": selection["weights_digest"], "source_access_started_at_ns": scanned["source_access_started_at_ns"],
                  "source_preparation_completed_at_ns": str(time.time_ns()),
                  "original_parent": spec["original_parent"], "original_commit": spec["original_commit"], "source_path": spec["source_path"],
                  "allowed_function": spec["function"], "original_source_sha256": spec["before_sha256"], "original_after_sha256": spec["after_sha256"],
                  "before_after_function_AST_sha256": [hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest() for node in functions],
                  "test_AST_sha256s": [row["normalized_ast_sha256"] for row in spec["test_ast"]],
                  "task": {"input": prompt, "messages": [{"role": "user", "content": prompt}]},
                  "task_spec_path": str(spec_path), "task_spec_sha256": spec["_spec_sha256"], "expected_cases": pair["expected_cases"],
                  "native_pair": materialized["native_pair"], "license_review": license_binding,
                  "native_result_sha256s": {side: c.sha(root / "native-material" / (side + "-run") / "RESULT.json") for side in ("before", "after")},
                  "reference": {"path": str(output / "REFERENCE.txt"), "sha256": c.sha(output / "REFERENCE.txt")},
                  "source_context_inventory": source_inventory, "test_context_inventory": test_inventory,
                  "training_allowed": False, "evaluation_allowed": True, "previously_exposed": False,
                  "split": "confirmation", "origin_kind": "curated_development", "capacity": {},
                  "authenticated_users": 0, "authenticated_independent_controller": False, "pretraining_contamination_eliminated": False}
        c.record_guard(record, selection, excluded, publication)
        from transformers import AutoTokenizer

        for mode in c.MODES:
            parent = manifests[mode]["frozen"]
            engine.probe.verify_model(parent["base_manifest"], deployment["artifact_root"])
            tokenizer = AutoTokenizer.from_pretrained(str(engine.probe._base(deployment["artifact_root"], parent["runtime"]["base_directory"])),
                                                      local_files_only=True, trust_remote_code=False)
            c.require(engine.chat_protocol.template_digest(tokenizer.get_chat_template()) == parent["runtime"]["chat_template_sha256"],
                      "actual parent tokenizer template changed")
            record["capacity"][mode] = {}
            for arm in c.ARMS:
                request = {"record_id": record["record_id"], "task": copy.deepcopy(record["task"])}
                request, retrieval = comparison.prepare_request("retrieval" if arm == "retrieval" else "frozen", request, bundle, mode, tokenizer, engine.chat_protocol)
                receipt = c.complete_capacity(request, reference, tokenizer, engine.chat_protocol)
                record["capacity"][mode][arm] = receipt
                c.write_new(output / f"CAPACITY-{mode}-{arm}.json", {"capacity": receipt, "retrieval": retrieval})
        record["source_preparation_completed_at_ns"] = str(time.time_ns())
        c.write_new(output / "TASK.json", record)
        result = {"status": "QUALIFIED", "record_id": record["record_id"], "task_digest": c.digest(record),
                  "task": {"path": str(output / "TASK.json"), "sha256": c.sha(output / "TASK.json")},
                  "model_calls": 0, "native_children": 0, "tokenizer_only_capacity_checks": 6}
        c.write_new(root / "FINAL.json", result)
        return result
    except BaseException as error:
        c.write_new(root / "FINAL.json", {"status": "REFUSED" if isinstance(error, ValueError) else "FAILED_NO_RETRY",
                    "error_type": type(error).__name__, "error": str(error), "automatic_retry": False,
                    "model_calls": 0, "native_children": 0})
        raise


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment", required=True)
    parser.add_argument("--deployment-sha256", required=True)
    parser.add_argument("--repository-index", type=int, required=True)
    parser.add_argument("--ordinal", type=int, required=True)
    parser.add_argument("--stage", choices=("materialize", "prepare"), required=True)
    parser.add_argument("--scan-sha256")
    parser.add_argument("--license-review")
    parser.add_argument("--license-review-sha256")
    args = parser.parse_args()
    deployment = c.read_bound({"path": args.deployment, "sha256": args.deployment_sha256})
    with acquisition.source_owner(deployment):
        if args.stage == "materialize":
            result = materialize(deployment, args.repository_index, args.ordinal, args.scan_sha256)
        else:
            result = prepare(deployment, args.repository_index, args.ordinal,
                             {"path": args.license_review, "sha256": args.license_review_sha256})
    print(json.dumps(result))
