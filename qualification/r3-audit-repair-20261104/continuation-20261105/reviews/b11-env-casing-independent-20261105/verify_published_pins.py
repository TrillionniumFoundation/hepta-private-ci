"""Bind all helper pins to the newly published diagnostic commit's actual root."""

import ast
from collections import defaultdict
import hashlib
import json
from pathlib import Path


BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
COMMIT = "021a59ff05ccd963bc087918db823aa86af31bb8"
TREE = "36ca349de7f4c7c5a2914cf1960a81d8621350fa"


def verify():
    responses = json.loads((BASE / "publication.actual-get.json").read_bytes())["responses"]
    commit, actual = (json.loads(row["api_content"]) for row in responses)
    assert commit["sha"] == COMMIT and commit["tree"]["sha"] == TREE
    assert [row["sha"] for row in commit["parents"]] == ["855733b0f88c82c68135b1879682358a818daa84", "67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed"]
    expected = json.loads((ROOT / "hepta-audit-fifth/b11-env-publication/intended-full-tree.json").read_bytes())
    assert expected["sha"] == actual["sha"] == TREE and not expected["truncated"] and not actual["truncated"]
    children = defaultdict(list)
    leaves = {}
    for row in expected["tree"]:
        parent, _, name = row["path"].rpartition("/")
        children[parent].append({**row, "name": name})
        if row["type"] != "tree":
            leaves[row["path"]] = row["sha"]
    computed = {}
    for directory in sorted(children, key=lambda value: value.count("/") + bool(value), reverse=True):
        body = b""
        for row in sorted(children[directory], key=lambda value: (value["name"] + ("/" if value["type"] == "tree" else "")).encode()):
            if row["type"] == "tree":
                assert computed[row["path"]] == row["sha"]
            body += row["mode"].lstrip("0").encode() + b" " + row["name"].encode() + b"\0" + bytes.fromhex(row["sha"])
        computed[directory] = hashlib.sha1(b"tree " + str(len(body)).encode() + b"\0" + body).hexdigest()
    assert computed[""] == TREE
    keys = ("path", "mode", "type", "sha")
    normalized_expected = sorted([{key: row[key] for key in keys} for row in children[""]], key=lambda row: row["path"])
    normalized_actual = sorted([{key: row[key] for key in keys} for row in actual["tree"]], key=lambda row: row["path"])
    assert normalized_expected == normalized_actual

    helper = ROOT / "architecture-audit/b11-windows-env-casing-20261105/candidate/.github/scripts/run_b11_read_acl_readiness.py"
    module = ast.parse(helper.read_bytes())
    constants = {}
    pins = {}
    for node in module.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        if name in {"CONTROL_SCRIPT", "CONTROL_BLOB"}:
            constants[name] = ast.literal_eval(node.value)
        if name == "PINS":
            for key, value in zip(node.value.keys, node.value.values):
                path = constants[key.id] if isinstance(key, ast.Name) else ast.literal_eval(key)
                sha = constants[value.id] if isinstance(value, ast.Name) else ast.literal_eval(value)
                pins[path] = sha
    assert len(pins) == 11
    for path, sha in pins.items():
        assert leaves[path] == sha, (path, sha, leaves[path])
    assert leaves[".github/scripts/run_b11_read_acl_readiness.py"] == "e77b32cce112f188d16063e787baca3019e3d892"
    return {"schema": "independent-b11-published-pins-verification-v1", "commit": COMMIT, "actual_tree": TREE,
            "parents": [row["sha"] for row in commit["parents"]], "expected_entries": len(expected["tree"]),
            "leaves": len(leaves), "all_directory_nodes_recomputed": len(computed),
            "complete_intended_tree_Merkle_equals_actual_GET_root_and_entries": True,
            "every_helper_pin_equals_published_HEAD_leaf": pins,
            "helper_script_blob_equals_published_HEAD_leaf": "e77b32cce112f188d16063e787baca3019e3d892",
            "method_limit": "Full intended tree Merkle proof bound to a complete actual root GET; not a recursive GitHub full-tree GET.",
            "source_pin_gate_discharged_for_this_commit_only": True, "Windows_execution_qualified": False, "B11": "OPEN"}


if __name__ == "__main__":
    print(json.dumps(verify(), ensure_ascii=False, indent=2))
