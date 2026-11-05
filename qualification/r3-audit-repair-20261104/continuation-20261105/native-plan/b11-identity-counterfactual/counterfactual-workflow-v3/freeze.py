from pathlib import Path
import ast
import hashlib
import json
import re
import runpy
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parents[2]
SCRIPT = ".github/scripts/run_b11_acl_identity_counterfactual.py"
WORKFLOW = ".github/workflows/hepta-windows-token-mechanism-probe.yml"


def pin(path):
    body = path.read_bytes()
    return {"path": str(path), "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()}


def save(name, value):
    path = ROOT / name
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    return pin(path)


pre = ROOT / "source" / SCRIPT
post = ROOT / "candidate" / SCRIPT
old = pre.read_text()
new = post.read_text()
assert pin(pre)["git_blob"] == "25def4386ea08bb72a7605cc113117f31fffcd1b"
old_ast = ast.parse(old)
new_ast = ast.parse(new)
old_functions = {n.name: ast.get_source_segment(old, n) for n in old_ast.body if isinstance(n, ast.FunctionDef)}
new_functions = {n.name: ast.get_source_segment(new, n) for n in new_ast.body if isinstance(n, ast.FunctionDef)}
assert set(old_functions) == set(new_functions)
unchanged = [name for name in old_functions if name != "main"]
assert all(old_functions[name] == new_functions[name] for name in unchanged)
start = old.index("        for required in [CASE,")
tail_marker = "\n        original_bytes = source.read_bytes()"
assert old[:start] == new[:start]
assert old[old.index(tail_marker):] == new[new.index(tail_marker):]
workflow = ROOT / "unchanged" / WORKFLOW
assert pin(workflow)["git_blob"] == "912e22789665b0081c83ae0fa632d2482e8b0eba"

commands = []


def git(cwd, *args):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True)
    record = {"argv": ["git", *args], "exit_code": result.returncode,
              "stdout": result.stdout.decode(), "stderr": result.stderr.decode()}
    commands.append(record)
    assert result.returncode == 0, record
    return result.stdout


work = Path(tempfile.mkdtemp(prefix="roundtrip-", dir=ROOT))
git(work, "init", "--quiet")
(work / SCRIPT).parent.mkdir(parents=True)
shutil.copyfile(pre, work / SCRIPT)
git(work, "add", "--", SCRIPT)
shutil.copyfile(post, work / SCRIPT)
patch = git(work, "diff", "--full-index", "--binary", "--no-ext-diff", "--", SCRIPT)
(ROOT / "v2-to-v3.delta.patch").write_bytes(patch)
(ROOT / "full.patch").write_bytes(patch)
shutil.copyfile(pre, work / SCRIPT)
git(work, "apply", "--check", str(ROOT / "full.patch"))
git(work, "apply", str(ROOT / "full.patch"))
assert (work / SCRIPT).read_bytes() == post.read_bytes()
git(work, "apply", "--reverse", "--check", str(ROOT / "full.patch"))
git(work, "apply", "--reverse", str(ROOT / "full.patch"))
assert (work / SCRIPT).read_bytes() == pre.read_bytes()

parser = runpy.run_path(str(post), run_name="positive_receipt_static_review")
required = [parser["CASE"], "acl::tests::existing_native_deny_does_not_require_write_dac",
            "acl::tests::native_file_and_directory_repairs_are_idempotent_for_read_and_write",
            "token::tests::partial_delete_deny_is_repaired_before_native_workspace_writes"]
actual = WORKSPACE / "architecture-audit/b11-pr4884-ci-20261105/terminal/probe-127429723742"
members = actual / "members"
source = members / "b11-token-mechanism-probe"
checkout, tree = (source / "source-head-tree.txt").read_text().splitlines()
assert checkout == "b5c23d8943a0a36a14a962175cb2ec75d22d5553"
assert tree == "29316e75554590382268dafa77869fab0394a264"
actual_terminal_path = source / "acl-identity-counterfactual/counterfactual-terminal.json"
actual_terminal = json.loads(actual_terminal_path.read_text())
assert actual_terminal["status"] == "INVALID_OR_NOT_RUN"
assert actual_terminal["source_mutation_attempted"] is False
assert actual_terminal["source_mutated"] is False
assert actual_terminal["physical_oracle_reached"] is False
assert actual_terminal["restore_error"] is None
records, retained_manifest = parser["retained_log"](members / "bazel-execution-logs", checkout, tree, False)
text = parser["ANSI"].sub("", records[".log"][0].decode()).replace("\r", "")
assert parser["target_terminal"]((source / "bazel-console.log").read_bytes(), "FAILED")
failed = re.findall(r"^---- (.+) stdout ----$", text, re.M)
assert len(failed) == 7 and not set(failed).intersection(required)
old_full_line_counts = {case: len(re.findall(r"^test " + re.escape(case) + r" \.\.\. ok$", text, re.M)) for case in required}
assert list(old_full_line_counts.values()) == [1, 1, 1, 0]
raw_interleaved_lines = [{"line": n, "raw": line} for n, line in enumerate(text.splitlines(), 1) if required[-1] in line]
assert len(raw_interleaved_lines) == 1
prior, = (WORKSPACE / "architecture-audit/b11-pr4884-ci-20261105/terminal/probe-127383345954/members/bazel-execution-logs/failed-test-logs").glob("*/targets/0000/test.log")
assert f"---- {required[1]} stdout ----" in prior.read_text()
validation = save("static-verification.json", {
    "kind": "V3_REAL_ORIGINAL_INPUT_AND_EXACT_SOURCE_DELTA_REVIEW",
    "AST_parse_only": True, "old_non_main_functions_byte_equal": unchanged,
    "old_initial_whole_source_and_console_checks_byte_equal": True,
    "entire_negative_argv_oracle_exception_finally_terminal_tail_byte_equal": True,
    "workflow_byte_equal": True, "git_commands": commands, "forward_inverse_exact": True,
    "native7_original_terminal": pin(actual_terminal_path), "native7_retained_manifest": retained_manifest,
    "native7_full_log": records[".log"][1], "native7_full_XML": records[".xml"][1],
    "native7_old_four_whole_line_counts": old_full_line_counts,
    "native7_interleaved_line_unchanged": raw_interleaved_lines,
    "native7_original_failure_headers": failed,
    "actual_prior_required_case_failure_header_rejected_before_additional_scopes": {
        "source": pin(prior), "case": required[1], "has_original_failure_header": True},
    "pure_actual_archive_parsers_only": True, "main_or_project_or_native_executed": False,
    "new_exact_positive_runs": 0, "negative_runs": 0,
    "limit": "V3's four new positive executions and the negative remain unexecuted. No corrupted PASS line is repaired or accepted."
})
added = sum(line.startswith(b"+") and not line.startswith(b"+++") for line in patch.splitlines())
removed = sum(line.startswith(b"-") and not line.startswith(b"---") for line in patch.splitlines())
manifest = save("manifest-DISABLED.json", {
    "schema": "b11-identity-counterfactual-windows-harness-candidate-v3",
    "status": "DISABLED_UNAPPLIED_PENDING_INDEPENDENT_REVIEW_AND_NATIVE",
    "base": {"head": "0f6148ea3fbe9d1263354791d5cc63c7e66d4628",
             "head_tree": "f717a84a856413d87a3b718b0bcae3adbd16b643",
             "actual_prior_checkout": checkout, "actual_prior_tree": tree},
    "paths": [{"repository_path": SCRIPT, "mode": "100644", "preimage": pin(pre), "postimage": pin(post)}],
    "patch": pin(ROOT / "full.patch"), "change_counts": {"paths": 1, "added": added, "removed": removed},
    "unchanged_workflow": pin(workflow),
    "actual_defect": "Native7 original whole target remained 147P/7F/2I. Concurrent observation output split a PASS record; V2 rejected before any source mutation or negative command. That original INVALID result remains immutable.",
    "required_original_cases": required,
    "protocol": [
        "Preserve the original full-target command, selected tests, raw log/XML, ordinary 0/3 exit, no-cache predicate and exact current source guards. A required case present in any original failed-test header stops before all new scopes.",
        "Do not reconstruct or accept interleaved PASS text. In the same job run each of the four original cases once with its full name plus --exact, same original wrapper/target/platform/configuration, --nocache_test_results and --flaky_test_attempts=1. No multi-filter assumption, retry or additional test is introduced.",
        "Each exact positive has its own newly created evidence/archive directory, full console/log/XML, command/exit, source/index/locks guards, one nonignored PASS/zero FAIL/155 filtered libtest summary and successful outer XML. A missing name yields zero tests and is rejected.",
        "Any exact-positive failure stops remaining scopes and the negative without changing source. Original whole-target failure remains visible and is never replaced by these qualification records.",
        "Only after all four exact positives qualify, run the original frozen negative and finally tail unchanged: physical replacement marker, macro597:9, original assertion, XML101, precise one-case failure, then guarded exact restore.",
        "The 120-minute original job budget, Rust source/tests, all access controls, and existing helper functions/terminal/source-restored interfaces remain unchanged."
    ],
    "positive_terminal": {"ordinary_bazel_exit": 0, "target": "noncached PASSED", "selected_name": "one exact full name per command",
                          "libtest": {"passed": 1, "failed": 0, "ignored": 0, "filtered_out": 155},
                          "outer_XML": "one status=run testcase with no error/failure/skipped", "attempts_each": 1},
    "negative_change": "None: full original tail byte-equal, including argv/marker/597/XML101/finally/source restoration and terminal.",
    "future_helper_interface": {"unchanged_functions": unchanged, "source_entry_and_source_restored_schema_unchanged": True,
                                "new_optional_terminal_field": "positive_scopes", "consumer_source_pin_requires_explicit_update": True},
    "scope_limits": ["No exact positive or negative execution in this preparation.",
                     "The old full result is preserved, not retried or repaired in evidence.",
                     "This does not repair strict-token outside deletion or the ordinary-host Neither failures.",
                     "No native host, project source, ref or PR mutation by this author."],
    "static_validation": validation
})
print(json.dumps({"manifest": manifest, "post": pin(post), "patch": pin(ROOT / "full.patch"), "validation": validation,
                  "added": added, "removed": removed}, indent=2))
