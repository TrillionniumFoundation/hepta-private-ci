"""Independently recover the exact native test roster and result from every archived invocation."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from xml.etree import ElementTree
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
CASE = "ndu_publication::tests::original_pending_begin_inspector_repeated_cold_reopen_retains_quarantine"
TARGET = "//codex-rs/hepta-control-plane:hepta-control-plane-unit-tests"
FIXED = "ae2ad4941e0734c311d74904c9bbacc6c5136b6c"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify(artifact):
    roster_bytes = (HERE / "roster185.txt").read_bytes()
    assert sha(roster_bytes) == "8dc2d94683f5b9be869913fa90171d86f1eb4942dddf7d16c6d1fa8f53618772"
    roster = set(roster_bytes.decode().splitlines())
    assert len(roster) == 185 and CASE in roster
    rows = []
    with ZipFile(artifact) as archive:
        summary = json.loads(archive.read("summary.json"))
        assert summary["source"] == FIXED and summary["roster_sha256"] == sha(roster_bytes)
        assert summary["platform"] == "macos-15 arm64"
        assert summary["original_job"] == 137481302908
        modes = [r["mode"] for r in summary["runs"]]
        assert modes[:6] == ["parallel", "serial", "serial", "parallel", "parallel", "serial"]
        assert modes[6:] in ([], ["fixture", "other184"] * 3)
        for run_index, mode in enumerate(modes, 1):
            prefix = f"{run_index:02d}-{mode}/"
            log, xml, bep, receipt = [archive.read(prefix + name) for name in ("test.log", "test.xml", "bazel-result.json", "receipt.json")]
            actual = json.loads(receipt)
            assert actual == summary["runs"][run_index - 1]
            bundle = json.loads(bep)
            assert bundle["id"]["testResult"]["label"] == TARGET and not bundle["testResult"].get("cachedLocally")
            execution = bundle["testResult"]["executionInfo"]
            assert not execution.get("cachedRemotely")
            assert bundle["id"]["testResult"]["attempt"] == 1
            assert "--flaky_test_attempts=1" in actual["argv"] and "--nocache_test_results" in actual["argv"] and actual["argv"][-1] == TARGET
            extra = [v.split("=",1)[1] for v in actual["argv"] if v.startswith("--test_arg=")]
            expected_args = {"parallel": [], "serial": ["--test-threads=1"], "fixture":["--exact",CASE],"other184":["--skip",CASE]}
            assert extra == expected_args[mode]
            outcomes = re.findall(rb"^test (\S+) \.\.\. (ok|FAILED)$", log, re.MULTILINE)
            names = {name.decode() for name, _ in outcomes}
            expected_names = roster if mode in ("parallel","serial") else {CASE} if mode == "fixture" else roster - {CASE}
            assert len(names) == len(outcomes) and names == expected_names
            failed = [n.decode() for n, status in outcomes if status == b"FAILED"]
            summary_line = re.findall(rb"^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out; finished in ([\d.]+)s", log, re.MULTILINE)
            selected = [r for r in summary_line if int(r[1]) + int(r[2]) == len(expected_names) and int(r[5]) == 185 - len(expected_names)]
            assert len(selected) == 1, selected
            result, passed, nfailed, ignored, measured, filtered, duration = selected[0]
            assert int(ignored) == 0 and int(measured) == 0 and int(nfailed) == len(failed)
            assert (result == b"ok") == (not failed) == (actual["exit_code"] == 0) == (bundle["testResult"]["status"] == "PASSED")
            assert actual["failed"] == failed and len(names) == actual["original_cases"]
            xml_root = ElementTree.fromstring(xml)
            xml_cases = list(xml_root.iter("testcase"))
            assert xml_cases, xml_root.tag
            xml_bad = any(any(e.tag in ("failure","error") for e in c) for c in xml_cases)
            assert xml_bad == bool(failed)
            rows.append(dict(index=run_index,mode=mode,bazel_strategy=execution.get("strategy"),passed=int(passed),failed=failed,filtered=int(filtered),seconds=float(duration),writer_unavailable=b"read-only cold orphan inspection: WriterUnavailable" in log,log_sha256=sha(log),xml_sha256=sha(xml)))
        parallel = [r for r in rows if r["mode"] == "parallel"]
        serial = [r for r in rows if r["mode"] == "serial"]
        contrast = all(not r["failed"] for r in serial) and all(not r["failed"] or r["failed"] == [CASE] for r in parallel) and any(r["failed"] == [CASE] and r["writer_unavailable"] for r in parallel)
        assert contrast == summary["observed_contrast"] == bool(modes[6:])
        assert all(not x.is_dir() or x.filename.endswith("/") for x in archive.infolist())
    return dict(source=FIXED,original_job=137481302908,run=45116325592,job=137499899180,
                artifact_sha256=sha(artifact.read_bytes()),roster_sha256=sha(roster_bytes),observed_contrast=contrast,
                scope="Full same-binary native ARM macOS libtest default and serial, on a single runner, in six fresh, non-retried processes. No global product or deployed concurrency claim.",runs=rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("zip", type=Path)
    print(json.dumps(verify(parser.parse_args().zip), indent=2))
