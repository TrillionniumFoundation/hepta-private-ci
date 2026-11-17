"""Independently calculate append-only publication trees using native Git."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def git(repository, *args, content=None):
    result = subprocess.run(["git", "--git-dir=" + str(repository), *args],
                            input=content, capture_output=True, check=True)
    return result.stdout.decode().strip()


def write_tree(repository, entries):
    rows = []
    for name, entry in entries.items():
        if not name or "/" in name or "\0" in name:
            raise ValueError("one immediate Git entry required")
        rows.append((entry["mode"] + " " + entry["type"] + " " + entry["sha"]
                     + "\t" + name).encode() + b"\0")
    return git(repository, "mktree", "--missing", "-z", content=b"".join(rows))


def calculate(base_trees, stages, repository):
    subprocess.run(["git", "init", "--bare", str(repository)], capture_output=True, check=True)
    trees = {}
    for path, tree in base_trees.items():
        if tree.get("truncated") or not isinstance(tree.get("tree"), list):
            raise ValueError("complete immediate tree required")
        entries = {row["path"]: {key: row[key] for key in ("mode", "type", "sha")}
                   for row in tree["tree"]}
        if write_tree(repository, entries) != tree["sha"]:
            raise ValueError("native base tree differs: " + path)
        trees[path] = entries
    reports = []
    for stage in stages:
        changed = set()
        for entry in stage["files"]:
            path, source = entry["repository_path"], Path(entry["local_path"])
            components = path.split("/")
            if path.startswith("/") or any(p in ("", ".", "..") for p in components):
                raise ValueError("bounded repository path required")
            blob = source.read_bytes()
            if hashlib.sha256(blob).hexdigest() != entry["sha256"]:
                raise ValueError("publication source changed: " + path)
            identity = git(repository, "hash-object", "-w", "--stdin", content=blob)
            if identity != entry["git_blob_sha"]:
                raise ValueError("native blob identity differs: " + path)
            for index in range(1, len(components)):
                parent, name = "/".join(components[:index - 1]), components[index - 1]
                directory = "/".join(components[:index])
                if directory not in trees:
                    if name in trees[parent]:
                        raise ValueError("unread existing subtree: " + directory)
                    trees[directory] = {}
                changed.add(directory)
            parent = "/".join(components[:-1])
            if components[-1] in trees[parent]:
                raise ValueError("append-only publication path exists: " + path)
            trees[parent][components[-1]] = {"mode": "100644", "type": "blob", "sha": identity}
        for path in sorted(changed, key=lambda p: (p.count("/"), p), reverse=True):
            identity = write_tree(repository, trees[path])
            parent, _, name = path.rpartition("/")
            trees[parent][name] = {"mode": "040000", "type": "tree", "sha": identity}
        reports.append({"stage": stage["stage"], "tree_sha": write_tree(repository, trees[""]),
                        "files": len(stage["files"]), "changed_lines": stage["changed_lines"]})
    return {"schema": "hepta.round03.native-tree-calculation.v1",
            "baseline_tree": base_trees[""]["sha"], "baseline_shallow_trees_verified": len(base_trees),
            "append_only": True, "stages": reports,
            "scope": "Native Git blobs/trees; unchanged subtrees are opaque identities, "
                     "not a full repository checkout or native push."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base-trees", "plan", "git-directory", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = calculate(json.loads(args.base_trees.read_text()),
                       json.loads(args.plan.read_text())["stages"], args.git_directory)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
