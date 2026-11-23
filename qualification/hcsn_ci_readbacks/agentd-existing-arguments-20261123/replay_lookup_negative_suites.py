"""Replay the original mutation suites on a separate proposed signature representation.

The maintained product checks are never written. In diagnostic mode the
existing protected-file predicate consumes a reversible projection solely at
the changed records file. All other predicates run directly on the candidate.
"""
import argparse
import errno
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter

from verify_argument_boundary import HERE, PREFIX, PATCHES, RECORDS, SOURCE, git_blob


def clone_file(source, target):
    try:
        return os.link(source, target)
    except OSError as exc:
        if exc.errno not in (errno.EXDEV, errno.EPERM, errno.EACCES, errno.EMLINK):
            raise
        return shutil.copy2(source, target)


def replace_file(path, data):
    path.unlink(missing_ok=True)
    path.write_bytes(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    parser.add_argument("mode", choices=["base", "raw", "proposal"])
    parser.add_argument("--original-files", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--temp-dir", type=Path)
    args = parser.parse_args()
    lookup = HERE/"lookup.patch"
    assert hashlib.sha256(lookup.read_bytes()).hexdigest() == PATCHES["lookup"][0]
    counts = Counter()
    with tempfile.TemporaryDirectory(dir=args.temp_dir) as name:
        root = Path(name)/"product"
        root.mkdir()
        source = args.checkout.resolve()
        for dirname in ("codex-rs", "scripts", "qa"):
            if dirname == "codex-rs":
                (root/dirname/"hepta-agentd").mkdir(parents=True)
                shutil.copytree(source/dirname/"hepta-agentd"/"src", root/dirname/"hepta-agentd"/"src", copy_function=clone_file)
            else:
                shutil.copytree(source/dirname, root/dirname, copy_function=clone_file)
        clone_file(source/"CALLERS.toml", root/"CALLERS.toml")
        for path, oid in SOURCE.items():
            if args.original_files:
                replace_file(root/PREFIX/path, (args.original_files/path).read_bytes())
            assert git_blob((root/PREFIX/path).read_bytes()) == oid
        if args.mode != "base":
            subprocess.run(["git","apply","--whitespace=nowarn",str(lookup)], cwd=root, check=True)
        suite = unittest.TestSuite()
        sys.path.insert(0, str(root/"qa/b4-no-bypass"))
        for key in ("test_original_evaluation_provider_source_closure","test_original_on_policy_evaluation_source_closure"):
            tests = importlib.import_module(key)
            released = tests.PROOF._verify_protected_files
            def check(root_to_check, manifest, *, original=released, proof=tests.PROOF):
                rows = manifest["protected_file"]
                assert len(rows) == 1
                path = rows[0]["path"]
                if args.mode == "proposal" and path == str(PREFIX/RECORDS):
                    with tempfile.TemporaryDirectory() as projection:
                        new = Path(projection)
                        (new/PREFIX).mkdir(parents=True)
                        (new/path).write_bytes((root_to_check/path).read_bytes())
                        result = subprocess.run(["git","apply","--reverse","--include="+path,"--whitespace=nowarn",str(lookup)],
                                                cwd=new, capture_output=True)
                        if result.returncode:
                            counts["projection_reject"] += 1
                            raise proof.VerificationFailure("changed original argument representation")
                        try:
                            value = original(new, manifest)
                        except proof.VerificationFailure:
                            counts["original_predicate_reject_after_projection"] += 1
                            raise
                        counts["original_predicate_pass_after_projection"] += 1
                        return value
                try:
                    value = original(root_to_check, manifest)
                except proof.VerificationFailure:
                    counts["direct_original_reject"] += 1
                    raise
                counts["direct_original_pass"] += 1
                return value
            tests.PROOF._verify_protected_files = check
            suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(tests))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        summary = {"mode":args.mode, "tests":result.testsRun, "failures":[case.id() for case,_ in result.failures],
                   "errors":[case.id() for case,_ in result.errors], "counts":counts}
    text=json.dumps(summary, indent=2)+"\n"
    print(text,end="")
    if args.output:
        args.output.write_text(text)
    assert result.testsRun == 16
    if args.mode == "raw":
        assert not result.failures and len(result.errors) == 3
    else:
        assert result.wasSuccessful()


if __name__ == "__main__":
    main()
