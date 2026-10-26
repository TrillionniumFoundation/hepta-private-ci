# PN0 original evidence retained in source history

The full original artifacts remain byte-for-byte in the immutable ancestor commit
`9d88e3e5acdd65272581b32735af8a08cfb65dbc`, tree
`90bfff72ff58144b5f098ef49244b82916c35fc8`, parent
`3e1afb5d3e199abf4fccab78f6812ffaf64f77ea`. Current source keeps a small,
explicit index instead of duplicate historical raw blobs. The original commit,
its raw logs, receipts, assertions and failures are neither rewritten nor removed
from reachable history. This follows the repository's existing source-ancestor
retention pattern; it is not new runtime authority or an executed qualification.

`source-history-artifacts-9d88-v1.json` records each original repository path,
Git blob, full SHA256 and byte count. The original manifests/receipts in these
packages describe the pinned9d layout. Materialize the originals into a separate
empty directory before replaying those manifests; do not treat a missing current
raw pathname as an empty artifact or as successful evidence. Existing full-history
checkouts retain9d as an ancestor. A shallow/missing history must fail closed or
explicitly fetch the exact pinned commit before verification, never guess a branch.

Recovery uses only ordinary Git reads and standard-library hashing. Ambient
repository/configuration injection is rejected; replacement objects, lazy fetch,
network transports, pagers, hooks and text conversion are not used. Missing
history or objects refuses without a hidden fetch. The byte header plus Git OID
and independent SHA256 are all checked. This is data recovery, not isolation
or native permission verification. Run the
following at a source checkout. Recovery creates a fresh private directory and does
not execute or install the recovered artifacts, create a qualification, change
an execution budget or authorize a process. Complete all verification before
using any recovered file as historical input. Recovery reconstructs all eighty
files in the six original packages, including unchanged manifests and sibling
files. The fourteen moved paths are only a subset of that complete layout.
Git executable bits are recorded as provenance; recovery writes private data,
not executable installation or proof of original ACLs/modes.

```python
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tempfile


def require(ok, message):
    if not ok:
        raise ValueError(message)


# Run only at the intended source checkout root. Repository-selection,
# object-store and configuration injection must never silently select a peer.
checkout = Path.cwd().resolve()
for name in os.environ:
    if name in {"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                "GIT_NAMESPACE", "GIT_REPLACE_REF_BASE", "GIT_SHALLOW_FILE",
                "GIT_CEILING_DIRECTORIES"} or name.startswith("GIT_CONFIG_"):
        raise ValueError("ambient Git repository/configuration selection")
# Discard other ambient Git options (including an ordinary pager setting).
git_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
git_env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_NO_LAZY_FETCH": "1", "GIT_NO_REPLACE_OBJECTS": "1",
                "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"})


def git(*args):
    return subprocess.check_output(
        ["git", "--no-pager", "-c", "protocol.allow=never",
         "-c", "core.fsmonitor=false", "-c", "core.hooksPath=" + os.devnull,
         *args], cwd=checkout, env=git_env)


require(Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve() == checkout,
        "run at source checkout root")
require(git("rev-parse", "--show-object-format").decode().strip() == "sha1", "original Git object format")

def safe_path(name):
    rel = PurePosixPath(name)
    require(not rel.is_absolute() and ".." not in rel.parts, "relative path")
    require("\\" not in name and ":" not in name and "\x00" not in name, "portable path")
    require(rel.parts and rel.parts[0] in ("qualification", "evidence"), "historical namespace")
    return rel


index_path = "qualification/pn0-ci/source-history-artifacts-9d88-v1.json"
index = json.loads(git("show", "--no-textconv", "HEAD:" + index_path))
require(index["schema"] == "hepta.audit.source-history-artifact-index.v1", "index schema")
require(index["schemaVersion"] == 1, "index version")
require(set(index["authorityFlags"]) == {"execution", "installation", "promotion", "budgetRefund", "qualification"}, "authority fields")
require(all(value is False for value in index["authorityFlags"].values()), "data only")
commit = index["evidenceCommit"]
require(commit == "9d88e3e5acdd65272581b32735af8a08cfb65dbc", "original source")
git("merge-base", "--is-ancestor", commit, "HEAD")
require(git("rev-parse", commit + "^{tree}").decode().strip() == index["evidenceTree"], "original tree")
require(git("show", "-s", "--format=%P", commit).decode().strip() == index["evidenceParentCommit"], "original parent")
require(len(index["artifacts"]) == 14 and len(index["originalPackages"]) == 6, "original set")
actual_files = {}
roots = []
for package in index["originalPackages"]:
    root = package["path"]
    safe_path(root)
    require(root not in roots and not any(root.startswith(old + "/") or old.startswith(root + "/") for old in roots), "package overlap")
    roots.append(root)
    require(git("cat-file", "-t", commit + ":" + root).decode().strip() == "tree", "package tree")
    require(git("rev-parse", commit + ":" + root).decode().strip() == package["gitTreeSha"], "package identity")
    children = git("ls-tree", "-r", "-z", commit, "--", root).split(bytes([0]))
    count = 0
    for record in children:
        if not record:
            continue
        attributes, raw_path = record.split(bytes([9]), 1)
        mode, kind, blob = attributes.decode().split()
        name = raw_path.decode()
        safe_path(name)
        require(name.startswith(root + "/") and name not in actual_files, "package member")
        require(kind == "blob" and mode in ("100644", "100755"), "regular original data")
        actual_files[name] = (mode, blob)
        count += 1
    require(count == package["files"], "complete package")
rows = {row["path"]: row for row in index["recoveryFiles"]}
require(len(rows) == len(index["recoveryFiles"]) == index["recoveryFileCount"] == 80, "complete recovery")
require(set(rows) == set(actual_files), "no missing or added original member")
require(len({name.casefold() for name in rows}) == len(rows), "portable unique paths")
for moved in index["artifacts"]:
    require(moved["path"] in rows, "moved original present")
    require(all(moved[key] == rows[moved["path"]][key] for key in ("path", "gitBlobSha", "sha256", "bytes")), "moved original binding")
verified = []
for name, row in rows.items():
    rel = safe_path(name)
    require(actual_files[name] == (row["gitMode"], row["gitBlobSha"]), "original blob mode")
    raw = git("show", "--no-textconv", commit + ":" + name)
    header = b"blob " + str(len(raw)).encode("ascii") + bytes([0])
    require(hashlib.sha1(header + raw, usedforsecurity=False).hexdigest() == row["gitBlobSha"], "independent Git blob identity")
    require(len(raw) == row["bytes"] and hashlib.sha256(raw).hexdigest() == row["sha256"], "original bytes")
    verified.append((rel, raw))
require(sum(len(raw) for _, raw in verified) == index["recoveryBytes"], "complete byte count")
# Every original package and manifest has verified before any recovery file is made.
out = Path(tempfile.mkdtemp(prefix="hepta-history-"))
for rel, raw in verified:
    target = out.joinpath(*rel.parts)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with target.open("xb") as stream:
        stream.write(raw)
print("Verified historical data:", out)

```

All fourteen original artifacts are retained, including the four Windows logs,
original failed host build, old blocking output and the complete dependency audit
container. Literal words in original logs/review JSON remain unchanged. The
512000-byte current-blob policy, allowlist, language checker, tests and resource
limits remain unchanged. No file is split into policy-sized pieces. Future
large evidence must use the existing asset policy; this recovery applies only
to the already-published original9d data. It does not permit hidden staging of
new large objects in history.

The new tuple still requires its own full CI and native validation. The old
Windows deletion failures, model/release/WAN and other PN0–PN6 gates remain
open. Historical recovery cannot convert a failure into PASS or an UNKNOWN
process into terminal, refund a charge or declare a new model installed.
