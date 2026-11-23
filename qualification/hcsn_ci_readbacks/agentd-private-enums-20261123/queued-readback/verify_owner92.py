"""Read original Rust test lines, process UID markers, exact rosters and binary fingerprints."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from zipfile import ZipFile

SHA = lambda data: hashlib.sha256(data).hexdigest()
OLD_ARCHIVE = "fc7fbc887f77883d185dd773c866560f02d3b118f46be196d59fe956dce3c115"
ROSTER = "92a1f91f2fda5cef559fee7957821f65ed8c0f4d14b4df057032204cda158837"
ORIGINAL_CASE = "authority_host_service::resident::authority::tests::resident_root_queued_admit_cancellation_sends_no_frame_and_consumes_channel"
SOURCES = {
    "original": {
        "base": ("e3277e9677688be5c4c235a7a127f0b51e373399", "e22096190fb955ee70491be789b22e245de06add07b46128503213e828c9aa04"),
        "candidate": ("43e5da1bb81369e4e999adfa8558f5ccb5460eb6", "1ad9942a18dcd2ccb69d40b8e38edd262cf4cfa5c137c3674e7316d4ad550278"),
    },
    "sync": {
        "base": ("3002afb8e319abd7909e57ac816b0fedc8f0233c", "9c6013bb5c1f7cff5a85464afdf694e0bbce2371b71c2095ea2eda2873605cd8"),
        "candidate": ("e1969bcf8dbb9e9e42cd718401a9df6d13f79d98", "abb79f99f59754cde2cec06e36b4c026f8ff042abcdb674abe0aad79e010e0c6"),
    },
}
VERDICT = re.compile(r"^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; 0 ignored; 0 measured; (\d+) filtered out; finished in ([0-9.]+)s$", re.M)


def verify(path, digest, stage):
    assert SHA(path.read_bytes()) == digest
    report = {"archive_sha256": digest, "stage": stage, "arms": {}}
    with ZipFile(path) as z:
        assert z.testzip() is None and len(z.namelist()) == len(set(z.namelist()))
        assert SHA(z.read("cases.json")) == ROSTER
        cases = json.loads(z.read("cases.json"))
        suites = {mode: {name for group in files.values() for name in group} for mode, files in cases.items()}
        assert {k: len(v) for k, v in suites.items()} == {"ordinary": 62, "uid0": 30}
        assert suites["ordinary"].isdisjoint(suites["uid0"]) and ORIGINAL_CASE in suites["uid0"]
        assert z.read("fixtures-base.txt") == z.read("fixtures-candidate.txt")
        fixture_names = [line.split("\t")[1].rsplit("/", 1)[1] for line in z.read("fixtures-base.txt").decode().splitlines()]
        assert set(fixture_names) == {f for files in cases.values() for f in files}
        assert len(fixture_names) == len(set(fixture_names))
        report["listed_fixture_blobs_sha256"] = SHA(z.read("fixtures-base.txt"))
        receipt = json.loads(z.read("native.json"))
        for arm, (commit, elf) in SOURCES[stage].items():
            assert z.read(f"identity-{arm}.txt").decode().strip() == commit
            assert z.read(f"binary-{arm}.txt").decode().split()[0] == elf
            assert json.loads(z.read(f"native-{arm}.json")) == receipt[arm]
            report["arms"][arm] = {"source": commit, "elf_sha256": elf, "tests": {}}
            for mode, names in suites.items():
                data = z.read(f"{arm}-{mode}.log")
                raw = data.decode()
                saved = receipt[arm][mode]
                assert raw.splitlines().count("libtest actual real/effective UID: 0 0") == (1 if mode == "uid0" else 0)
                rows = re.findall(r"^test ([^ ]+) \.\.\. (ok|FAILED|ignored)\s*$", raw, re.M)
                assert len(rows) == len(names) and {n for n, _ in rows} == names
                assert ("running " + str(len(names)) + " tests") in raw.splitlines()
                assert dict(rows) == saved["tests"] and SHA(data) == saved["log_sha256"] and saved["ELF"] == elf
                ms = VERDICT.findall(raw)
                assert len(ms) == 1
                state, passed, failed, filtered, seconds = ms[0]
                fail_names = [n for n, verdict in rows if verdict == "FAILED"]
                assert len(rows) == int(passed) + int(failed) and int(failed) == len(fail_names)
                assert int(filtered) > 0 and all(v != "ignored" for _, v in rows)
                assert (state == "ok") == (saved["code"] == 0) == (not fail_names)
                assert saved["libtest_summary"] == [VERDICT.search(raw).group(0)]
                if stage == "original":
                    expected = [ORIGINAL_CASE] if (arm, mode) == ("base", "uid0") else []
                    assert fail_names == expected
                    if expected:
                        assert "authority_host_learning_resident_transport_tests.rs:112:9" in raw
                        assert "assertion failed: matches!(client.readback().await, Err(Error::Unavailable))" in raw
                report["arms"][arm]["tests"][mode] = {"passed": int(passed), "failed": fail_names, "libtest_s": float(seconds)}
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("sync", nargs="?", type=Path)
    parser.add_argument("--sync-sha256")
    args = parser.parse_args()
    reports = {"original": verify(args.original, OLD_ARCHIVE, "original")}
    if args.sync is not None:
        assert args.sync_sha256, "provide the published Actions artifact SHA-256 for the new archive"
        reports["sync"] = verify(args.sync, args.sync_sha256, "sync")
        assert reports["original"]["listed_fixture_blobs_sha256"] == reports["sync"]["listed_fixture_blobs_sha256"]
    print(json.dumps(reports, indent=2))
