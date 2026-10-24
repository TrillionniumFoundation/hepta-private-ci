"""Lock natural BugsInPy sources and repository partitions before execution.

These are patch-local command decisions with supplied candidate-change context,
not unconstrained fault localization or synthetic repair mutations.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

PROJECT_SPLITS = {
    "youtube-dl": "train", "thefuck": "train", "luigi": "train", "scrapy": "train",
    "tqdm": "calibration", "PySnooper": "calibration", "black": "holdout", "tornado": "holdout",
}
DEPENDENCIES = (
    "pytest==5.4.3", "mock==4.0.2", "pytest-mock==3.1.0", "six==1.15.0", "nose==1.3.7",
    "click==7.1.2", "appdirs==1.4.4", "pathspec==0.8.0", "toml==0.10.1", "typed-ast==1.4.1",
    "regex==2020.6.8", "decorator==4.4.2", "psutil==5.7.0", "pexpect==4.8.0", "pyte==0.8.0",
    "colorama==0.4.3", "tornado==6.0.4", "python-dateutil==2.8.1", "python-daemon==2.2.4",
    "Twisted==20.3.0", "lxml==4.5.1", "parsel==1.6.0", "cssselect==1.1.0", "w3lib==1.21.0",
    "queuelib==1.5.0", "Protego==0.1.16", "PyDispatcher==2.0.5", "service-identity==18.1.0",
    "pyOpenSSL==19.1.0", "cryptography==2.9.2", "testfixtures==6.14.1", "Pillow==7.1.2",
)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def decode(path):
    raw = Path(path).read_bytes()
    return raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8")


def properties(path):
    return dict(re.findall(r'^\s*([a-z_]+)\s*=\s*"([^"]*)"\s*$', decode(path), re.MULTILINE))


def command_specs(text):
    specs = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        words = shlex.split(line)
        if words[:3] in (["python", "-m", "unittest"], ["python3", "-m", "unittest"]):
            runner, args = "unittest", words[3:]
        elif words[:3] in (["python", "-m", "pytest"], ["python3", "-m", "pytest"]):
            runner, args = "pytest", words[3:]
        elif words and words[0] == "pytest":
            runner, args = "pytest", words[1:]
        else:
            raise ValueError("unsupported upstream command: " + line)
        if any(arg.startswith("-") and arg not in ("-q", "-s", "-v") for arg in args):
            raise ValueError("unsupported test option")
        nodes = [arg for arg in args if not arg.startswith("-")]
        if not nodes or any(re.fullmatch(r"[A-Za-z0-9_./:\[\]-]+", n) is None for n in nodes):
            raise ValueError("malformed or shell-bearing test selector")
        specs.append({"original": line, "runner": runner, "nodes": nodes})
    if not specs:
        raise ValueError("no upstream test commands")
    return specs


def build_plan(root):
    root = Path(root)
    commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    projects, bugs = {}, []
    for project, split in PROJECT_SPLITS.items():
        directory = root / "projects" / project
        info = properties(directory / "project.info")
        if re.fullmatch(r"https://github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", info["github_url"]) is None:
            raise ValueError("unexpected project origin")
        projects[project] = {"url": info["github_url"], "split": split}
        for folder in sorted((directory / "bugs").iterdir(), key=lambda p: int(p.name) if p.name.isdigit() else -1):
            if not folder.is_dir() or not folder.name.isdigit():
                continue
            info = properties(folder / "bug.info")
            revisions = {name: info[key] for name, key in (("base", "buggy_commit_id"), ("candidate", "fixed_commit_id"))}
            if any(re.fullmatch(r"[0-9a-f]{40}", value) is None for value in revisions.values()):
                raise ValueError("full immutable source revisions required")
            tests = info["test_file"].split(";")
            if any(not path or path.startswith("/") or ".." in Path(path).parts for path in tests):
                raise ValueError("invalid test source path")
            records = {name: {"sha256": digest((folder / name).read_bytes()), "bytes": (folder / name).stat().st_size}
                       for name in ("bug.info", "run_test.sh", "requirements.txt", "bug_patch.txt") if (folder / name).is_file()}
            bugs.append({"group_id": "bugsinpy/" + project + "/" + folder.name, "project": project,
                "bug_id": int(folder.name), "split": split, "revisions": revisions, "test_files": tests,
                "upstream_python": info.get("python_version"), "declared_pythonpath": info.get("pythonpath"),
                "commands": command_specs(decode(folder / "run_test.sh")), "metadata_files": records})
    return {"schema": "hepta.operational-cohort-protocol.v1", "upstream": {
        "repository": "https://github.com/soarsmu/BugsInPy", "commit": commit},
        "projects": projects, "bugs": bugs, "python_version": "3.8.20", "dependencies": list(DEPENDENCIES),
        "partition_policy": "Entire project and all its revisions, modules, tests and bug groups remain in one partition.",
        "heldout_status": "new operational groups; no model metrics observed before protocol and selection freeze",
        "task_definitions": {
            "regression_outcome": {"family_id": "command_outcome_prediction", "classes": ["fails", "passes"],
                "decision": "Predict whether this actual regression command passes on the supplied candidate implementation.",
                "input": "Candidate-change source regions plus actual regression test source; no observed outcome."},
            "diagnostic_test_selection": {"family_id": "next_diagnostic_action", "classes": ["action_0", "action_1"],
                "decision": "Choose which real test distinguishes the two supplied implementation states.",
                "input": "Supplied candidate diff and two existing test commands/sources; no observed outcome."}},
        "context_policy": {"scope": "Patch-local decisions; candidate-change locations are supplied context, not inferred fault localization.",
            "production_context_lines": 40, "test_source": "selected complete function or class, with module imports",
            "max_input_utf8_bytes": 131072, "oversize": "unavailable; never silently truncated",
            "full_original_sources_retained": True,
            "predictor_excludes": ["revision IDs", "base/candidate status", "buggy/fixed path names", "observed logs", "labels"]},
        "diagnostic_policy": {"comparators_per_primary": 3, "selection": "Existing same-file test nodes ordered by SHA256(group_id + node); freeze before command outcomes.",
            "action_order": "SHA256(group_id) parity, independent of outcomes", "eligibility": "Exactly one action fails before and passes after; comparator passes both.",
            "ties_and_uninformative": "recorded as unavailable, not relabelled"},
        "execution_policy": {"workers": 3, "wall_timeout_seconds": 45, "cpu_seconds": 40,
            "address_space_bytes": 1610612736, "log_file_bytes": 2097152,
            "acquired_artifact_byte_limit": 1000000000, "dependencies_frozen_before_cases": True,
            "test_overlay": "Use declared fixed-revision test files unchanged on both pinned implementation revisions.",
            "outcome_eligibility": "Nonzero test execution; candidate passes; base has at least one test-call failure; no setup/collection/timeout failure.",
            "infrastructure_errors": "Preserve exact logs and mark unavailable; never count as semantic target failures."},
        "sampling": {"budgets": [8, 32, 128], "seeds": [7, 17, 29],
            "independent_unit": "bug group", "max_rows_per_group_per_task_budget": 1,
            "unsupported_budgets": "explicit unavailable receipt; no duplication or replacement"},
        "source_code_sha256": {Path(__file__).name: digest(Path(__file__).read_bytes())}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bugsinpy", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    plan = build_plan(args.bugsinpy)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    raw = canonical(plan)
    (output / "protocol.json").write_bytes(raw)
    (output / "requirements.txt").write_text("\n".join(DEPENDENCIES) + "\n")
    print(json.dumps({"protocol_sha256": digest(raw), "bugs": len(plan["bugs"]),
        "groups_by_split": {s: sum(b["split"] == s for b in plan["bugs"]) for s in ("train", "calibration", "holdout")}}))


if __name__ == "__main__":
    main()
