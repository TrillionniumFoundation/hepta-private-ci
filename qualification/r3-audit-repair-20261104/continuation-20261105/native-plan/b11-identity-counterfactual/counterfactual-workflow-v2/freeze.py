from pathlib import Path
import ast
import hashlib
import json
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parents[2]
WORKFLOW = ".github/workflows/hepta-windows-token-mechanism-probe.yml"
SCRIPT = ".github/scripts/run_b11_acl_identity_counterfactual.py"
PATHS = [WORKFLOW, SCRIPT]


def pin(path):
    path = path.resolve()
    b = path.read_bytes()
    return {"path": str(path), "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(b)).encode() + b"\0" + b).hexdigest()}


def save(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


commands = []


def git(cwd, args):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True)
    record = {"argv": ["git", *args], "exit_code": r.returncode, "stdout": r.stdout.decode(), "stderr": r.stderr.decode()}
    commands.append(record)
    assert r.returncode == 0, record
    return r.stdout


assert pin(ROOT / "source" / WORKFLOW)["git_blob"] == "70f3145268e042ec04fbfe85eda83ccbbc4ff79c"
parsed = ast.parse((ROOT / "candidate" / SCRIPT).read_text())
original = (ROOT / "source" / WORKFLOW).read_text()
post = (ROOT / "candidate" / WORKFLOW).read_text()
start = post.index("      - name: Check the ACL identity counterfactual and restore its source\n")
end = post.index("      # The unchanged wrapper already retains", start)
added_step = post[start:end]
reconstructed = post[:start] + post[end:]
reconstructed = reconstructed.replace("      - .github/scripts/run_b11_acl_identity_counterfactual.py\n", "")
reconstructed = reconstructed.replace("        id: original_unit_target\n", "")
assert reconstructed == original

work = Path(tempfile.mkdtemp(prefix="generate-", dir=ROOT))
git(work, ["init", "--quiet"])
(work / WORKFLOW).parent.mkdir(parents=True)
shutil.copyfile(ROOT / "source" / WORKFLOW, work / WORKFLOW)
git(work, ["add", "--", WORKFLOW])
for path in PATHS:
    (work / path).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "candidate" / path, work / path)
git(work, ["add", "--intent-to-add", "--", SCRIPT])
patch = git(work, ["diff", "--binary", "--full-index", "--no-ext-diff", "--", *PATHS])
(ROOT / "full.patch").write_bytes(patch)
verify = Path(tempfile.mkdtemp(prefix="verify-", dir=ROOT))
git(verify, ["init", "--quiet"])
(verify / WORKFLOW).parent.mkdir(parents=True)
shutil.copyfile(ROOT / "source" / WORKFLOW, verify / WORKFLOW)
git(verify, ["add", "--", WORKFLOW])
git(verify, ["apply", "--check", str(ROOT / "full.patch")])
git(verify, ["apply", str(ROOT / "full.patch")])
assert all((verify / p).read_bytes() == (ROOT / "candidate" / p).read_bytes() for p in PATHS)
git(verify, ["apply", "--reverse", "--check", str(ROOT / "full.patch")])
git(verify, ["apply", "--reverse", str(ROOT / "full.patch")])
assert (verify / WORKFLOW).read_bytes() == (ROOT / "source" / WORKFLOW).read_bytes() and not (verify / SCRIPT).exists()
save("roundtrip.json", {"commands": commands, "postimages_exact": True, "reverse_exact": True,
                         "AST_parse_only": True, "project_or_windows_commands_executed": False})
counts = {"additions": sum(x.startswith(b"+") and not x.startswith(b"+++") for x in patch.splitlines()),
          "deletions": sum(x.startswith(b"-") and not x.startswith(b"---") for x in patch.splitlines()), "paths": 2}
assert counts["additions"] < 500
native = WORKSPACE / "architecture-audit/b11-pr4884-ci-20261105/terminal/probe-127383345954/members"
bat = WORKSPACE / "architecture-audit/original-exit-selection-5b-20261105/source/workspace_root_test_launcher.bat.tpl"
defs = WORKSPACE / "architecture-audit/b11-mic-physical-probe-20261105/source/defs.bzl"
collector = WORKSPACE / "architecture-audit/b11-mic-physical-probe-20261105/source/.github/scripts/collect_bazel_failed_test_logs.py"
assert pin(bat)["git_blob"] == "fa18c301dd22ca9023ba2f59801a8119dfbf8a69"
assert pin(defs)["git_blob"] == "6f588ec3057fddfea35170e28e74036162ce6a23"
assert pin(collector)["git_blob"] == "2142eeb382664d95f77d83ac7ae3da4459601abf"
manifest = {
    "schema": "b11-identity-counterfactual-windows-workflow-candidate-v2",
    "status": "DISABLED_UNAPPLIED_PENDING_ROOT_AND_INDEPENDENT_REVIEW",
    "product_source": {"published_head": "19d2fdfcaefbb41cdf2a72754d695d4b47cb3f14",
                       "positive_blob": "da5346c220c41cf0c83f62b596132c74c02284d8",
                       "negative_blob": "0baeb6ec2f3bfd0964be6d014fc5d80d890ea3d7",
                       "test_blob_unchanged": "ec0264a7615097bec1b554cb60918b4f4662eec2",
                       "source_candidate_manifest": "64b84c70930361580d65fe0d47e4b44733ef36b4",
                       "frozen_Rust_source_changes": 0},
    "paths": [{"repository_path": p, "mode": "100644", "preimage": pin(ROOT / "source" / p) if p == WORKFLOW else None,
               "postimage": pin(ROOT / "candidate" / p)} for p in PATHS],
    "change_counts": counts, "patch": pin(ROOT / "full.patch"),
    "original_target_preservation": {
        "exact_original_workflow_after_removing_three_additions": True,
        "three_additions": ["New script exact path trigger", "Step ID on original target", "One subsequent conditional counterfactual step"],
        "original_full_command_return_code_assertions_target_retry_budget_artifact_paths": "All byte-identical.",
        "failure_remains_visible": "Original full-target step is never continue-on-error and still exits its original Bazel code. A successful counterfactual step cannot turn its failure into success.",
        "runner": "Same existing windows-latest job and prepared MSVC environment, 120-minute whole-job budget unchanged.",
        "new_permissions_or_secrets": False
    },
    "new_execution_protocol": [
        "Read-only exact positive source/test Git-blob and clean checkout/index/lock guards; accept uniform LF or uniform CRLF worktree only, keep original raw bytes.",
        "Require original whole-target ordinary exit 0/3, successful full console copy, clean source snapshots and noncached/nonflaky PASSED/FAILED target terminal. Read only the wrapper's exact source-bound target log/XML copies.",
        "Require each of the two existing directory repair cases, existing no-WRITE_DAC case, and new replacement case to have one exact PASS in that complete original target log. Otherwise do not mutate or execute the negative.",
        "Atomically install only the approved negative source; both ID queries remain and the sole enforcement becomes an ignored comparison. Preserve the ordinary index and both locks; allow exactly that one tracked modification.",
        "Invoke the same outer Bazel target and wrapper/MSVC/selection flags, adding only full-case --test_arg plus --exact and fresh single-attempt controls. Negative artifacts use their own newly created compact-log directory inside this owned evidence root.",
        "Require ordinary Bazel exit3, noncached FAILED target, unique exact physical marker, exactly this failure header and panic macro597:9, exact DACL assertion message, one failed/zero passed/zero ignored/155 filtered libtest summary, and outer XML error101. A build error, timeout, crash, wrong assertion, missing/cached record or extra case cannot qualify.",
        "In finally, first require the known positive/negative bytes AND the complete corresponding source guard plus unchanged semantic ordinary index and both locks. Only then atomically restore original raw bytes and recheck exact clean entry state. Any unknown source/index/lock drift is preserved and reported, not overwritten.",
        "Record physical_oracle_reached separately from final qualified status. Qualification requires successful exact restoration; original full-target exit remains unchanged. Upload through the original existing artifact path and run the original clean-worktree check."
    ],
    "exact_route_evidence": {
        "defs": pin(defs), "Windows_launcher": pin(bat), "collector": pin(collector),
        "nonempty_args": "Windows template routes nonempty %* directly to its resolved test_bin and returns that exact ERRORLEVEL, including within run_selected_libtest. Full name plus --exact selects the one test; no reliance on TESTBRIDGE substring matching.",
        "current_native5_manifest": pin(native / "bazel-execution-logs/failed-test-logs/invocation-iloq9z78/manifest.json"),
        "current_native5_XML": pin(native / "bazel-execution-logs/failed-test-logs/invocation-iloq9z78/targets/0000/test.xml"),
        "terminal_limit": "Native5's original bat runs multiple batches and records exit1. The new argument route statically returns libtest101 directly; that new XML endpoint remains to be verified on actual Windows. A mismatch is a harness failure, not a valid negative."
    },
    "negative_additions_only": ["--build_metadata=TAG_b11_identity_counterfactual=true", "--nocache_test_results", "--flaky_test_attempts=1", "--test_arg=acl::tests::deny_repair_rejects_a_replaced_path_before_mutating_either_object", "--test_arg=--exact"],
    "negative_oracle": {"marker": "deny_repair_identity: directory=false returned_ok=true replacement_changed=true original_changed=false",
                        "assertion": "a replacement object must not receive the queried object's deny", "macro_line": 597,
                        "executed": False, "effective": False},
    "limits": ["No actual Windows execution or CI dispatch/ref mutation performed during preparation.",
               "B11 strict outside deletion remains OPEN even if this counterfactual validates.",
               "Normal exceptions run finally; a hard runner/process cancellation is not an exact-restoration guarantee and never supplies qualification.",
               "The original retained collector's recorded bytes and checkout are checked. Arbitrary remote test execution/authority is not inferred from a missing cached marker alone; this protocol is confined to the original hosted job and its owned evidence directory.",
               "A future formatter/source/roster change requires a separately reviewed update of pinned blobs, line and count; no dynamic relaxation."],
    "cloud_checks": {"Python_AST_parse": True, "Git_roundtrip": pin(ROOT / "roundtrip.json"),
                     "original_workflow_preserved": True, "script_executed": False, "native_executed": False}
}
save("manifest-DISABLED.json", manifest)
print(json.dumps({"counts": counts, "patch": pin(ROOT / "full.patch"), "manifest": pin(ROOT / "manifest-DISABLED.json"),
                  "posts": [pin(ROOT / "candidate" / x) for x in PATHS]}, indent=2))
