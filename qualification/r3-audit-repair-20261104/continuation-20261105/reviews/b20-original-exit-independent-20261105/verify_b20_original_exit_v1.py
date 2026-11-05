"""Verify retained B20 evidence only; never starts a product or native process.

The only subprocesses are local `git apply` in a new temporary directory for
checking source reconstruction. Optional --windows-zip independently decodes
the complete upstream original ZIP/execution log instead of trusting a slice.
"""
import argparse
import base64
import hashlib
import importlib.machinery
import importlib.util
import json
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


TARGET = "codex-rs/app-server/tests/suite/v2/remote_control.rs"
NEGATIVE = "9cf0d41be64c6fc2ecca8661e6aa071551f109dc"
FIXED = "10a523727b458839c4c2899596f01338e871248e"
NEG_TREE = "0ec7ee504e4450a6a959a437a54363d8634100a9"
FIX_TREE = "98e7be301dec58f14d51738221e4445e3a06d900"
CONNECTED = "suite::v2::remote_control::connected_backend_handles_models_lookup_before_websocket_initialize"
HTTP_NEGATIVE = "suite::v2::remote_control::models_http_request_is_not_a_websocket_upgrade"
STDIO = "suite::v2::remote_control::stdio_eof_exits_with_remote_control_connection"
EOF = "suite::v2::remote_control::http_fixture_rejects_eof_before_request_headers_complete"
SAME_ERROR = 'Error: WebSocket protocol error: No "Connection: upgrade" header'


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def load(path):
    return json.loads(path.read_bytes())


def unwrap(value):
    assert not value.get("isError", False)
    if isinstance(value.get("structuredContent"), dict):
        return value["structuredContent"]
    return json.loads(next(row["text"] for row in value["content"] if row["type"] == "text"))


def git_tree(leaves):
    root = {}
    for path, row in leaves.items():
        current = root
        parts = path.split("/")
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        assert parts[-1] not in current
        current[parts[-1]] = (row["mode"].lstrip("0"), row["sha"])

    def digest(directory):
        entries = []
        for name, value in directory.items():
            if isinstance(value, dict):
                mode, sha, key = "40000", digest(value), name.encode() + b"/"
            else:
                mode, sha = value
                key = name.encode()
            entries.append((key, mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(sha)))
        raw = b"".join(value for _, value in sorted(entries))
        return hashlib.sha1(b"tree " + str(len(raw)).encode() + b"\0" + raw).hexdigest()

    return digest(root)


def function(source, name):
    """Extract a Rust fn, handling quoted/raw strings and comments in these files."""
    match = re.search(r"\b(?:async\s+)?fn\s+" + re.escape(name) + r"\s*\(", source)
    assert match, name
    start = source.index("{", match.end())
    level = 0
    pos = start
    while pos < len(source):
        if source.startswith("//", pos):
            end = source.find("\n", pos)
            pos = len(source) if end < 0 else end + 1
            continue
        if source.startswith("/*", pos):
            comments = 1
            pos += 2
            while comments:
                assert pos < len(source)
                if source.startswith("/*", pos):
                    comments += 1
                    pos += 2
                elif source.startswith("*/", pos):
                    comments -= 1
                    pos += 2
                else:
                    pos += 1
            continue
        raw = re.match(r'(?:b)?r(#{0,16})"', source[pos:])
        if raw:
            closing = '"' + raw.group(1)
            end = source.find(closing, pos + raw.end())
            assert end >= 0
            pos = end + len(closing)
            continue
        if source[pos] == '"':
            pos += 1
            while pos < len(source):
                if source[pos] == "\\":
                    pos += 2
                elif source[pos] == '"':
                    pos += 1
                    break
                else:
                    pos += 1
            continue
        character = re.match(r"'(?:\\.|[^'\\])'", source[pos:])
        if character:
            pos += character.end()
            continue
        if source[pos] == "{":
            level += 1
        elif source[pos] == "}":
            level -= 1
            if level == 0:
                return source[match.start():pos + 1]
        pos += 1
    raise AssertionError("unclosed function " + name)


def native_custody(root):
    rows = []
    for name in ["original-app-statuses.read-multiple.original-tool-response.json", "original-app-xml-manifests.read-multiple.original-tool-response.json", "original-app-extra-statuses.read-multiple.original-tool-response.json"]:
        response = unwrap(load(root / name))
        assert response["truncated"] is False
        for row in response["files"]:
            raw = row["text"].encode("utf-8")
            assert row["eof"] and len(raw) == row["size"] and identity(raw)["sha256"] == row["sha256"]
            assert raw == (root / "originals" / Path(row["path"]).name).read_bytes()
            rows.append({"retrieval": name, "native_path": row["path"], "native_version": row["version"], **identity(raw)})
    for name in ["app-remote-original-negative.log", "app-remote-fixed-originals.log"]:
        response = unwrap(load(root / f"{name}.binary-read.original-tool-response.json"))
        metadata = unwrap(load(root / f"{name}.file-info.original-tool-response.json"))
        raw = base64.b64decode(response["data_base64"], validate=True)
        assert response["offset"] == 0 and response["eof"] and response["next_offset"] == len(raw) == response["size"] == metadata["size"]
        assert response["version"] == metadata["version"]
        assert identity(raw)["sha256"] == response["chunk_sha256"] == metadata["sha256"]
        assert raw == (root / "originals" / name).read_bytes()
        rows.append({"retrieval": f"{name}.binary-read.original-tool-response.json", "native_path": response["path"], "native_version": response["version"], **identity(raw)})
    patch_metadata = unwrap(load(root / "app-remote-regression-only-after-e729.patch.file-info.original-tool-response.json"))
    raw = b""
    for offset in [0, 65536]:
        response = unwrap(load(root / f"negative-fullpatch-{offset}.binary-read.original-tool-response.json"))
        part = base64.b64decode(response["data_base64"], validate=True)
        assert response["offset"] == offset == len(raw)
        assert response["version"] == patch_metadata["version"] and response["size"] == patch_metadata["size"]
        assert identity(part)["sha256"] == response["chunk_sha256"]
        raw += part
        assert response["next_offset"] == len(raw)
    assert response["eof"] and len(raw) == patch_metadata["size"]
    assert identity(raw)["sha256"] == patch_metadata["sha256"]
    assert raw == (root / "originals/app-remote-regression-only-after-e729.patch").read_bytes()
    rows.append({"native_path": patch_metadata["path"], "native_version": patch_metadata["version"], "complete_chunks": 2, **identity(raw)})
    stdout = b""
    status = unwrap(load(root / "known-hygiene-desktop-status.original-tool-response.json"))
    assert status["job_id"] == "1a1a774e5e5-fc05-2b81" and status["state"] == "succeeded" and status["exit_code"] == 0 and status["output_complete"]
    for offset in [0, 16384]:
        response = unwrap(load(root / f"known-hygiene-read-{offset}.original-tool-response.json"))
        assert response["job_id"] == status["job_id"]
        row = response["stdout"]
        part = bytes.fromhex(row["bytes_hex"])
        assert row["offset"] == offset == len(stdout) and part == row["text"].encode()
        stdout += part
        assert row["next_offset"] == len(stdout)
        assert response["stderr"]["size"] == 0
    assert row["eof"] and len(stdout) == row["size"] == 27701 and stdout == (root / "known-hygiene.stdout").read_bytes()
    return {"pinned_original_files": rows, "known_hygiene_job": {"job_id": status["job_id"], "full_stdout": identity(stdout), "role": "Existing owned hygiene job identifies the prior worktree context; it is not relabeled as the negative/fixed test process."}, "read_multiple_atomic_snapshot": False}


def verify_native_result(root, prefix, expected_count, expected_failures):
    status = load(root / f"originals/{prefix}-status.json")
    xml_bytes = (root / f"originals/{prefix}.junit.xml").read_bytes()
    log_bytes = (root / f"originals/{prefix}.log").read_bytes()
    xml = ET.fromstring(xml_bytes)
    assert identity(xml_bytes)["sha256"] == status["junit_sha256"]
    assert xml.attrib == status["junit_attributes"]
    cases = list(xml.iter("testcase"))
    assert len(cases) == expected_count and int(xml.attrib["failures"]) == expected_failures and int(xml.attrib["errors"]) == 0
    assert status["exit_code"] == (100 if expected_failures else 0)
    cmd = status["command"]
    assert cmd[:9] == ["just", "test", "--locked", "--offline", "-p", "codex-app-server", "--test", "all", "-E"]
    assert cmd[-6:] == ["--no-tests", "fail", "--retries", "0", "--test-threads", "4"]
    assert status["source_unchanged"] and status["selection_complete"] and not status["missing_filters"]
    log = log_bytes.decode()
    summary_start = log.index("     Summary [")
    executed = []
    for match in re.finditer(r"^\s*(PASS|FAIL|TIMEOUT|LEAK|SKIP)\s+\[([^\]]+)\]\s+\(\s*\d+/\d+\) codex-app-server::all (\S+)\s*$", log[:summary_start], re.M):
        executed.append({"name": match.group(3), "result": match.group(1), "duration": match.group(2).strip()})
    assert len(executed) == expected_count and len({r["name"] for r in executed}) == expected_count
    raw_map = {r["name"]: r for r in executed}
    status_map = {r["name"]: r for r in status["testcases"]}
    assert set(raw_map) == set(status_map) == {c.get("name") for c in cases}
    rows = []
    for case in cases:
        name = case.get("name")
        assert case.get("classname") == "codex-app-server::all"
        assert not any(x.tag in ["skipped", "error", "rerunFailure", "rerunError", "flakyFailure", "flakyError"] for x in case)
        failed = case.find("failure") is not None
        assert status_map[name]["failed"] == failed and not status_map[name]["skipped"]
        assert raw_map[name]["result"] == ("FAIL" if failed else "PASS")
        rows.append({"name": name, "result": raw_map[name]["result"], "junit_attributes": case.attrib, "failure": case.find("failure").attrib if failed else None})
    if expected_failures:
        assert set(raw_map) == {CONNECTED, HTTP_NEGATIVE}
        failure = next(c.find("failure") for c in cases if c.get("name") == CONNECTED)
        assert failure.get("message") == SAME_ERROR and failure.text == SAME_ERROR
        assert SAME_ERROR in log
        assert "1 passed, 1 failed, 1016 skipped" in log
    else:
        assert all(row["result"] == "PASS" for row in rows)
        assert {CONNECTED, HTTP_NEGATIVE, STDIO, EOF} <= set(raw_map)
        assert "19 tests run: 19 passed, 1000 skipped" in log
    return {"command": cmd, "source_tree": status["source_tree"], "source_stage": status["source_stage"], "started_unix": status["started_unix"], "exit_code": status["exit_code"], "total_elapsed_seconds_including_compile": status["elapsed_seconds"], "junit_test_duration_seconds": float(xml.get("time")), "raw": identity(log_bytes), "junit": identity(xml_bytes), "cases": rows, "selection_exclusions_are_filtered_not_ignored": 1016 if expected_failures else 1000, "selected_ignored_or_early_return": 0}


def source_proof(root):
    base_data = load(root / "source-api/base-e729-full-leaves.json")
    base = {v["path"]: v for v in base_data["leaves"]}
    assert base_data["truncated"] is False
    assert git_tree(base) == base_data["actual_tree"] == "6790800b883d3655538869ea90f17c5ff86b7507"
    trees, old_maps = {}, {}
    for stage, name, expected in [("negative", "app-remote-regression-only-manifest.json", NEG_TREE), ("fixed", "app-remote-final-manifest.json", FIX_TREE)]:
        manifest = load(root / "originals" / name)
        assert manifest["base_tree"] == base_data["actual_tree"]
        leaves = dict(base)
        assert len(manifest["files"]) == 47
        for row in manifest["files"]:
            assert row["path"] in leaves
            leaves[row["path"]] = {**base[row["path"]], "sha": row["git_blob"], "size": row["bytes"]}
        assert git_tree(leaves) == manifest["source_tree"] == expected
        trees[stage] = {"tree": expected, "leaves": len(leaves), "all_original_manifest_leaves_applied": 47}
        old_maps[stage] = leaves
    differences = [path for path in base if old_maps["negative"][path]["sha"] != old_maps["fixed"][path]["sha"]]
    assert differences == [TARGET]
    neg = (root / "derived/remote_control.negative.reconstructed.source.txt").read_bytes()
    fixed = (root / "originals/remote_control.fixed.source.txt").read_bytes()
    before = (root / "derived/remote_control.base-e729.source.txt").read_bytes()
    assert identity(neg)["git_blob"] == NEGATIVE and identity(fixed)["git_blob"] == FIXED
    assert identity(before)["git_blob"] == base[TARGET]["sha"]
    original_patch = (root / "originals/app-remote-regression-only-after-e729.patch").read_bytes()
    header = f"diff --git a/{TARGET} b/{TARGET}\n".encode()
    position = original_patch.index(header)
    end = original_patch.find(b"\ndiff --git ", position + len(header))
    extracted = original_patch[position:] if end < 0 else original_patch[position:end + 1]
    assert extracted == (root / "derived/remote_control.negative-extracted.patch").read_bytes()
    git_steps = []
    with tempfile.TemporaryDirectory(prefix="b20-source-reconstruction-") as directory:
        directory = Path(directory)
        path = directory / TARGET
        path.parent.mkdir(parents=True)
        path.write_bytes(before)
        for arguments in [["init", "-q"], ["apply", "--check", str((root / "derived/remote_control.negative-extracted.patch").resolve())], ["apply", str((root / "derived/remote_control.negative-extracted.patch").resolve())]]:
            result = subprocess.run(["git", *arguments], cwd=directory, capture_output=True, text=True)
            assert result.returncode == 0, result.stderr
            git_steps.append({"argv": ["git", *arguments], "exit_code": result.returncode})
        assert path.read_bytes() == neg
        for arguments in [["apply", "--reverse", "--check", str((root / "derived/remote_control.negative-extracted.patch").resolve())], ["apply", "--reverse", str((root / "derived/remote_control.negative-extracted.patch").resolve())]]:
            result = subprocess.run(["git", *arguments], cwd=directory, capture_output=True, text=True)
            assert result.returncode == 0, result.stderr
            git_steps.append({"argv": ["git", *arguments], "exit_code": result.returncode})
        assert path.read_bytes() == before
    negative_direct = load(root / f"source-{NEGATIVE}.github-original-response.json")
    assert negative_direct.get("isError") and "404" in json.dumps(negative_direct)
    fixed_api = unwrap(load(root / f"source-{FIXED}.github-original-response.json"))
    assert fixed_api["content"].encode() == fixed
    assert identity(fixed_api["content"].encode())["git_blob"] == FIXED
    base_api = unwrap(load(root / "base-remote-control-e729.github-original-response.json"))
    assert base_api["content"].encode() == before

    source = fixed.decode()
    names = re.findall(r"#\[tokio::test\]\s*(?:#\[serial\]\s*)?async fn\s+(\w+)\s*\(", source)
    old_names = re.findall(r"#\[tokio::test\]\s*(?:#\[serial\]\s*)?async fn\s+(\w+)\s*\(", neg.decode())
    assert len(names) == 19 and len(old_names) == 18
    assert set(names) - set(old_names) == {EOF.rsplit("::", 1)[-1]}
    assert all(function(source, name) == function(neg.decode(), name) for name in old_names)
    assert function(source, STDIO.rsplit("::", 1)[-1]) == function(before.decode(), STDIO.rsplit("::", 1)[-1])
    for name in names:
        body = function(source, name)
        assert not re.search(r"return\s+Ok\s*\(|skip_if_|\bignore\s*=", body), name
    assert "#[ignore" not in source
    for raw_source in [before.decode(), neg.decode(), source]:
        assert "const DEFAULT_TIMEOUT: Duration = Duration::from_secs(10);" in raw_source
        assert "const STARTUP_TIMEOUT: Duration = Duration::from_secs(30);" in raw_source

    current_maps = {}
    current_roots = {}
    for label in ["5b", "e78", "eed"]:
        original = load(root / "source-trees" / f"{label}-leaves.json")
        leaves = {row["path"]: row for row in original["leaves"]}
        assert len(leaves) == original["leaf_count"] and git_tree(leaves) == original["tree"]
        assert leaves[TARGET]["sha"] == FIXED
        current_maps[label] = leaves
        current_roots[label] = {"tree": original["tree"], "leaves": len(leaves), "complete_Git_Merkle_recomputed": True}
    main = load(root / "source-trees/67cc-intended-full-tree.json")
    main_actual = load(root / "source-trees/67cc-actual-tree-root.json")["response"]
    main_leaves = {row["path"]: row for row in main["tree"] if row["type"] != "tree"}
    assert git_tree(main_leaves) == main["sha"] == main_actual["sha"] == "3982ba56dc5a3f1da0c1de7ea57992f88125c359"
    assert main_leaves[TARGET]["sha"] == FIXED
    current_maps["67cc"] = main_leaves
    current_roots["67cc"] = {"commit": "67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed", "tree": main["sha"], "leaves": len(main_leaves), "complete_Git_Merkle_recomputed": True, "custody": "Root's full intended leaf tree recomputes to the actually fetched Git root. It is not mislabeled as a recursive Git GET."}
    relevant = load(root / "derived/dependency-source-identity-rows.json")
    complete_files = []
    for row in relevant:
        path = row["path"]
        basename = path.replace("/", "__") + ".source.txt"
        old_bytes = (root / "sources" / ("base-" + basename)).read_bytes()
        current_bytes = (root / "sources" / ("current-" + basename)).read_bytes()
        assert identity(old_bytes) == row["base"] and identity(current_bytes) == row["current"]
        assert identity(old_bytes)["git_blob"] == base[path]["sha"] == old_maps["negative"][path]["sha"] == old_maps["fixed"][path]["sha"]
        assert all(leaves[path]["sha"] == identity(current_bytes)["git_blob"] for leaves in current_maps.values())
        api = unwrap(load(root / "source-api" / ("base-" + path.replace("/", "__") + ".json"))["result"])
        assert api["content"].encode() == old_bytes
        complete_files.append({"path": path, "old": identity(old_bytes), "5b_e78_eed": identity(current_bytes), "full_bytes_equal": old_bytes == current_bytes})
    for file in sorted((root / "sources").glob("shared-*.source.txt")):
        path = file.name.removeprefix("shared-").removesuffix(".source.txt").replace("__", "/")
        raw = file.read_bytes()
        blob = identity(raw)["git_blob"]
        assert base[path]["sha"] == old_maps["negative"][path]["sha"] == old_maps["fixed"][path]["sha"] == blob
        assert all(leaves[path]["sha"] == blob for leaves in current_maps.values())
        api = unwrap(load(root / "source-api" / ("shared-" + path.replace("/", "__") + ".json"))["result"])
        assert api["content"].encode() == raw
        assert load(root / "source-api" / ("shared-" + path.replace("/", "__") + ".json"))["request"]["blob_sha"] == blob
        complete_files.append({"path": path, "old_and_5b_e78_eed": identity(raw), "full_bytes_equal": True})
    unchanged_subtrees = []
    for prefix in ["codex-rs/app-server-transport/", "codex-rs/app-server-protocol/", "codex-rs/state/", "codex-rs/utils/cargo-bin/", "codex-rs/app-server/tests/common/"]:
        paths = {path for path in base if path.startswith(prefix)}
        for leaves in current_maps.values():
            assert paths == {path for path in leaves if path.startswith(prefix)}
            assert all(base[path]["sha"] == leaves[path]["sha"] and base[path]["mode"] == leaves[path]["mode"] for path in paths)
        unchanged_subtrees.append({"prefix": prefix, "entire_subtree_unchanged_leaf_count": len(paths)})
    app_paths = {path for path in current_maps["eed"] if path.startswith("codex-rs/app-server/")}
    assert all({path for path in leaves if path.startswith("codex-rs/app-server/")} == app_paths for leaves in current_maps.values())
    assert all(all(leaves[path]["sha"] == current_maps["eed"][path]["sha"] for path in app_paths) for leaves in current_maps.values())
    old_lib = (root / "sources/base-codex-rs__app-server__src__lib.rs.source.txt").read_text()
    current_lib = (root / "sources/current-codex-rs__app-server__src__lib.rs.source.txt").read_text()
    stdio_branch = lambda text: text[text.index("TransportEvent::ConnectionClosed { connection_id } => {"):text.index("TransportEvent::IncomingMessage { connection_id, message } => {")]
    assert stdio_branch(old_lib) == stdio_branch(current_lib)
    assert "let single_client_mode = matches!(&transport, AppServerTransport::Stdio);" in old_lib and "let single_client_mode = matches!(&transport, AppServerTransport::Stdio);" in current_lib
    assert "runtime_options.install_shutdown_signal_handler && !single_client_mode;" in old_lib and "runtime_options.install_shutdown_signal_handler && !single_client_mode;" in current_lib
    builder = (root / "sources/base-codex-rs__app-server__tests__common__test_app_server.rs.source.txt").read_text()
    assert "drop(self.stdin.take());\n        self.process.wait().await" in function(builder, "shutdown_gracefully")
    assert 'cargo_bin("codex-app-server")' in builder and "let mut cmd = Command::new(program);" in builder
    return {"old_source_trees": trees, "old_whole_source_only_difference": differences, "negative_source": identity(neg), "fixed_source": identity(fixed), "negative_recovery": "Direct GET returned 404. Exact local reconstruction from actual e729 source plus exact original negative patch; reconstructed bytes match original negative manifest. Not relabeled as original Git GET.", "negative_reconstruction_steps": git_steps, "old18_test_function_bodies_unchanged": old_names, "original_stdio_function_unchanged_from_base": True, "new_EOF_test": EOF, "original_10s_and_30s_budgets_unchanged": True, "selected_tests_have_no_skip_macros_or_early_Ok_return": True, "current_complete_roots": current_roots, "complete_source_files": complete_files, "unchanged_subtrees": unchanged_subtrees, "app_server_subtree_5b_e78_eed_equal": {"leaf_count": len(app_paths)}, "production_lib_exception": {"old_blob": identity(old_lib.encode())["git_blob"], "current_blob": identity(current_lib.encode())["git_blob"], "exact_diff": "derived/bridge-codex-rs__app-server__src__lib.rs.patch", "classification": "B23 signal subscription implementation changed, so whole lib/binary is not byte identical to old GNU. Original stdio ConnectionClosed handling is byte identical; signal path is disabled for Stdio by the unchanged !single_client_mode guard. Listen-off signal branch is not claimed identical.", "current_Windows_bridge": "Entire app-server subtree including changed lib is identical across 5b/e78/eed; separate original 5b Windows target evidence is retained."}}


def windows_proof(root, upstream_zip):
    data = load(root / "windows/original-selection-and-execution-verification.json")
    loader = importlib.machinery.SourceFileLoader("b20_archived_parser", str(root / "windows/upstream-b10-project-originals.py.source.txt"))
    parser = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(parser)
    primary = (root / "windows/bazel-9.3.0-spawn.proto.source.txt").read_bytes()
    assert identity(primary)["git_blob"] == data["primary_schema_git_blob"] == "19f68f22a4d62c4fd1aa28fd1c7c0217aa6a7cb0"
    primary_api = unwrap(load(root / "windows/bazel-9.3.0-spawn-proto-GitHub-original-response.json"))
    assert primary_api["content"].encode() == primary
    for row in data["wrappers"]:
        raw = (root / "windows" / row["raw"]).read_bytes()
        wrapper = (root / "windows" / row["wrapper"]).read_bytes()
        assert identity(raw) == {k: row[k] for k in ["bytes", "sha256", "git_blob"]}
        assert identity(wrapper) == row["wrapper_identity"]
        content = ET.fromstring(wrapper).find(".//system-out").text
        assert content == raw.decode().replace("\x1b", "?")
        assert row["ESC_byte_offsets"] == [i for i, byte in enumerate(raw) if byte == 27]
    for name, rows in data["selected_19_final_rows"].items():
        assert len(rows) == 1 and rows[0]["result"] == "ok"
        lines = (root / "windows/zip-members" / rows[0]["member"]).read_text().splitlines()
        assert lines[rows[0]["line"] - 1] == rows[0]["physical_line"] == f"test {name} ... ok"
    for row in data["selected_actions"]:
        frame = (root / "windows" / row["frame"]).read_bytes()
        assert identity(frame) == row["frame_identity"]
        size, pos = parser.varint(frame, 0)
        assert pos + size == len(frame)
        fields = parser.fields(frame[pos:])
        spawn = parser.fields(parser.first(fields, 7))
        assert parser.first(spawn, 7) == b"//codex-rs/app-server:app-server-all-test"
        assert parser.first(spawn, 8) == b"TestRunner"
        assert [value.decode() for value in spawn.get(1, [])] == row["args"]
        assert parser.first(spawn, 9, 0) == row["exit_code"]
        assert parser.first(spawn, 11).decode() == row["runner"] and bool(parser.first(spawn, 12, 0)) == row["cache_hit"]
        assert parser.first(spawn, 17, 0) == row["timeout_millis"]
        env = {parser.first(parser.fields(v), 1).decode(): parser.first(parser.fields(v), 2).decode() for v in spawn.get(2, [])}
        assert sorted(env) == row["environment_keys"]
        assert not any(k.upper() == "CODEX_SANDBOX_NETWORK_DISABLED" for k in env)
        if row["role"] == "actual_test_action":
            assert row["runner"] == "local" and not row["cache_hit"] and row["exit_code"] == 0 and row["timeout_millis"] == 900000
    if upstream_zip is not None:
        import zstandard
        assert identity(upstream_zip.read_bytes()) == data["original_zip"]
        with zipfile.ZipFile(upstream_zip) as z:
            assert z.testzip() is None and len(z.infolist()) == len(data["members"]) == 54
            for row in data["members"]:
                assert identity(z.read(row["member"])) == {k: row[k] for k in ["bytes", "sha256", "git_blob"]}
                assert f"{z.getinfo(row['member']).CRC:08x}" == row["crc32"]
            compressed = z.read(data["compressed_execution_log"]["member"])
        decoder = zstandard.ZstdDecompressor().decompressobj()
        compact = decoder.decompress(compressed) + decoder.flush()
        assert decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail
        assert identity(compact) == data["decompressed_execution_log"]
        position = count = 0
        selected = []
        while position < len(compact):
            start = position
            size, position = parser.varint(compact, position)
            assert position + size <= len(compact)
            fields = parser.fields(compact[position:position + size])
            position += size
            count += 1
            if 7 in fields:
                spawn = parser.fields(parser.first(fields, 7))
                if parser.first(spawn, 7) == b"//codex-rs/app-server:app-server-all-test" and parser.first(spawn, 8) == b"TestRunner":
                    selected.append((count, start, position, compact[start:position]))
        assert position == len(compact) == data["all_bytes_consumed"]
        assert count == data["complete_entries"] == 87246 and len(selected) == 32
        for actual, row in zip(selected, data["selected_actions"]):
            assert actual[:3] == (row["entry_number"], row["start_byte"], row["end_byte"])
            assert actual[3] == (root / "windows" / row["frame"]).read_bytes()
    return {"job_id": data["job_id"], "artifact_id": data["artifact_id"], "checkout_merge": data["checkout_merge"], "final_original_names": 19, "full_raw_and_XML_pairs": 16, "literal_raw_XML_equal_pairs": sum(row["entire_raw_equals_wrapper_system_out"] for row in data["wrappers"]), "only_ESC_to_question_mark_count": sum(row["ESC_character_count"] for row in data["wrappers"]), "actual_test_actions": 16, "wrapper_xml_actions": 16, "all_original_actions_local_noncache_exit0": True, "original_timeout_millis": 900000, "complete_upstream_ZIP_and_compact_reopened_this_verifier_run": upstream_zip is not None, "upstream_complete_entries": data["complete_entries"], "target_terminal_original_line": data["target_terminal_original_line"], "whole_job_pass": False}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    ap.add_argument("--windows-zip", type=Path)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    root = args.root.resolve()
    custody = native_custody(root)
    negative = verify_native_result(root, "app-remote-original-negative", 2, 1)
    fixed = verify_native_result(root, "app-remote-fixed-originals", 19, 0)
    assert negative["source_tree"] == NEG_TREE and fixed["source_tree"] == FIX_TREE
    source = source_proof(root)
    assert {case["name"].rsplit("::", 1)[-1] for case in fixed["cases"]} == set(source["old18_test_function_bodies_unchanged"]) | {EOF.rsplit("::", 1)[-1]}
    windows = windows_proof(root, args.windows_zip)
    host = load(root / "originals/native-host-toolchain-receipt.json")
    assert host["configured_host"] == "desktop" and "host: x86_64-unknown-linux-gnu" in host["rustc_vV"]
    assert host["source_tree"] == load(root / "originals/app-remote-regression-only-manifest.json")["previous_source_tree"]
    result = {"schema": "b20-original-exit-independent-verification-v1", "original_exit_condition_zh": "确定性旧源同握手错误、新源对照及原真实AppServer关闭/断连断言全部通过。", "evidence_action": "READ_ONLY_EXISTING_ORIGINALS_AND_ISOLATED_SOURCE_PATCH_CHECK", "native_custody": custody, "negative": negative, "fixed": fixed, "source": source, "windows_supplement": windows, "host_receipt": host, "recommendation": "ORIGINAL_B20_EXIT_EVIDENCE_SATISFIED_PENDING_ROOT_REVIEW", "native_execution_started": False, "source_ref_modified": False, "blocker_ledger_modified": False, "whole_candidate_qualified": False, "platform_limits": ["Original historical 48-case GNU/musl platform rows are retained, not relabeled by Windows evidence.", "This is the recovered original GNU causal contrast and original 19-case behavior scope plus separate 5b Windows supplement; no current-head full workspace pass.", "B23 current lib differs in signal registration; original stdio branch and its disabled signal guard remain byte identical. Final Unix signal CI remains separate.", "Original fixed GNU successful cases have PASS rows and JUnit but no --success-output immediate; complete case source has no skip macros/early Ok returns. Do not invent successful-case captured stdout."]}
    encoded = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.exists():
            assert args.output.read_bytes() == encoded, "frozen verifier output differs"
        else:
            args.output.write_bytes(encoded)
    print(json.dumps({"verified": True, "negative": "1 PASS / 1 FAIL exact original handshake error", "fixed": "19 PASS / 0 skipped", "windows": "19 original names, 16 local noncache TestRunner actions", "old_complete_trees_recomputed": 3, "current_complete_trees_recomputed": 4, "output": str(args.output) if args.output else None, "output_identity": identity(encoded)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
