"""Publish a frozen, bounded evidence stack from verified local bytes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import time
import zipfile

ROOT = Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
WORK = ROOT / "publication-native-01"
ENV = dict(os.environ, GIT_TERMINAL_PROMPT="0")


def run(args):
    output = ROOT / args.operation
    if output.parent != ROOT or not args.operation.startswith("publication-final-operation-"):
        raise ValueError("operation must be an isolated direct child")
    output.mkdir(exist_ok=False)
    commands, commits = [], []

    def save(name, value):
        with (output / name).open("x") as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write("\n")

    def git(*argv):
        started = time.monotonic()
        result = subprocess.run(["git", *argv], cwd=WORK, env=ENV,
                                capture_output=True, timeout=180)
        commands.append({"argv": ["git", *argv], "exit_code": result.returncode,
                         "wall_seconds": time.monotonic() - started,
                         "stderr": result.stderr.decode(errors="replace")[-4000:]})
        if result.returncode:
            raise RuntimeError(commands[-1])
        return result.stdout

    def core_tree():
        lines = git("ls-tree", "-r", "HEAD", "--", "scripts/cell_experiments").decode().splitlines()
        return {line.split("\t", 1)[1]: line.split("\t", 1)[0].split()[2]
                for line in lines if line.endswith(".py")}

    try:
        archive_path = ROOT / args.archive
        if archive_path.parent != ROOT or archive_path.is_symlink():
            raise ValueError("archive must be a regular direct child")
        data = archive_path.read_bytes()
        if hashlib.sha256(data).hexdigest() != args.archive_sha256:
            raise ValueError("archive digest differs")
        with zipfile.ZipFile(archive_path) as archive:
            if archive.testzip() is not None:
                raise ValueError("archive CRC failure")
            raw_plan = archive.read("NATIVE_FINAL_PLAN_01.json")
            if hashlib.sha256(raw_plan).hexdigest() != args.plan_sha256:
                raise ValueError("plan digest differs")
            plan = json.loads(raw_plan)
            expected = set(plan["files"]) | {"NATIVE_FINAL_PLAN_01.json"}
            if set(archive.namelist()) != expected or len(archive.namelist()) != len(expected):
                raise ValueError("archive membership differs")
            if git("rev-parse", "HEAD").decode().strip() != plan["base_commit"]:
                raise ValueError("publication base changed")
            if git("status", "--porcelain=v1").strip():
                raise ValueError("publication worktree is not clean")
            if core_tree() != plan["expected_complete_core_git_blobs"]:
                raise ValueError("frozen model source tree differs")
            names = [name for stage in plan["stages"] for name in stage["files"]]
            if len(names) != len(set(names)) or set(names) != set(plan["files"]):
                raise ValueError("stages must partition the exact file set")
            save("STARTED.json", {"archive_sha256": args.archive_sha256,
                                  "plan_sha256": args.plan_sha256,
                                  "base": plan["base_commit"], "files": len(names)})
            for name, identity in plan["files"].items():
                path = Path(name)
                info = archive.getinfo(name)
                if (path.is_absolute() or ".." in path.parts or ".git" in path.parts
                        or stat.S_ISLNK(info.external_attr >> 16)):
                    raise ValueError("unsafe artifact path")
                raw = archive.read(name)
                if (len(raw) != identity["bytes"] or len(raw) >= 512000
                        or hashlib.sha256(raw).hexdigest() != identity["sha256"]):
                    raise ValueError("artifact identity or object limit differs: " + name)
                target = WORK / path
                for ancestor in target.parents:
                    if ancestor == WORK:
                        break
                    if ancestor.is_symlink():
                        raise ValueError("artifact ancestor is a symlink")
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as stream:
                    stream.write(raw)
        parent = plan["base_commit"]
        for stage in plan["stages"]:
            if git("rev-parse", "HEAD").decode().strip() != parent:
                raise ValueError("stage base changed")
            git("diff", "--cached", "--quiet")
            git("add", "-f", "--", *stage["files"])
            changed = git("diff", "--cached", "--name-only").decode().splitlines()
            if sorted(changed) != sorted(stage["files"]):
                raise ValueError("unexpected staged paths")
            summary = git("diff", "--cached", "--numstat").decode()
            additions = deletions = 0
            for line in summary.splitlines():
                added, removed, _ = line.split("\t", 2)
                if added != "-":
                    additions += int(added)
                    deletions += int(removed)
            exception = (stage.get("kind") == "immutable_mechanical_evidence"
                         and bool(stage.get("mechanical_evidence_exception"))
                         and all(name.endswith((".json", ".jsonl", ".log", ".txt"))
                                 for name in stage["files"]))
            if (deletions or additions != stage["added_text_lines"]
                    or (additions > 800 and not exception)):
                raise ValueError("stage size differs from the reviewed freeze")
            git("commit", "-m", stage["commit_subject"])
            head = git("rev-parse", "HEAD").decode().strip()
            ref = "refs/heads/" + stage["draft_pr_head"]
            git("update-ref", ref, head, "0" * 40)
            row = {"stage": stage["id"], "base_commit": parent, "commit": head,
                   "branch": stage["draft_pr_head"], "base_branch": stage["draft_pr_base"],
                   "files": stage["files"], "added_lines": additions,
                   "tree": git("rev-parse", "HEAD^{tree}").decode().strip()}
            save("COMMIT_" + stage["id"] + ".json", row)
            commits.append(row)
            parent = head
        if core_tree() != plan["expected_complete_core_git_blobs"]:
            raise ValueError("frozen source changed during publication")
        if git("status", "--porcelain=v1").strip():
            raise ValueError("publication left unexpected files")
        refs = ["refs/heads/" + row["branch"] for row in commits]
        save("PUSH_STARTED.json", {"refs": refs, "commits": commits,
                                   "atomic": True, "expected_remote_state": "all absent"})
        leases = ["--force-with-lease=" + ref + ":" for ref in refs]
        pushed = git("push", "--atomic", "--porcelain", *leases, "origin", *refs).decode()
        save("COMPLETE.json", {"status": "PUSHED_PENDING_API_VERIFICATION",
                               "commits": commits, "commands": commands,
                               "archive_sha256": args.archive_sha256,
                               "plan_sha256": args.plan_sha256, "push_stdout": pushed,
                               "merged": False, "production_adoption": False})
        print(json.dumps({"status": "PUSHED_PENDING_API_VERIFICATION",
                          "stages": len(commits), "head": parent}), flush=True)
    except BaseException as error:
        save("FAILED.json", {"error": repr(error), "commands": commands,
                             "completed_commits": commits,
                             "reconcile_remote_refs_before_retry": True})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--operation", required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
