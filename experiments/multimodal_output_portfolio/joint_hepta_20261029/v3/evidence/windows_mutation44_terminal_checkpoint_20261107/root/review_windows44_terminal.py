"""Independently check fixed Windows44 source and original native summaries."""

import hashlib
import json
from pathlib import Path
import re
import stat

WORK = Path("/dev/shm/ndu_root_continuation_20261107")
OWNER = Path("/dev/shm/ndu_windows44_20261107/source_auto_ci_42352197933")
HEAD = "883b85f2c0198e9373022e8082d866c080178c0a"
PARENT = "47723bb04013bf2d98647e9470561194f438a786"
TREE = "6634442bb8fb0bc8b1f86278ff4fffefdaafd23e"
CHECKOUT = "194e8fa6ba96e0b717e4ca25612b1f02720cb1cf"
RUN, JOB = 42352197933, 128343024490
TARGET = "//codex-rs/windows-sandbox-rs:windows-sandbox-rs-unit-tests"
CASES = {
    "token::tests::read_authority_probe::full_restriction_preserves_prepared_read_and_mutation_boundaries": "ok",
    "token::tests::workspace_capabilities_deny_writes_and_deletes_under_broad_identity_aces": "FAILED",
    "unified_exec::tests::legacy_workspace_write_delete_is_limited_to_writable_roots": "FAILED",
    "acl::tests::complete_denies_compare_mapped_masks_and_require_every_right": "ok",
    "acl::tests::normalized_deny_pair_requires_every_right_in_effective_and_recursive_scopes": "ok",
    "acl::tests::fresh_write_deny_preserves_generic_read_and_denies_data_mutation": "ok",
}


def require(value, reason):
    if not value:
        raise ValueError(reason)


def read(path, digest=None):
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode), "Input must be regular")
    raw = path.read_bytes()
    after = path.lstat()
    fields = (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_nlink",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
    )
    require(
        all(getattr(before, f) == getattr(after, f) for f in fields), "Input changed"
    )
    sha = hashlib.sha256(raw).hexdigest()
    require(digest is None or sha == digest, f"Input SHA changed: {path}")
    return raw, {
        "path": str(path),
        "bytes": len(raw),
        "sha256": sha,
        "mode": format(stat.S_IMODE(before.st_mode), "04o"),
    }


def load(path, digest=None):
    raw, pin = read(path, digest)
    return json.loads(raw), pin


def git_object(kind, raw):
    return hashlib.sha1(f"{kind} {len(raw)}".encode() + b"\0" + raw).hexdigest()


def main():
    safe, safe_pin = load(
        OWNER / "SAFE_NATIVE_OBSERVATIONS.json",
        "da2b21954d83b2ef840d63368598a5c819411be8061f63688d955b17a478f107",
    )
    api, api_pin = load(
        WORK / "windows44_root_terminal_api.json",
        "9c5c0600df4fc79bd72d2d74dd2d2788d8a2ae6ce98dc13b0472263153506df3",
    )
    sources, source_pin = load(
        WORK / "windows44_root_source_trees.json",
        "341bb96fce563291c12ad3b9fe517bfbd036dce2dd43ef37394ccd044d786726",
    )
    require(
        api["head"]["sha"] == HEAD and api["head"]["tree"]["sha"] == TREE,
        "Head binding",
    )
    require([row["sha"] for row in api["head"]["parents"]] == [PARENT], "Head parent")
    require(
        api["checkout"]["sha"] == CHECKOUT and api["checkout"]["tree"]["sha"] == TREE,
        "Checkout binding",
    )
    require(
        [row["sha"] for row in api["checkout"]["parents"]] == [PARENT, HEAD],
        "Checkout parents",
    )
    require(
        api["run"]["id"] == RUN
        and api["run"]["run_attempt"] == 1
        and api["run"]["head_sha"] == HEAD,
        "Run binding",
    )
    require(
        api["run"]["status"] == "completed" and api["run"]["conclusion"] == "failure",
        "Terminal run",
    )
    jobs = api["jobs"]["jobs"]
    require(
        len(jobs)
        == api["jobs"]["total_count"]
        == len({row["id"] for row in jobs})
        == 38,
        "Full jobs",
    )
    owning = next(row for row in jobs if row["id"] == JOB)
    require(
        owning["run_id"] == RUN
        and owning["run_attempt"] == 1
        and owning["head_sha"] == HEAD,
        "Owning job source",
    )
    require(
        owning["status"] == "completed" and owning["conclusion"] == "failure",
        "Owning result",
    )
    require(sources["root_tree"] == TREE and len(sources["trees"]) == 5, "Tree root")
    for prefix, tree in sources["trees"].items():
        require(tree["truncated"] is False, "Tree completeness")
        ordered = sorted(
            tree["tree"],
            key=lambda x: (x["path"] + ("/" if x["type"] == "tree" else "")).encode(),
        )
        body = b"".join(
            (row["mode"].lstrip("0") + " " + row["path"]).encode()
            + b"\0"
            + bytes.fromhex(row["sha"])
            for row in ordered
        )
        require(git_object("tree", body) == tree["sha"], "Tree identity")
        if prefix:
            parent, _, name = prefix.rpartition("/")
            entry = next(
                row for row in sources["trees"][parent]["tree"] if row["path"] == name
            )
            require(
                entry["type"] == "tree" and entry["sha"] == tree["sha"], "Ancestor link"
            )
        else:
            require(tree["sha"] == TREE, "Actual source root")
    source_rows = []
    require(
        len(safe["source"]["source_leaves"]) == len(sources["leaves"]) == 10,
        "Ten source leaves",
    )
    for item in safe["source"]["source_leaves"]:
        raw, pin = read(Path(item["local_path"]), item["sha256"])
        path = item["repository_path"]
        parent, _, name = path.rpartition("/")
        entry = next(
            row for row in sources["trees"][parent]["tree"] if row["path"] == name
        )
        require(entry == sources["leaves"][path], "Leaf link")
        require(entry["mode"] == "100644" and entry["type"] == "blob", "Leaf mode")
        require(
            len(raw) == item["bytes"]
            and git_object("blob", raw) == item["git_blob"] == entry["sha"],
            "Source byte binding",
        )
        source_rows.append({"repository_path": path, "git_blob": entry["sha"], **pin})
    path = OWNER / f"job_{JOB}.log"
    raw, original = read(
        path, "afc8e0e074eb2243ad53db45a0832f93d9c496c3cb38bfece3f094522c4297cb"
    )
    require(
        original["bytes"] == 532020
        and original["mode"] == "0600"
        and path.stat().st_nlink == 1,
        "Private original boundary",
    )
    lines = [
        re.sub(r"^\d{4}-\d{2}-\d{2}T\S+\s+", "", line)
        for line in raw.decode().splitlines()
    ]
    checkout_lines = [
        i + 1
        for i, line in enumerate(lines)
        if i
        and line.strip() == CHECKOUT
        and re.search(r'git(?:\.exe)?"? log -1 --format=%H', lines[i - 1])
    ]
    require(checkout_lines == [212], "Actual checkout log")
    case_rows = {}
    for name, expected in CASES.items():
        rows = []
        pattern = re.compile("test " + re.escape(name) + r" \.\.\. (ok|FAILED|ignored)")
        for number, line in enumerate(lines, 1):
            match = pattern.fullmatch(line)
            if match:
                rows.append({"line": number, "result": match[1]})
        require(
            rows and {row["result"] for row in rows} == {expected}, "Fixed case outcome"
        )
        case_rows[name] = rows
    require(
        case_rows == safe["fixed_case_results"] | safe["fixed_mask_case_results"],
        "Independent case rows differ",
    )
    targets = []
    pattern = re.compile(
        re.escape(TARGET)
        + r"\s+(\(cached\) )?(PASSED|FAILED|TIMEOUT) in (\d+(?:\.\d+)?)s"
    )
    for number, line in enumerate(lines, 1):
        match = pattern.fullmatch(line)
        if match:
            targets.append(
                {
                    "line": number,
                    "cached_marker": match[1] is not None,
                    "status": match[2],
                    "seconds": float(match[3]),
                }
            )
    require(
        targets
        == safe["target_rows"]
        == [
            {"line": 4094, "cached_marker": False, "status": "FAILED", "seconds": 114.1}
        ],
        "Owning target",
    )
    full_rows = [
        i
        for i, line in enumerate(lines, 1)
        if line.startswith(("FULL_", "Error: FULL_"))
    ]
    require(
        full_rows == safe["all_full_prefix_line_positions"] == [],
        "No FULL numeric observation",
    )
    require(lines[3344:3493] == lines[4332:4481], "Repeated fixed-case context differs")
    report = {
        "schema": "windows44-root-terminal-fixed-observation-review-v1",
        "head": HEAD,
        "tree": TREE,
        "parent": PARENT,
        "actual_checkout": CHECKOUT,
        "run": RUN,
        "attempt": 1,
        "job": JOB,
        "fresh_complete_API": api_pin,
        "fresh_source_API": source_pin,
        "peer_observation": safe_pin,
        "complete_ancestor_trees_rehashed": 5,
        "source_leaves": source_rows,
        "private_original_identity_only": original | {"included": False},
        "whole_workflow": "FAIL",
        "whole_job_count": 38,
        "job_conclusions": {
            label: sum(row["conclusion"] == label for row in jobs)
            for label in ("success", "failure", "skipped")
        },
        "target_rows": targets,
        "fixed_case_rows": case_rows,
        "distinct_prepared_probe_and_ACL_cases_passed": 4,
        "distinct_original_production_cases_failed": 2,
        "repeated_case_context_lines_equal": 149,
        "F0_F4_numeric_and_cleanup_records": "UNOBSERVED",
        "root_native_execution_or_retry": False,
        "root_executed_peer_observer": False,
        "unknown_private_text_exported": False,
        "P0_closed": False,
        "legacy_ACL_migration_closed": False,
        "limits": [
            "Four distinct direct case passes do not make the owning target or workflow pass.",
            "Repeated case context is a duplicate print, not independent execution evidence.",
            "No numeric values or token/handle cleanup fields are imported from Windows43.",
            "Assertion-value diagnostics remain a separate read-only observation.",
        ],
    }
    dest = WORK / "windows44_terminal_root"
    dest.mkdir(exist_ok=False)
    out = dest / "ROOT_REVIEW.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(read(out)[1]))


if __name__ == "__main__":
    main()
