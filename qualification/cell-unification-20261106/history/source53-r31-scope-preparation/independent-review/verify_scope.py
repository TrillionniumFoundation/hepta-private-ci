"""Read-only independent scope verification; never imports/runs a formatter."""
from pathlib import Path, PurePosixPath
import ast
import base64
import gzip
import hashlib
import json
import re
import tomllib

ROOT = Path(__file__).resolve().parent.parent
INPUT = ROOT / "source53-final-scope-preparation"
OUT = Path(__file__).resolve().parent
SOURCE = PurePosixPath("/home/alex/work/hepta-cell-unified-20261106-a/source")
COMMIT = "f74be175de66a4b351cd239d39d98cd34fe9cc1b"
TREE = "440d4a8e09af4009e4d9ea067388826308da8803"
HEAD = "bef6fa7645df9df12b69fda499e97eed25de6c75"


def pin(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def get(name):
    path = INPUT / name
    assert path.is_file() and not path.is_symlink(), name
    return path.read_bytes()


def doc(name):
    return json.loads(get(name))


def projected(row):
    return {key: row[key] for key in ("bytes", "sha256", "git_blob")}


def main():
    handoff_raw = get("HANDOFF-MANIFEST.json")
    assert pin(handoff_raw)["sha256"] == "d217d3c9c195623b71b9763ccfa929013d4e77b2c62496ef2e3fba81450cc685"
    handoff = json.loads(handoff_raw)
    assert len(handoff["files"]) == handoff["file_count_excluding_this_manifest"] == 85
    for row in handoff["files"]:
        assert pin(get(row["path"])) == projected(row), row["path"]
    assert sum(row["bytes"] for row in handoff["files"]) == handoff["bytes_excluding_this_manifest"]

    metadata_raw = gzip.decompress(get("input/native-workspace-r31-metadata.json.gz"))
    metadata = json.loads(metadata_raw)
    metadata_pin = pin(metadata_raw)
    assert metadata_pin == {"bytes": 937659, "sha256": "b29d6b0c49c63d6345f50597873e3fa98c79ea0cbfe923ae3dd700b5cc08af8d", "git_blob": "0db6b5ccf051718a85b4aa0e7a57b7d62b393ecb"}
    scope_raw = get("input/native-workspace-r31-scope.json")
    scope = json.loads(scope_raw)
    info = doc("transport/scope-file-info-original.json")
    chunks = [doc("transport/scope-chunk-" + str(i) + "-original.json") for i in range(2)]
    joined = b""
    for i, chunk in enumerate(chunks):
        part = base64.b64decode(chunk["data_base64"], validate=True)
        assert chunk["offset"] == len(joined)
        assert chunk["next_offset"] == len(joined) + len(part)
        assert chunk["version"] == info["version"] and chunk["path"] == info["path"]
        assert chunk["size"] == info["size"] == len(scope_raw)
        assert chunk["eof"] is (i == 1)
        assert hashlib.sha256(part).hexdigest() == chunk["chunk_sha256"]
        joined += part
    assert joined == scope_raw and pin(joined)["sha256"] == info["sha256"]
    mdi = doc("input/r31-start/transport/metadata_info-original.json")
    assert mdi["size"] == metadata_pin["bytes"] and mdi["sha256"] == metadata_pin["sha256"]
    assert mdi["path"].endswith("/native-workspace-r31-metadata.json")
    raw_name = "native-workspace-r31-metadata-raw-process-result.json"
    receipt = doc("input/r31-start/evidence/native-workspace-r31-metadata-receipt.json")
    raw = doc("input/r31-start/evidence/" + raw_name)
    expected_command = ["cargo", "metadata", "--locked", "--no-deps", "--format-version", "1"]
    for value in (raw, receipt):
        assert value["source_commit"] == COMMIT and value["source_tree"] == TREE
        assert value["command"] == expected_command and value["exit_code"] == 0
        assert value["cwd"] == str(SOURCE / "codex-rs")
    for key in ("command", "cwd", "start_unix", "end_unix", "exit_code"):
        assert raw[key] == receipt[key]
    assert abs(receipt["elapsed_seconds"] - (raw["end_unix"] - raw["start_unix"])) < 1e-6
    assert receipt["stdout"] == metadata_pin
    assert receipt["stderr"] == pin(get("input/r31-start/evidence/native-workspace-r31-metadata-stderr.log")) == pin(b"")
    assert receipt["raw_process_result"] == {"path": raw_name, **pin(get("input/r31-start/evidence/" + raw_name))}
    post_name = "native-workspace-r31-metadata-source-post-verification.json"
    post = doc("input/r31-start/evidence/" + post_name)
    assert receipt["source_postguard"] == {"path": post_name, **pin(get("input/r31-start/evidence/" + post_name))}
    assert receipt["source_guards_pass"] is post["pass"] is True
    assert post["expected_tree"] == post["actual_tree"] == TREE and post["source_commit"] == COMMIT
    assert post["changed_file_count"] == 197 and post["native_head"] == HEAD
    assert post["changed_path_set_matches"] is True
    assert post["file_mismatches"] == post["unstaged_paths"] == post["untracked_paths"] == []
    assert post["cargo_lock_sha256"] == "4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c"
    assert post["bazel_lock_sha256"] == "e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb"
    launch = doc("input/r31-start/controller/launch-original.json")
    assert launch["job"]["id"] == "1a1b275ba33-fc05-7e17" and launch["launch"]["ok"] is True and launch["reused"] is False
    assert launch["job"]["created_unix_ms"] / 1000 <= raw["start_unix"]
    assert launch["job"]["args"] == [str(SOURCE.parent / "native-run-r31.py")]
    assert scope["source_commit"] == COMMIT and scope["source_tree"] == TREE
    assert scope["metadata"] == {"path": "native-workspace-r31-metadata.json", **metadata_pin}
    assert scope["metadata_generated_on_current_source"] is True and scope["old_metadata_reused_as_current"] is False
    assert scope["command"] == ["just", "test", "--locked", "--retries", "0"]
    member_ids = set(metadata["workspace_members"])
    assert len(member_ids) == len(metadata["workspace_members"]) == len(metadata["workspace_default_members"]) == 193
    assert member_ids == set(metadata["workspace_default_members"])
    assert {r["id"] for r in scope["workspace_members"]} == {r["id"] for r in scope["workspace_default_members"]} == member_ids

    manifest_raw = get("input/native-candidate-r30-source.json")
    manifest = json.loads(manifest_raw)
    assert pin(manifest_raw)["sha256"] == "9292bd9002716a0bec35ecea294f9dfef3dbb1e9c1d8fe66660e502aecc5cdda"
    assert manifest["source_commit"] == COMMIT and manifest["source_tree"] == TREE
    files = {row["path"]: row for row in manifest["changed_files"]}
    assert len(files) == len(manifest["changed_files"]) == 197
    parent = doc("input/source52-parent-manifest.json")
    previous = {row["path"]: row for row in parent["changed_files"]}
    assert len(previous) == 195 and all(files[name] == row for name, row in previous.items())
    assert set(files) - set(previous) == {
        "codex-rs/app-server/src/request_processors/account_processor/bedrock_setup.rs",
        "codex-rs/app-server/tests/suite/v2/bedrock_setup.rs"}
    expected = doc("EXPECTED-SELECTION.json")
    args = doc("PACKAGE-ARGS.json")
    commands = doc("RUST-FILE-COMMANDS.json")
    primary = doc("PRIMARY-SOURCE-PINS.json")
    assert get("PRIMARY-SOURCE-PINS.json") == get("input/unchanged-PRIMARY-SOURCE-PINS.json")
    assert len(primary) == 34
    for row in primary:
        assert pin(get("input/primary/" + row["path"])) == projected(row), row["path"]
    rust = sorted(path for path in files if path.endswith(".rs"))
    python = sorted(path for path in files if path.startswith(("scripts/", ".github/")) and path.endswith((".py", ".pyi")))
    assert len(rust) == 183 and python == ["scripts/run-nextest.py", "scripts/test_run_nextest_helpers.py"]
    assert not any(PurePosixPath(path).name in {"justfile", "rustfmt.toml", ".rustfmt.toml", "pyproject.toml", "ruff.toml", ".ruff.toml"} for path in files)
    assert expected["changed_paths"] == sorted(files) and expected["changed_path_count"] == 197
    assert expected["rust_paths"] == rust and expected["rust_count"] == 183
    assert expected["python_paths"] == ["./" + path for path in python] and expected["python_count"] == 2
    assert expected["native_HEAD"] == HEAD and expected["native_created_commit_checkout_claimed"] is False
    assert expected["formatting_configuration_changed_paths"] == []
    primary_by_path = {row["path"].removeprefix("original/"): row for row in primary}
    package_by_root = {}
    for package in metadata["packages"]:
        if package["id"] in member_ids:
            manifest_path = PurePosixPath(package["manifest_path"]).relative_to(SOURCE)
            package_by_root[manifest_path.parent.as_posix()] = package
    owners = {}
    expected_commands = []
    for path in rust:
        ancestors = [p.as_posix() for p in PurePosixPath(path).parents]
        owning_root = next(directory for directory in ancestors if directory in package_by_root)
        package = package_by_root[owning_root]
        manifest_path = owning_root + "/Cargo.toml"
        assert manifest_path in primary_by_path
        manifest_toml = tomllib.loads(get("input/primary/original/" + manifest_path).decode())
        assert manifest_toml["package"]["name"] == package["name"]
        edition = manifest_toml["package"].get("edition", "2015")
        if isinstance(edition, dict):
            assert edition == {"workspace": True}
            edition = tomllib.loads(get("input/primary/original/codex-rs/Cargo.toml").decode())["workspace"]["package"]["edition"]
        assert edition == package["edition"] == "2024"
        entry = owners.setdefault(package["name"], {
            "package": package["name"], "package_id": package["id"], "package_directory": owning_root,
            "manifest_path": manifest_path, "edition": edition, "default_workspace_member": True, "rust_paths": []})
        assert entry["package_directory"] == owning_root
        entry["rust_paths"].append(path)
        expected_commands.append({"path": path, "owning_package": package["name"], "manifest_path": manifest_path,
                                  "cwd": str(SOURCE / owning_root), "command": ["rustfmt", "--edition", edition,
                                  "--config", "imports_granularity=Item,skip_children=true", "--", str(SOURCE / path)]})
    names = sorted(owners)
    for owner in owners.values(): owner["rust_path_count"] = len(owner["rust_paths"])
    assert len(names) == expected["owner_count"] == 26
    assert expected["owners"] == [owners[name] for name in names] and args["owners"] == names
    assert commands == expected_commands
    package_args = [value for name in names for value in ("-p", name)]
    assert args["package_args"] == package_args and args["command"] == ["just", "fix", "--locked", *package_args]
    assert args["recipe_expansion"] == ["cargo", "clippy", "--fix", "--tests", "--allow-dirty", "--locked", *package_args]
    assert args["cwd"] == str(SOURCE / "codex-rs") and args["fresh_metadata"] == metadata_pin
    assert expected["default_formatter_command"] == ["just", "fmt"] and expected["all_flag_used"] is False
    assert expected["python_formatter_command"] == ["uv", "run", "--frozen", "--project", "scripts", "ruff", "format", *["./" + path for path in python]]
    assert expected["unselected_by_default_formatter"] == sorted(set(files) - set(rust) - set(python))
    ci = re.findall(r"(?<!\S)-p\s+(codex-[A-Za-z0-9_-]+|core_test_support)(?=\s|$)", get("input/hepta-cell-framework-native.yml").decode())
    assert len(ci) == len(set(ci)) == expected["ci_selector_count"] == 27
    assert expected["ci_selectors"] == ci and set(ci) - set(names) == {"codex-hepta-control-plane"}
    assert expected["extra_ci_only_owner"] == ["codex-hepta-control-plane"]
    assert expected["workspace_members"] == expected["workspace_default_members"] == 193
    assert expected["fresh_source53_r31_metadata_verified"] is True and expected["workspace_result"] is None
    assert expected["final_scope_execution_authorized"] is False and args["fix_executed"] is False
    for value in (expected, args):
        assert value["source_commit"] == COMMIT and value["source_tree"] == TREE
        assert value["source_manifest"] == {"path": "input/native-candidate-r30-source.json", **pin(manifest_raw)}
        assert value["diagnostic_only"] is True and value["behavior_repair_claimed"] is False
    consumer = ROOT / "source53-finalize-preparation/native-finalize-source53-template.py"
    consumer_raw = consumer.read_bytes()
    assert pin(consumer_raw)["sha256"] == "41c18849f6ebd24b17695051ee9c1c47c38ae207f87bf6c004f76248210fa22d"
    text = consumer_raw.decode(); tree = ast.parse(text)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    consumer_function = ast.get_source_segment(text, functions["load_final_scope"])
    required = {}
    for variable, value in (("expected", expected), ("proposed", args)):
        keys = sorted({node.slice.value for node in ast.walk(functions["load_final_scope"])
                       if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                       and node.value.id == variable and isinstance(node.slice, ast.Constant)
                       and isinstance(node.slice.value, str)})
        assert set(keys) <= set(value)
        required[variable] = keys
    assert hashlib.sha256(consumer_function.encode()).hexdigest() == "0628aedf121719f89f0cd6eaec2082efb2319abc3f034bc93262514b29679f3d"
    report = {"schema": "hepta.source53-final-scope-independent-review.v1", "result": "STATIC_SCOPE_CLEAR_NOT_EXECUTION_AUTHORIZATION",
              "input_handoff": pin(handoff_raw), "source_commit": COMMIT, "source_tree": TREE,
              "all85_listed_input_pins_recomputed": True, "scope_chunks_exact_full_reconstruction": True,
              "metadata": metadata_pin, "metadata_original_return": 0, "metadata_elapsed_seconds": receipt["elapsed_seconds"],
              "metadata_provenance": "New R31 native invocation receipt and file_info bound; local equal-hash metadata bytes reused, not the old invocation.",
              "source_guard": projected(receipt["source_postguard"]), "source52_rows_unchanged": 195,
              "counts": {"changed": 197, "rust": 183, "python_formatter": 2, "owners": 26, "ci_selectors": 27, "members": 193, "defaults": 193},
              "owner_names": names, "all183_original_edition_cwd_argv_recomputed": True,
              "all34_primary_source_pins_recomputed": True, "native_HEAD": HEAD, "HEAD_not_changed": True,
              "commands": {"fix": args["command"], "fmt": ["just", "fmt"], "python": expected["python_formatter_command"]},
              "consumer": pin(consumer_raw), "consumer_function_sha256": hashlib.sha256(consumer_function.encode()).hexdigest(),
              "consumer_required_literal_keys": required,
              "four_outputs": [{"path": name, **pin(get(name))} for name in handoff["scope_input_names"]],
              "workspace_terminal_result": None, "fresh_tool_inventory_bound": False, "formatter_authorized": False,
              "diagnostic_only": True, "behavior_repair_claimed": False,
              "scope_limit": "Static artifact and consumer-contract verification only. Finalizer still must recheck actual HEAD/default selection, complete same-source R31/R30 qualification and fresh tool inventory.",
              "native_cargo_metadata_runner_formatter_or_git_execution_by_this_review": False,
              "consumer_imported_or_executed": False, "original_inputs_modified": False}
    data = (json.dumps(report, indent=2) + "\n").encode()
    with (OUT / "INDEPENDENT-REVIEW.json").open("xb") as stream: stream.write(data)
    listed = [{"path": path.name, **pin(path.read_bytes())} for path in (Path(__file__), OUT / "INDEPENDENT-REVIEW.json")]
    handoff_data = (json.dumps({"schema": "hepta.source53-final-scope-independent-handoff.v1", "files": listed,
                               "result": "STATIC_SCOPE_CLEAR", "execution_authorized": False}, indent=2) + "\n").encode()
    with (OUT / "HANDOFF-MANIFEST.json").open("xb") as stream: stream.write(handoff_data)
    print(json.dumps({"report": pin(data), "handoff": pin(handoff_data), "checked_original_files": 85, "counts": report["counts"]}))


if __name__ == "__main__":
    main()
