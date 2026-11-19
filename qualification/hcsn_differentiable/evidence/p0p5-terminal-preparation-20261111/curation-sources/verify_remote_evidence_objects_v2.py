"""Read a committed evidence delta from a fresh remote Git object store."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("local-repo", "output", "local-base", "local-head", "remote-head", "expected-tree"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--expected-files", type=int, required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(exist_ok=False)
    gitdir = output / "fresh-objects.git"
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    def local(*words):
        return subprocess.check_output(["git", *words], cwd=args.local_repo, timeout=120)

    assert local("rev-parse", args.local_head + "^{tree}").decode().strip() == args.expected_tree
    changes = local("diff", "--name-status", args.local_base, args.local_head).decode().splitlines()
    expected = []
    for change in changes:
        status, name = change.split("\t")
        assert status in ("A", "M"), "Only the declared append/update evidence delta is supported"
        entry = local("ls-tree", args.local_head, "--", name).decode().split("\t", 1)[0].split()
        assert entry[0] == "100644" and entry[1] == "blob"
        expected.append((name, entry[2]))
    assert len(expected) == args.expected_files and expected
    with (output / "git-transfer.log").open("xb") as log:
        subprocess.run([
            "git", "clone", "--bare", "--filter=blob:none", "--depth", "1", "--single-branch",
            "--branch", "codex/hcsn-c2-launch-api-20261110-c385",
            "https://github.com/TrillionniumFoundation/hepta-private-ci.git", str(gitdir),
        ], check=True, env=env, stdout=log, stderr=log, timeout=120)

        def remote(*words):
            return subprocess.check_output(["git", "--git-dir", str(gitdir), *words], env=env, stderr=log, timeout=120)

        head, tree = remote("rev-parse", "HEAD", "HEAD^{tree}").decode().splitlines()
        assert (head, tree) == (args.remote_head, args.expected_tree), "Remote head changed; no retry"
        assert not (gitdir / "objects/info/alternates").exists()
        for name, oid in expected:
            assert remote("rev-parse", head + ":" + name).decode().strip() == oid
        bulk = subprocess.run(
            ["git", "--git-dir", str(gitdir), "fetch", "--no-tags", "--no-write-fetch-head",
             "origin", *sorted({oid for _, oid in expected})],
            env=env, stdout=log, stderr=log, timeout=120, check=False)
        results = []
        for name, oid in expected:
            original = local("cat-file", "blob", oid)
            raw = remote("cat-file", "blob", oid)
            assert raw == original
            assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == oid
            results.append({"path": name, "git_blob": oid, "bytes": len(raw),
                            "sha256": hashlib.sha256(raw).hexdigest()})
    result = {
        "schema": "hcsn-fresh-remote-git-object-readback-v2", "passed": True,
        "local_base": args.local_base, "local_commit": args.local_head,
        "remote_commit": head, "tree": tree, "fresh_git_object_directory": True,
        "bulk_fetch_returncode": bulk.returncode, "all_changed_files": results,
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope": "Full committed local/remote byte comparison through a new clone with no alternates or local object seeding. Bulk transfer is an optimization; every file is still read in full. No CI or scientific admission.",
    }
    (output / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"passed": True, "files": len(results), "bulk_fetch_returncode": bulk.returncode,
                      "remote_commit": head, "tree": tree}))


if __name__ == "__main__":
    main()
