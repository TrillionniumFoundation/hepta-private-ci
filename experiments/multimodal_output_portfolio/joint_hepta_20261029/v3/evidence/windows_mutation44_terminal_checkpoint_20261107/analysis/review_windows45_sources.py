"""Rebind the read-only Windows45 call-chain argument to exact source bytes."""

import hashlib
import json
from pathlib import Path
import stat

WORK = Path("/dev/shm/ndu_root_continuation_20261107")
OWNER = Path("/dev/shm/ndu_windows45_analysis_20261107")
TREE = "6634442bb8fb0bc8b1f86278ff4fffefdaafd23e"


def need(value, message):
    if not value:
        raise ValueError(message)


def checked(path, expected):
    st = path.lstat()
    need(
        stat.S_ISREG(st.st_mode) and stat.S_IMODE(st.st_mode) == 0o644,
        "Ordinary reviewed source required",
    )
    raw = path.read_bytes()
    need(hashlib.sha256(raw).hexdigest() == expected, "Exact source identity")
    return raw, {
        "path": str(path),
        "bytes": len(raw),
        "sha256": expected,
        "mode": "0644",
    }


def git_object(kind, raw):
    return hashlib.sha1(f"{kind} {len(raw)}".encode() + b"\0" + raw).hexdigest()


def main():
    raw, manifest_pin = checked(
        OWNER / "MANIFEST.json",
        "4e6d05aee9b0a575f264e2e0d590f74450371ca47910be1bd2336799e1e5078f",
    )
    manifest = json.loads(raw)
    need(manifest["tree"] == TREE and manifest["P0_closed"] is False, "Report scope")
    for item in manifest["files"]:
        _, pin = checked(Path(item["path"]), item["sha256"])
        need(pin == item, "Report manifest item")
    raw, binding_pin = checked(
        OWNER / "SOURCE_BINDING.json",
        "74adf9fa38757c8fca13b8fc28443739665c45548bc2e7e7f0da0406b34b7245",
    )
    binding = json.loads(raw)
    raw, api_pin = checked(
        WORK / "windows45_root_source_trees.json",
        "9bb6d2986c0a327b34672bf7c9bd8c81d99aaa86475a419f7169b6929187c283",
    )
    api = json.loads(raw)
    need(
        api["root_tree"] == TREE
        and len(api["trees"]) == 9
        and len(api["leaves"]) == 16,
        "Fresh root scope",
    )
    for prefix, tree in api["trees"].items():
        need(tree["truncated"] is False, "Complete tree required")
        ordered = sorted(
            tree["tree"],
            key=lambda row: (
                row["path"] + ("/" if row["type"] == "tree" else "")
            ).encode(),
        )
        body = b"".join(
            (row["mode"].lstrip("0") + " " + row["path"]).encode()
            + b"\0"
            + bytes.fromhex(row["sha"])
            for row in ordered
        )
        need(git_object("tree", body) == tree["sha"], "Tree SHA")
        if prefix:
            parent, _, name = prefix.rpartition("/")
            entry = next(
                row for row in api["trees"][parent]["tree"] if row["path"] == name
            )
            need(entry["type"] == "tree" and entry["sha"] == tree["sha"], "Tree chain")
        else:
            need(tree["sha"] == TREE, "Native source tree")
    source_rows = []
    need(len(binding["files"]) == 16, "Sixteen selected source bodies")
    for item in binding["files"]:
        raw, pin = checked(Path(item["local_path"]), item["sha256"])
        path = item["repository_path"]
        parent, _, name = path.rpartition("/")
        entry = next(row for row in api["trees"][parent]["tree"] if row["path"] == name)
        need(entry == api["leaves"][path], "Leaf identity")
        need(entry["type"] == "blob" and entry["mode"] == "100644", "Source mode")
        need(
            len(raw) == item["bytes"]
            and git_object("blob", raw) == item["git_blob"] == entry["sha"],
            "Exact current source body",
        )
        source_rows.append({"repository_path": path, "git_blob": entry["sha"], **pin})
    _, peer_pin = checked(
        Path("/dev/shm/ndu_windows45_peer_20261107/REVIEW.json"),
        "36c2ec42536e6722a38f581525e116778a6c1dc8505fea895f56e7ba390f9329",
    )
    result = {
        "schema": "windows45-root-source-and-argument-review-v1",
        "source": binding["source"],
        "owner_manifest": manifest_pin,
        "owner_source_binding": binding_pin,
        "fresh_source_API": api_pin,
        "independent_peer_review": peer_pin,
        "source_files": source_rows,
        "fresh_complete_ancestor_trees_rehashed": 9,
        "owner_full_src_subtree_trees_distinct_scope": 11,
        "root_read_complete_report_and_164_line_binder": True,
        "source_and_primary_argument_scope": [
            "All six current raw token factories share a write-only restriction constructor.",
            "The legacy full-read path has no completed read-authority input before token creation.",
            "The conditional Q counterexample assumes an enabled readable normal identity, non-owner object, non-null DACL, no privilege bypass, no extra read-only matching ACE, and no object preparation provider.",
            "Matching Q in the second DACL check recovers both its read and DELETE; omitting it loses the required read in this class.",
            "This is a limitation of the current token-only interface and stated object class, not all Windows enforcement mechanisms.",
            "Legacy read Option None and is_dir false do not identify an underlying error or prove deletion.",
        ],
        "primary_sources_opened_by_root": [
            "https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken",
            "https://learn.microsoft.com/en-us/windows/win32/secauthz/restricted-tokens",
            "https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-setsecurityinfo",
            "https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights",
            "https://learn.microsoft.com/en-us/windows/win32/secauthz/security-information",
        ],
        "direct_WRITE_DAC_source": "SECURITY_INFORMATION: DACL_SECURITY_INFORMATION requires WRITE_DAC to set.",
        "candidate_or_binder_or_native_or_model_execution": False,
        "private_console_or_execution_ZIP_read": False,
        "P0_closed": False,
        "old_ACL_migration_closed": False,
        "product_candidate_ready": False,
    }
    out = WORK / "windows45_call_chain_root"
    out.mkdir(exist_ok=False)
    dest = out / "ROOT_REVIEW.json"
    payload = (json.dumps(result, indent=2) + "\n").encode()
    dest.write_bytes(payload)
    print(
        json.dumps(
            {
                "path": str(dest),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    )


if __name__ == "__main__":
    main()
