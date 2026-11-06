#!/usr/bin/env python3
"""Restore exact C4 root evidence and run bounded, offline identity checks.

This verifies C3 trees/delta/contracts and actual publication readbacks. It
does not execute the preserved C3 builder or any restored product code.
"""
from pathlib import Path, PurePosixPath
from collections import Counter
import argparse
import base64
import hashlib
import json
import posixpath
import tempfile
import zipfile


PREFIX = "qualification/r3-audit-repair-20261104/continuation-20261105/"
C2_COMMIT = "9ad1f5902f3a2b0b2c712e718a39c2ad2a6c791f"
C2_TREE = "8b9bfcacea9c3ff40b0d58ca78209e2b7537a753"
C3_TREE = "d7716cca653bf7795307b052352e8671cd9fd944"
PRODUCT_PARENT = "2d1137b1ba39fab0e6a28bac8decc114dfa0138c"
TARGET = "63652be658ebed8d3052eb789b951793384fd5e4"
API = "https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def identity(raw):
    return {"bytes": len(raw), "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
            "sha256": hashlib.sha256(raw).hexdigest()}


def same(raw, expected):
    require(identity(raw) == {k: expected[k] for k in ("bytes", "git_blob", "sha256")}, "complete byte identity mismatch")


def safe_path(name):
    require(isinstance(name, str) and name and not name.startswith("/") and "\\" not in name and "\0" not in name,
            "unsafe archive path")
    require(all(p not in ("", ".", "..") for p in name.split("/")), "noncanonical archive path")
    return PurePosixPath(name)


def tree_hashes(tree):
    require(tree.get("truncated") is False, "full tree is truncated")
    rows = {r["path"]: {k: r[k] for k in ("path", "mode", "type", "sha")} for r in tree["tree"]}
    require(len(rows) == len(tree["tree"]), "duplicate full-tree paths")
    leaves = {p: r for p, r in rows.items() if r["type"] != "tree"}
    directories = {"": {}}
    for path, row in leaves.items():
        safe_path(path)
        require(row["type"] == "blob" and row["mode"] in ("100644", "100755", "120000"), "unexpected leaf type/mode")
        parent, name = posixpath.split(path)
        directories.setdefault(parent, {})[name] = (row["mode"], row["sha"])
        while parent:
            parent = posixpath.dirname(parent)
            directories.setdefault(parent, {})
    hashes = {}
    for directory in sorted(directories, key=lambda p: (p.count("/") + bool(p), p), reverse=True):
        entries = directories[directory]
        ordered = sorted(entries.items(), key=lambda item: (item[0] + ("/" if item[1][0] == "40000" else "")).encode())
        raw = b"".join(mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(sha) for name, (mode, sha) in ordered)
        sha = hashlib.sha1(b"tree " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        hashes[directory] = sha
        if directory:
            parent, name = posixpath.split(directory)
            require(name not in directories[parent], "file/directory collision")
            directories[parent][name] = ("40000", sha)
    declared = {p: r["sha"] for p, r in rows.items() if r["type"] == "tree"}
    require(declared == {p: sha for p, sha in hashes.items() if p}, "directory hash mismatch")
    require(hashes[""] == tree["sha"], "root tree hash mismatch")
    return leaves


def actual_readbacks(folder):
    """Accept only successful full JSON GET bodies with a repository API URL."""
    results = []
    for path in sorted(folder.glob("*.json")):
        value = json.loads(path.read_bytes())
        if not isinstance(value, dict) or value.get("isError") is not False:
            continue
        wrapper = value.get("structuredContent", {})
        if not isinstance(wrapper, dict) or not isinstance(wrapper.get("content"), str):
            continue
        url = wrapper.get("url", "")
        if not isinstance(url, str) or not url.startswith(API):
            continue
        try:
            body = json.loads(wrapper["content"])
        except ValueError:
            continue
        if isinstance(body, dict):
            results.append({"file": path.name, "url": url, "body": body})
    return results


def matching(records, predicate, label):
    found = [r for r in records if predicate(r["body"], r["url"])]
    require(found, "missing actual publication readback: " + label)
    return found


def publication_checks(root, expected):
    c3, fmt = actual_readbacks(root / "second-audit-publication"), actual_readbacks(root / "integration-fmt-publication")
    result = {}
    for label, records, sha, tree, parents, ref in (
        ("C3", c3, expected["c3_commit"], C3_TREE, [C2_COMMIT], "refs/heads/audit/r3-evidence-20261105"),
        ("fmt", fmt, expected["fmt_head"], expected["fmt_tree"], [PRODUCT_PARENT], "refs/heads/integration/r3-repairs-and-locks-20261106"),
    ):
        commits = matching(records, lambda b, u: u.rstrip("/").endswith("/git/commits/" + sha) and b.get("sha") == sha, label + " commit")
        for r in commits:
            require(r["body"]["tree"]["sha"] == tree and [p["sha"] for p in r["body"]["parents"]] == parents, label + " tree/ordered parents mismatch")
        refs = matching(records, lambda b, u: ("/git/ref/" in u or "/git/refs/" in u) and b.get("ref") == ref and b.get("object", {}).get("sha") == sha, label + " ref")
        result[label] = {"commit": sha, "tree": tree, "ordered_parents": parents,
                         "actual_commit_files": [r["file"] for r in commits], "actual_ref_files": [r["file"] for r in refs]}
    prs = matching(fmt, lambda b, u: u.rstrip("/").endswith("/pulls/4936") and b.get("number") == 4936 and b.get("head", {}).get("sha") == expected["fmt_head"], "fmt PR4936")
    require(all(row["body"]["base"]["sha"] == TARGET for row in prs), "fmt PR base changed")
    final_prs = [row for row in prs if row["body"].get("merge_commit_sha") == expected["fmt_merge"]]
    require(final_prs, "missing final fmt PR readback with the actual successor merge")
    merges = matching(fmt, lambda b, u: u.rstrip("/").endswith("/git/commits/" + expected["fmt_merge"]) and b.get("sha") == expected["fmt_merge"], "fmt actual merge")
    for row in merges:
        body = row["body"]
        require(body["tree"]["sha"] == expected["fmt_tree"] and [p["sha"] for p in body["parents"]] == [TARGET, expected["fmt_head"]], "fmt merge tree/parents mismatch")
    result["fmt"].update({"PR": 4936, "actual_final_PR_files": [r["file"] for r in final_prs],
                          "all_PR_observations_preserved": [{"file": r["file"], "observed_merge_field": r["body"].get("merge_commit_sha")} for r in prs],
                          "historical_stale_merge_fields_are_not_promoted_to_final_identity": True,
                          "merge": expected["fmt_merge"], "actual_merge_files": [r["file"] for r in merges]})
    return result


def verify_root_evidence(root, expected):
    load = lambda name: json.loads((root / name).read_bytes())
    before = load("publication/post-audit-final-full-tree.json")
    after = load("publication/second-post-audit-final-full-tree.json")
    a, b = tree_hashes(before), tree_hashes(after)
    plan = load("publication/second-post-audit-delta.plan.json")
    require(before["sha"] == C2_TREE and after["sha"] == C3_TREE, "wrong fixed C2/C3 trees")
    require(plan["parent_commit"] == C2_COMMIT and plan["base_tree"] == C2_TREE and plan["expected_tree"] == C3_TREE, "C3 plan identity changed")
    changed = {p for p in a if a[p] != b.get(p)}
    require(changed == {PREFIX + "LATEST.md", PREFIX + "LATEST.zh-CN.md"} and not set(a) - set(b), "old C2 paths changed/deleted")
    require(len(a) == 14725 and len(b) == 15232 and len(set(b) - set(a)) == 507, "wrong C3 denominators")
    delta = {p: r for p, r in b.items() if r != a.get(p)}
    require(len(delta) == 509 and {r["path"]: r for r in plan["tree_elements"]} == delta, "C3 delta projection mismatch")
    for suffix in (".md", ".zh-CN.md"):
        require(b[PREFIX + "history/LATEST.pre-second-post-audit" + suffix]["sha"] == a[PREFIX + "LATEST" + suffix]["sha"], "C2 history alias identity mismatch")
    ledger_raw = (root / "documents/continuation-blocker-progress-v8.json").read_bytes()
    machine_raw = (root / "second-post-audit-documents/post-audit-execution-v2.json").read_bytes()
    require(identity(ledger_raw)["git_blob"] == a[PREFIX + "continuation-blocker-progress-v8.json"]["sha"], "ledger body is not the fixed C2 leaf")
    require(identity(machine_raw)["git_blob"] == b[PREFIX + "post-audit-execution-v2.json"]["sha"], "machine body is not the fixed C3 leaf")
    ledger, machine = json.loads(ledger_raw), json.loads(machine_raw)
    fields = ("id", "name", "status", "closure_class", "original_exit_condition_zh")
    contracts = [{key: row[key] for key in fields} for row in ledger["items"]]
    require(len(contracts) == 23 and machine["original_blocker_contracts"] == contracts, "original 23 contracts changed")
    require(dict(Counter(r["closure_class"] for r in contracts)) == machine["counts"] == {"CLOSED_SCOPED": 16, "OPEN": 6, "SCIENTIFIC_HOLD": 1}, "closure counts changed")
    require(machine["closure_transitions_in_this_increment"] == [] and machine["all_blockers_closed"] is False and machine["whole_candidate_qualified"] is False, "unsupported closure transition")
    execution = load("publication/second-post-audit-delta.execute-02.receipt.json")
    require(execution["exit_code"] == 0, "preserved final C3 builder exit not zero")
    same((root / "prepare_second_post_audit_delta.py").read_bytes(), execution["source"])
    same((root / "publication/second-post-audit-delta.execute-02.stdout.json").read_bytes(), execution["stdout"])
    same((root / "publication/second-post-audit-delta.execute-02.stderr.txt").read_bytes(), execution["stderr"])
    require(execution["stderr"]["bytes"] == 0, "preserved C3 final stderr nonempty")
    first = load("publication/second-post-audit-delta.execute-01.receipt.json")
    require(first["exit_code"] == 1, "original first preparation failure changed")
    for stream, extension in (("stdout", "json"), ("stderr", "txt")):
        same((root / ("publication/second-post-audit-delta.execute-01." + stream + "." + extension)).read_bytes(), first[stream])
    return {"C2_tree": C2_TREE, "C3_tree": C3_TREE, "old_leaves_retained": 14723, "delta_paths": 509,
            "final_leaves": 15232, "original_contracts_equal": 23, "counts": machine["counts"],
            "C3_builder_first_failure_and_final_success_retained": True,
            "publication": publication_checks(root, expected),
            "full_C3_builder_executed": False, "restored_product_or_CI_executed": False,
            "limits": "The full C3 builder needs its separately registered external packets/411 original inputs. This packet verifies only integrity, fixed tree/delta/contracts and publication readback identities; it does not repeat component/native qualification."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    packet, output = args.packet.resolve(), args.output.resolve()
    require(not output.exists(), "restore only to a new output directory")
    archive = json.loads((packet / "archive.json").read_bytes())
    manifest_raw = (packet / "manifest.json").read_bytes()
    same(manifest_raw, archive["payload_manifest"])
    manifest = json.loads(manifest_raw)
    rows = {r["path"]: r for r in manifest["files"]}
    require(len(rows) == len(manifest["files"]) == manifest["member_count"], "duplicate/missing member declarations")
    require(sum(r["bytes"] for r in rows.values()) == manifest["total_original_bytes"], "member byte denominator mismatch")
    with tempfile.TemporaryDirectory(prefix="hepta-C4-root-restore-") as temp:
        zip_path = Path(temp) / "snapshot.zip"
        names = set()
        with zip_path.open("xb") as writer:
            for part in archive["parts"]:
                p = safe_path(part["path"])
                require(len(p.parts) == 1 and p.name not in names, "duplicate/unsafe part name")
                names.add(p.name)
                raw = (packet / p.name).read_bytes()
                same(raw, part)
                require(len(raw) <= 400000, "part exceeds registered text limit")
                writer.write(base64.b64decode(raw, validate=True))
        same(zip_path.read_bytes(), archive["archive"])
        with zipfile.ZipFile(zip_path) as z:
            require(len(z.infolist()) == len(rows) and set(z.namelist()) == set(rows) and z.testzip() is None, "ZIP inventory/CRC mismatch")
            for member in z.infolist():
                p = safe_path(member.filename)
                require(not member.is_dir() and member.external_attr >> 16 == 0o100644, "unexpected ZIP member type/mode")
                raw = z.read(member)
                same(raw, rows[member.filename])
                dest = output.joinpath(*p.parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open("xb") as writer:
                    writer.write(raw)
    result = verify_root_evidence(output, manifest["publication_expectations"])
    print(json.dumps({"archive": archive["archive"], "parts": len(archive["parts"]), "members": len(rows),
                      "all_original_bytes_equal": True, "verification": result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
