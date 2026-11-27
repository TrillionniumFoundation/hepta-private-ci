"""Freeze source-pinned historical repairs without importing training code."""

import argparse
import ast
import hashlib
import json
import platform
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TEST_PATH = "scripts/test_run_hepta_local_closeout.py"
SOURCE_PATHS = (
    "scripts/run_hepta_local_closeout.py",
    TEST_PATH,
    ".github/workflows/hepta-p6-codex-native-parity.yml",
)
CASE_IDS = ("newline-syntax", "hosted-loader-fixture", "git-index-flag-reset")
COMMAND = [
    "python3",
    "-m",
    "unittest",
    "discover",
    "-v",
    "-s",
    "scripts",
    "-p",
    "test_run_hepta_local_closeout.py",
]
ARMS = ("no-op", "wrong-action", "oracle", "exact", "tfidf")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path, data):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write("\n")


def file_record(path):
    data = Path(path).read_bytes()
    return {"sha256": digest(data), "bytes": len(data)}


def test_audit(before, after):
    def inspect(data):
        source = data.decode("utf-8")
        names = re.findall(r"^    def (test_\w+)\(", source, flags=re.M)
        try:
            tree = ast.parse(source)
        except SyntaxError as error:
            return names, {}, {"message": error.msg, "line": error.lineno}
        methods = {
            node.name: ast.dump(node, include_attributes=False)
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        }
        return names, methods, None

    old_names, old_methods, old_error = inspect(before)
    new_names, new_methods, new_error = inspect(after)
    removed = sorted(set(old_names) - set(new_names))
    if removed or new_error or len(new_names) != len(set(new_names)):
        raise ValueError("Original repair removed tests or has invalid postimage")
    return {
        "before_test_names": old_names,
        "after_test_names": new_names,
        "removed_tests": removed,
        "added_tests": sorted(set(new_names) - set(old_names)),
        "changed_existing_tests": (
            sorted(
                name for name in old_methods if old_methods[name] != new_methods[name]
            )
            if not old_error
            else None
        ),
        "before_parse_error": old_error,
        "after_parse_error": new_error,
        "fix_changes_tests": True,
        "production_source_unchanged": True,
        "workflow_unchanged": True,
    }


def failure_query(log):
    """Keep observed diagnostic lines; remove timestamps and terminal colors."""
    rows = []
    for line in log.splitlines():
        line = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line)
        line = re.sub(r"^\ufeff?\d{4}-\d\d-\d\dT\S+\s+", "", line)
        if re.match(r"(?:FAIL:|ERROR:|AssertionError:|SyntaxError:)", line):
            rows.append(line)
    if not rows:
        raise ValueError("No original diagnostic in log")
    return "\n".join(rows)


def freeze(destination):
    destination.mkdir(parents=True, exist_ok=False)
    input_inventory = {}
    cases = []
    for case_id in CASE_IDS:
        evidence = ROOT / "evidence" / case_id
        github = load_json(evidence / "github.json")
        before_sha, after_sha = github["before"], github["after"]
        if github["fix_commit"]["parents"] != [before_sha]:
            raise ValueError("Not a direct-parent repair")
        failure, success = github["failure"], github["success"]
        if (failure["head_sha"], success["head_sha"]) != (before_sha, after_sha):
            raise ValueError("Run SHA mismatch")
        if failure["conclusion"] != "failure" or success["conclusion"] != "success":
            raise ValueError("Run conclusion mismatch")
        if failure["path"] != success["path"]:
            raise ValueError("Different workflows")
        if (
            not failure["updated_at"]
            < github["fix_commit"]["committed_at"]
            < success["created_at"]
        ):
            raise ValueError("Not a chronological hosted-failure / fix / success pair")
        files = github["fix_commit"]["files"]
        if len(files) != 1 or files[0]["filename"] != TEST_PATH:
            raise ValueError("Unexpected changed file")
        old_root, new_root = (
            ROOT / "source_bundle" / sha for sha in (before_sha, after_sha)
        )
        old, new = (
            root.joinpath(TEST_PATH).read_bytes() for root in (old_root, new_root)
        )
        git_blob = hashlib.sha1(f"blob {len(new)}\0".encode() + new).hexdigest()
        if git_blob != files[0]["sha"]:
            raise ValueError("Downloaded fixed file differs from GitHub commit blob")
        for path in SOURCE_PATHS:
            if (
                path != TEST_PATH
                and (old_root / path).read_bytes() != (new_root / path).read_bytes()
            ):
                raise ValueError("Production runner or workflow changed")
            for root in (old_root, new_root):
                member = root / path
                input_inventory[str(member.relative_to(ROOT))] = file_record(member)
        for member in sorted(evidence.iterdir()):
            input_inventory[str(member.relative_to(ROOT))] = file_record(member)
        patch_text = (
            f"diff --git a/{TEST_PATH} b/{TEST_PATH}\n"
            f"--- a/{TEST_PATH}\n+++ b/{TEST_PATH}\n" + files[0]["patch"] + "\n"
        )
        patch_path = destination / f"{case_id}.patch"
        patch_path.write_text(patch_text, encoding="utf-8", newline="\n")
        query = failure_query((evidence / "failure.log").read_text(encoding="utf-8"))
        signature = {
            "newline-syntax": ["SyntaxError: invalid syntax"],
            "hosted-loader-fixture": [
                "BLOCKED_UNREVIEWED_ENVIRONMENT",
                "LD_LIBRARY_PATH",
                "PKG_CONFIG_PATH",
            ],
            "git-index-flag-reset": [
                "FAIL: test_hidden_index_flags_rejected_even_for_unrequired_source",
                "AssertionError: False is not true",
            ],
        }[case_id]
        cases.append(
            {
                "id": case_id,
                "before": before_sha,
                "after": after_sha,
                "failure_run": failure["id"],
                "success_run": success["id"],
                "patch": patch_path.name,
                "patch_record": file_record(patch_path),
                "query": query,
                "failure_signature": signature,
                "preimage": digest(old),
                "postimage": digest(new),
                "fixed_git_blob_sha1": git_blob,
                "test_change_audit": test_audit(old, new),
            }
        )
    code = {path.name: file_record(path) for path in sorted(ROOT.glob("replay_*.py"))}
    plan = {
        "schema": "hepta.historical-procedure-replay.v1",
        "scope": "Known historical development execution plumbing; no learned policy, future-task or capacity claim",
        "cases": cases,
        "arms": ARMS,
        "command": COMMAND,
        "wrong_action": "Next case cyclically in fixed CASE_IDS order",
        "retrieval": "Exact and TF-IDF use the same observed failure diagnostic as query and library document; known-incident replay only",
        "tfidf": {
            "token_regex": "[a-z0-9_]+",
            "tf": "1+log(count)",
            "idf": "1+log((N+1)/(df+1))",
            "similarity": "cosine",
            "tie_break": "library order",
        },
        "action_contract": "Full test-file preimage SHA-256, actual git apply --check then git apply, fixed postimage SHA-256; production/workflow immutable",
        "observer": "Actual raw exit/log plus immutable source hashes and original failure signature; no-op must reproduce for a repair effect",
        "environment": "Inherit current environment; set only PYTHONDONTWRITEBYTECODE=1 as original workflow; no loader injection",
        "timeouts_seconds": 120,
        "max_log_bytes": 1048576,
        "learned_route": {
            "status": "unavailable",
            "model_calls": 0,
            "reason": "No artifact trained or authorized for these new incident/action IDs",
        },
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
            "git": subprocess.check_output(["git", "--version"], text=True).strip(),
        },
        "inputs": input_inventory,
        "code": code,
        "limitations": [
            "Minimal target-module closure; not the entire original workflow",
            "All actions are genuine test/fixture repairs",
            "Nonreproduced failures remain in output but have no repair-effect score",
            "Observer shares the local process principal and is not an authenticated independent signer",
        ],
    }
    save_json(destination / "plan.json", plan)
    print(digest((destination / "plan.json").read_bytes()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    freeze(parser.parse_args().output.resolve())
