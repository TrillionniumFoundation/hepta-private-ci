#!/usr/bin/env python3
"""Read one fixed file and print a value-redacted, non-executing AST summary."""

import ast
import hashlib
import json
import os
import re
import stat
import sys
import warnings

TARGET = "/data/hepta-service-root-01.py"
MAX_FILE_BYTES = 64 * 1024
MAX_AST_NODES = 50_000
MAX_RECORDS_PER_KIND = 512
MAX_IDENTIFIER_CHARS = 256

# These are fixed public interface names, not values copied from source literals.
INTERFACES = {
    "ordinary": (
        "AgentdProductionStartup",
        "AgentdProductionLaunch",
        "AgentdConfig",
        "with_q24_circuit_task_profile",
        "with_root_learning_stage_owners",
        "with_root_resident_learning_enrollment",
        "run_original_resident_delivery",
    ),
    "root": (
        "DeploymentFinalUseIssuer",
        "AgentdRootResidentLearningClientV3",
        "RootResidentLearningProfileV3",
        "enroll_original_root",
        "register_host_resident_learning_v3",
        "into_candidate_runtime",
        "from_original_root_stream",
        "recover_original_root_stream",
    ),
    "owner": (
        "OriginalCellQ24TrainingBootstrapCustodyV1",
        "OriginalCellQ24TrainingBootstrapOwnerV1",
        "OriginalCellEvaluationPanelMemberOwnersV1",
        "OriginalCircuitModelSelectionReceiptOwnerV1",
        "OriginalCircuitModelVersionHostV1",
        "from_original_custody",
        "from_original_owners",
        "into_host_from_original_training_readback",
    ),
}
GENERIC_WORDS = {
    "fixture": ("fixture", "fixtures", "mock", "synthetic"),
    "ordinary": ("ordinary",),
    "root": ("root",),
    "owner": ("owner", "owners", "custody"),
    "learning": ("learn", "learning"),
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


def summarize(module):
    rows = {"imports": [], "definitions": [], "calls": [], "interface_markers": []}
    counts = {name: 0 for name in rows}
    names_omitted = 0
    nodes_visited = 0
    node_limit_reached = False

    def record(kind, value):
        counts[kind] += 1
        if len(rows[kind]) < MAX_RECORDS_PER_KIND:
            rows[kind].append(value)

    def markers(value, node, field):
        # Only identifier-bearing AST fields enter here. No Constant.value,
        # docstring, comment, source line, argument value or environment is read.
        if not isinstance(value, str):
            return
        components = value.split(".")
        hits = set()
        for category, vocabulary in INTERFACES.items():
            for marker in vocabulary:
                if marker in components:
                    hits.add((category, marker))
        for component in components:
            split = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", component)
            words = set(re.split(r"[_\W]+", split.casefold()))
            for category, vocabulary in GENERIC_WORDS.items():
                for marker in vocabulary:
                    if marker in words:
                        hits.add((category, marker))
        for category, marker in sorted(hits):
            record("interface_markers", {
                "category": category,
                "marker": marker,
                "ast_node": type(node).__name__,
                "identifier_field": field,
                **location(node),
            })

    for node in ast.walk(module):
        nodes_visited += 1
        if nodes_visited > MAX_AST_NODES:
            node_limit_reached = True
            break
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = dotted_name(alias.name)
                alias_name = identifier(alias.asname)
                names_omitted += int(name is None)
                names_omitted += int(alias.asname is not None and alias_name is None)
                record("imports", {
                    "kind": "import",
                    "module": name,
                    "alias": alias_name,
                    **location(alias),
                })
                markers(alias.name, alias, "import_module")
                if alias.asname is not None:
                    markers(alias.asname, alias, "import_alias")
        elif isinstance(node, ast.ImportFrom):
            module_name = dotted_name(node.module) if node.module else None
            names_omitted += int(node.module is not None and module_name is None)
            if node.module:
                markers(node.module, node, "from_module")
            for alias in node.names:
                name = "*" if alias.name == "*" else identifier(alias.name)
                alias_name = identifier(alias.asname)
                names_omitted += int(name is None)
                names_omitted += int(alias.asname is not None and alias_name is None)
                record("imports", {
                    "kind": "from_import",
                    "module": module_name,
                    "relative_level": node.level,
                    "name": name,
                    "alias": alias_name,
                    **location(alias),
                })
                markers(alias.name, alias, "import_name")
                if alias.asname is not None:
                    markers(alias.asname, alias, "import_alias")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = identifier(node.name)
            names_omitted += int(name is None)
            record("definitions", {
                "kind": type(node).__name__,
                "name": name,
                **location(node),
            })
            markers(node.name, node, "definition_name")
        elif isinstance(node, ast.Call):
            name = callee_name(node.func)
            record("calls", {
                "name": name,
                "callee_ast_node": type(node.func).__name__,
                "statically_named": name is not None,
                **location(node),
            })
        elif isinstance(node, ast.Name):
            markers(node.id, node, "identifier")
        elif isinstance(node, ast.Attribute):
            markers(node.attr, node, "attribute")
        elif isinstance(node, ast.arg):
            markers(node.arg, node, "parameter_name")

    for values in rows.values():
        values.sort(key=lambda row: (
            row.get("line") or 0,
            row.get("column") or 0,
            json.dumps(row, ensure_ascii=True, sort_keys=True),
        ))
    omitted = {name: counts[name] - len(rows[name]) for name in rows}
    complete = not node_limit_reached and not any(omitted.values()) and names_omitted == 0
    return {
        **rows,
        "observed_record_counts": counts,
        "omitted_record_counts": omitted,
        "identifier_names_omitted": names_omitted,
        "ast_nodes_visited": min(nodes_visited, MAX_AST_NODES),
        "node_limit_reached": node_limit_reached,
        "summary_complete": complete,
        "position_units": "line: 1-based; column: CPython UTF-8 byte offset, 0-based",
    }


def main():
    report = {
        "schema": "hepta.service-root01.safe-static-ast.v1",
        "target": TARGET,
        "status": "unknown",
        "assessment": "unknown_from_static_ast",
        "ordinary_execution_authority_proven": False,
        "runtime_owner_custody_observed": False,
        "limits": {
            "max_file_bytes": MAX_FILE_BYTES,
            "max_ast_nodes": MAX_AST_NODES,
            "max_records_per_kind": MAX_RECORDS_PER_KIND,
            "max_identifier_chars": MAX_IDENTIFIER_CHARS,
            "accepted_source_encoding": "UTF-8 with optional BOM",
        },
        "limitations": [
            "Identifier mentions and call syntax do not prove execution, imports, grants or deployment.",
            "Dynamic callees and runtime argument values are not resolved.",
            "All source literal values, docstrings, comments and source-line text are omitted.",
            "Only the fixed target is read; referenced files and modules are not opened or imported.",
            "Metadata stability is checked at the sampled points; no filesystem lock is claimed.",
        ],
    }
    exit_code = 1
    try:
        source, metadata = read_stable_source()
        report["source"] = metadata
        # Decode with a fixed codec before parsing. A source encoding cookie
        # must not select a codec/import hook during this bounded inspection.
        try:
            source_text = source.decode("utf-8")
        except UnicodeDecodeError:
            raise InspectionRejected("target_encoding_not_utf8") from None
        if source_text.startswith("\ufeff"):
            source_text = source_text[1:]
        # mode='exec' selects the grammar only; no target bytecode is executed.
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            module = ast.parse(source_text, filename=TARGET, mode="exec")
        report["ast"] = summarize(module)
        report["status"] = "ok" if report["ast"]["summary_complete"] else "incomplete"
        exit_code = 0 if report["status"] == "ok" else 2
    except InspectionRejected as error:
        report["status"] = "rejected"
        report["error"] = {"code": error.code}
    except SyntaxError as error:
        report["status"] = "unparseable"
        # Do not print exception text: SyntaxError can contain a source literal.
        report["error"] = {
            "type": type(error).__name__,
            "line": error.lineno,
            "column": error.offset,
        }
    except Exception as error:
        report["status"] = "unavailable"
        # Error messages/args/reprs can expose source or environment values.
        report["error"] = {"type": type(error).__name__}
        if isinstance(error, OSError):
            report["error"]["errno"] = error.errno
    print(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
