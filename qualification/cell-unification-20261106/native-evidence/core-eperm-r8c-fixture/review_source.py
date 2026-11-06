"""Verify the five fixture-only configuration insertions without running Rust."""

from collections import Counter
import difflib
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent
CASES = {
    "codex-rs/core/tests/suite/approvals.rs": [
        "approving_execpolicy_amendment_persists_policy_and_skips_future_prompts",
    ],
    "codex-rs/core/tests/suite/request_permissions.rs": [
        "request_permissions_grants_apply_to_later_exec_command_calls",
        "request_permissions_preapprove_explicit_exec_permissions_outside_on_request",
        "request_permissions_grants_apply_to_later_exec_command_calls_without_inline_permission_feature",
        "partial_request_permissions_grants_do_not_preapprove_new_permissions",
    ],
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def function_text(source, name):
    marker = "async fn " + name + "()"
    assert source.count(marker) == 1, name
    start = source.index(marker)
    # Every selected test closes at column zero; nested blocks are indented.
    end = source.index("\n}\n", start) + 3
    return source[start:end]


def main():
    report = []
    patch = []
    for relative, names in CASES.items():
        before_bytes = (ROOT / "original" / relative).read_bytes()
        after_bytes = (ROOT / "source" / relative).read_bytes()
        before = before_bytes.decode()
        after = after_bytes.decode()
        kind = "approval" if relative.endswith("/approvals.rs") else "permission"
        insertion = (
            f"        // Keep {kind}/output assertions independent of host login profiles.\n"
            "        config.permissions.allow_login_shell = false;\n"
        )
        anchor = "    let mut builder = test_codex().with_config(move |config| {\n"
        expected = before
        case_checks = []
        for name in names:
            original_function = function_text(before, name)
            assert original_function.count(anchor) == 1
            expected_function = original_function.replace(anchor, anchor + insertion, 1)
            candidate_function = function_text(after, name)
            assert candidate_function == expected_function, name
            assert "allow_login_shell" not in original_function, name
            assert '"login"' not in original_function, name
            assert "with_user_shell" not in original_function, name
            assert "allow_login_shell" in candidate_function, name
            expected = expected.replace(original_function, expected_function, 1)
            case_checks.append({
                "test": name,
                "only_existing_config_insertion": True,
                "original_function_sha256": sha256(original_function.encode()),
                "candidate_function_sha256": sha256(candidate_function.encode()),
                "original_assertion_macro_count": len(re.findall(r"\bassert(?:_eq|_ne)?!", original_function)),
            })
        assert expected == after
        assert after.count(insertion) == len(names)
        assert after.replace(insertion, "") == before
        before_assertions = Counter(re.findall(r"\bassert(?:_eq|_ne)?!", before))
        after_assertions = Counter(re.findall(r"\bassert(?:_eq|_ne)?!", after))
        assert before_assertions == after_assertions
        patch.extend(difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile="a/" + relative,
            tofile="b/" + relative,
        ))
        report.append({
            "path": relative,
            "before": {"bytes": len(before_bytes), "sha256": sha256(before_bytes), "git_blob": git_blob(before_bytes)},
            "after": {"bytes": len(after_bytes), "sha256": sha256(after_bytes), "git_blob": git_blob(after_bytes)},
            "fixture_insertions": len(names),
            "assertion_macro_counts": dict(sorted(before_assertions.items())),
            "whole_file_inverse_exact": True,
            "all_original_bytes_preserved_in_order": True,
            "case_checks": case_checks,
        })
    patch_bytes = "".join(patch).encode()
    (ROOT / "repair.patch").write_bytes(patch_bytes)
    output = {
        "schema": "hepta.core-eperm-fixture-source-review.v1",
        "source_files": report,
        "changed_fixtures": sum(len(names) for names in CASES.values()),
        "added_lines": 10,
        "removed_lines": 0,
        "new_or_removed_tests": 0,
        "assertions_modified": 0,
        "production_files_modified": 0,
        "rust_execution": False,
        "patch": {"bytes": len(patch_bytes), "sha256": sha256(patch_bytes)},
    }
    (ROOT / "mechanical-review.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
