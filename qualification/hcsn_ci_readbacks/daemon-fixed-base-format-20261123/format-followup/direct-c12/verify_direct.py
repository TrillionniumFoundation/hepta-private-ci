"""Verify the direct current-parent run from its original GitHub artifact ZIP."""
import gzip
import hashlib
import json
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
BASE = "b8e8c6e82abc1479c573f61a5e17d28d581e6cad"
PARENT = "c12ee03f3185d5a13949faca54f066dfd634e509"
CANDIDATE = "fe38676fae170002fcdce90b36dc949fac3ff671"
ARTIFACT_SHA = "fd2e0e3d8ffd070534f19041cce1f045b0d357735d6389439d2cb90612b96970"


def main():
    disk = HERE / "direct-fixed-base.zip"
    assert hashlib.sha256(disk.read_bytes()).hexdigest() == ARTIFACT_SHA
    listed = json.loads((HERE / "product-diff.json").read_bytes())
    assert len(listed) == 18 and sum(row[2] == "added" for row in listed) == 2
    with zipfile.ZipFile(disk) as archive:
        diff = archive.read("direct-diff.raw").decode().splitlines()
        assert len(diff) == len(listed)
        for raw, (expected_path, blob, action, *_lines) in zip(diff, listed):
            meta, path = raw.split("\t")
            before_mode, after_mode, before, after, status = meta[1:].split()
            assert before_mode == ("000000" if action == "added" else "100644")
            assert after_mode == "100644" and status == ("A" if action == "added" else "M")
            assert expected_path == path and after == blob
            assert not path.startswith(".github/") and before != after
        metadata = json.loads(archive.read("scope.json"))
        assert (metadata["candidate"], metadata["old"], metadata["base"]) == (CANDIDATE, PARENT, BASE)
        assert (metadata["original_rust_list_identical"], metadata["other_commands_unchanged"]) == (4219, 4175)
        assert (metadata["verified_immutable"], metadata["maintained"], metadata["checked_commands"]) == (37, 7, 88)
        original_list = json.loads(gzip.decompress(archive.read("original-rust.json.gz")))
        runs = json.loads(archive.read("actual-44.json"))
        assert len(original_list) == len(set(original_list)) == 4219
        assert len({(r["path"], r["check_mode"]) for r in runs if r["exit"] == 0}) == 88
        assert b"Ran 41 tests" in archive.read("formatter-tests.log")
        assert b"Ran 3 tests" in archive.read("starlark-tests.log")
        for mode in ("check", "original"):
            assert archive.read(f"full-{mode}.exit") == b"0\n"
            assert archive.read(f"after-{mode}.status") == b""
        times = list(map(float, archive.read("actual-entry-clock.txt").decode().splitlines()))
        assert len(times) == 4 and times == sorted(times)
    guards = json.loads((HERE / "postimage-guard-pair.json").read_bytes())["results"]
    assert guards[PARENT] == guards[CANDIDATE] and guards[PARENT]["original_owner_cases"] == 2
    results = guards[PARENT]["path_controls"]
    assert sum(v == "accepted" for v in results.values()) == 1 and results["all_twelve_at_once"] == "rejected"
    assert results["codex-rs/hepta-agentd/src/prompt_product_v3.rs"] == "accepted"
    print(json.dumps({"files": len(listed), "existing_mode_changes": 0, "candidate": CANDIDATE, "parent": PARENT, "original_base": BASE, "format_check": 0, "format_check_seconds": round(times[1] - times[0], 3), "format_write": 0, "format_write_seconds": round(times[3] - times[2], 3), "dirty_paths_after_each": [0, 0], "source_commands_identical": 4175, "archive_and_builder_calls": 88, "tests": 44, "additional_postimage_permissions": 0}, indent=2))


if __name__ == "__main__":
    main()
