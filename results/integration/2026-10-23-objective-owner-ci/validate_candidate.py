#!/usr/bin/env python3
"""Static-only owner CI validation: YAML shape, Bash parsing and Python compilation."""
from pathlib import Path
import ast
import datetime
import hashlib
import json
import re
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parent
WORKFLOW = ROOT / "change/.github/workflows/hepta-objective-owner.yml"
OUT = ROOT / "validation"


class UniqueLoader(yaml.BaseLoader):
    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in result:
                raise ValueError(f"Duplicate YAML key: {key}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def fingerprint(path):
    data = path.read_bytes()
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }


def main():
    text = WORKFLOW.read_text()
    document = yaml.load(text, Loader=UniqueLoader)
    assert list(document["on"]) == ["pull_request"]
    assert "branches" not in document["on"]["pull_request"]
    assert set(document["on"]["pull_request"]["types"]) == {
        "opened", "synchronize", "reopened", "ready_for_review"
    }
    assert document["permissions"] == {"contents": "read"}
    assert len(document["jobs"]) == 1
    job = document["jobs"]["owning-packages"]
    assert "if" not in job and "strategy" not in job
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["timeout-minutes"] == "240"
    assert job["env"]["RUSTUP_TOOLCHAIN"] == "1.95.0"
    assert job["env"]["CARGO_BUILD_JOBS"] == "1"
    assert job["env"]["CARGO_INCREMENTAL"] == "0"
    assert job["env"]["SOURCE_SHA"] == "${{ github.event.pull_request.head.sha }}"
    assert job["env"]["BASE_SHA"] == "${{ github.event.pull_request.base.sha }}"
    steps = job["steps"]
    identifiers = [step["id"] for step in steps if "id" in step]
    assert len(identifiers) == len(set(identifiers))
    by_id = {step["id"]: step for step in steps if "id" in step}
    checkout = by_id["checkout"]
    assert checkout["with"] == {
        "ref": "${{ env.SOURCE_SHA }}", "fetch-depth": "0", "persist-credentials": "false"
    }
    assert by_id["tools"]["uses"] == "./.github/actions/prepare-bazel-ci"
    assert by_id["nextest"]["with"]["tool"] == "nextest@0.9.103"
    assert by_id["v8"]["env"]["RUSTY_V8_ARCHIVE"] == ""
    assert by_id["v8"]["env"]["RUSTY_V8_SRC_BINDING_PATH"] == ""
    assert by_id["v8"]["env"]["V8_FROM_SOURCE"] == "0"
    assert steps[-1]["if"] == "always()" and steps[-2]["if"] == "always()"
    assert steps[-1]["with"]["if-no-files-found"] == "error"

    known_actions = set()
    for path in (ROOT / "base/.github").rglob("*.yml"):
        known_actions.update(re.findall(r"\buses:\s*([^\s#]+)", path.read_text()))
    action_checks = []
    for step in steps:
        if "uses" not in step:
            continue
        uses = step["uses"]
        assert uses in known_actions, uses
        assert uses.startswith("./") or re.fullmatch(r"[^@]+@[0-9a-f]{40}", uses), uses
        action_checks.append({"uses": uses, "present_in_original_workflow_or_action": True})

    checks = []
    embedded = []
    for number, step in enumerate(steps, 1):
        if "run" not in step:
            continue
        assert step["shell"] == "bash"
        name = step.get("id", f"step-{number:02d}")
        shell_path = OUT / "shell" / (name + ".bash")
        shell_path.parent.mkdir(parents=True, exist_ok=True)
        shell_path.write_text(step["run"])
        result = subprocess.run(["bash", "-n", str(shell_path)], capture_output=True, check=False)
        (shell_path.with_suffix(".stdout")).write_bytes(result.stdout)
        (shell_path.with_suffix(".stderr")).write_bytes(result.stderr)
        checks.append({"step": name, "command": ["bash", "-n", str(shell_path)], "exit_code": result.returncode,
                       "script": str(shell_path), **fingerprint(shell_path)})
        assert result.returncode == 0, (name, result.stderr.decode())
        lines = step["run"].splitlines()
        index = 0
        while index < len(lines):
            match = re.search(r"<<'([A-Za-z_][A-Za-z_0-9]*)'", lines[index])
            if not match:
                index += 1
                continue
            marker = match.group(1)
            end = index + 1
            while end < len(lines) and lines[end] != marker:
                end += 1
            assert end < len(lines), (name, marker)
            program = "\n".join(lines[index + 1:end]) + "\n"
            path = OUT / "embedded-python" / f"{name}-{len(embedded) + 1:02d}.py"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(program)
            tree = ast.parse(program, filename=str(path))
            compile(tree, str(path), "exec")
            embedded.append({"step": name, "script": str(path), **fingerprint(path),
                             "python_ast_parse": "passed", "python_compile_without_execution": "passed"})
            index = end + 1
    assert len(embedded) == 4
    runner = next(Path(row["script"]).read_text() for row in embedded if row["step"] == "source")
    required_fragments = [
        '"just", "test", "--locked", "--cargo-profile", "dev-small"',
        '"--build-jobs", "1", "--test-threads", "1", "-p", package, "--lib", "--no-tests", "fail"',
        '"memory": "codex-hepta-memory", "agentd": "codex-hepta-agentd"',
        '"just", "fix", "-p", package, "--locked", "--profile", "dev-small", "--lib"',
        '"just", "fmt", "--check", "--base", BASE',
        '"cargo", "metadata", "--locked", "--no-deps", "--format-version", "1"',
        '"python3", "scripts/hepta_ci_v8.py"',
        'len(members) != 193',
        'value["files_sha256"] == original["files_sha256"]',
        '"production_composition::objective_sender_tests::": 3',
        '"production_composition::tests::": 7',
        '"production_composition::notes_tests::": 5',
        '"production_authority::tests::": 5',
        '"final_use_issuer::tests::": 7',
    ]
    assert all(fragment in runner for fragment in required_fragments)
    assert '"-E"' not in runner and '"--filterset"' not in runner
    assert '"--all-features"' not in runner and '"--workspace"' not in runner
    assert '"--offline"' not in runner  # CI must be able to fetch the unchanged locked original graph.
    receipt = {
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "Local static source validation only; no candidate workflow, embedded command, Cargo command or CI job executed.",
        "workflow": {"path": str(WORKFLOW), **fingerprint(WORKFLOW), "lines": len(text.splitlines())},
        "python_version": sys.version,
        "yaml_parser": "PyYAML " + yaml.__version__ + " BaseLoader with duplicate-key rejection",
        "yaml_parse_and_reviewed_schema_assertions": "passed",
        "actions": action_checks,
        "bash_syntax": checks,
        "embedded_python_syntax": embedded,
        "workflow_executed": False, "Cargo_executed": False,
        "GitHub_actionlint_executed": False,
        "qualification": "Source and syntax evidence only; actual GitHub setup/build/test/Clippy behavior remains to be executed on the published PR head.",
    }
    path = OUT / "candidate-syntax.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"receipt": str(path), "workflow": receipt["workflow"],
                      "bash_blocks": len(checks), "python_blocks": len(embedded),
                      "syntax_passed": True, "workflow_executed": False}, indent=2))


if __name__ == "__main__":
    main()
