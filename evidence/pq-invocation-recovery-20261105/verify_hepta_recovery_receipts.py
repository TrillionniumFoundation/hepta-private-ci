#!/usr/bin/env python3
"""Check local recovery receipts against the frozen workflow's two rosters.

This reads evidence only. It neither runs tests nor authenticates arbitrary
stdout. Full-library observations are not the original selected hosted jobs.
Missing/running/failed receipts never pass. Exit zero requires both rosters.
The expected source and tree are explicit full object IDs, never the current
worktree HEAD. Inspect different source attempts in separate invocations; an
older failure or success cannot be relabelled as evidence for a repair commit.
"""

import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

WORKFLOW = ".github/workflows/hepta-pq-policy-renewal.yml"
GROUPS = {"owner": (17, "codex-hepta-evidence"), "signed": (11, "codex-hepta-agentd")}
# These are the exact ANSI and per-test patterns in the frozen workflow reader.
ANSI = re.compile(r"\x1b\[[0-9;]*m")
CASE = re.compile(r"^test ([A-Za-z0-9_:]+) \.\.\. (ok|ignored|FAILED)\s*$", re.M)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def git(repo, *arguments):
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    env.update(
        GIT_NO_LAZY_FETCH="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_GRAFT_FILE=os.devnull,
    )
    return subprocess.check_output(
        [
            "git",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "advice.graftFileDeprecated=false",
            "-C",
            str(repo),
            *arguments,
        ],
        env=env,
    )


def selector_names(expression):
    names = re.findall(r"test\(=([A-Za-z0-9_:]+)\)", expression)
    residue = re.sub(r"test\(=[A-Za-z0-9_:]+\)", "", expression)
    require(not residue.replace("|", "").strip(), "unrecognized selector grammar")
    require(len(names) == len(set(names)), "duplicate selector identity")
    return set(names)


def load_contract(repo, source, tree):
    require(re.fullmatch(r"[0-9a-f]{40}", source), "source must be a full commit ID")
    require(re.fullmatch(r"[0-9a-f]{40}", tree), "tree must be a full tree ID")
    require(
        git(repo, "rev-parse", f"{source}^{{commit}}").decode().strip() == source,
        "source is not the requested commit object",
    )
    require(
        git(repo, "rev-parse", f"{source}^{{tree}}").decode().strip() == tree,
        "frozen source/tree mismatch",
    )
    workflow_bytes = git(repo, "show", f"{source}:{WORKFLOW}")
    workflow = workflow_bytes.decode("utf-8")
    rosters = {}
    for group, (count, package) in GROUPS.items():
        blocks = [
            block
            for block in re.split(r"(?m)^      - name:", workflow)
            if f'--output "$RUNNER_TEMP/pq-policy-renewal/recovery-{group}.json"'
            in block
        ]
        require(len(blocks) == 1, f"missing/ambiguous {group} workflow step")
        block = blocks[0]
        require(
            f"--minimum-tests {count} --timeout-seconds 600 --" in block,
            f"{group} workflow count/budget changed",
        )
        require(
            f"just test --locked -p {package} --lib" in block,
            f"{group} workflow package changed",
        )
        names = selector_names(re.search(r"-E '([^']+)'", block, re.S).group(1))
        require(len(names) == count, f"{group} workflow roster is not {count}")
        rosters[group] = names
    # Reuse the actual official terminal-summary reader, from the same Git object.
    reader_bytes = git(repo, "show", f"{source}:scripts/hepta_ci_exec.py")
    namespace = {"__name__": "_frozen_hepta_receipt_reader"}
    exec(compile(reader_bytes, "scripts/hepta_ci_exec.py", "exec"), namespace)
    pins = re.search(r"tool: just@([^,\s]+),nextest@([^\s]+)", workflow)
    require(pins is not None, "workflow tool pins missing")
    return (
        rosters,
        namespace["observed_test_counts"],
        {
            "source_sha": source,
            "tree": tree,
            "workflow": WORKFLOW,
            "workflow_sha256": hashlib.sha256(workflow_bytes).hexdigest(),
            "official_reader_sha256": hashlib.sha256(reader_bytes).hexdigest(),
            "workflow_tools": {"just": pins[1], "nextest": pins[2]},
        },
    )


def check_receipt(path, group, names, observed_counts, source, tree):
    result = {
        "passed": False,
        "status": "PENDING",
        "receipt": str(path) if path else None,
        "expected_source_sha": source,
        "expected_tree": tree,
        "required_tests": sorted(names),
    }
    if path is None or not path.is_file():
        result["reason"] = "receipt not supplied or missing"
        return result
    try:
        receipt_bytes = path.read_bytes()
        record = json.loads(receipt_bytes)
        result["receipt_sha256"] = hashlib.sha256(receipt_bytes).hexdigest()
        result["recorded_status"] = record.get("status")
        result["recorded_source_sha"] = record.get("source_sha")
        result["recorded_tested_sha"] = record.get("tested_sha")
        result["recorded_before"] = record.get("before")
        result["recorded_after"] = record.get("after")
        result["recorded_exit_code"] = record.get("exit_code")
        result["recorded_command_exit_code"] = record.get("command_exit_code")
        result["recorded_passed_tests"] = record.get("observed_passed_tests")
        result["recorded_failed_tests"] = record.get("observed_failed_tests")
        require(record.get("schema_version") == 1, "unsupported receipt schema")
        require(
            record.get("source_sha") == source
            and record.get("tested_sha") == source
            and record.get("lane") == "source-head",
            "wrong source/tested SHA or lane; retain this attempt under its original source",
        )
        if record.get("status") == "running":
            result["reason"] = (
                "official receipt is running; partial logs are not a result"
            )
            return result
        before = record["before"]
        require(
            before == record["after"]
            and before.get("commit") == source
            and before.get("tree") == tree
            and before.get("dirty") is False,
            "before/after source identity does not match frozen clean source",
        )
        require(record.get("status") == "passed", "receipt is not passed")
        for field in (
            "command_exit_code",
            "returncode",
            "exit_code",
            "observed_failed_tests",
        ):
            require(
                type(record.get(field)) is int and record[field] == 0,
                f"nonzero/missing {field}",
            )
        require(
            record.get("timed_out") is False
            and record.get("output_limit_exceeded") is False,
            "timeout/output status is not successful",
        )
        require(
            not record.get("error") and record.get("finished_at"),
            "incomplete/error receipt",
        )
        count, package = GROUPS[group]
        require(record.get("minimum_tests") == count, "different recorded minimum")
        command = record["command"]
        prefix = ["just", "test", "--locked", "-p", package, "--lib"]
        tail = ["--no-capture", "--retries", "0", "--test-threads=1"]
        require(command[: len(prefix)] == prefix, "different package/command")
        suffix = command[len(prefix) :]
        full_library = suffix == tail
        require(
            full_library
            or (
                len(suffix) == 2 + len(tail)
                and suffix[0] == "-E"
                and suffix[2:] == tail
                and selector_names(suffix[1]) == names
            ),
            "command is neither full library nor the exact selected roster",
        )
        result["command"] = command
        result["run_scope"] = (
            "local full-library observation containing the required roster"
            if full_library
            else "local selected-roster command"
        )
        result["original_selected_workflow_invocation"] = False
        log_name = record["log_file"]
        require(
            isinstance(log_name, str) and Path(log_name).name == log_name,
            "log_file must be the retained sibling basename",
        )
        raw = (path.parent / log_name).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        require(
            digest == record["log_sha256"] and len(raw) == record["log_bytes"],
            "retained log hash/length mismatch",
        )
        text = ANSI.sub("", raw.decode("utf-8"))
        passed, failed = observed_counts(text)
        require(
            passed == record["observed_passed_tests"]
            and failed == 0
            and passed >= count,
            "official summary does not match the successful receipt",
        )
        cases = CASE.findall(text)
        outcomes = defaultdict(list)
        for name, outcome in cases:
            outcomes[name].append(outcome)
        bad = {
            name: outcomes[name] for name in sorted(names) if outcomes[name] != ["ok"]
        }
        result.update(
            log_file=log_name,
            log_sha256=digest,
            observed_passed_tests=passed,
            required_outcomes={name: outcomes[name] for name in sorted(names)},
            extra_case_count=sum(name not in names for name, _ in cases),
        )
        require(not bad, f"required tests missing, skipped, failed or repeated: {bad}")
        if not full_library:
            require(
                len(cases) == count and passed == count,
                "selected roster contains extra cases",
            )
        result.update(passed=True, status="PASS")
    except (OSError, ValueError, KeyError, TypeError) as error:
        result.update(status="FAIL", reason=str(error))
    return result


def tool_observation(directory, expected):
    observations = {}
    for name, binary in (("just", "just"), ("nextest", "cargo-nextest")):
        path = directory / binary
        try:
            line = subprocess.check_output(
                [str(path), "--version"], text=True, timeout=10
            ).splitlines()[0]
            version = line.split()[1]
            observations[name] = {
                "path": str(path),
                "version": version,
                "workflow_pin": expected[name],
                "matches_pin": version == expected[name],
            }
        except (OSError, ValueError, IndexError, subprocess.SubprocessError) as error:
            observations[name] = {"matches_pin": False, "error": str(error)}
    return observations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[1] / "hepta"
    )
    parser.add_argument("--source", required=True, help="full expected tested commit ID")
    parser.add_argument("--tree", required=True, help="full expected tested tree ID")
    parser.add_argument("--owner-receipt", type=Path)
    parser.add_argument("--signed-receipt", type=Path)
    parser.add_argument(
        "--tool-dir",
        type=Path,
        default=Path(
            "/workspace/scratch/822cc50e24f0/authority-recovery/native-20261105/bin"
        ),
    )
    args = parser.parse_args()
    try:
        rosters, counts, contract = load_contract(args.repo, args.source, args.tree)
        results = {
            group: check_receipt(
                getattr(args, f"{group}_receipt"), group, names, counts,
                args.source, args.tree,
            )
            for group, names in rosters.items()
        }
        passed = all(result["passed"] for result in results.values())
        report = {
            "status": "LOCAL_ROSTERS_PASS" if passed else "NOT_PASSED",
            "contract": contract,
            "rosters": results,
            "local_tools": tool_observation(args.tool_dir, contract["workflow_tools"]),
            "hosted_qualification": False,
            "limits": "Receipt lacks configured timeout and binary hashes; neither is inferred. "
            "Tool probes describe this local environment, not attested receipt provenance.",
        }
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        subprocess.SubprocessError,
    ) as error:
        passed = False
        report = {
            "status": "NOT_PASSED",
            "requested_source_sha": args.source,
            "requested_tree": args.tree,
            "error": str(error),
            "hosted_qualification": False,
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
