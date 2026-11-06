#!/usr/bin/env python3
"""Add literal bytes equality to every archive/restoration identity comparison.

The original frozen verifier and first restoration receipt remain unchanged.
This wrapper loads complete expected bytes from the lossless archive, then runs
the existing restoration with a stronger comparison hook. No network or product
test is run, and the original verifier still writes only its disposable copy.
"""
import argparse
import base64
from contextlib import redirect_stdout
import gzip
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile


def main(package):
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("original_frozen_restorer", package / "restore_and_verify.py")
    restored = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(restored)
    transport = restored.load(package / "archive-transport.json")
    manifest = restored.load(package / "member-manifest.json")
    replay = restored.load(package / "replay-spec.json")
    expected = {}
    def remember(body):
        key = restored.identity(body)["git_blob"]
        if key in expected:
            assert expected[key] == body
        expected[key] = body
        return body
    parts = [remember((package / part["path"]).read_bytes()) for part in transport["parts"]]
    archive = remember(base64.b64decode(b"".join(parts), validate=True))
    remember((package / replay["expected_stdout_file"]).read_bytes())
    original_by_path = {}
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(archive)), mode="r:") as tar:
        entries = tar.getmembers()
        assert [entry.name for entry in entries] == [row["path"] for row in manifest["members"]]
        for entry in entries:
            assert entry.isfile()
            original_by_path[entry.name] = remember(tar.extractfile(entry).read())
    original_same = restored.same
    comparison_calls = []
    def compare_full_bytes(body, declaration):
        original_same(body, declaration)
        assert body == expected[declaration["git_blob"]]
        comparison_calls.append(declaration["git_blob"])
    restored.same = compare_full_bytes
    output = io.StringIO()
    with redirect_stdout(output):
        restored.main(package)
    literal_stdout = output.getvalue().encode()
    assert literal_stdout == (package / "offline-roundtrip.stdout.json").read_bytes()
    checks = []
    for path in replay["verifier_written_frozen_files"]:
        body = original_by_path["root/" + path]
        key = restored.identity(body)["git_blob"]
        assert comparison_calls.count(key) >= 3
        checks.append({"path": path, **restored.identity(body),
                       "comparison": "actual_regenerated_bytes == complete_original_archive_member_bytes",
                       "direct_byte_comparison": True})
    print(json.dumps({"schema": "hepta-publication-direct-byte-equality-addendum-v1",
                      "kind": replay["kind"], "authority": replay["authority"],
                      "all_original_members_restored_and_compared_as_complete_bytes": len(original_by_path),
                      "comparison_calls_with_literal_bytes_equality": len(comparison_calls),
                      "regenerated_outputs": checks,
                      "original_restoration_stdout_equals_frozen_receipt_complete_bytes": True,
                      "original_restoration_stdout": restored.identity(literal_stdout),
                      "frozen_verifier_and_archive_unmodified": True,
                      "native_or_product_test_or_compile_or_fmt": False,
                      "network_or_external_ref_action": False,
                      "scope": "Supplement first hash-verified restoration with direct bytes equality; publication custody only"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("package", nargs="?", type=Path, default=Path(__file__).resolve().parent)
    main(parser.parse_args().package.resolve())
