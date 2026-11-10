"""Publish reviewed HCSN stages through native gh, with immutable write intents."""

import base64
import datetime
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
from urllib.parse import quote


ROOT = Path(sys.argv[1]).resolve()
if os.environ.get("GODEBUG") != "http2client=0":
    raise RuntimeError("inline-tree publication requires GODEBUG=http2client=0")
EXPECTED_PLAN_SHA256 = "52e1e4baf0b45012031ff3d9d6cb9ec44c7d2cdffd6a4fc2e60d6403abfee253"
plan_bytes = (ROOT / "plan.json").read_bytes()
if hashlib.sha256(plan_bytes).hexdigest() != EXPECTED_PLAN_SHA256:
    raise RuntimeError("frozen publication plan changed")
SPEC = json.loads(plan_bytes)
REPO = "TrillionniumFoundation/hepta-private-ci"
PREFIX = "repos/" + REPO
GH = "/opt/homebrew/bin/gh"
JOURNAL = ROOT / "journal-inline-tree-v1"
JOURNAL.mkdir(exist_ok=True)
ALLOWED = ("qualification/hcsn_differentiable/", ".github/workflows/hcsn-differentiable.yml")
REVIEWED_PARENT = ("bb048cb811c2b755b7e54e97d24c63ec7ec8d1b7",
                   "0f615c0b512d37cb4ec129c66e1a7ae07f90f163",
                   "codex/hcsn-diff-07-evidence-20261108")
if (SPEC["parent_commit"], SPEC["parent_tree"], SPEC["parent_branch"]) != REVIEWED_PARENT:
    raise RuntimeError("plan differs from the independently reviewed HCSN parent")
branches = [stage["branch"] for stage in SPEC["stages"]]
if (not branches or len(set(branches)) != len(branches)
        or any(re.fullmatch(r"codex/hcsn-math-[a-z0-9-]+-20261108-v1", branch) is None for branch in branches)):
    raise RuntimeError("only distinct new HCSN math stack namespaces are admitted")


def save(path, value):
    if path.exists():
        if json.loads(path.read_text()) != value:
            raise RuntimeError("immutable journal mismatch: " + path.name)
        return
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def get(endpoint):
    result = subprocess.run([GH, "api", endpoint], capture_output=True, text=True, timeout=90)
    if result.returncode == 0:
        return json.loads(result.stdout)
    if "(HTTP 404)" in result.stderr:
        return None
    raise RuntimeError(result.stderr[-2000:])


def mutate(label, endpoint, payload, reconcile):
    intent, response = JOURNAL / (label + ".intent.json"), JOURNAL / (label + ".response.json")
    specification = {"endpoint": endpoint, "payload": payload}
    if response.exists():
        if json.loads(intent.read_text()) != specification:
            raise RuntimeError("changed mutation identity")
        return json.loads(response.read_text())
    if intent.exists():
        if json.loads(intent.read_text()) != specification:
            raise RuntimeError("changed uncertain mutation identity")
        value = reconcile()
        if value is None:
            raise RuntimeError("unresolved mutation; no replay: " + label)
        save(response, value)
        return value
    save(intent, specification)
    request = JOURNAL / (label + ".request.json")
    save(request, payload)
    try:
        result = subprocess.run([GH, "api", "--method", "POST", endpoint, "--input", str(request)],
                                capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        save(JOURNAL / (label + ".uncertain.json"), {"reason": "client timeout; read reconciliation required"})
        value = reconcile()
        if value is None:
            raise
    else:
        if result.returncode == 0:
            value = json.loads(result.stdout)
        else:
            save(JOURNAL / (label + ".uncertain.json"), {"stderr": result.stderr[-2000:], "returncode": result.returncode})
            value = reconcile()
            if value is None:
                raise RuntimeError("mutation failed or uncertain; no blind replay: " + label)
    save(response, value)
    return value


def git_hash(kind, data):
    return hashlib.sha1(kind.encode() + b" " + str(len(data)).encode() + b"\0" + data).hexdigest()


def hash_tree(entries):
    raw = bytearray()
    for name, entry in sorted(entries.items(), key=lambda pair: pair[0].encode() +
                              (b"/" if pair[1]["type"] == "tree" else b"")):
        raw.extend(entry["mode"].lstrip("0").encode() + b" " + name.encode() + b"\0" + bytes.fromhex(entry["sha"]))
    return git_hash("tree", bytes(raw))


def direct_tree(sha):
    obj = get(f"{PREFIX}/git/trees/{sha}")
    if not obj or obj.get("truncated"):
        raise RuntimeError("missing or truncated direct tree")
    result = {x["path"]: {k: x[k] for k in ("mode", "type", "sha")} for x in obj["tree"]}
    if hash_tree(result) != sha:
        raise RuntimeError("Git tree hash reconstruction mismatch")
    return result


def find_pr(branch, base):
    items = get(f"{PREFIX}/pulls?state=all&head=" + quote("TrillionniumFoundation:" + branch, safe="")
                + "&base=" + quote(base, safe="") + "&per_page=100")
    if len(items) > 1:
        raise RuntimeError("multiple exact head/base pull requests")
    return items[0] if items else None


parent = get(f"{PREFIX}/git/commits/{SPEC['parent_commit']}")
if not parent or parent["tree"]["sha"] != SPEC["parent_tree"]:
    raise RuntimeError("parent commit/tree mismatch")
parent_ref = get(f"{PREFIX}/git/ref/heads/{SPEC['parent_branch']}")
if not parent_ref or parent_ref["object"]["sha"] != SPEC["parent_commit"]:
    raise RuntimeError("reviewed base ref moved")
identity = get("user")
if (identity.get("login"), identity.get("id")) != ("ProfHepta", 102159240):
    raise RuntimeError("native publication identity differs from the reviewed operator")
repo = get(PREFIX)
if not repo.get("permissions", {}).get("push"):
    raise RuntimeError("native identity lacks repository push permission")
save(JOURNAL / "operator.json", {"login": identity["login"], "id": identity["id"], "repository": REPO})
save(JOURNAL / "reviewed-plan.json", SPEC)
maps = {"": direct_tree(SPEC["parent_tree"])}


def ensure_map(path):
    if path in maps:
        return maps[path]
    parent_dir, _, name = path.rpartition("/")
    ancestor = ensure_map(parent_dir)
    entry = ancestor.get(name)
    if entry is None:
        maps[path] = {}
    elif entry["type"] == "tree":
        maps[path] = direct_tree(entry["sha"])
    else:
        raise RuntimeError("file blocks directory: " + path)
    return maps[path]


previous_sha, previous_tree, base_branch = SPEC["parent_commit"], SPEC["parent_tree"], SPEC["parent_branch"]
published, final_hashes = [], {}
inline_text_files, binary_blob_files = 0, 0
for index, stage in enumerate(SPEC["stages"], 1):
    label = f"stage-{index:02d}"
    additions, affected = [], set()
    for item in stage["files"]:
        path = item["path"]
        if (not (path.startswith(ALLOWED[0]) or path == ALLOWED[1])
                or ".." in Path(path).parts or Path(path).is_absolute()):
            raise RuntimeError("unreviewed publication path")
        directory, _, name = path.rpartition("/")
        entries = ensure_map(directory)
        if entries.get(name, {}).get("sha") != item.get("previous_blob_sha"):
            raise RuntimeError("exact previous blob mismatch: " + path)
        if path.startswith("qualification/hcsn_differentiable/evidence/") and name in entries:
            raise RuntimeError("existing evidence is immutable; publish a new attempt")
        raw = base64.b64decode(item["base64"], validate=True)
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise RuntimeError("source digest mismatch")
        sha = git_hash("blob", raw)
        entry = {"mode": "100644", "type": "blob", "sha": sha}
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            obj = mutate("blob-" + sha, f"{PREFIX}/git/blobs", {"encoding": "base64", "content": item["base64"]},
                         lambda s=sha: get(f"{PREFIX}/git/blobs/{s}"))
            if obj["sha"] != sha:
                raise RuntimeError("blob creation mismatch")
            additions.append(dict(entry, path=path))
            binary_blob_files += 1
        else:
            if content.encode("utf-8") != raw:
                raise RuntimeError("inline UTF-8 bytes do not round-trip: " + path)
            additions.append({"mode": "100644", "type": "blob", "path": path, "content": content})
            inline_text_files += 1
        entries[name] = entry
        final_hashes[path] = item["sha256"]
        while True:
            affected.add(directory)
            if not directory:
                break
            directory = directory.rpartition("/")[0]
    for directory in sorted(affected, key=lambda p: (p.count("/") + bool(p)), reverse=True):
        sha = hash_tree(maps[directory])
        if directory:
            ancestor, _, name = directory.rpartition("/")
            maps[ancestor][name] = {"mode": "040000", "type": "tree", "sha": sha}
    expected_tree = hash_tree(maps[""])
    tree = mutate(label + "-tree", f"{PREFIX}/git/trees", {"base_tree": previous_tree, "tree": additions},
                  lambda s=expected_tree: get(f"{PREFIX}/git/trees/{s}"))
    if tree["sha"] != expected_tree:
        raise RuntimeError("independent complete-tree Merkle mismatch")
    epoch = SPEC["commit_epoch"] + index
    date = datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    author = {"name": identity["login"], "email": f"{identity['id']}+{identity['login']}@users.noreply.github.com", "date": date}
    message = stage["message"].rstrip() + "\n"
    raw = (f"tree {expected_tree}\nparent {previous_sha}\nauthor {author['name']} <{author['email']}> {epoch} +0000\n"
           f"committer {author['name']} <{author['email']}> {epoch} +0000\n\n{message}").encode()
    expected_commit = git_hash("commit", raw)
    commit = mutate(label + "-commit", f"{PREFIX}/git/commits",
                    {"message": message, "tree": expected_tree, "parents": [previous_sha], "author": author, "committer": author},
                    lambda s=expected_commit: get(f"{PREFIX}/git/commits/{s}"))
    if commit["sha"] != expected_commit:
        raise RuntimeError("deterministic commit mismatch")
    branch = stage["branch"]
    endpoint = f"{PREFIX}/git/ref/heads/{branch}"
    existing = get(endpoint)
    if existing is not None and existing["object"]["sha"] != expected_commit:
        raise RuntimeError("branch collision; never force update")
    if existing is None:
        mutate(label + "-ref", f"{PREFIX}/git/refs", {"ref": "refs/heads/" + branch, "sha": expected_commit}, lambda e=endpoint: get(e))
    if get(endpoint)["object"]["sha"] != expected_commit:
        raise RuntimeError("ref readback mismatch")
    current_base = get(f"{PREFIX}/git/ref/heads/{base_branch}")
    if current_base["object"]["sha"] != previous_sha:
        raise RuntimeError("PR base moved; no silent rebase")
    pull = find_pr(branch, base_branch)
    if pull is None:
        pull = mutate(label + "-pr", f"{PREFIX}/pulls",
                      {"head": branch, "base": base_branch, "title": stage["title"], "body": stage["body"],
                       "draft": True, "maintainer_can_modify": True}, lambda h=branch, b=base_branch: find_pr(h, b))
    verified = get(f"{PREFIX}/pulls/{pull['number']}")
    if (verified["head"]["sha"] != expected_commit or verified["base"]["sha"] != previous_sha
            or verified["head"]["ref"] != branch or verified["base"]["ref"] != base_branch
            or verified["head"]["repo"]["full_name"] != REPO
            or verified["title"] != stage["title"] or verified["body"] != stage["body"]
            or not verified["draft"] or verified["state"] != "open"):
        raise RuntimeError("draft PR identity mismatch")
    row = {"stage": index, "branch": branch, "base": base_branch, "base_sha": previous_sha, "head_sha": expected_commit,
           "tree": expected_tree, "url": verified["html_url"], "number": verified["number"],
           "additions": verified["additions"], "deletions": verified["deletions"], "changed_files": verified["changed_files"]}
    save(JOURNAL / (label + "-verified.json"), row)
    published.append(row)
    print(json.dumps(row), flush=True)
    previous_sha, previous_tree, base_branch = expected_commit, expected_tree, branch

for directory, expected in maps.items():
    actual = direct_tree(hash_tree(expected))
    if actual != expected:
        raise RuntimeError("changed-subtree readback mismatch: " + directory)
for path, expected in final_hashes.items():
    directory, _, name = path.rpartition("/")
    blob = get(f"{PREFIX}/git/blobs/{maps[directory][name]['sha']}")
    raw = base64.b64decode(blob["content"].replace("\n", ""), validate=True)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise RuntimeError("complete-byte readback mismatch: " + path)
for stage, planned in zip(published, SPEC["stages"]):
    ref = get(f"{PREFIX}/git/ref/heads/{stage['branch']}")
    base = get(f"{PREFIX}/git/ref/heads/{stage['base']}")
    pr = get(f"{PREFIX}/pulls/{stage['number']}")
    if (not ref or not base or ref["object"]["sha"] != stage["head_sha"]
            or base["object"]["sha"] != stage["base_sha"]
            or pr["head"]["sha"] != stage["head_sha"] or pr["base"]["sha"] != stage["base_sha"]
            or pr["head"]["ref"] != stage["branch"] or pr["base"]["ref"] != stage["base"]
            or pr["title"] != planned["title"] or pr["body"] != planned["body"]
            or pr["state"] != "open" or not pr["draft"]):
        raise RuntimeError("published stack moved before final verification")
if (inline_text_files, binary_blob_files) != (61, 2):
    raise RuntimeError("frozen plan text/binary inventory mismatch")
receipt = {"status": "verified", "repository": REPO, "parent": SPEC["parent_commit"], "stages": published,
           "final_commit": previous_sha, "final_tree": previous_tree, "file_count": len(final_hashes),
           "plan_sha256": EXPECTED_PLAN_SHA256, "inline_text_files": inline_text_files,
           "binary_blob_files": binary_blob_files,
           "complete_tree_merkle_verified": True, "all_changed_files_sha256_readback_matches": True,
           "merged": False, "main_targeted_by_this_publisher": False}
save(ROOT / "receipt-inline-tree-v1.json", receipt)
print(json.dumps({"status": "verified", "final_commit": previous_sha, "stages": len(published)}), flush=True)
