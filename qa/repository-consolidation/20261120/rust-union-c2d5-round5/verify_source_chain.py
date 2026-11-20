"""Rebuild the complete source trees from archived leaves and exact source changes."""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile

from verify_evidence import require, safe_file, safe_name, verify


def git_oid(kind, data):
    header = kind.encode() + b" " + str(len(data)).encode() + b"\0"
    return hashlib.sha1(header + data).hexdigest()


def unwrap(value):
    for _ in range(12):
        if isinstance(value, dict) and "structuredContent" in value:
            value = value["structuredContent"]
            continue
        content = value.get("content") if isinstance(value, dict) else None
        if isinstance(content, str):
            try:
                value = json.loads(content)
                continue
            except ValueError:
                return value
        if isinstance(content, list) and len(content) == 1:
            item = content[0]
            if item.get("type") == "text":
                try:
                    value = json.loads(item["text"])
                    continue
                except ValueError:
                    return value
        return value
    raise ValueError("Unexpected response wrapper depth")


def merkle_root(leaves):
    root = {}
    for path, value in leaves.items():
        safe_name(path)
        node = root
        parts = path.split("/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            require(isinstance(node, dict), "File and directory overlap")
        require(parts[-1] not in node, "Duplicate leaf")
        node[parts[-1]] = value

    def tree_bytes(node):
        children = []
        for name, value in node.items():
            if isinstance(value, dict):
                mode = "40000"
                object_id = git_oid("tree", tree_bytes(value))
                suffix = b"/"
            else:
                mode, kind, object_id = value
                require(kind in ("blob", "commit"), "Unexpected leaf type")
                suffix = b""
            data = mode.encode() + b" " + name.encode() + b"\0"
            data += bytes.fromhex(object_id)
            children.append((name.encode() + suffix, data))
        return b"".join(data for _, data in sorted(children))

    return git_oid("tree", tree_bytes(root))


def verify_source_chain(root):
    archive_verification = verify(root)
    index = json.loads(safe_file(root, "evidence-index.json").read_bytes())
    contract = index["source_chain_verification"]
    groups = {group["id"]: group for group in index["groups"]}
    archives = {}

    def member(record):
        group_id, name = record["group"], record["member"]
        safe_name(name)
        if group_id not in archives:
            group = groups[group_id]
            archives[group_id] = b"".join(
                gzip.decompress(safe_file(root, part["path"]).read_bytes())
                for part in group["parts"]
            )
        with tarfile.open(fileobj=io.BytesIO(archives[group_id]), mode="r:gz") as tf:
            entry = tf.getmember(name)
            require(entry.isfile(), "Selected member is not a regular file")
            stream = tf.extractfile(entry)
            require(stream is not None, "Missing selected member")
            return stream.read()

    leaves = {}
    flat = gzip.decompress(member(contract["base_leaf_inventory"]))
    require(flat.endswith(b"\0"), "Leaf inventory lacks its final separator")
    for record in flat[:-1].split(b"\0"):
        metadata, raw_path = record.split(b"\t", 1)
        mode, kind, object_id = metadata.decode().split()
        path = raw_path.decode()
        safe_name(path)
        require(path not in leaves, "Duplicate base leaf")
        require(mode in ("100644", "100755", "120000", "160000"), "Unknown mode")
        require(bool(re.fullmatch("[0-9a-f]{40}", object_id)), "Invalid object ID")
        leaves[path] = (mode, kind, object_id)
    require(len(leaves) == contract["base_leaf_count"], "Base leaf count mismatch")
    require(merkle_root(leaves) == contract["base_tree"], "Base Merkle root mismatch")
    parent = contract["base_commit"]
    reviewed = []
    require(bool(contract["steps"]), "Source chain is empty")
    for step in contract["steps"]:
        require(step["parent"] == parent, "Source parent sequence mismatch")
        seen = set()
        for change in step["changes"]:
            path = change["path"]
            require(path not in seen, "Duplicate source change")
            seen.add(path)
            require(leaves[path] == tuple(change["before"]), "Source before mismatch")
            new_value = tuple(change["after"])
            data = member(change["content"])
            require(new_value[1] == "blob", "Source change is not a blob")
            require(git_oid("blob", data) == new_value[2], "Source content ID mismatch")
            require(new_value[0] == leaves[path][0], "Unexpected source mode change")
            leaves[path] = new_value
        require(len(leaves) == contract["base_leaf_count"], "Source leaf count changed")
        require(merkle_root(leaves) == step["tree"], "Source Merkle root mismatch")
        receipt = unwrap(json.loads(member(step["official_commit_receipt"])))
        require(receipt["sha"] == step["commit"], "Official commit ID mismatch")
        require(receipt["tree"]["sha"] == step["tree"], "Official tree mismatch")
        require([x["sha"] for x in receipt["parents"]] == [parent], "Unexpected parents")
        reviewed.append({"commit": step["commit"], "tree": step["tree"], "changed_paths": sorted(seen)})
        parent = step["commit"]
    final_tree = merkle_root(leaves)
    require(parent == index["source_head"], "Final source head differs from index")
    require(final_tree == index["source_tree"], "Final source tree differs from index")
    return {
        "status": "PASS_COMPLETE_SOURCE_TREE_CHAIN",
        "base_commit": contract["base_commit"],
        "base_tree": contract["base_tree"],
        "source_leaf_count": len(leaves),
        "final_head": parent,
        "final_tree": final_tree,
        "source_steps": reviewed,
        "archive_members_verified": archive_verification["members_verified"],
        "qualification": "Exact bytes and source tree identity only; no Rust or native execution.",
        "archive_members_extracted_or_executed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    print(json.dumps(verify_source_chain(args.root.resolve(strict=True)), indent=2))


if __name__ == "__main__":
    main()
