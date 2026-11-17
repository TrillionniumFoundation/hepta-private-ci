"""Publish the frozen research-source stack through ordinary native Git."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import zipfile

ROOT = Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
WORK = ROOT / "publication-native-01"
OPS = ROOT / "publication-source-operation-01"
ARCHIVE = ROOT / "publication-source-input-01.zip"
ARCHIVE_SHA = "e9aeda8dc070d7a0d222abf6dadc8634f2a5106861dab15fcfe246770bfa4a75"
PLAN_SHA = "bb7de08e66f5129fd1f88117bbc34d31a0541971d13286e5043483428ea91cd0"
ENV = dict(os.environ, GIT_TERMINAL_PROMPT="0")
COMMANDS = []
COMPLETED = []


def save(name, value):
    with (OPS / name).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")


def git(*args, input_bytes=None, timeout=180):
    started = time.perf_counter()
    result = subprocess.run(
        ["git", *args], cwd=WORK, env=ENV, input=input_bytes,
        capture_output=True, timeout=timeout,
    )
    COMMANDS.append({
        "argv": ["git", *args], "exit_code": result.returncode,
        "wall_seconds": time.perf_counter() - started,
        "stderr": result.stderr.decode(errors="replace")[-4000:],
    })
    if result.returncode:
        raise RuntimeError(COMMANDS[-1])
    return result.stdout


def tree_blobs(commit, prefix):
    rows = git("ls-tree", "-r", commit, "--", prefix).decode().splitlines()
    return {row.split("\t", 1)[1]: row.split("\t", 1)[0].split()[2]
            for row in rows if row.endswith(".py")}


OPS.mkdir(exist_ok=False)
try:
    if hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() != ARCHIVE_SHA:
        raise ValueError("publication archive changed")
    with zipfile.ZipFile(ARCHIVE) as archive:
        raw_plan = archive.read("NATIVE_SOURCE_PLAN_01.json")
        if hashlib.sha256(raw_plan).hexdigest() != PLAN_SHA:
            raise ValueError("publication plan changed")
        plan = json.loads(raw_plan)
        expected = set(plan["files"]) | {"NATIVE_SOURCE_PLAN_01.json"}
        if set(archive.namelist()) != expected or len(archive.namelist()) != len(expected):
            raise ValueError("publication member set changed")
        if git("rev-parse", "HEAD").decode().strip() != plan["base_commit"]:
            raise ValueError("publication base changed")
        dependencies = tree_blobs(plan["base_commit"], "scripts/hepta_cells")
        if dependencies != plan["expected_runtime_dependency_git_blobs"]:
            raise ValueError("runtime dependency snapshot differs from Git base")
        save("STARTED.json", {
            "source_archive_sha256": ARCHIVE_SHA, "plan_sha256": PLAN_SHA,
            "base_commit": plan["base_commit"],
            "tracked_paths": len(git("ls-files", "-z").split(b"\0")) - 1,
            "dependency_modules_verified": len(dependencies),
            "preparation_tracked_paths_display_bug": "prior receipt counted a literal escape; this is the actual index count",
        })
        for name, identity in plan["files"].items():
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts or ".git" in relative.parts:
                raise ValueError("unsafe publication path")
            data = archive.read(name)
            if len(data) != identity["bytes"] or hashlib.sha256(data).hexdigest() != identity["sha256"]:
                raise ValueError("publication source changed: " + name)
            target = WORK / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(data)
    parent = plan["base_commit"]
    for stage in plan["stages"]:
        if git("rev-parse", "HEAD").decode().strip() != parent:
            raise ValueError("stage parent changed")
        git("diff", "--cached", "--quiet")
        git("add", "--", *stage["files"])
        changed = git("diff", "--cached", "--name-only", "-z").decode().strip("\0").split("\0")
        if sorted(changed) != sorted(stage["files"]):
            raise ValueError("unexpected staged file set")
        stat = git("diff", "--cached", "--numstat").decode()
        added = deleted = 0
        for line in stat.splitlines():
            additions, removals, _ = line.split("\t", 2)
            if additions != "-":
                added += int(additions)
                deleted += int(removals)
        if deleted or added != stage["added_text_lines"] or added > 800:
            raise ValueError("reviewable stage size differs from plan")
        git("commit", "-m", stage["commit_subject"])
        head = git("rev-parse", "HEAD").decode().strip()
        ref = "refs/heads/" + stage["draft_pr_head"]
        git("update-ref", ref, head, "0" * 40)
        receipt = {"stage": stage["id"], "base_commit": parent,
                   "commit": head, "branch": stage["draft_pr_head"],
                   "base_branch": stage["draft_pr_base"], "added_lines": added,
                   "files": stage["files"], "tree": git("rev-parse", "HEAD^{tree}").decode().strip()}
        save("COMMIT_" + stage["id"] + ".json", receipt)
        COMPLETED.append(receipt)
        parent = head
    if tree_blobs(parent, "scripts/cell_experiments") != plan["expected_complete_core_git_blobs"]:
        raise ValueError("final source tree differs from the tested source")
    refs = ["refs/heads/" + row["branch"] for row in COMPLETED]
    if git("ls-remote", "origin", *refs).strip():
        raise ValueError("a publication branch already exists; inspect without updating it")
    save("PUSH_STARTED.json", {"refs": refs, "commits": COMPLETED, "atomic": True,
                              "expected_remote_state": "all refs absent"})
    leases = ["--force-with-lease=" + ref + ":" for ref in refs]
    output = git("push", "--atomic", "--porcelain", *leases, "origin", *refs).decode()
    actual = dict(line.split("\t")[::-1] for line in git("ls-remote", "origin", *refs).decode().splitlines())
    expected = {"refs/heads/" + row["branch"]: row["commit"] for row in COMPLETED}
    if actual != expected:
        raise ValueError("remote refs do not match the local publication")
    save("COMPLETE.json", {"status": "SOURCE_STACK_PUSHED", "commits": COMPLETED,
                           "source_archive_sha256": ARCHIVE_SHA, "plan_sha256": PLAN_SHA,
                           "remote_ref_verification": actual, "push_stdout": output,
                           "commands": COMMANDS, "draft_prs_created": False,
                           "merged": False, "production_adoption": False})
    print(json.dumps({"status": "SOURCE_STACK_PUSHED", "stages": len(COMPLETED), "head": parent}))
except BaseException as error:
    save("FAILED.json", {"error": repr(error), "completed_commits": COMPLETED,
                         "commands": COMMANDS, "remote_push_outcome": "inspect retained push-start and remote refs"})
    raise
