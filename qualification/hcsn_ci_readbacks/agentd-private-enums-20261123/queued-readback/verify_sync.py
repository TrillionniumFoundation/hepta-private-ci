"""Validate the immutable cancelled-readback experiment using only the Python standard library."""
import argparse
import hashlib
import json
import re
import statistics
from pathlib import Path
from zipfile import ZipFile

CASE = "authority_host_service::resident::authority::tests::resident_root_queued_admit_cancellation_sends_no_frame_and_consumes_channel"
COMMITS = {
    "base": ["e3277e9677688be5c4c235a7a127f0b51e373399", "3002afb8e319abd7909e57ac816b0fedc8f0233c"],
    "combined": ["43e5da1bb81369e4e999adfa8558f5ccb5460eb6", "e1969bcf8dbb9e9e42cd718401a9df6d13f79d98"],
}
SRC = "codex-rs/hepta-agentd/src/authority_host_learning_resident_transport"
TRANSPORT = "40b744877e6e3a0e02dea0fdc9fffb8859eefdf7"
TEST_OLD = "12f37a10e306a9ede9f67cedb1a4a02306b1c0b0"
TEST_NEW = "a5e77fc7ee60034461139cef18bfca52c0e927ab"
INSERTED = [
    "        // EOF can precede the cancelled blocking exchange returning its lane permit.",
    "        // Wait for that permit before testing the consumed channel.",
    "        let permit = tokio::time::timeout(Duration::from_secs(2), client.lane.acquire()).await??;",
    "        drop(permit);",
]
VERDICT = re.compile(r"^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; 0 ignored; 0 measured; (\d+) filtered out; finished in ([0-9.]+)s$", re.M)


def verify(path):
    report = {"run": 45135852345, "job": 137561814315, "archive_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "arms": {}}
    with ZipFile(path) as z:
        assert z.testzip() is None and len(z.namelist()) == len(set(z.namelist()))
        def string(name):
            return z.read(name).decode()
        assert string("base-source.diff") == string("combined-source.diff")
        for arm, commits in COMMITS.items():
            assert string(f"{arm}-commits.txt").splitlines() == commits
            for when, test_sha in (("before", TEST_OLD), ("after", TEST_NEW)):
                names = string(f"{arm}-{when}.tsv").splitlines()
                assert names == [f"100644 blob {TRANSPORT}\t{SRC}.rs", f"100644 blob {test_sha}\t{SRC}_tests.rs"]
            diff = string(f"{arm}-source.diff").splitlines()
            assert [x[1:] for x in diff if x.startswith("+") and not x.startswith("+++")] == INSERTED
            assert not any(x.startswith("-") and not x.startswith("---") for x in diff)
            assert any("assert!(matches!(client.readback().await, Err(Error::Unavailable)))" in x for x in diff)
            binary = string(f"{arm}-elf.txt").split()[0]
            assert re.fullmatch("[a-f0-9]{64}", binary)
            assert "//codex-rs/hepta-agentd:hepta-agentd-unit-tests-bin" in string(f"build-{arm}.log")
            report["arms"][arm] = {"sources": commits, "elf_sha256": binary}
        assert report["arms"]["base"]["elf_sha256"] != report["arms"]["combined"]["elf_sha256"]
        runs = json.loads(string("runs.json"))
        expected = [(i, a) for i in range(1, 11) for a in (("base", "combined") if i % 2 else ("combined", "base"))]
        assert [(r["pair"], r["arm"]) for r in runs] == expected
        logs = {f"{i:02d}-{a}.log" for i, a in expected}
        assert {n for n in z.namelist() if re.fullmatch(r"\d\d-(base|combined)\.log", n)} == logs
        for r in runs:
            data = z.read(f"{r['pair']:02d}-{r['arm']}.log")
            raw = data.decode()
            assert hashlib.sha256(data).hexdigest() == r["sha256"]
            assert raw.splitlines().count("real_uid=0 effective_uid=0") == 1
            matches = VERDICT.findall(raw)
            assert len(matches) == 1
            state, passed, failed, filtered, elapsed = matches[0]
            assert int(passed) + int(failed) == 1 and int(filtered) > 0
            ok = (state == "ok")
            assert (int(passed) == 1) == (r["code"] == 0) == ok
            assert r["result"] == state and float(elapsed) == r["libtest_s"]
            assert raw.splitlines().count("test " + CASE + " ... " + ("ok" if ok else "FAILED")) == 1
            assert r["wall_s"] > 0
        original = json.loads(string("summary.json"))
        for arm in COMMITS:
            subset = [r for r in runs if r["arm"] == arm]
            times = [r["wall_s"] for r in subset]
            counts = {
                "pass": sum(r["code"] == 0 for r in subset),
                "fail": sum(r["code"] != 0 for r in subset),
                "wall_s_total": sum(times), "wall_s_median": statistics.median(times),
                "wall_s_min": min(times), "wall_s_max": max(times),
                "libtest_s_total": sum(r["libtest_s"] for r in subset),
            }
            assert counts == original[arm]
            report["arms"][arm].update(counts)
        assert original["all_wall_s"] >= sum(r["wall_s"] for r in runs)
        report["whole_loop_wall_s"] = original["all_wall_s"]
        report["actual_uid"] = [0, 0]
        report["transport_git_blob"] = TRANSPORT
        report["test_git_blobs"] = [TEST_OLD, TEST_NEW]
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip", type=Path)
    parser.add_argument("--sha256", required=True, help="published SHA-256 of the original Actions archive")
    args = parser.parse_args()
    report = verify(args.zip)
    assert report["archive_sha256"] == args.sha256
    print(json.dumps(report, indent=2))
