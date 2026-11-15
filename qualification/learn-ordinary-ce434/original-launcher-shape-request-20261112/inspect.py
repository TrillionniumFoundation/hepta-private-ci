#!/usr/bin/env python3
"""Inspect one pinned file's syntax without exporting source values or executing it."""

import ast
import hashlib
import json
import os
import stat
import sys
import warnings

TARGET = "/data/hepta-service-root-01.py"
MAX_FILE_BYTES = 64 * 1024
MAX_AST_NODES = 50_000
MAX_RECORDS_PER_KIND = 64
MAX_IDENTIFIER_CHARS = 256
MAX_ORIGIN_DEPTH = 6
EXPECTED_SOURCE = {
    "device": 2067,
    "inode": 83,
    "mode": "0o664",
    "nlink": 1,
    "size_bytes": 1379,
    "mtime_ns": 1792775306676468050,
    "ctime_ns": 1792775306676468050,
    "sha256": "9919f15ae0ba3c58fa1630345b51adb566fc1ba18914c0d0051e50075246ef77"
}
ALLOWED_IMPORTS = frozenset(("pathlib", "json", "subprocess", "os", "time", "hashlib"))
ALLOWED_CALLS = frozenset((
    "pathlib.Path", "p.exists", "p.rename", "str", "time.monotonic",
    "subprocess.run", "dict", "hashlib.sha256", "binary.read_bytes",
    "json.dumps", "print",
))
ALLOWED_PATH_NAMES = frozenset(("root", "p", "binary"))
# These are fixed method labels, not source literal values or trusted receivers.
FILE_METHOD_ROLES = {
    "exists": "existence_probe",
    "rename": "rename_source",
    "read_bytes": "file_read",
    "open": "file_open",
    "write_text": "text_output",
}

class InspectionRejected(Exception):
    def __init__(self, code):
        self.code = code


def checked_stat(value):
    if not stat.S_ISREG(value.st_mode):
        raise InspectionRejected("target_not_regular")
    if value.st_nlink != 1:
        raise InspectionRejected("target_link_count_not_one")
    if not 0 <= value.st_size <= MAX_FILE_BYTES:
        raise InspectionRejected("target_size_out_of_bounds")
    return value


def identity(value):
    # atime is deliberately excluded: the authorized read can update it.
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def read_stable_source():
    before = checked_stat(os.lstat(TARGET))
    required_flags = ("O_NOFOLLOW", "O_CLOEXEC", "O_NONBLOCK")
    if any(not hasattr(os, name) for name in required_flags):
        raise InspectionRejected("required_open_flags_unavailable")
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    fd = os.open(TARGET, flags)
    try:
        opened = checked_stat(os.fstat(fd))
        if identity(opened) != identity(before):
            raise InspectionRejected("target_changed_before_read")
        data = bytearray()
        # Never read beyond the originally observed bounded regular-file size.
        while len(data) < before.st_size:
            chunk = os.read(fd, min(8192, before.st_size - len(data)))
            if not chunk:
                raise InspectionRejected("unexpected_end_of_file")
            data.extend(chunk)
        after_fd = checked_stat(os.fstat(fd))
        after_path = checked_stat(os.lstat(TARGET))
        if (
            identity(after_fd) != identity(before)
            or identity(after_path) != identity(before)
            or len(data) != before.st_size
        ):
            raise InspectionRejected("target_changed_during_read")
        data = bytes(data)
        metadata = {
            "device": before.st_dev,
            "inode": before.st_ino,
            "mode": oct(stat.S_IMODE(before.st_mode)),
            "nlink": before.st_nlink,
            "size_bytes": before.st_size,
            "mtime_ns": before.st_mtime_ns,
            "ctime_ns": before.st_ctime_ns,
            "sha256": hashlib.sha256(data).hexdigest(),
            "read_before_after_identity_equal": True,
        }
        return data, metadata
    finally:
        os.close(fd)

def identifier(value):
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or len(value) > MAX_IDENTIFIER_CHARS
        or not value.isidentifier()
    ):
        return None
    return value


def dotted_name(value):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_IDENTIFIER_CHARS
        or not all(part.isidentifier() for part in value.split("."))
    ):
        return None
    return value


def location(node):
    return {
        "line": getattr(node, "lineno", None),
        "column": getattr(node, "col_offset", None),
        "end_line": getattr(node, "end_lineno", None),
        "end_column": getattr(node, "end_col_offset", None),
    }


def callee_name(node):
    parts = []
    while isinstance(node, ast.Attribute):
        part = identifier(node.attr)
        if part is None:
            return None
        parts.append(part)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    first = identifier(node.id)
    if first is None:
        return None
    return dotted_name(".".join([first, *reversed(parts)]))


def project(module):
    nodes = []
    for node in ast.walk(module):
        if len(nodes) >= MAX_AST_NODES:
            raise InspectionRejected("ast_node_bound_exceeded")
        nodes.append(node)

    writes = {}
    for node in nodes:
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            writes[node.id] = writes.get(node.id, 0) + 1
    bindings = {}
    for statement in module.body:
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            name = statement.targets[0].id
            if writes.get(name) == 1:
                bindings[name] = (statement, statement.value)

    def origin(node, depth=0, seen=()):
        if node is None:
            return {"kind": "absent"}
        result = {"kind": type(node).__name__, **location(node)}
        if depth >= MAX_ORIGIN_DEPTH:
            result["resolution"] = "depth_bound"
        elif isinstance(node, ast.Constant):
            # Do not read, render, hash or classify Constant.value.
            result["resolution"] = "literal_value_omitted"
        elif isinstance(node, ast.Name):
            result["known_path_name"] = node.id if node.id in ALLOWED_PATH_NAMES else None
            binding = bindings.get(node.id)
            if node.id in seen:
                result["resolution"] = "cyclic_reference"
            elif binding and (
                getattr(binding[0], "lineno", 0),
                getattr(binding[0], "col_offset", 0),
            ) < (getattr(node, "lineno", 0), getattr(node, "col_offset", 0)):
                result["resolution"] = "single_top_level_assignment_syntax"
                result["assignment"] = location(binding[0])
                result["origin"] = origin(binding[1], depth + 1, (*seen, node.id))
            else:
                result["resolution"] = "no_unique_prior_top_level_assignment"
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            result["resolution"] = "path_join_operator_syntax"
            result["base"] = origin(node.left, depth + 1, seen)
            result["component"] = origin(node.right, depth + 1, seen)
        elif isinstance(node, ast.Call):
            name = callee_name(node.func)
            result["allowed_call"] = name if name in ALLOWED_CALLS else None
            if name in ("pathlib.Path", "str") and len(node.args) == 1 and not node.keywords:
                result["resolution"] = "allowed_single_argument_call_syntax"
                result["argument"] = origin(node.args[0], depth + 1, seen)
            else:
                result["resolution"] = "call_arguments_omitted"
        elif isinstance(node, (ast.List, ast.Tuple)):
            result["resolution"] = "sequence_syntax"
            result["element_count"] = len(node.elts)
            result["first_element"] = origin(node.elts[0], depth + 1, seen) if node.elts else None
            result["remaining_values_omitted"] = True
        else:
            # Includes mappings, subscripts, attributes, formatted strings and
            # arbitrary expressions. No value or environment lookup is attempted.
            result["resolution"] = "expression_values_omitted"
        return result

    rows = {"imports": [], "calls": [], "path_uses": [], "subprocess_calls": []}
    counts = {name: 0 for name in rows}

    def record(kind, value):
        counts[kind] += 1
        if len(rows[kind]) < MAX_RECORDS_PER_KIND:
            rows[kind].append(value)

    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                allowed = alias.name if alias.name in ALLOWED_IMPORTS else None
                record("imports", {
                    "allowed_module": allowed,
                    "alias_present": alias.asname is not None,
                    "unlisted_identifier_omitted": allowed is None,
                    **location(alias),
                })
        elif isinstance(node, ast.ImportFrom):
            allowed = node.module if node.module in ALLOWED_IMPORTS else None
            record("imports", {
                "allowed_module": allowed,
                "from_import_names_omitted": True,
                "relative_import": bool(node.level),
                "unlisted_identifier_omitted": allowed is None,
                **location(node),
            })
        elif isinstance(node, ast.Call):
            name = callee_name(node.func)
            allowed = name if name in ALLOWED_CALLS else None
            record("calls", {
                "allowed_name": allowed,
                "dynamic_or_unlisted_callee": allowed is None,
                "positional_argument_count": len(node.args),
                "keyword_count": len(node.keywords),
                **location(node),
            })
            if name == "pathlib.Path":
                record("path_uses", {
                    "role": "path_constructor_argument",
                    "expression": origin(node.args[0]) if node.args else {"kind": "absent"},
                    **location(node),
                })
            if isinstance(node.func, ast.Attribute):
                role = FILE_METHOD_ROLES.get(node.func.attr)
                if role is not None:
                    record("path_uses", {
                        "role": role,
                        "receiver": origin(node.func.value),
                        "receiver_runtime_type_proven": False,
                        **location(node),
                    })
                    if node.func.attr == "rename" and node.args:
                        record("path_uses", {
                            "role": "rename_destination",
                            "expression": origin(node.args[0]),
                            **location(node.args[0]),
                        })
            if name == "hashlib.sha256" and node.args:
                record("path_uses", {
                    "role": "hash_input_syntax",
                    "expression": origin(node.args[0]),
                    **location(node),
                })
            if name == "subprocess.run":
                keywords = {item.arg: item.value for item in node.keywords if item.arg is not None}
                command = node.args[0] if node.args else keywords.get("args")
                record("subprocess_calls", {
                    "callee_is_syntax_only": True,
                    "command_source": origin(command),
                    "working_directory_source": origin(keywords.get("cwd")),
                    "stdout_binding": origin(keywords.get("stdout")),
                    "stderr_binding": origin(keywords.get("stderr")),
                    "environment_argument_present": "env" in keywords,
                    "environment_argument_value_not_resolved": True,
                    "shell_argument_present": "shell" in keywords,
                    "all_argument_literal_values_omitted": True,
                    "remaining_keyword_values_omitted": True,
                    "double_star_keywords_present": any(item.arg is None for item in node.keywords),
                    **location(node),
                })

    for values in rows.values():
        values.sort(key=lambda row: (row.get("line") or 0, row.get("column") or 0))
    omitted = {kind: counts[kind] - len(rows[kind]) for kind in rows}
    return {
        **rows,
        "ast_nodes_visited": len(nodes),
        "observed_record_counts": counts,
        "omitted_record_counts": omitted,
        "summary_complete": not any(omitted.values()),
        "bindings_are_syntactic_not_runtime_dataflow": True,
        "position_units": "line: 1-based; column: CPython UTF-8 byte offset, 0-based",
    }


def main():
    report = {
        "schema": "hepta.service-root01.safe-static-locator-shape.v2",
        "target": TARGET,
        "prior_result_git_blob": "ec6d9be38af816b8e74bd6746193547b0b671ae9",
        "status": "unknown",
        "assessment": "unknown_from_static_ast",
        "ordinary_execution_authority_proven": False,
        "runtime_owner_custody_observed": False,
        "limitations": [
            "Only the same pinned target is read; no referenced file or directory is opened.",
            "The script is parsed, never imported, evaluated, executed or spawned.",
            "Literal values, environment values, argv contents and source lines are omitted.",
            "Names, assignment syntax and path-use categories do not prove runtime identity or deployment.",
            "No command or factory is classified as production, fixture or authorized from these shapes.",
            "Metadata equality is sampled; no filesystem lock or external supervisor guarantee is claimed.",
        ],
    }
    exit_code = 1
    try:
        source, metadata = read_stable_source()
        report["source"] = metadata
        if any(metadata.get(key) != value for key, value in EXPECTED_SOURCE.items()):
            raise InspectionRejected("observed_target_identity_or_content_changed")
        try:
            source_text = source.decode("utf-8")
        except UnicodeDecodeError:
            raise InspectionRejected("target_encoding_not_utf8") from None
        if source_text.startswith("\ufeff"):
            source_text = source_text[1:]
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            module = ast.parse(source_text, filename=TARGET, mode="exec")
        report["projection"] = project(module)
        report["status"] = "ok" if report["projection"]["summary_complete"] else "incomplete"
        exit_code = 0 if report["status"] == "ok" else 2
    except InspectionRejected as error:
        report["status"] = "rejected"
        report["error"] = {"code": error.code}
    except SyntaxError as error:
        report["status"] = "unparseable"
        report["error"] = {"type": type(error).__name__, "line": error.lineno, "column": error.offset}
    except Exception as error:
        report["status"] = "unavailable"
        report["error"] = {"type": type(error).__name__}
        if isinstance(error, OSError):
            report["error"]["errno"] = error.errno
    print(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
