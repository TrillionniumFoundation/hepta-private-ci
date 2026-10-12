"""Synthetic object-graph tests; never assert this substitutes for live Git bytes."""

import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import project_pr_extension_source_bytes as trial


def oid(label):
    return hashlib.sha1(label.encode()).hexdigest()


def synthetic():
    """Exactly six projects, fourteen commits and thirty-two tree-bound blobs."""
    counts = [4, 1, 10, 4, 7, 6]
    commit_counts = [1, 1, 7, 1, 1, 3]
    cases, source_objects = [], {}
    binary = None
    for i, ((repo, part), number, ncommits) in enumerate(
        zip(trial.PARTITIONS.items(), counts, commit_counts, strict=True)
    ):
        root = oid(f"root{i}")
        subtree = oid(f"sub{i}")
        commit_ids = [oid(f"commit{i}-{j}") for j in range(ncommits)]
        parent_ids = (
            [commit_ids[-2]] if len(commit_ids) > 1 else [oid(f"parent{i}")]
        )
        case = dict(
            repo=repo,
            partition=part,
            pull_number=1000 + i,
            head_sha=commit_ids[-1],
            tree_sha=root,
            parents=parent_ids,
            files=[],
            commits=[
                dict(sha=c, committed_at="2026-10-12T15:00:00Z")
                for c in commit_ids
            ],
        )
        entries = []
        for k in range(number):
            data = f"// {repo} {k}\n".encode()
            if repo == "denoland/deno" and k == number - 1:
                data = b"// caf\xe9\n"
                binary = trial.git_blob(data)
            content_sha = trial.git_blob(data)
            path = f"src/code_{k}.txt"
            case["files"].append(dict(path=path, blob_sha=content_sha))
            entries.append(
                dict(path=f"code_{k}.txt", type="blob", mode="100644", sha=content_sha)
            )
            source_objects[(repo, "blobs", content_sha)] = dict(
                sha=content_sha,
                size=len(data),
                encoding="base64",
                content=base64.b64encode(data).decode(),
            )
        source_objects[(repo, "trees", root)] = dict(
            sha=root,
            truncated=False,
            tree=[dict(path="src", type="tree", mode="040000", sha=subtree)],
        )
        source_objects[(repo, "trees", subtree)] = dict(
            sha=subtree, truncated=False, tree=entries
        )
        for index, c in enumerate(commit_ids):
            original_parent = (
                commit_ids[index - 1] if index else oid(f"parent{i}")
            )
            source_objects[(repo, "commits", c)] = dict(
                sha=c,
                author=dict(date="2026-10-12T14:00:00Z"),
                committer=dict(date="2026-10-12T15:00:00Z"),
                tree=dict(sha=root),
                parents=[dict(sha=original_parent)],
            )
        cases.append(case)
    return dict(cases=cases), source_objects, binary


class ExternalImmutableBytesTests(unittest.TestCase):
    def test_exact_thirty_two_raw_blobs_and_fourteen_commits_roundtrip(self):
        manifest, objects, binary = synthetic()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "original"
            ready = trial.acquire(
                manifest,
                target,
                manifest_sha="e" * 64,
                fetch=lambda *key: deepcopy(objects[key]),
            )
            self.assertEqual(ready["verified_file_bindings"], 32)
            inventory = trial.strict_json((target / "inventory.json").read_bytes())
            self.assertEqual(inventory["non_utf8_original_blobs"], 1)
            self.assertEqual(
                (target / "blobs" / (binary + ".blob")).read_bytes(),
                b"// caf\xe9\n",
            )
            result = trial.reopen(manifest, target, manifest_sha="e" * 64)
            self.assertEqual(result["verified_original_file_bindings"], 32)
            self.assertEqual(result["verified_original_commit_objects"], 14)
            self.assertTrue(result["original_binary_reopen_completed"])
            self.assertFalse(result["production_accepted"])

    def test_latin1_bytes_cannot_be_silently_reencoded(self):
        data = b"// caf\xe9\n"
        key = trial.git_blob(data)
        object_value = dict(
            sha=key, size=len(data), encoding="base64",
            content=base64.b64encode(data).decode(),
        )
        self.assertEqual(trial.original_blob(object_value, key), data)
        bad = deepcopy(object_value)
        bad["content"] = base64.b64encode(b"// caf\xef\xbf\xbd\n").decode()
        with self.assertRaises(ValueError):
            trial.original_blob(bad, key)

    def test_reopen_rejects_mutated_and_extra_original_bytes(self):
        manifest, objects, binary = synthetic()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "original"
            trial.acquire(
                manifest, target, manifest_sha="e" * 64,
                fetch=lambda *key: objects[key],
            )
            path = target / "blobs" / (binary + ".blob")
            path.write_bytes(b"// caf\xc3\xa9\n")
            with self.assertRaises(ValueError):
                trial.reopen(manifest, target, manifest_sha="e" * 64)
            path.write_bytes(b"// caf\xe9\n")
            (target / "blobs" / "extra.blob").write_bytes(b"forged")
            with self.assertRaises(ValueError):
                trial.reopen(manifest, target, manifest_sha="e" * 64)

    def test_wrong_original_tree_fails_closed_without_ready(self):
        manifest, objects, _ = synthetic()
        case = manifest["cases"][0]
        key = (case["repo"], "trees", case["tree_sha"])
        objects[key]["tree"] = []
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "original"
            with self.assertRaises(ValueError):
                trial.acquire(
                manifest, target, manifest_sha="e" * 64,
                fetch=lambda *key: objects[key],
            )
            self.assertTrue((target / "INCOMPLETE.json").is_file())
            self.assertFalse((target / "READY.json").exists())

    def test_wrong_parent_or_future_commit_fails_closed(self):
        for mode in ("parent", "future"):
            manifest, objects, _ = synthetic()
            c = manifest["cases"][0]
            key = (c["repo"], "commits", c["head_sha"])
            if mode == "parent":
                objects[key]["parents"] = []
            else:
                objects[key]["committer"]["date"] = "2026-10-13T00:00:00Z"
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    trial.acquire(
                        manifest, Path(directory) / "original",
                        manifest_sha="e" * 64, fetch=lambda *key: objects[key],
                    )

    def test_nonancestor_or_reordered_original_git_commit_rejected(self):
        for violation in ("orphan", "reverse", "duplicate"):
            manifest, objects, _ = synthetic()
            case = next(c for c in manifest["cases"] if len(c["commits"]) > 1)
            if violation == "orphan":
                second = case["commits"][1]["sha"]
                objects[(case["repo"], "commits", second)]["parents"] = [
                    dict(sha=oid("unrelated-branch"))
                ]
            elif violation == "reverse":
                case["commits"].reverse()
            else:
                case["commits"][0] = case["commits"][1].copy()
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "original"
                with self.subTest(violation=violation), self.assertRaises(ValueError):
                    trial.acquire(
                        manifest, output, manifest_sha="e" * 64,
                        fetch=lambda *key: objects[key],
                    )
                self.assertFalse((output / "READY.json").exists())

    def test_reopen_rejects_forged_original_commit_parent_chain(self):
        manifest, objects, _ = synthetic()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "original"
            trial.acquire(
                manifest, output, manifest_sha="e" * 64,
                fetch=lambda *key: deepcopy(objects[key]),
            )
            from project_pr_extension_source_bytes import canonical, digest

            inv = output / "inventory.json"
            ready = output / "READY.json"
            inventory = trial.strict_json(inv.read_bytes())
            case = next(c for c in manifest["cases"] if len(c["commits"]) > 1)
            position = next(
                i for i, row in enumerate(inventory["commits"])
                if row["sha"] == case["commits"][1]["sha"]
            )
            inventory["commits"][position]["parents"] = [oid("orphan")]
            changed = canonical(inventory)
            inv.write_bytes(changed)
            marker = trial.strict_json(ready.read_bytes())
            marker["inventory_sha256"] = digest(changed)
            ready.write_bytes(canonical(marker))
            with self.assertRaises(ValueError):
                trial.reopen(manifest, output, manifest_sha="e" * 64)

    def test_bad_base64_or_size_or_duplicate_json_rejected(self):
        obj = dict(
            sha=trial.git_blob(b"abc"), size=3, content="YWJj", encoding="base64"
        )
        for field, value in (("content", "YWJ$"), ("size", 4), ("encoding", "utf-8")):
            altered = dict(obj)
            altered[field] = value
            with self.assertRaises(ValueError):
                trial.original_blob(altered, obj["sha"])
        with self.assertRaises(ValueError):
            trial.strict_json('{"sha":1,"sha":2}')
        with self.assertRaises(ValueError):
            trial.strict_json('{"time":NaN}')

    def test_bounded_git_endpoints_and_no_overwrite(self):
        with self.assertRaises(ValueError):
            trial.fetch_git("unknown/other", "blobs", "a" * 40)
        with self.assertRaises(ValueError):
            trial.fetch_git("python/cpython", "issues", "a" * 40)
        with self.assertRaises(ValueError):
            trial.fetch_git("python/cpython", "blobs", "0" * 39)
        manifest, objects, _ = synthetic()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "original"
            trial.acquire(
                manifest, path, manifest_sha="e" * 64, fetch=lambda *key: objects[key]
            )
            with self.assertRaises(ValueError):
                trial.acquire(
                manifest, path, manifest_sha="e" * 64, fetch=lambda *key: objects[key]
            )

    def test_wrong_manifest_sha_or_original_prior_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / "extension.json"
            previous = root / "prior.json"
            current.write_text('{"not":"original"}')
            previous.write_text('{}')
            with self.assertRaises(ValueError):
                trial.load_manifest(current, previous)


if __name__ == "__main__":
    unittest.main()
