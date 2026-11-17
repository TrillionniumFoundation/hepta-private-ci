"""Publish the two mechanically formatted workflow files with exact old bytes."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
WORK = ROOT / "publication-native-01"
OPS = ROOT / "publication-workflow-operation-01"
BASE = "9d62fafa3713e25fa4c80eaab403e094ef4bc647"
BRANCH = "codex/cell-experiments-v3-20261116-0c078a-s35"
FILES = {
    ".github/workflows/cell-experiments.yml": (
        "c8bfed0d2111d26edc35ace35068cb661670784e6ef032b0ce564571a3121ec6",
        "8aa264b4a862318e0b54e2a1af2cf1df70fcf161b8229e8352efec956cf84346"),
    ".github/workflows/cell-hia-joint.yml": (
        "97e0655210c7cf339ced8fe46039ab37417a26c5ec7476004fd83bde223c40c1",
        "0953fa8834289dbcdfd5c042703ae1a96f5474e9456d21f90102b4cc923d23b0"),
}
COMMANDS = []
ENV = dict(os.environ, GIT_TERMINAL_PROMPT="0")

def save(name, value):
    with (OPS / name).open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")

def git(*args):
    start = time.monotonic()
    result = subprocess.run(["git", *args], cwd=WORK, env=ENV,
                            capture_output=True, timeout=180)
    COMMANDS.append({"argv": ["git", *args], "exit_code": result.returncode,
                     "seconds": time.monotonic() - start,
                     "stderr": result.stderr.decode(errors="replace")[-4000:]})
    if result.returncode:
        raise RuntimeError(COMMANDS[-1])
    return result.stdout

OPS.mkdir(exist_ok=False)
try:
    assert git("rev-parse", "HEAD").decode().strip() == BASE
    assert not git("status", "--porcelain=v1").strip()
    before_core = git("ls-tree", "-r", "HEAD", "--", "scripts/cell_experiments")
    save("STARTED.json", {"base": BASE, "branch": BRANCH, "files": FILES})
    for name, (old_sha, new_sha) in FILES.items():
        before = git("show", "HEAD:" + name)
        after = (ROOT / "operations/format-workflows-01" / Path(name).name).read_bytes()
        assert hashlib.sha256(before).hexdigest() == old_sha
        assert hashlib.sha256(after).hexdigest() == new_sha
        target = WORK / name
        assert not target.is_symlink()
        if target.exists():
            assert target.read_bytes() == before
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(after)
    git("add", "--sparse", "--", *FILES)
    changed = git("diff", "--cached", "--name-only").decode().splitlines()
    assert sorted(changed) == sorted(FILES)
    stat = git("diff", "--cached", "--numstat").decode()
    assert sum(int(v) for line in stat.splitlines() for v in line.split("\t")[:2]) <= 100
    save("DIFF.json", {"numstat": stat, "patch": git("diff", "--cached").decode()})
    git("commit", "-m", "style: format cell experiment workflow strings")
    head = git("rev-parse", "HEAD").decode().strip()
    assert git("ls-tree", "-r", "HEAD", "--", "scripts/cell_experiments") == before_core
    ref = "refs/heads/" + BRANCH
    git("update-ref", ref, head, "0" * 40)
    save("COMMIT.json", {"head": head, "base": BASE, "branch": BRANCH,
                         "tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
                         "core_unchanged": True})
    save("PUSH_STARTED.json", {"head": head, "ref": ref, "expected_remote_state": "absent"})
    stdout = git("push", "--atomic", "--porcelain", "--force-with-lease=" + ref + ":",
                 "origin", ref).decode()
    save("COMPLETE.json", {"status": "PUSHED_PENDING_API_VERIFICATION", "head": head,
                           "base": BASE, "branch": BRANCH, "commands": COMMANDS,
                           "push_stdout": stdout, "merged": False})
    print(json.dumps({"status": "PUSHED_PENDING_API_VERIFICATION", "head": head}))
except BaseException as error:
    save("FAILED.json", {"error": repr(error), "commands": COMMANDS,
                         "reconcile_push_started_and_remote_ref_before_retry": True})
    raise
