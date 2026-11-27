"""Explicit, bounded PR reconciliation for the frozen native HCSN publisher.

No execution is performed by importing this module.  A reviewed invocation must
use --execute.  Three total PR POSTs means the original publisher's one POST
plus at most two recovery POSTs, counted persistently across driver invocations.
"""

import argparse
import base64
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import time
import traceback
from urllib.parse import quote
import uuid


ROOT = Path("/Users/qianqi/hepta-hcsn-math-closure-20261108-v1/publication")
GH = "/opt/homebrew/bin/gh"
REPO = "TrillionniumFoundation/hepta-private-ci"
PREFIX = "repos/" + REPO
PULLS = PREFIX + "/pulls"
OPERATOR = ("ProfHepta", 102159240)
FROZEN = {
    "plan.json": "52e1e4baf0b45012031ff3d9d6cb9ec44c7d2cdffd6a4fc2e60d6403abfee253",
    "native_publish_inline_tree.py": "94ba6d816c1b1997ce6ca51f17be28437f5aed594ae3bf4a65053a04658c2e55",
    "retry_native_transport_inline_tree.py": "9afc06181bd8a0765d7b9e4fc270fc32ec0a84cb4ed2f7059b5cfcef0ee12ea2",
    "inline_tree_review.json": "054e2c84991642c966157e72b2cd85ffbe9146bd3b4bfae1501026be1cb86ad8",
}
TERMINAL_FILE = "inline-v2-terminal-status.json"
TERMINAL_SHA256 = "4730dba0ae67a8344cf2d26aaa951d939476c27fde7d100f520438ce6c11b69c"
ORIGINAL_JOB = "1a1bb188227-13c47-99"
ORIGINAL_PID = 92584
ORIGINAL_LSTART = "Sun Nov 8 20:18:47 2026"
MAX_TOTAL_PR_POSTS = 3
ORIGINAL_PR_POSTS = 1
MAX_RECOVERY_POSTS = MAX_TOTAL_PR_POSTS - ORIGINAL_PR_POSTS
MAX_WRAPPER_RUNS = 8
NATIVE_RUN = subprocess.run
NETWORK_ERROR = re.compile(
    r'(?P<method>Get|Post) "(?P<url>https://api\.github\.com/[^"\n]+)": '
    r'(?:dial tcp [0-9.]+:443: (?:i/o timeout|connect: network is unreachable|connect: connection refused)'
    r'|net/http: TLS handshake timeout)\n?\Z'
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git_hash(kind, data):
    return hashlib.sha1(kind.encode() + b" " + str(len(data)).encode() + b"\0" + data).hexdigest()


def hash_tree(entries):
    raw = bytearray()
    for name, entry in sorted(entries.items(), key=lambda pair: pair[0].encode() +
                              (b"/" if pair[1]["type"] == "tree" else b"")):
        raw.extend(entry["mode"].lstrip("0").encode() + b" " + name.encode() + b"\0" + bytes.fromhex(entry["sha"]))
    return git_hash("tree", bytes(raw))


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def create_only(path, value):
    data = encode(value)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def immutable(path, value):
    if path.exists():
        if json.loads(path.read_bytes()) != value:
            raise RuntimeError("immutable recovery identity mismatch: " + path.name)
    else:
        create_only(path, value)


def network_failure(result, method, endpoint):
    match = NETWORK_ERROR.fullmatch(result.get("stderr", ""))
    return (type(result.get("returncode")) is int and result["returncode"] == 1
            and not result.get("outer_timeout")
            and result.get("stdout") == "" and match is not None
            and match["method"].upper() == method
            and match["url"] == "https://api.github.com/" + endpoint)


def original_network_uncertain(value):
    # The original helper did not retain stdout; do not infer that it was empty.
    match = NETWORK_ERROR.fullmatch(value.get("stderr", ""))
    return (type(value.get("returncode")) is int and value["returncode"] == 1 and match is not None
            and match["method"] == "Post" and match["url"] == "https://api.github.com/" + PULLS)


def process_result(command, timeout):
    started = time.monotonic()
    def streams(stdout, stderr):
        stdout = stdout if isinstance(stdout, bytes) else (stdout or "").encode()
        stderr = stderr if isinstance(stderr, bytes) else (stderr or "").encode()
        return {"stdout": stdout.decode("utf-8", "replace"), "stderr": stderr.decode("utf-8", "replace"),
                "stdout_bytes_hex": stdout.hex(), "stderr_bytes_hex": stderr.hex()}
    try:
        result = NATIVE_RUN(command, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        return dict(streams(error.stdout, error.stderr), returncode=None, outer_timeout=True,
                    elapsed_seconds=time.monotonic() - started)
    return dict(streams(result.stdout, result.stderr), returncode=result.returncode, outer_timeout=False,
                elapsed_seconds=time.monotonic() - started)


class Recovery:
    def __init__(self, root=ROOT):
        self.root = root
        self.original = root / "journal-inline-tree-v1"
        self.ledger = root / "pr-recovery-v1"
        self.ledger.mkdir(exist_ok=True)
        self.run_dir = self.ledger / ("run-" + uuid.uuid4().hex)
        self.run_dir.mkdir()
        self.sequence = 0
        self.spec = json.loads((root / "plan.json").read_bytes())
        self.expected = []

    def event(self, kind, value):
        self.sequence += 1
        create_only(self.run_dir / ("%04d-%s.json" % (self.sequence, kind)), value)

    def frozen(self):
        if os.environ.get("GODEBUG") != "http2client=0":
            raise RuntimeError("GODEBUG must remain http2client=0")
        for name, expected in FROZEN.items():
            if digest((self.root / name).read_bytes()) != expected:
                raise RuntimeError("frozen input changed: " + name)

    def confirm_old_job_terminal(self):
        data = (self.root / TERMINAL_FILE).read_bytes()
        if digest(data) != TERMINAL_SHA256:
            raise RuntimeError("original native terminal receipt digest mismatch")
        receipt = json.loads(data)
        if not (receipt["job_id"] == ORIGINAL_JOB and receipt["state"] == "failed"
                and receipt["exit_code"] == 1 and receipt["terminal_publication_confirmed"]
                and receipt["output_complete"] and receipt["output_durable"]):
            raise RuntimeError("original job is not confirmed terminal")
        result = process_result(["/bin/ps", "-p", str(ORIGINAL_PID), "-o", "lstart="], 10)
        if result["outer_timeout"] or result["stderr"]:
            raise RuntimeError("old native process liveness is unconfirmed")
        active_identity = " ".join(result["stdout"].split())
        if result["returncode"] == 0:
            if not active_identity or active_identity == ORIGINAL_LSTART:
                raise RuntimeError("original publisher identity remains active or ambiguous")
        elif result["returncode"] != 1 or active_identity:
            raise RuntimeError("unexpected process-liveness result")
        self.event("old-job-terminal", {"receipt": receipt, "pid_probe": result,
                                       "original_lstart": ORIGINAL_LSTART})

    def get(self, endpoint):
        for attempt in range(1, 5):
            result = process_result([GH, "api", endpoint], 90)
            evidence = dict(result, endpoint=endpoint, method="GET", attempt=attempt)
            if endpoint == "user" and result["returncode"] == 0:
                identity = json.loads(result["stdout"])
                evidence.pop("stdout")
                evidence.pop("stdout_bytes_hex", None)
                evidence.update(stdout_kind="explicit_identity_fields_derivative",
                                original_stdout_sha256=digest(result["stdout"].encode()),
                                identity={k: identity.get(k) for k in ("login", "id")})
            self.event("read", evidence)
            if result["returncode"] == 0:
                return json.loads(result["stdout"])
            if "(HTTP 404)" in result["stderr"]:
                return None
            retryable = network_failure(result, "GET", endpoint) or (
                result["outer_timeout"] and result["stdout"] == "")
            if not retryable or attempt == 4:
                raise RuntimeError("read failed; not an empty result: " + endpoint)
        raise AssertionError("unreachable")

    def identity(self):
        identity = self.get("user")
        if (identity.get("login"), identity.get("id")) != OPERATOR:
            raise RuntimeError("native GitHub identity changed")

    def ref(self, branch):
        value = self.get(PREFIX + "/git/ref/heads/" + branch)
        if not value or value.get("ref") != "refs/heads/" + branch or value["object"]["type"] != "commit":
            raise RuntimeError("required exact branch is absent or invalid")
        return value["object"]["sha"]

    def prepare_expected_stack(self):
        spec = self.spec
        if (spec["parent_commit"], spec["parent_tree"], spec["parent_branch"]) != (
                "bb048cb811c2b755b7e54e97d24c63ec7ec8d1b7",
                "0f615c0b512d37cb4ec129c66e1a7ae07f90f163",
                "codex/hcsn-diff-07-evidence-20261108"):
            raise RuntimeError("reviewed parent changed")
        branches = [s["branch"] for s in spec["stages"]]
        if len(branches) != 7 or len(set(branches)) != 7 or any(
                re.fullmatch(r"codex/hcsn-math-[a-z0-9-]+-20261108-v1", b) is None for b in branches):
            raise RuntimeError("unreviewed branch namespace")
        parent = self.get(PREFIX + "/git/commits/" + spec["parent_commit"])
        if not parent or parent["tree"]["sha"] != spec["parent_tree"] or self.ref(spec["parent_branch"]) != spec["parent_commit"]:
            raise RuntimeError("reviewed parent commit/ref moved")
        maps = {}
        def direct_tree(sha):
            value = self.get(PREFIX + "/git/trees/" + sha)
            if not value or value.get("truncated"):
                raise RuntimeError("missing or truncated original tree")
            entries = {x["path"]: {k: x[k] for k in ("mode", "type", "sha")} for x in value["tree"]}
            if hash_tree(entries) != sha:
                raise RuntimeError("original tree Merkle mismatch")
            return entries
        maps[""] = direct_tree(spec["parent_tree"])
        def ensure_map(path):
            if path not in maps:
                parent_path, _, name = path.rpartition("/")
                entry = ensure_map(parent_path).get(name)
                if entry is not None and entry["type"] != "tree":
                    raise RuntimeError("file blocks planned directory")
                maps[path] = direct_tree(entry["sha"]) if entry else {}
            return maps[path]
        previous, previous_tree, base = spec["parent_commit"], spec["parent_tree"], spec["parent_branch"]
        all_paths = set()
        for index, stage in enumerate(spec["stages"], 1):
            affected = set()
            for item in stage["files"]:
                path = item["path"]
                if (not (path.startswith("qualification/hcsn_differentiable/") or
                         path == ".github/workflows/hcsn-differentiable.yml")
                        or ".." in Path(path).parts or Path(path).is_absolute() or path in all_paths):
                    raise RuntimeError("unreviewed or repeated file path")
                all_paths.add(path)
                directory, _, name = path.rpartition("/")
                entries = ensure_map(directory)
                if entries.get(name, {}).get("sha") != item.get("previous_blob_sha"):
                    raise RuntimeError("exact old blob mismatch")
                if path.startswith("qualification/hcsn_differentiable/evidence/") and name in entries:
                    raise RuntimeError("frozen evidence replacement")
                raw = base64.b64decode(item["base64"], validate=True)
                if digest(raw) != item["sha256"]:
                    raise RuntimeError("planned source digest mismatch")
                entries[name] = {"mode": "100644", "type": "blob", "sha": git_hash("blob", raw)}
                while True:
                    affected.add(directory)
                    if not directory:
                        break
                    directory = directory.rpartition("/")[0]
            for directory in sorted(affected, key=lambda p: p.count("/") + bool(p), reverse=True):
                tree_sha = hash_tree(maps[directory])
                if directory:
                    ancestor, _, name = directory.rpartition("/")
                    maps[ancestor][name] = {"mode": "040000", "type": "tree", "sha": tree_sha}
            tree_sha = hash_tree(maps[""])
            epoch = spec["commit_epoch"] + index
            date = datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            author = {"name": OPERATOR[0], "email": "%s+%s@users.noreply.github.com" % (OPERATOR[1], OPERATOR[0]), "date": date}
            message = stage["message"].rstrip() + "\n"
            raw_commit = (f"tree {tree_sha}\nparent {previous}\nauthor {author['name']} <{author['email']}> {epoch} +0000\n"
                          f"committer {author['name']} <{author['email']}> {epoch} +0000\n\n{message}").encode()
            head = git_hash("commit", raw_commit)
            commit_payload = {"message": message, "tree": tree_sha, "parents": [previous], "author": author, "committer": author}
            pr_payload = {"head": stage["branch"], "base": base, "title": stage["title"], "body": stage["body"],
                          "draft": True, "maintainer_can_modify": True}
            self.expected.append({"index": index, "branch": stage["branch"], "base": base, "head": head,
                                  "parent": previous, "tree": tree_sha, "parent_tree": previous_tree,
                                  "commit_payload": commit_payload, "pr_payload": pr_payload})
            previous, previous_tree, base = head, tree_sha, stage["branch"]
        if len(all_paths) != 63:
            raise RuntimeError("frozen file inventory mismatch")
        if [s["head"] for s in self.expected[:2]] != [
                "6f348b68a93fe74d0dd01f5836d503b225a4676b", "62323b65b8b1423aec439039c69112883546e859"]:
            raise RuntimeError("reconstructed stack disagrees with observed first two commits")
        self.event("expected-stack", {"plan_sha256": FROZEN["plan.json"], "stages": self.expected,
                                      "expected_only_not_publication_receipt": True})

    def validate_refs_and_commit(self, stage):
        label = "stage-%02d" % stage["index"]
        expected_intent = {"endpoint": PREFIX + "/git/commits", "payload": stage["commit_payload"]}
        if json.loads((self.original / (label + "-commit.intent.json")).read_bytes()) != expected_intent:
            raise RuntimeError("original commit intent differs from reconstructed plan")
        if self.ref(stage["base"]) != stage["parent"] or self.ref(stage["branch"]) != stage["head"]:
            raise RuntimeError("head or base branch moved")
        value = self.get(PREFIX + "/git/commits/" + stage["head"])
        payload = stage["commit_payload"]
        if (not value or value["sha"] != stage["head"] or value["tree"]["sha"] != stage["tree"]
                or [p["sha"] for p in value["parents"]] != [stage["parent"]]
                or value["message"].rstrip("\n") != payload["message"].rstrip("\n")
                or value["author"] != payload["author"] or value["committer"] != payload["committer"]):
            raise RuntimeError("actual commit identity differs from reconstructed plan")

    def verify_pr(self, value, stage):
        payload = stage["pr_payload"]
        if (value["head"]["ref"] != stage["branch"] or value["base"]["ref"] != stage["base"]
                or value["head"]["sha"] != stage["head"] or value["base"]["sha"] != stage["parent"]
                or value["head"]["repo"]["full_name"] != REPO or value["base"]["repo"]["full_name"] != REPO
                or value["title"] != payload["title"] or value["body"] != payload["body"]
                or value["state"] != "open" or value.get("merged_at") is not None or not value["draft"]):
            raise RuntimeError("existing exact PR is closed, merged, or differs from the reviewed identity")
        return value

    def find_pr(self, stage):
        endpoint = (PULLS + "?state=all&head=" + quote("TrillionniumFoundation:" + stage["branch"], safe="")
                    + "&base=" + quote(stage["base"], safe="") + "&per_page=100")
        values = self.get(endpoint)
        if not isinstance(values, list):
            raise RuntimeError("PR query did not return a list")
        if len(values) > 1:
            raise RuntimeError("multiple exact head/base PRs; no new PR")
        return self.verify_pr(values[0], stage) if values else None

    def response(self, path, value, stage):
        self.verify_pr(value, stage)
        if path.exists():
            self.verify_pr(json.loads(path.read_bytes()), stage)
        else:
            create_only(path, value)
        self.event("pr-reconciled", {"stage": stage["index"], "pr": value["number"],
                                    "url": value["html_url"], "head": stage["head"],
                                    "response_created_or_verified": True})

    def recover_pr(self, stage):
        self.frozen()
        self.wrapper_ledger()
        label = "stage-%02d-pr" % stage["index"]
        original_intent = self.original / (label + ".intent.json")
        uncertain_path = self.original / (label + ".uncertain.json")
        request = self.original / (label + ".request.json")
        response = self.original / (label + ".response.json")
        intent_bytes, uncertain_bytes, request_bytes = original_intent.read_bytes(), uncertain_path.read_bytes(), request.read_bytes()
        if json.loads(intent_bytes) != {"endpoint": PULLS, "payload": stage["pr_payload"]}:
            raise RuntimeError("original PR intent differs from pinned plan")
        if json.loads(request_bytes) != stage["pr_payload"] or not original_network_uncertain(json.loads(uncertain_bytes)):
            raise RuntimeError("original PR request or network error is not admitted")
        request_sha = digest(request_bytes)
        target = self.ledger / label
        target.mkdir(exist_ok=True)
        immutable(target / "scope.json", {"plan_sha256": FROZEN["plan.json"], "stage": stage["index"],
                  "request_sha256": request_sha, "original_intent_sha256": digest(intent_bytes),
                  "original_uncertain_sha256": digest(uncertain_bytes), "original_stdout": "not retained; no inference",
                  "original_post_attempts": ORIGINAL_PR_POSTS, "maximum_total_post_attempts": MAX_TOTAL_PR_POSTS,
                  "maximum_recovery_post_attempts": MAX_RECOVERY_POSTS,
                  "transmission_outcome": "not inferred", "expected_head": stage["head"], "expected_base": stage["parent"]})
        for next_index in range(1, MAX_RECOVERY_POSTS + 2):
            found = self.find_pr(stage)
            if found is not None:
                self.validate_refs_and_commit(stage)
                self.response(response, found, stage)
                return
            if response.exists():
                raise RuntimeError("previously recorded PR no longer appears; no new PR")
            existing = [n for n in range(1, MAX_RECOVERY_POSTS + 1) if (target / ("post-%02d.intent.json" % n)).exists()]
            if existing != list(range(1, len(existing) + 1)):
                raise RuntimeError("non-contiguous recovery call ledger")
            if existing:
                prior_path = target / ("post-%02d.result.json" % existing[-1])
                if not prior_path.exists() or not network_failure(json.loads(prior_path.read_bytes()), "POST", PULLS):
                    raise RuntimeError("previous recovery result is unknown or not an exact empty-stdout network failure")
            if len(existing) >= MAX_RECOVERY_POSTS:
                raise RuntimeError("total PR POST budget exhausted; no additional POST")
            self.frozen()
            self.wrapper_ledger()
            self.identity()
            self.validate_refs_and_commit(stage)
            # Reconcile once more immediately before writing an explicit new intent.
            found = self.find_pr(stage)
            if found is not None:
                self.response(response, found, stage)
                return
            if digest(request.read_bytes()) != request_sha:
                raise RuntimeError("original PR request bytes changed")
            number = len(existing) + 1
            create_only(target / ("post-%02d.intent.json" % number),
                        {"stage": stage["index"], "endpoint": PULLS, "request_sha256": request_sha,
                         "recovery_post_index": number, "total_post_index": ORIGINAL_PR_POSTS + number,
                         "expected_head": stage["head"], "expected_base": stage["parent"],
                         "transmission_outcome": "not inferred", "fresh_exact_pr_query_was_empty": True})
            if digest(request.read_bytes()) != request_sha:
                raise RuntimeError("request changed after recovery intent; no call made")
            result = process_result([GH, "api", "--method", "POST", PULLS, "--input", str(request)], 120)
            create_only(target / ("post-%02d.result.json" % number), result)
            # Even an HTTP error or outer timeout gets read-only reconciliation.
            found = self.find_pr(stage)
            if found is not None:
                self.validate_refs_and_commit(stage)
                self.response(response, found, stage)
                return
            if not network_failure(result, "POST", PULLS):
                raise RuntimeError("PR POST was not an admitted network failure; no automatic replay")
        raise RuntimeError("bounded PR recovery exhausted")

    def pending_prs(self):
        pending = []
        for stage in self.expected:
            label = "stage-%02d-pr" % stage["index"]
            if (self.original / (label + ".intent.json")).exists() and not (self.original / (label + ".response.json")).exists():
                pending.append(stage)
        if len(pending) > 1:
            raise RuntimeError("more than one incomplete PR intent; manual review required")
        return pending

    def wrapper_ledger(self):
        intents = [n for n in range(1, MAX_WRAPPER_RUNS + 1) if (self.ledger / ("wrapper-%02d.intent.json" % n)).exists()]
        if intents != list(range(1, len(intents) + 1)):
            raise RuntimeError("non-contiguous wrapper-run ledger")
        for number in intents:
            if not (self.ledger / ("wrapper-%02d.result.json" % number)).exists():
                raise RuntimeError("previous wrapper run is unresolved; no new wrapper")
        return intents

    def run_wrapper(self):
        intents = self.wrapper_ledger()
        if len(intents) >= MAX_WRAPPER_RUNS:
            raise RuntimeError("bounded wrapper-run budget exhausted")
        self.frozen()
        number = len(intents) + 1
        create_only(self.ledger / ("wrapper-%02d.intent.json" % number),
                    {"wrapper_sha256": FROZEN["retry_native_transport_inline_tree.py"],
                     "plan_sha256": FROZEN["plan.json"], "same_original_journal": True})
        old_argv = sys.argv[:]
        subprocess.run = NATIVE_RUN
        try:
            runpy.run_path(str(self.root / "retry_native_transport_inline_tree.py"), run_name="__main__")
        except Exception as error:
            result = {"success": False, "exception_type": type(error).__name__, "error": str(error),
                      "traceback": traceback.format_exc()}
        else:
            result = {"success": True}
        finally:
            subprocess.run = NATIVE_RUN
            sys.argv = old_argv
        create_only(self.ledger / ("wrapper-%02d.result.json" % number), result)
        return result

    def execute(self):
        self.frozen()
        self.confirm_old_job_terminal()
        self.wrapper_ledger()
        self.identity()
        self.prepare_expected_stack()
        for _ in range(MAX_WRAPPER_RUNS):
            pending = self.pending_prs()
            if pending:
                self.recover_pr(pending[0])
            outcome = self.run_wrapper()
            if outcome["success"]:
                receipt = json.loads((self.root / "receipt-inline-tree-v1.json").read_bytes())
                if (receipt["status"] != "verified" or len(receipt["stages"]) != 7 or receipt["file_count"] != 63
                        or receipt["final_commit"] != self.expected[-1]["head"]
                        or receipt["final_tree"] != self.expected[-1]["tree"]
                        or not receipt["all_changed_files_sha256_readback_matches"]):
                    raise RuntimeError("final original publication receipt differs from reconstructed plan")
                self.event("completed", {"original_receipt_sha256": digest((self.root / "receipt-inline-tree-v1.json").read_bytes()),
                                         "final_commit": receipt["final_commit"], "final_tree": receipt["final_tree"]})
                print(json.dumps({"recovery_status": "verified", "final_commit": receipt["final_commit"],
                                  "final_tree": receipt["final_tree"], "stages": 7}), flush=True)
                return
            pending = self.pending_prs()
            if not pending:
                raise RuntimeError("wrapper failed outside an incomplete PR; preserved without restart: " + outcome["error"])
            uncertain = self.original / ("stage-%02d-pr.uncertain.json" % pending[0]["index"])
            if not uncertain.exists() or not original_network_uncertain(json.loads(uncertain.read_bytes())):
                raise RuntimeError("wrapper PR failure is not an admitted exact network failure")
        raise RuntimeError("overall recovery bound exhausted")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"status": "prepared_not_executed", "maximum_total_posts_per_pr": MAX_TOTAL_PR_POSTS,
                          "original_posts_per_failed_pr": ORIGINAL_PR_POSTS,
                          "maximum_recovery_posts_per_pr": MAX_RECOVERY_POSTS, "maximum_wrapper_runs": MAX_WRAPPER_RUNS}))
        return
    with (ROOT / "publication-operation.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        recovery = Recovery()
        recovery.execute()


if __name__ == "__main__":
    main()
