"""Read-only independent verification of the bounded B11 environment edit."""

import ast
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "architecture-audit/b11-windows-env-casing-20261105"


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def verify():
    sources = json.loads((BASE / "source-map.json").read_bytes())
    checked = []
    for row in sources:
        for kind in ("preimage", "postimage"):
            data = Path(row[kind + "_file"]).read_bytes()
            assert identity(data) == row[kind]
            ast.parse(data)
        pre = Path(row["preimage_file"]).read_text()
        post = Path(row["postimage_file"]).read_text()
        if row["path"].endswith("run_b11_acl_identity_counterfactual.py"):
            begin = post.index("\n\ndef bazel_environment(archive):")
            end = post.index("\n\ndef save(", begin)
            inverse = post[:begin] + post[end:]
            replacements = [
                ('            positive_env = bazel_environment(positive_archive)\n', '            positive_env = os.environ.copy()\n            positive_env["CODEX_BAZEL_EXECUTION_LOG_COMPACT_DIR"] = str(positive_archive)\n'),
                ('        env = bazel_environment(negative_archive)\n', '        env = os.environ.copy()\n        env["CODEX_BAZEL_EXECUTION_LOG_COMPACT_DIR"] = str(negative_archive)\n'),
            ]
            module = ast.parse(post)
            fn = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "bazel_environment")
            loop = next(node for node in fn.body if isinstance(node, ast.For))
            canonical = ast.literal_eval(loop.iter)
            required_if = next(node for node in loop.body if isinstance(node, ast.If) and isinstance(node.test, ast.Compare))
            required = ast.literal_eval(required_if.test.comparators[0])
        else:
            inverse = post
            replacements = [
                ('        env = control.bazel_environment(archive)\n', '        env = os.environ.copy()\n        env["CODEX_BAZEL_EXECUTION_LOG_COMPACT_DIR"] = str(archive)\n'),
                ('CONTROL_BLOB = "90ae8f030ee405706217d7cb2cdc12f1a7cda443"', 'CONTROL_BLOB = "e6a191a2d3c66c740aa3cb2ccd42c3e4fdb6880e"'),
                ('".github/scripts/collect_bazel_failed_test_logs.py": "76a183d6a45e4a6c1493de194f8a1f6c422f0892"', '".github/scripts/collect_bazel_failed_test_logs.py": "e15bfb8a75678ff7d4bab4b82b2e54e80b8b61c9"'),
            ]
        for after, before in replacements:
            assert inverse.count(after) == 1
            inverse = inverse.replace(after, before, 1)
        assert inverse == pre
        checked.append({"path": row["path"], "preimage": row["preimage"], "postimage": row["postimage"], "inverse_complete_preimage_byte_equal": True})

    wrapper = (BASE / "primary/run-bazel-ci.sh.source.txt").read_bytes()
    assert identity(wrapper)["git_blob"] == "42b59b6354b5933c8155b992519682c06d024ca1"
    forwarding_names = re.search(r"    windows_action_env_vars=\(\n(.*?)    \)", wrapper.decode(), re.S).group(1).split()
    required_names = re.search(r"    required_windows_action_env_vars=\(\n(.*?)    \)", wrapper.decode(), re.S).group(1).split()
    assert canonical == tuple(name for name in forwarding_names if name.upper() != name)
    assert required == tuple(name for name in required_names if name.upper() != name)

    collector_before = (BASE / "primary/collector-diag-head-e15.source.txt").read_bytes()
    collector_after = (ROOT / "hepta-audit-fifth/main-format-retention/diagnostic-collector.merged.py.source.txt").read_bytes()
    insertion = b'    "//codex-rs/utils/pty:pty-unit-tests",\n'
    assert collector_after.count(insertion) == 1
    assert collector_after.replace(insertion, b"", 1) == collector_before
    assert identity(collector_before)["git_blob"] == "e15bfb8a75678ff7d4bab4b82b2e54e80b8b61c9"
    assert identity(collector_after)["git_blob"] == "76a183d6a45e4a6c1493de194f8a1f6c422f0892"
    collector_module = ast.parse(collector_after)
    targets = ast.literal_eval(next(node for node in collector_module.body if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "RETAINED_TARGETS").value)
    assert len(targets) == len(set(targets)) == 13
    assert targets[-2:] == ("//codex-rs/windows-sandbox-rs:codex-windows-sandbox-setup-bin-unit-tests", "//codex-rs/utils/pty:pty-unit-tests")
    return {
        "schema": "independent-b11-env-source-scope-v1",
        "sources": checked,
        "canonical_names_equal_all_eight_mixed_case_forwarded_names": list(canonical),
        "required_names_equal_all_three_mixed_case_required_names": list(required),
        "unchanged_uppercase_required_names": [name for name in required_names if name.upper() == name],
        "all_three_environment_sites_share_the_same_helper": True,
        "entire_other_source_bytes_unchanged_including_argv_guards_budgets_assertions_and_finally": True,
        "collector_before": identity(collector_before),
        "collector_after": identity(collector_after),
        "collector_exactly_old_eleven_plus_helper_plus_one_PTY_entry": True,
        "actual_future_HEAD_and_merge_PIN_binding": "ROOT_PUBLICATION_GATE_REQUIRED",
        "new_candidate_native_qualification": "NOT_RUN",
        "product_B11": "OPEN",
        "only_evidence_reads_no_script_main_no_process_no_native_execution": True,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), ensure_ascii=False, indent=2))
