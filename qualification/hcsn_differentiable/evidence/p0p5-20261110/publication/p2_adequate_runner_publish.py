"""Publish one already-tested HCSN implementation branch; never merge."""
import hashlib
import json
from pathlib import Path
import subprocess
import time

ROOT = Path("/Users/qianqi/hepta-hcsn-p0p5-20261110-c385/recovery")
OUT = ROOT / "p2-adequate-runner-publish-v1"
OUT.mkdir(exist_ok=False)
BARE = Path("/Users/qianqi/hepta-hcsn-p0p5-20261110-c385/stage-publish.git")
BUNDLE = ROOT / "hcsn-p2-adequate-runner.bundle"
BRANCH = "codex/hcsn-p2-adequate-runner-20261110-c385"
SHA = "6d18f16050dabab063a324087a7b4e00618bd1bb"
URL = "https://github.com/TrillionniumFoundation/hepta-private-ci.git"
GIT = ["/usr/bin/git", "-C", str(BARE), "-c", "credential.helper=", "-c", "credential.helper=!/opt/homebrew/bin/gh auth git-credential"]

def run(args, name):
    start = time.perf_counter()
    p = subprocess.run(args, capture_output=True, text=True, timeout=240)
    (OUT / (name + ".stdout")).write_text(p.stdout)
    (OUT / (name + ".stderr")).write_text(p.stderr)
    (OUT / (name + ".process.json")).write_text(json.dumps({"argv": args, "returncode": p.returncode, "wall_seconds": time.perf_counter()-start}, indent=2)+"\n")
    if p.returncode:
        raise RuntimeError(name + " failed; retained raw logs")
    return p.stdout.strip()

start = time.perf_counter()
assert BUNDLE.stat().st_size == 5483
assert hashlib.sha256(BUNDLE.read_bytes()).hexdigest() == "f7f4e889429845347cb1d2eba9e158e30fed0f8b545b904a09842554a4b7989e"
run(GIT + ["bundle", "verify", str(BUNDLE)], "verify")
run(GIT + ["fetch", str(BUNDLE), "refs/heads/"+BRANCH+":refs/heads/"+BRANCH], "fetch")
assert run(GIT + ["rev-parse", "refs/heads/"+BRANCH], "local-head") == SHA
before = run(GIT + ["ls-remote", URL, "refs/heads/"+BRANCH], "remote-before")
assert not before or before.split()[0] == SHA
if not before:
    run(GIT + ["push", "--porcelain", URL, "refs/heads/"+BRANCH+":refs/heads/"+BRANCH], "push")
after = run(GIT + ["ls-remote", URL, "refs/heads/"+BRANCH], "remote-after")
assert after.split()[0] == SHA
receipt = {"schema": "hcsn-p2-adequate-runner-publication-v1", "branch": BRANCH, "head": SHA, "base": "3e49eda398778220fc45604908aaedb9bca9f1a0", "bundle_sha256": hashlib.sha256(BUNDLE.read_bytes()).hexdigest(), "remote_head_verified": True, "preexisting_same_head": bool(before), "main_modified": False, "wall_seconds": time.perf_counter()-start}
(OUT / "receipt.json").write_text(json.dumps(receipt, indent=2)+"\n")
print(json.dumps(receipt), flush=True)
