#!/usr/bin/env python3
"""Restore both frozen versions and independent review; replay only offline fixtures."""
from pathlib import Path, PurePosixPath
import argparse
import base64
import gzip
import hashlib
import io
import json
import re
import subprocess
import tarfile


def identity(data):
    return {"bytes": len(data), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
            "sha256": hashlib.sha256(data).hexdigest()}


def normalize_ast_pair(raw):
    """Only reorder the first two exact, successful Python AST check blocks."""
    block = (rb'    \{\n      "name": "Python AST parses '
             rb'(?:propose_pin_utils_backport|pin_utils_proposal_evidence)\.py",\n'
             rb'      "passed": true\n    \},\n')
    matches = list(re.finditer(rb'(?m)^  "checks": \[\n(' + block + rb')(' + block + rb')', raw))
    assert len(matches) == 1
    found = matches[0]
    pair = [found.group(1), found.group(2)]
    names = [re.search(rb'"name": "([^"]+)"', part).group(1) for part in pair]
    assert set(names) == {b"Python AST parses propose_pin_utils_backport.py",
                          b"Python AST parses pin_utils_proposal_evidence.py"}
    ordered = b"".join(part for _, part in sorted(zip(names, pair)))
    return raw[:found.start()] + b'  "checks": [\n' + ordered + raw[found.end():]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--extract", type=Path, required=True)
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    base = subprocess.run(["python3", str(args.root / "restore_packet.py"), "--root", str(args.root),
                           "--extract", str(args.extract)], capture_output=True)
    assert base.returncode == 0 and not base.stderr
    (args.extract / "archive-verification.stdout.original.json").write_bytes(base.stdout)
    core = json.loads(base.stdout)
    supplement = json.loads((args.root / "independent-archive.json").read_bytes())
    encoded = (args.root / "independent-review.tar.gz.b64").read_bytes()
    assert identity(encoded) == supplement["base64"]
    archive = base64.b64decode(encoded, validate=True)
    assert identity(archive) == supplement["archive"]
    extracted = {}
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(archive)), mode="r:") as tar:
        for member in tar:
            name = PurePosixPath(member.name)
            assert member.isfile() and not name.is_absolute() and ".." not in name.parts
            assert member.name not in extracted
            extracted[member.name] = tar.extractfile(member).read()
    assert set(extracted) == set(supplement["files"])
    for name, raw in extracted.items():
        assert identity(raw) == supplement["files"][name]
        target = args.extract / "independent-review" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        assert not target.exists()
        target.write_bytes(raw)
    assert identity(extracted["REVIEW.json"])["git_blob"] == "f22966fd399dccc6719d1546ea16dcae5f0384d4"
    replay = None
    if args.replay:
        source = args.extract / "root/v2/final-review"
        output = args.extract / "portable-verification-output"
        run = subprocess.run(["python3", str(source / "verify_candidate.py"), "--root", str(source),
                              "--output", str(output)], capture_output=True)
        (args.extract / "portable-replay.stdout.original.txt").write_bytes(run.stdout)
        (args.extract / "portable-replay.stderr.original.txt").write_bytes(run.stderr)
        assert run.returncode == 0 and not run.stderr
        expected = (source / "verification-02.stdout.original.txt").read_bytes()
        assert normalize_ast_pair(run.stdout) == normalize_ast_pair(expected)
        derived = {}
        for name in ["intended-full-tree.json", "static-verification.json", "pipeline-controls.json", "workspace-manifest.static-preview.toml"]:
            actual = (output / name).read_bytes()
            frozen = (source / "verification-v2" / name).read_bytes()
            exact = actual == frozen
            if name == "static-verification.json":
                assert normalize_ast_pair(actual) == normalize_ast_pair(frozen)
            else:
                assert exact
            derived[name] = {"raw_bytes_equal": exact, "actual": identity(actual), "frozen": identity(frozen)}
        replay = {"exit_code": run.returncode, "actual_stdout": identity(run.stdout), "frozen_stdout": identity(expected),
                  "stderr": identity(run.stderr), "raw_stdout_bytes_equal": run.stdout == expected,
                  "equal_after_only_two_initial_AST_rows_ordering": True, "derived_outputs": derived,
                  "scope": "Offline source/fake replay only. No Cargo, Bazel or product-native execution."}
    result = {"schema": "pin-utils-complete-portable-recovery-v2", "core": core,
              "independent_original_members": len(extracted), "independent_review_actual_blob": "f22966fd399dccc6719d1546ea16dcae5f0384d4",
              "offline_replay": replay, "old_source_and_verifier_bytes_rewritten": False,
              "normalization_scope": "Only two exact successful AST check blocks may swap order; every other byte remains identical.",
              "real_product_locks_generated": False, "product_native_qualification": False}
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
