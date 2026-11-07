#!/usr/bin/env python3
"""Static output/consumer compatibility readback; never imports either runner."""
import ast
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath

D = Path(__file__).resolve().parent


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def load(name):
    return json.loads((D / name).read_bytes())


def main():
    bindings = load("ACTUAL-BINDINGS.json")
    for name, expected_pin in bindings["bindings"]["INPUT_PINS"].items():
        assert pin((D / name).read_bytes()) == expected_pin, name
    template = (D / "generate_scope_template.py").read_text()
    bound = (D / "generate_scope_bound.py").read_text()
    inverse = bound.replace("FROZEN = True", "FROZEN = False", 1)
    for name, value in bindings["bindings"].items():
        inverse = inverse.replace(name + " = " + repr(value), name + " = None", 1)
    assert inverse == template
    for text in (template, bound):
        parsed = ast.parse(text)
        imports = [n.module for n in ast.walk(parsed) if isinstance(n, ast.ImportFrom)]
        imports += [a.name for n in ast.walk(parsed) if isinstance(n, ast.Import) for a in n.names]
        assert not set(imports) & {"subprocess", "runpy", "importlib", "socket", "urllib", "requests"}

    expected, proposed = load("EXPECTED-SELECTION.json"), load("PACKAGE-ARGS.json")
    commands, primary = load("RUST-FILE-COMMANDS.json"), load("PRIMARY-SOURCE-PINS.json")
    metadata = json.loads(gzip.decompress((D / "input/native-workspace-r31-metadata.json.gz").read_bytes()))
    source_raw = (D / "input/native-candidate-r30-source.json").read_bytes()
    source = json.loads(source_raw)
    files = {row["path"]: row for row in source["changed_files"]}
    assert expected["changed_paths"] == sorted(files)
    rust = sorted(path for path in files if path.endswith(".rs"))
    assert expected["rust_paths"] == rust and len(rust) == len(commands) == 183
    native = PurePosixPath(metadata["workspace_root"]).parent
    member_ids = set(metadata["workspace_members"])
    assert len(member_ids) == len(metadata["workspace_default_members"]) == 193
    packages = [row for row in metadata["packages"] if row["id"] in member_ids]
    roots = {PurePosixPath(row["manifest_path"]).parent: row for row in packages}
    counts = {}
    rebuilt_commands = []
    for path in rust:
        absolute = native / path
        owner_root = next(parent for parent in absolute.parents if parent in roots)
        owner = roots[owner_root]
        counts[owner["name"]] = counts.get(owner["name"], 0) + 1
        rebuilt_commands.append({"path": path, "owning_package": owner["name"],
            "manifest_path": (owner_root / "Cargo.toml").relative_to(native).as_posix(),
            "cwd": str(owner_root), "command": ["rustfmt", "--edition", owner["edition"], "--config",
                "imports_granularity=Item,skip_children=true", "--", str(absolute)]})
    assert commands == rebuilt_commands
    assert sorted(counts) == proposed["owners"] and len(counts) == 26
    assert {row["package"]: row["rust_path_count"] for row in expected["owners"]} == counts
    assert proposed["fresh_metadata"] == pin(gzip.decompress((D / "input/native-workspace-r31-metadata.json.gz").read_bytes()))
    assert expected["source_manifest"] == proposed["source_manifest"] == {"path": "input/native-candidate-r30-source.json", **pin(source_raw)}
    assert (D / "PRIMARY-SOURCE-PINS.json").read_bytes() == (D / "input/unchanged-PRIMARY-SOURCE-PINS.json").read_bytes()
    assert len(primary) == 34 and len(expected["ci_selectors"]) == 27
    assert expected["python_paths"] == ["./scripts/run-nextest.py", "./scripts/test_run_nextest_helpers.py"]
    assert expected["workspace_result"] is None and proposed["same_source_workspace_pass_bound"] is False
    assert expected["final_scope_execution_authorized"] is False
    assert "--all" not in expected["default_formatter_command"] and "--allow-staged" not in proposed["recipe_expansion"]

    sources = load("references/PRODUCER-CONSUMER-FUNCTIONS.json")
    consumer = next(row for row in sources if row["original_path"].endswith("native-finalize-source53-template.py"))
    consumer_text = consumer["functions"]["load_final_scope"]
    tree = ast.parse(consumer_text)
    accesses = {"expected": set(), "proposed": set()}
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id in accesses:
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                accesses[node.value.id].add(node.slice.value)
    for name, values in (("expected", expected), ("proposed", proposed)):
        assert accesses[name] <= set(values), (name, accesses[name] - set(values))
    outputs = [{"path": name, **pin((D / name).read_bytes())} for name in
               ["EXPECTED-SELECTION.json", "PACKAGE-ARGS.json", "RUST-FILE-COMMANDS.json", "PRIMARY-SOURCE-PINS.json"]]
    audit = load("READ-ONLY-AUDIT.json")
    assert audit["outputs"] == outputs
    report = {"schema": "hepta.source53-r31-scope-static-consumer-readback.v1",
        "result": "STATIC_OUTPUT_CONTRACT_CLEAR_NOT_FINALIZER_EXECUTION", "outputs": outputs,
        "consumer_original": {key: consumer[key] for key in ("original_path", "bytes", "sha256", "git_blob")},
        "consumer_function_sha256": hashlib.sha256(consumer_text.encode()).hexdigest(),
        "required_top_level_keys": {name: sorted(keys) for name, keys in accesses.items()},
        "required_keys_present": True, "per_file_commands_rebuilt_by_ancestor_walk": True,
        "original_owner_count": len(counts), "actual_fresh_metadata_members": len(member_ids),
        "unchanged_primary_raw_bytes": True, "template_binding_exact_inverse": True,
        "generator_has_no_subprocess_or_network_imports": True,
        "consumer_imported_or_executed": False, "native_or_Rust_or_metadata_or_formatter_executed": False,
        "workspace_result": None, "finalizer_authorization": False}
    data = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
    with (D / "CONSUMER-CONTRACT-READBACK.json").open("xb") as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    print(json.dumps({"readback": pin(data), "outputs": outputs}))


if __name__ == "__main__":
    main()
