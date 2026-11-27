#!/usr/bin/env python3
"""Data-only collector for one new Windows credential candidate and exact nine cases."""

import hashlib
import json
import math
import os
from pathlib import Path
import re
import tomllib

PACKAGE = "codex-windows-sandbox"
LIBRARY = "codex_windows_sandbox"
HELPERS = ("codex-windows-sandbox-setup", "codex-command-runner")
TESTS = (
    "token::tests::workspace_capabilities_deny_writes_and_deletes_under_broad_identity_aces",
    "unified_exec::tests::acl_setup_tests::elevated_capture_rejects_deny_acl_setup_failure_before_spawn",
    "unified_exec::tests::acl_setup_tests::elevated_session_rejects_deny_acl_setup_failure_before_spawn",
    "unified_exec::tests::elevated_non_tty_cmd_forwards_env_output_and_exit",
    "unified_exec::tests::elevated_non_tty_cmd_emits_output",
    "unified_exec::tests::elevated_non_tty_cmd_enforces_deny_read_overrides",
    "unified_exec::tests::elevated_workspace_write_delete_is_limited_to_writable_roots",
    "token::tests::workspace_capability_delete_routes_require_the_capability_in_all_four_cells",
    "unified_exec::tests::delete_permission_tests::elevated_delete_routes_require_workspace_capability_in_all_four_cells",
)
UNIT_INVENTORY_ONLY = (
    "identity::tests::failed_login_revalidation_preserves_existing_credential_bytes",
    "identity::tests::failed_login_revalidation_does_not_create_missing_credentials",
    "elevated::runner_client::tests::rejected_revalidation_keeps_initial_native_failure_and_never_spawns_again",
    "elevated::runner_client::tests::failed_single_retry_keeps_both_native_failures_without_third_attempt",
)


class CollectionFailure(ValueError):
    pass


def need(value, message):
    if not value:
        raise CollectionFailure(message)


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def parse_json(raw):
    need(isinstance(raw, bytes), "collector requires retained original bytes")
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=no_duplicates,
        parse_constant=lambda value: (_ for _ in ()).throw(
            CollectionFailure("nonfinite JSON value: " + value)
        ),
    )


def same_path(left, right):
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(
        os.path.abspath(right)
    )


def beneath(child, root):
    left, right = (
        os.path.normcase(os.path.abspath(child)),
        os.path.normcase(os.path.abspath(root)),
    )
    return os.path.commonpath((left, right)) == right and left != right


def metadata(raw, workspace, fresh_target):
    value = parse_json(raw)
    need(value.get("version") == 1, "complete Cargo metadata version")
    need(same_path(value.get("workspace_root", ""), workspace), "actual workspace")
    need(same_path(value.get("target_directory", ""), fresh_target), "fresh target")
    packages = value.get("packages")
    need(isinstance(packages, list) and 0 < len(packages) <= 20000, "package bound")
    by_id = {item["id"]: item for item in packages}
    need(len(by_id) == len(packages), "duplicate complete package identity")
    selected = [item for item in packages if item.get("name") == PACKAGE]
    need(len(selected) == 1, "one exact owning package")
    package = selected[0]
    need(package["id"] in value.get("workspace_members", []), "workspace member")
    need(
        same_path(
            package.get("manifest_path", ""),
            Path(workspace) / "windows-sandbox-rs/Cargo.toml",
        ),
        "owning manifest",
    )
    targets = package.get("targets", [])
    wanted = {
        LIBRARY: ("lib", "src/lib.rs"),
        HELPERS[0]: ("bin", "src/bin/setup_main/main.rs"),
        HELPERS[1]: ("bin", "src/bin/command_runner/main.rs"),
    }
    for name, (kind, path) in wanted.items():
        matches = [item for item in targets if item.get("name") == name]
        need(len(matches) == 1, "target declaration: " + name)
        target = matches[0]
        need(
            target.get("kind") == [kind] and target.get("edition") == "2024",
            "target kind/edition: " + name,
        )
        need(
            same_path(
                target.get("src_path", ""),
                Path(workspace) / "windows-sandbox-rs" / path,
            ),
            "target original source: " + name,
        )
        if name == LIBRARY:
            need(target.get("test") is True, "native library test harness disabled")
    resolve = value.get("resolve")
    need(isinstance(resolve, dict), "complete locked resolve graph")
    nodes = resolve.get("nodes")
    need(isinstance(nodes, list) and 0 < len(nodes) <= 20000, "resolve node bound")
    by_node = {item["id"]: item for item in nodes}
    need(
        len(by_node) == len(nodes) and set(by_node) <= set(by_id),
        "resolve node identities",
    )
    pending, reachable = [package["id"]], set()
    while pending:
        identity = pending.pop()
        if identity in reachable:
            continue
        need(identity in by_node, "missing reachable resolve node")
        reachable.add(identity)
        node = by_node[identity]
        edges = node.get("deps")
        need(isinstance(edges, list), "complete typed dependency edges")
        edge_ids = [edge["pkg"] for edge in edges]
        need(
            set(edge_ids) == set(node.get("dependencies", [])),
            "typed/untyped dependency edge disagreement",
        )
        need(all(dep in by_node for dep in edge_ids), "unresolved dependency edge")
        pending.extend(edge_ids)
    return value, package, [by_id[item] for item in sorted(reachable)]


def compiler_artifacts(raw, package, workspace, fresh_target, *, helpers):
    need(
        isinstance(raw, bytes) and raw.endswith(b"\n"),
        "complete original compiler JSON",
    )
    rows = [parse_json(line) for line in raw.splitlines() if line]
    need(rows and len(rows) <= 100000, "bounded compiler JSON rows")
    finished = [row for row in rows if row.get("reason") == "build-finished"]
    need(
        len(finished) == 1
        and finished[0].get("success") is True
        and rows[-1] is finished[0],
        "one final successful build-finished",
    )
    expected = set(HELPERS) if helpers else {LIBRARY}
    selected = {}
    for row in rows:
        reason = row.get("reason")
        need(
            reason
            in (
                "compiler-artifact",
                "compiler-message",
                "build-script-executed",
                "build-finished",
            ),
            "unknown compiler JSON message",
        )
        if reason == "compiler-message":
            need(
                row.get("message", {}).get("level") != "error",
                "compiler error retained",
            )
        if reason != "compiler-artifact" or row.get("package_id") != package["id"]:
            continue
        executable = row.get("executable")
        target = row.get("target", {})
        name = target.get("name")
        if executable is None:
            continue
        need(
            name in expected and name not in selected,
            "unexpected/duplicate owning executable",
        )
        need(
            same_path(
                row.get("manifest_path", ""),
                Path(workspace) / "windows-sandbox-rs/Cargo.toml",
            ),
            "compiler owning manifest",
        )
        need(
            target.get("kind") == (["bin"] if helpers else ["lib"]),
            "compiler target kind",
        )
        need(
            row.get("profile", {}).get("test") is (not helpers),
            "binary/test profile identity",
        )
        need(target.get("edition") == "2024", "compiled target edition")
        need(
            beneath(executable, fresh_target)
            and Path(executable).suffix.lower() == ".exe",
            "compiler executable escaped the fresh target",
        )
        need(
            any(same_path(executable, path) for path in row.get("filenames", [])),
            "executable not in the original compiler output set",
        )
        selected[name] = row
    need(set(selected) == expected, "complete requested compiler artifact roster")
    return selected


def libtest_inventory(all_raw, ignored_raw):
    # rust-lang/rust@1.96.0 TerseFormatter writes only "name: test/benchmark".
    # It emits no ignored bit or final count; a separate --ignored list under the
    # same90-second inventory deadline binds that property without running bodies.
    def names(raw, label):
        need(
            isinstance(raw, bytes) and (not raw or raw.endswith(b"\n")),
            "complete original libtest list: " + label,
        )
        text = raw.decode("utf-8")
        need("\x1b" not in text and "\0" not in text, "escaped list content")
        result = {}
        for line in text.splitlines():
            match = re.fullmatch(
                r"([A-Za-z0-9_][A-Za-z0-9_:<>., /()=+-]*): (test|benchmark)", line
            )
            need(match is not None, "unrecognized original libtest list line: " + label)
            name, kind = match.groups()
            need(name not in result, "duplicate libtest identity: " + name)
            result[name] = kind
        need(len(result) <= 10000, "native inventory bound")
        return result

    complete, ignored = names(all_raw, "all"), names(ignored_raw, "ignored")
    need(
        complete and set(ignored) <= set(complete), "ignored inventory is not a subset"
    )
    need(
        all(complete[name] == kind for name, kind in ignored.items()),
        "ignored kind drift",
    )
    for name in TESTS + UNIT_INVENTORY_ONLY:
        need(
            complete.get(name) == "test" and name not in ignored,
            "missing/benchmark/ignored required test: " + name,
        )
    return {
        "complete_original_test_count": sum(
            kind == "test" for kind in complete.values()
        ),
        "complete_original_benchmark_count": sum(
            kind == "benchmark" for kind in complete.values()
        ),
        "all_names_and_kinds": complete,
        "ignored_names_and_kinds": ignored,
        "exact_nine": list(TESTS),
        "unit_controls_inventoried_not_executed": list(UNIT_INVENTORY_ONLY),
        "selected_count": 9,
        "selected_ignored": 0,
        "ConPTY_selected": 0,
        "old167_or19_execution_authorized": False,
    }


def compiler_identity(rustc_raw, cargo_raw):
    def record(raw, name):
        text = raw.decode("utf-8")
        need(
            text.endswith("\n") and "\x1b" not in text and "\0" not in text,
            "complete native version text: " + name,
        )
        lines = text.splitlines()
        need(lines and lines[0].startswith(name + " "), "native tool version name")
        fields = {}
        for line in lines[1:]:
            if ": " in line and not line.startswith(" "):
                key, value = line.split(": ", 1)
                need(key not in fields, "duplicate native version field")
                fields[key] = value
        need(fields.get("host") == "x86_64-pc-windows-msvc", "native compiler host")
        return {
            "first_line": lines[0],
            "fields": fields,
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
        }

    rustc, cargo = record(rustc_raw, "rustc"), record(cargo_raw, "cargo")
    need(rustc["fields"].get("release") == "1.96.0", "actual Rust release mismatch")
    need(
        re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", cargo["fields"].get("release", "")),
        "actual Cargo release missing",
    )
    return {
        "rustc": rustc,
        "cargo": cargo,
        "same_explicit_toolchain_bin_required": True,
        "native_tool_bytes_observed_not_hermetic_reuse_qualified": True,
    }


def command_terminal(row):
    need(
        row.get("launch_attempts") == 1 and row.get("created") is True,
        "command original launch missing",
    )
    need(
        row.get("successful") is True and row.get("native_complete") is True,
        "command has no full native terminal success",
    )
    need(
        row.get("root_handle_exit_code") == 0
        and row.get("root_handle_signaled") is True,
        "root original native terminal missing",
    )
    need(
        not row.get("errors") and row.get("error_overflow_count") == 0,
        "owned command retained an error",
    )
    need(
        row.get("termination_attempts") == 0 and row.get("cancellation_count") == 0,
        "terminated/cancelled attempt is not a pass",
    )
    members = row.get("members", [])
    need(
        members
        and len({(m["pid"], m["creation_filetime"]) for m in members}) == len(members),
        "native process identity set",
    )
    need(
        all(
            m.get("in_original_job") is True
            and m.get("terminal") is True
            and m.get("exit_continued") is True
            and m.get("closed") is True
            and m.get("actual_exit_code") == m.get("exit_event_code")
            for m in members
        ),
        "a descendant lacks original-handle actual terminal",
    )
    need(
        row.get("accounting_before_handle_release", {}).get("total_processes")
        == len(members),
        "lifetime Job count does not cover every retained process",
    )
    need(
        row.get("accounting_after_handle_release", {}).get("active_processes") == 0,
        "native references remain after terminal-handle release",
    )
    for label in ("stdout", "stderr"):
        stream = row.get(label, {})
        need(
            stream.get("eof") is True and stream.get("truncated") is False,
            "actual complete output EOF is required: " + label,
        )
        need(
            stream.get("observed_bytes") == stream.get("retained_bytes"),
            "output byte truncation",
        )
    need(
        row.get("completed_monotonic", math.inf)
        <= row.get("operation_deadline", -math.inf),
        "command over its original operation budget",
    )


def dependency_plan(packages, lock_raw, repo, cargo_home):
    lock = tomllib.loads(lock_raw.decode("utf-8"))
    entries = lock.get("package")
    need(isinstance(entries, list) and entries, "complete original Cargo.lock packages")
    plan = []
    for package in packages:
        source = package.get("source")
        manifest = Path(package["manifest_path"]).absolute()
        root = manifest.parent
        if source is None:
            need(
                beneath(manifest, repo),
                "unbound local path dependency outside complete tree",
            )
            plan.append(
                {
                    "id": package["id"],
                    "kind": "retained_complete_candidate",
                    "manifest": str(manifest),
                    "root": str(root),
                }
            )
            continue
        matches = [
            item
            for item in entries
            if item.get("name") == package["name"]
            and item.get("version") == package["version"]
            and item.get("source") == source
        ]
        need(len(matches) == 1, "metadata dependency is not exactly locked")
        entry = matches[0]
        if source.startswith("registry+"):
            need(
                beneath(root, Path(cargo_home) / "registry/src"),
                "registry dependency escaped fresh declared Cargo home",
            )
            need(
                re.fullmatch("[0-9a-f]{64}", entry.get("checksum", "")),
                "locked registry checksum missing",
            )
            registry_name = root.parent.name
            archive = (
                Path(cargo_home)
                / "registry/cache"
                / registry_name
                / (package["name"] + "-" + package["version"] + ".crate")
            )
            plan.append(
                {
                    "id": package["id"],
                    "kind": "registry",
                    "source": source,
                    "manifest": str(manifest),
                    "root": str(root),
                    "archive": str(archive),
                    "archive_sha256": entry["checksum"],
                }
            )
        elif source.startswith("git+"):
            need(
                beneath(root, Path(cargo_home) / "git/checkouts"),
                "Git dependency escaped fresh declared Cargo home",
            )
            commit = source.rsplit("#", 1)
            need(
                len(commit) == 2 and re.fullmatch("[0-9a-f]{40}", commit[1]),
                "locked Git dependency lacks an exact commit",
            )
            plan.append(
                {
                    "id": package["id"],
                    "kind": "git",
                    "source": source,
                    "manifest": str(manifest),
                    "root": str(root),
                    "locked_commit": commit[1],
                    "independent_git_object_graph_authentication": False,
                }
            )
        else:
            raise CollectionFailure("unsupported external Cargo source: " + source)
    return plan
