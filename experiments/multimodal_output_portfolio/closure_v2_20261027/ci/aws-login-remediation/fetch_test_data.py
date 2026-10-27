"""Restore every official AWS config test fixture at the crate's source commit."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path, PurePosixPath
import urllib.request


COMMIT = "f031610a8cbb4ac2dac3229bfaeaa88182787ab4"
REPOSITORY = "awslabs/aws-sdk-rust"


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Hepta-source-compatibility-review"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def run(package, evidence):
    evidence.mkdir(parents=True, exist_ok=False)
    url = f"https://api.github.com/repos/{REPOSITORY}/contents/sdk/aws-config?ref={COMMIT}"
    directory_bytes = fetch(url)
    (evidence / "PACKAGE_DIRECTORY.json").write_bytes(directory_bytes)
    directory = json.loads(directory_bytes)
    selected = [entry for entry in directory if entry["name"] == "test-data" and entry["type"] == "dir"]
    if len(selected) != 1:
        raise ValueError("Official test-data directory is not uniquely identified")
    tree_bytes = fetch(f"https://api.github.com/repos/{REPOSITORY}/git/trees/{selected[0]['sha']}?recursive=1")
    (evidence / "TEST_DATA_TREE.json").write_bytes(tree_bytes)
    tree = json.loads(tree_bytes)
    files = [entry for entry in tree["tree"] if entry["type"] == "blob"]
    if tree.get("truncated") or len(files) > 500 or sum(entry["size"] for entry in files) > 10_000_000:
        raise ValueError("The complete fixture tree exceeds the predeclared bounded download")

    def restore(entry):
        relative = PurePosixPath(entry["path"])
        if relative.is_absolute() or ".." in relative.parts or entry["mode"] not in {"100644", "100755"}:
            raise ValueError("Non-regular or unsafe fixture entry")
        url = f"https://raw.githubusercontent.com/{REPOSITORY}/{COMMIT}/sdk/aws-config/test-data/{relative}"
        data = fetch(url)
        git_hash = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        if len(data) != entry["size"] or git_hash != entry["sha"]:
            raise ValueError(f"Official fixture git-object identity mismatch: {relative}")
        path = package / "test-data" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != data:
                raise ValueError(f"Existing fixture differs: {relative}")
        else:
            with path.open("xb") as stream:
                stream.write(data)
        path.chmod(0o755 if entry["mode"] == "100755" else 0o644)
        return {"path": str(relative), "url": url, "git_sha1": git_hash,
            "bytes": len(data), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    with ThreadPoolExecutor(max_workers=4) as executor:
        receipts = list(executor.map(restore, files))
    result = {"source_commit": COMMIT, "directory_tree_sha1": selected[0]["sha"],
        "all_official_fixture_files_restored": len(receipts),
        "bytes": sum(entry["bytes"] for entry in receipts), "files": receipts}
    (evidence / "RESTORATION.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "files"}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    run(args.package, args.evidence)
