#!/usr/bin/env python3
"""Classify only fixed AST slots in one pinned file; never execute it or export values."""

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
MAX_IDENTIFIER_CHARS = 256
EXPECTED_SOURCE = {
    "device": 2067,
    "inode": 83,
    "mode": "0o664",
    "nlink": 1,
    "size_bytes": 1379,
    "mtime_ns": "1792775306676468050",
    "ctime_ns": "1792775306676468050",
    "sha256": "9919f15ae0ba3c58fa1630345b51adb566fc1ba18914c0d0051e50075246ef77"
}
COMMAND_HEADS = {
    "sudo": "head_sudo",
    "/usr/bin/sudo": "head_absolute_sudo",
    "env": "head_env",
    "/usr/bin/env": "head_absolute_env",
}
WRAPPER_LITERALS = {
    "sudo": "wrapper_sudo",
    "/usr/bin/sudo": "wrapper_absolute_sudo",
    "env": "wrapper_env",
    "/usr/bin/env": "wrapper_absolute_env",
}
FLAG_LITERALS = {
    "-n": "flag_noninteractive",
    "-i": "flag_empty_environment",
    "--exact": "flag_exact",
    "--nocapture": "flag_nocapture",
    "--test-threads=1": "flag_one_test_thread",
}
ROOT29_INVENTORY_BLOB = "5553a141941861e63f50204904c1c28bc20def16"
ROOT29_CASES = (
    "authority_host_service::writer::learning_registration::tests::root_learning_registration_reopens_without_replacing_original_history",
    "authority_host_service::writer::learning_registration::tests::root_learning_sealed_pin_and_dedicated_uds_recover_original_checkpoint",
    "authority_host_service::writer::learning_registration::tests::root_scoped_learning_reopens_exact_scope_and_refuses_legacy_client",
    "authority_host_service::writer::learning_registration::tests::root_learning_scoped_sealed_pin_preserves_scope_on_cold_reopen",
    "root_production_handoff::learning::tests::root_learning_handoff_reaches_dedicated_uid_with_original_root_pin",
    "authority_host_learning_service_root_tests::root_learning_public_registration_serves_retained_writer_and_recovers_history",
    "learning_iteration_evidence_client::tests::root::original_external_uid_returns_a_verified_receipt_through_held_pidfd",
    "authority_host_service::resident::authority::tests::resident_root_formatter_and_original_registration_pin_both_scopes",
    "authority_host_service::resident::authority::tests::resident_root_reissued_intent_cannot_create_another_operation_namespace",
    "authority_host_service::resident::authority::tests::resident_root_only_actual_vacant_cas_creates_one_live_continuation",
    "authority_host_service::resident::authority::tests::resident_root_same_epoch_grant_revocation_fences_the_pending_effect",
    "authority_host_service::resident::authority::tests::resident_root_exact_lease_revocation_fences_without_restarting_dispatch",
    "authority_host_service::resident::authority::tests::resident_root_lost_fresh_ack_recovers_only_under_explicit_readback_intent",
    "authority_host_service::resident::authority::tests::resident_root_queued_admit_cancellation_sends_no_frame_and_consumes_channel",
    "authority_host_service::resident::authority::tests::resident_root_structured_uncertain_allows_only_same_operation_readback",
    "authority_host_service::resident::authority::tests::checkpoint_expiry::resident_root_checkpoint_expiry_stops_next_stage_and_preserves_committed_bytes",
    "authority_host_service::resident::authority::tests::evaluation::resident_root_original_evaluation_requires_actual_checkpoint_and_independent_signature",
    "runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::retained_publication::retained_support::version_issuer::tests::retained_version_issuer_uses_actual_prepared_binding_and_installs_distinct_c",
    "runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::retained_publication::retained_support::version_issuer::tests::retained_version_issuer_denied_once_keeps_actual_prepared_operation_read_only",
    "runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::retained_publication::retained_support::version_issuer::tests::retained_version_issuer_lost_ack_never_reissues_original_intent",
    "runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::retained_publication::retained_support::version_issuer::tests::retained_version_issuer_wrong_grant_cannot_replace_prepared_purpose",
    "runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::retained_publication::retained_support::version_issuer::tests::retained_version_issuer_withdrawal_before_root_request_sends_no_frame",
    "runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::retained_publication::retained_support::version_issuer::tests::retained_version_issuer_queued_cancellation_sends_no_frame_and_never_reopens_once",
    "authority_host_service::resident::authority::tests::original_model::resident_root_model_four_cut_preserves_original_wire_and_all_signatures",
    "authority_host_service::resident::authority::tests::original_model::resident_root_model_five_cut_uses_original_record_without_fifth_signature",
    "authority_host_service::resident::authority::tests::original_model::resident_root_model_refuses_missing_extra_wrong_stage_or_reordered_evidence",
    "authority_host_service::resident::authority::tests::original_model::resident_root_model_refuses_changed_record_context_and_signature_window",
    "authority_host_service::resident::authority::tests::original_model::resident_root_model_cold_checkpoint_is_readonly_and_pins_complete_original_bytes",
    "authority_host_service::resident::authority::tests::original_model::resident_root_model_unknown_dispatch_never_recommits_or_mints_fresh_gate",
)
ROOT29_CASE_INDEX = {
    name: index for index, name in enumerate(ROOT29_CASES, start=1)
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

    if len(ROOT29_CASES) != 29 or len(ROOT29_CASE_INDEX) != 29:
        raise InspectionRejected("frozen_test_inventory_invalid")

    # These checks examine only fixed binding names, never unknown source values.
    watched = frozenset(("binary", "cmd", "pathlib", "subprocess", "str"))
    writes = {name: 0 for name in watched}
    imported = {name: 0 for name in watched}
    for node in nodes:
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            if node.id in watched:
                writes[node.id] += 1
        elif isinstance(node, ast.alias):
            bound = node.asname or node.name.split(".", 1)[0]
            if bound in watched:
                imported[bound] += 1
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in watched:
                raise InspectionRejected("ambiguous_fixed_binding")
        elif isinstance(node, ast.arg):
            if node.arg in watched:
                raise InspectionRejected("ambiguous_fixed_binding")
        elif isinstance(node, ast.ExceptHandler):
            if node.name in watched:
                raise InspectionRejected("ambiguous_fixed_binding")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            if any(name in watched for name in node.names):
                raise InspectionRejected("ambiguous_fixed_binding")
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
            receiver = node.value
            while isinstance(receiver, ast.Attribute):
                receiver = receiver.value
            if isinstance(receiver, ast.Name) and receiver.id in watched:
                raise InspectionRejected("ambiguous_fixed_binding")

    exact_imports = {"pathlib": 0, "subprocess": 0}
    assignments = {"binary": [], "cmd": []}
    for statement in module.body:
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                if alias.name in exact_imports and alias.asname is None:
                    exact_imports[alias.name] += 1
        elif (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id in assignments
        ):
            assignments[statement.targets[0].id].append(statement)

    if (
        writes["binary"] != 1
        or writes["cmd"] != 1
        or imported["binary"] != 0
        or imported["cmd"] != 0
        or writes["str"] != 0
        or imported["str"] != 0
        or any(
            writes[name] != 0 or imported[name] != 1 or exact_imports[name] != 1
            for name in ("pathlib", "subprocess")
        )
        or any(len(values) != 1 for values in assignments.values())
    ):
        raise InspectionRejected("ambiguous_fixed_binding")

    binary_assignment = assignments["binary"][0]
    command_assignment = assignments["cmd"][0]
    binary_call = binary_assignment.value
    command = command_assignment.value
    if (
        binary_assignment.lineno != 7
        or binary_assignment.end_lineno != 7
        or binary_assignment.col_offset != 0
        or command_assignment.lineno != 8
        or command_assignment.end_lineno != 8
        or command_assignment.col_offset != 0
        or not isinstance(binary_call, ast.Call)
        or callee_name(binary_call.func) != "pathlib.Path"
        or len(binary_call.args) != 1
        or binary_call.keywords
        or not isinstance(binary_call.args[0], ast.Constant)
        or not isinstance(command, ast.List)
        or len(command.elts) != 10
        or any(isinstance(slot, ast.Starred) for slot in command.elts)
    ):
        raise InspectionRejected("fixed_slot_shape_mismatch")

    # Only the already observed subprocess.run(cmd, cwd=..., stdout=..., stderr=...)
    # syntax is accepted. The keyword values are neither followed nor exported.
    uses = [
        node
        for node in nodes
        if isinstance(node, ast.Call) and callee_name(node.func) == "subprocess.run"
    ]
    if len(uses) != 1:
        raise InspectionRejected("fixed_command_use_mismatch")
    use = uses[0]
    if (
        use.lineno != 10
        or use.end_lineno != 10
        or len(use.args) != 1
        or not isinstance(use.args[0], ast.Name)
        or use.args[0].id != "cmd"
        or len(use.keywords) != 3
        or {keyword.arg for keyword in use.keywords} != {"cwd", "stdout", "stderr"}
    ):
        raise InspectionRejected("fixed_command_use_mismatch")

    # First and only path-literal value access: the fixed line7 Path argument.
    # It is never resolved, split, hashed, rendered, opened, or used as an OS path.
    binary_value = binary_call.args[0].value
    if type(binary_value) is not str:
        raise InspectionRejected("fixed_slot_shape_mismatch")
    binary_shape = (
        "static_absolute_literal_omitted"
        if binary_value.startswith("/")
        else "static_relative_literal_omitted"
    )

    slots = []
    binary_references = []
    case_matches = []
    exact_flags = []
    for index, slot in enumerate(command.elts):
        entry = {"index": index}
        if (
            isinstance(slot, ast.Call)
            and isinstance(slot.func, ast.Name)
            and slot.func.id == "str"
            and len(slot.args) == 1
            and isinstance(slot.args[0], ast.Name)
            and slot.args[0].id == "binary"
            and not slot.keywords
        ):
            entry["classification"] = "pinned_binary_reference_syntax"
            binary_references.append(index)
        elif isinstance(slot, ast.Constant):
            # No nested values, env assignments, formatting or other expressions
            # are inspected. Only a direct value in one of the 10 fixed slots.
            value = slot.value
            if type(value) is not str:
                entry["classification"] = "unknown_literal_omitted"
            elif index == 0 and value in COMMAND_HEADS:
                entry["classification"] = COMMAND_HEADS[value]
            elif value in WRAPPER_LITERALS:
                entry["classification"] = WRAPPER_LITERALS[value]
            elif value in FLAG_LITERALS:
                entry["classification"] = FLAG_LITERALS[value]
                if value == "--exact":
                    exact_flags.append(index)
            elif value in ROOT29_CASE_INDEX:
                ordinal = ROOT29_CASE_INDEX[value]
                entry["classification"] = "root29_case_match"
                entry["case_index"] = ordinal
                case_matches.append((index, ordinal))
            else:
                entry["classification"] = "unknown_literal_omitted"
        else:
            entry["classification"] = "unknown_expression_omitted"
        slots.append(entry)

    selector = None
    if len(binary_references) == 1 and len(case_matches) == 1:
        binary_index = binary_references[0]
        case_slot, case_index = case_matches[0]
        if case_slot > binary_index and any(index > binary_index for index in exact_flags):
            selector = {
                "binary_slot": binary_index,
                "case_slot": case_slot,
                "case_index": case_index,
            }

    return {
        "summary_complete": True,
        "ast_nodes_visited": len(nodes),
        "binding_checks_are_syntactic_not_runtime_dataflow": True,
        "fixed_slots": {"binary_assignment_line": 7, "command_assignment_line": 8, "command_use_line": 10},
        "binary_path_classification": binary_shape,
        "command_slot_count": 10,
        "command_slots": slots,
        "slot_index_base": 0,
        "case_index_base": 1,
        "frozen_test_inventory_blob": ROOT29_INVENTORY_BLOB,
        "frozen_test_inventory_count": 29,
        "declared_original_test_selector": selector,
        "assessment": (
            "static_original_root29_selector_declared"
            if selector is not None
            else "unknown_static_purpose"
        ),
        "full_command_semantics_proven": False,
        "referenced_binary_identity_proven": False,
    }


def main():
    report = {
        "schema": "hepta.service-root01.safe-static-token-classification.v3",
        "target": TARGET,
        "prior_result_git_blob": "24ea024bbcb7bc8d13ab6b9bd56a3fadc198c91f",
        "status": "unknown",
        "assessment": "unknown_static_purpose",
        "ordinary_execution_authority_proven": False,
        "runtime_owner_custody_observed": False,
        "current_runtime_instance_observed": False,
        "limitations": [
            "Only the same pinned target is read; no referenced file or directory is opened.",
            "The target script is parsed, never imported, evaluated, executed or spawned.",
            "Unknown literals, paths, environment names and values, argv values and source lines are omitted.",
            "Known tokens are represented only by fixed enums; original CI cases only by fixed-list indices.",
            "An exact original test selector is a static declaration, not a verified command or actual fixture execution.",
            "No token or shape grants authority, proves ordinary deployment, or proves absence of a launcher.",
            "Negative or ambiguous matching stays unknown; no other file, symbol or source value is searched.",
            "Metadata equality is sampled; no filesystem lock or external supervisor guarantee is claimed.",
        ],
    }
    exit_code = 1
    try:
        source, metadata = read_stable_source()
        # Decimal strings preserve the previously observed exact nanoseconds
        # across JSON consumers that otherwise round integers through binary64.
        for key in ("mtime_ns", "ctime_ns"):
            metadata[key] = str(metadata[key])
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
        report["assessment"] = report["projection"]["assessment"]
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
