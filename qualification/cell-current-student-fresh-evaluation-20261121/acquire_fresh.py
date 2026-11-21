"""Release-gated bounded acquisition; original static/native predicates remain.

No candidate repository is opened before both real child freezes and the
published selection digest are verified. Never invoke an archived owner main.
"""

import argparse
import configparser
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time
import tomllib

import fresh_contract as c
import run_fresh as runtime

SCANNER_SHA = "b8edd528f1e4401a007430fca9364d53a75398742e6af0f46e95bb019c4a178a"
MATERIALIZER_SHA = "b4bc2a6eea7c8f2b9b5a21cd157b030b2b4b8484354f4ef63017d155e058598f"


class AcquisitionFailure(RuntimeError):
    """Resource exhaustion is terminal for this owner, not a static rejection."""


class GitRejected(RuntimeError):
    """An ordinary Git nonzero exit retains its original command receipt."""


def budget(condition, reason):
    if not condition:
        raise AcquisitionFailure(reason)


def retained_bytes(root):
    return sum(path.stat().st_size for path in Path(root).rglob("*") if path.is_file() and not path.is_symlink())


class GitCommands:
    def __init__(self, output, owner, repository_index, started=None):
        self.output, self.owner = Path(output), Path(owner)
        self.started = time.monotonic() if started is None else started
        self.index = 0
        self.budget_root = self.owner / "git-command-slots" / str(repository_index)
        self.budget_root.mkdir(parents=True, exist_ok=True)

    def run(self, args):
        budget(time.monotonic() - self.started < 1800, "acquisition wall cap reached")
        budget(retained_bytes(self.owner) <= c.CAPS["owner_material_bytes"], "retained material cap reached")
        with (self.budget_root / "OWNER.lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            number = len(list(self.budget_root.glob("*.json")))
            budget(number < 2000, "repository command budget exhausted")
            c.write_new(self.budget_root / f"{number:04d}.json", {"argv_digest": c.digest(args),
                        "output": str(self.output), "automatic_retry": False})
        folder = self.output / "commands" / f"{self.index:04d}"
        self.index += 1
        folder.mkdir(parents=True, exist_ok=False)
        c.write_new(folder / "INTENT.json", {"argv": args, "timeout_seconds": 600, "automatic_retry": False})
        limit = c.CAPS["archive_bytes"]
        launcher = "import os,resource,sys;resource.setrlimit(resource.RLIMIT_FSIZE,(int(sys.argv[1]),int(sys.argv[1])));os.execvp(sys.argv[2],sys.argv[2:])"
        process = subprocess.Popen([sys.executable, "-I", "-c", launcher, str(limit), *args],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "GIT_TERMINAL_PROMPT": "0",
                 "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"})
        started, counts, error, code = time.monotonic(), {"STDOUT": 0, "STDERR": 0}, None, None
        observed_peak = acquisition_bytes = retained_bytes(self.owner)
        with selectors.DefaultSelector() as selector, (folder / "STDOUT").open("xb") as stdout, (folder / "STDERR").open("xb") as stderr:
            selector.register(process.stdout, selectors.EVENT_READ, ("STDOUT", stdout, limit))
            selector.register(process.stderr, selectors.EVENT_READ, ("STDERR", stderr, c.CAPS["blob_bytes"]))
            try:
                while selector.get_map():
                    c.require(time.monotonic() - started < 600 and time.monotonic() - self.started < 1800,
                              "acquisition timeout; no retry")
                    acquisition_bytes = retained_bytes(self.owner)
                    observed_peak = max(observed_peak, acquisition_bytes)
                    c.require(acquisition_bytes <= c.CAPS["owner_material_bytes"], "owner material cap exceeded")
                    for key, _ in selector.select(timeout=0.25):
                        name, target, maximum = key.data
                        chunk = os.read(key.fileobj.fileno(), 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        c.require(counts[name] + len(chunk) <= maximum, "bounded command output exceeded")
                        target.write(chunk)
                        counts[name] += len(chunk)
                code = process.wait(timeout=10)
            except BaseException as caught:
                error = repr(caught)
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    code = process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    try:
                        code = process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        code = None
            finally:
                process.stdout.close()
                process.stderr.close()
        observed_peak = max(observed_peak, retained_bytes(self.owner))
        c.write_new(folder / "EXIT.json", {"returncode": code, "error": error, "retained_stream_bytes": counts,
                    "output_complete": error is None, "wall_seconds": time.monotonic() - started,
                    "owner_bytes_observed": retained_bytes(self.owner), "observed_owner_bytes_peak": observed_peak,
                    "storage_limit_scope": "polling termination/admission threshold; possible sampling overshoot; not a filesystem hard quota",
                    "physical_network_bytes": None})
        if error is not None:
            c.write_new(self.owner / "ACQUISITION_UNCERTAIN.json", {"pid": process.pid, "command_owner": str(folder),
                        "launcher_exit_confirmed": code is not None,
                        "reason": "forced Git stop does not establish descendant cleanup", "automatic_retry": False})
        budget(error is None and retained_bytes(self.owner) <= c.CAPS["owner_material_bytes"],
               "bounded Git command failed; original partial logs retained")
        if code != 0:
            raise GitRejected("original Git nonzero exit; retained " + str(folder))
        return (folder / "STDOUT").read_bytes()


def release(deployment):
    c.require(deployment["schema"] == "hepta.current-student-fresh-acquisition.v1", "new acquisition deployment required")
    for name in ("fresh_contract.py", "run_fresh.py", "acquire_fresh.py", "prepare_fresh.py", "assemble_fresh.py"):
        c.require(c.sha(Path(__file__).parent / name) == deployment["source_files"][name], "acquisition executable changed")
    selection, weights, excluded, publication = [c.read_bound(deployment[key]) for key in
                                               ("selection", "weights", "excluded", "selection_publication")]
    admissions = c.validate_selection(selection, weights, excluded, publication)
    owner = Path(selection["owner_root"])
    c.require(not (owner / "PANEL_FROZEN.json").exists() and not (owner / "PANEL_REFUSED.json").exists(),
              "source acquisition closed after the final panel decision")
    c.require(not (owner / "ACQUISITION_UNCERTAIN.json").exists(), "previous acquisition cleanup remains uncertain")
    assets = runtime.assets(deployment, weights)
    return selection, excluded, publication, admissions, assets


@contextmanager
def source_owner(deployment):
    selection, _, _, _, _ = release(deployment)
    root = Path(selection["owner_root"])
    root.mkdir(parents=True, exist_ok=True)
    with (root / "ACQUISITION.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def preceding_sources(selection, excluded, index):
    """Finish each earlier fixed source before opening the next one."""
    owner, selected = Path(selection["owner_root"]), 0
    for prior in range(index):
        project = c.REPOSITORIES[prior]
        if project.split("/")[0].casefold() in excluded["owners"]:
            continue
        scan = owner / "scans" / f"{prior:02d}-{project.replace('/', '--')}" / "RESULT.json"
        scanned = c.read_bound({"path": str(scan), "sha256": c.sha(scan)})
        if scanned["status"] == "FAILED_NO_RETRY":
            continue
        for ordinal, _ in enumerate(c.ordered_potentials(scanned)):
            path = owner / "materials" / f"{prior:02d}" / str(ordinal) / "FINAL.json"
            receipt = c.read_bound({"path": str(path), "sha256": c.sha(path)})
            c.require(receipt["status"] in ("QUALIFIED", "REFUSED", "FAILED_NO_RETRY"), "earlier material lacks terminal state")
            if receipt["status"] == "QUALIFIED":
                selected += 1
                break
    c.require(selected < 4, "four sources already selected; acquisition must stop")


def scan(deployment, index):
    selection, excluded, publication, admissions, _ = release(deployment)
    c.require(type(index) is int and 0 <= index < 8, "listed repository slot required")
    project = c.REPOSITORIES[index]
    owner = Path(selection["owner_root"])
    output = owner / "scans" / f"{index:02d}-{project.replace('/', '--')}"
    if admissions[project] == "BEFORE_SCAN_REFUSAL":
        output.mkdir(parents=True, exist_ok=False)
        receipt = {"status": "BEFORE_SCAN_REFUSAL", "project_id": project, "candidate_content_read": False}
        c.write_new(output / "RESULT.json", receipt)
        return receipt
    preceding_sources(selection, excluded, index)
    c.Slots(selection, excluded).claim("scan", (index,), {"project_id": project})
    output.mkdir(parents=True, exist_ok=False)
    started_ns = str(time.time_ns())
    c.write_new(output / "INTENT.json", {"source_access_started_at_ns": started_ns, "selection_digest": c.digest(selection),
                "publication_commit": publication["commit"], "as_of": c.AS_OF, "inspector_sha256": SCANNER_SHA})
    try:
        metadata = c.read_bound(deployment["repository_metadata"][project])
        c.require(metadata["full_name"] == project and metadata["fork"] is False
                  and metadata["owner"]["login"].casefold() == project.split("/")[0].casefold()
                  and metadata["clone_url"] == "https://github.com/" + project + ".git", "canonical source metadata differs")
        c.write_new(output / "REPOSITORY.json", metadata)
        original = runtime.module("fresh_original_static_inspector", deployment["scanner_source"], SCANNER_SHA)
        commands = GitCommands(output, owner, index)
        version = commands.run(["git", "--version"]).decode().strip()
        git = output / "upstream.git"
        commands.run(["git", "clone", "--bare", "--single-branch", "--depth=256", "--filter=blob:none",
                      "--branch", metadata["default_branch"], metadata["clone_url"], str(git)])
        prefix = ["git", "--git-dir", str(git)]
        head = commands.run(prefix + ["rev-parse", "HEAD"]).decode().strip()
        commits = commands.run(prefix + ["rev-list", "--no-merges", "--max-count=50", "--before=" + c.AS_OF, head]).decode().splitlines()
        c.write_new(output / "COMMITS.json", {"HEAD": head, "as_of": c.AS_OF, "commits": commits,
                    "git_version": version, "order": c.COMMIT_ORDER, "automatic_deepen": False})
        summaries, potentials = [], 0
        for commit_index, commit in enumerate(commits):
            folder = output / "candidates" / f"{commit_index:02d}-{commit}"
            folder.mkdir(parents=True)
            parents = commands.run(prefix + ["rev-list", "--parents", "-n", "1", commit]).decode().split()
            if len(parents) != 2:
                summaries.append({"commit": commit, "status": "REJECT", "reason": "one original parent unavailable in retained history", "source_candidates": []})
                c.write_new(folder / "STATIC.json", summaries[-1])
                continue
            diff = commands.run(prefix + ["diff-tree", "--no-commit-id", "--name-status", "-r", commit]).decode()
            (folder / "CHANGED_PATHS.txt").write_text(diff)
            paths = sorted(line.split("\t")[-1] for line in diff.splitlines() if line.split("\t")[-1].endswith(".py"))
            source_paths = [path for path in paths if not original.is_test(path)]
            row = {"commit": commit, "parent": parents[1], "original_changed_test_paths": [path for path in paths if original.is_test(path)],
                   "source_paths_in_order": source_paths, "source_candidates": []}
            if len(paths) > c.CAPS["changed_python_paths_per_commit"]:
                row.update(status="REJECT", reason="entire commit exceeds 32 changed Python paths, including tests")
            else:
                for source_index, path in enumerate(source_paths):
                    directory = folder / f"source-{source_index:02d}"
                    directory.mkdir()
                    try:
                        blobs, content = [], []
                        for revision in (parents[1], commit):
                            blob = commands.run(prefix + ["rev-parse", revision + ":" + path]).decode().strip()
                            size = int(commands.run(prefix + ["cat-file", "-s", blob]).decode())
                            c.require(0 < size <= c.CAPS["blob_bytes"], "source blob exceeds admission cap")
                            blobs.append(blob)
                            content.append(commands.run(prefix + ["cat-file", "blob", blob]))
                        (directory / "BEFORE.py").write_bytes(content[0])
                        (directory / "AFTER.py").write_bytes(content[1])
                        review = original.inspect_change(*content)
                        review.update(path=path, before_git_blob=blobs[0], after_git_blob=blobs[1])
                    except (GitRejected, SyntaxError, UnicodeError, ValueError) as error:
                        review = {"path": path, "status": "TOOL_FAILURE_RETAINED" if isinstance(error, GitRejected) else "REJECT",
                                  "reason": str(error), "error_type": type(error).__name__,
                                  "tool_failure_is_not_source_invalidity": isinstance(error, GitRejected)}
                    c.write_new(directory / "STATIC.json", review)
                    row["source_candidates"].append(review)
                    potentials += review["status"] == "REQUIRES_QUALIFICATION"
                    if potentials == 4:
                        break
                row.update(status="ORDERED_SOURCE_PREFIX_REVIEWED", unread_source_paths=len(source_paths) - len(row["source_candidates"]))
            summaries.append(row)
            c.write_new(folder / "STATIC.json", row)
            if potentials == 4:
                break
        budget(time.monotonic() - commands.started < 1800
               and retained_bytes(owner) <= c.CAPS["owner_material_bytes"], "final scan cap exceeded")
        result = {"schema": "hepta.current-student-fresh-history.v1", "status": "ORDERED_STATIC_SCAN_COMPLETE",
                  "canonical_repository": project, "HEAD": head, "commits": summaries, "as_of": c.AS_OF,
                  "source_access_started_at_ns": started_ns, "stopped_at_first_four_potentials": potentials == 4,
                  "unread_commit_count": len(commits) - len(summaries), "model_calls": 0, "native_children": 0}
        c.write_new(output / "RESULT.json", result)
        return {"status": result["status"], "result_path": str(output / "RESULT.json"), "result_sha256": c.sha(output / "RESULT.json")}
    except BaseException as error:
        c.write_new(output / "RESULT.json", {"schema": "hepta.current-student-fresh-history.v1", "status": "FAILED_NO_RETRY",
                    "canonical_repository": project, "error_type": type(error).__name__, "error": str(error), "automatic_retry": False})
        raise


def compatibility(tree, changed_tests, configurations):
    """Refuse original test/configuration shapes the retained runner omits."""
    roots = [name for name in ("tests", "test", "testing", "test_suite") if any(path.startswith(name + "/") for path in tree)]
    c.require(len(roots) == 1, "exactly one original supported test root required")
    test_root = roots[0]
    c.require("pytest.ini" not in configurations or "conftest.py" in tree, "original pytest.ini would be omitted")
    for name, raw in configurations.items():
        if name == "pyproject.toml":
            c.require("pytest" not in tomllib.loads(raw.decode()).get("tool", {}), "unsupported original pyproject pytest config")
        elif name in ("setup.cfg", "tox.ini"):
            config = configparser.ConfigParser(interpolation=None)
            config.read_string(raw.decode())
            c.require(not ({"pytest", "tool:pytest"} & set(config.sections())), "unsupported original pytest configuration")
    for path in changed_tests:
        c.require(path in tree, "deleted original changed test file cannot be silently dropped")
        c.require(path == "conftest.py" or path.startswith(test_root + "/") and
                  (Path(path).name.startswith("test") or Path(path).name == "conftest.py"), "unsupported changed test layout")
    if not changed_tests or all(Path(path).name == "conftest.py" for path in changed_tests):
        c.require(not any(path.startswith(test_root + "/") and Path(path).name.endswith("_test.py")
                          and not Path(path).name.startswith("test") for path in tree), "fallback would omit original suffix tests")
    return test_root


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment", required=True)
    parser.add_argument("--deployment-sha256", required=True)
    parser.add_argument("--repository-index", type=int, required=True)
    args = parser.parse_args()
    deployment = c.read_bound({"path": args.deployment, "sha256": args.deployment_sha256})
    with source_owner(deployment):
        print(json.dumps(scan(deployment, args.repository_index)))
