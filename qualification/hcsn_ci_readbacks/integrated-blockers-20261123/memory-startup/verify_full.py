"""Replay the hosted source/roster and full nextest results from the downloaded artifacts."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from zipfile import ZipFile

directory = Path(__file__).resolve().parent
full_log = "all-agentd-unit-tests.log"
controls = ("bootstrap.log", "readiness.log", "process.log", "fleet.log")
outcome = re.compile(r"^\s*(?:(?:TRY \d+) )?PASS\s+\[[^\n]*?\]\s*\(\s*\d+/\d+\) codex-hepta-agentd (\S+)\s*$", re.MULTILINE)


def sums(raw):
    result = {}
    for row in raw.decode().splitlines():
        digest, name = row.split(maxsplit=1)
        name = name.removeprefix("./")
        assert name not in result and re.fullmatch("[0-9a-f]{64}", digest)
        result[name] = digest
    return result


def read_cases(raw):
    data = json.loads(raw)
    suites = list(data["rust-suites"].values())
    assert len(suites) == 1
    suite = suites[0]
    assert (suite["kind"], suite["package-name"], suite["status"]) == ("lib", "codex-hepta-agentd", "listed")
    return suite["binary-id"], {name: (entry["ignored"], entry["filter-match"]) for name, entry in suite["testcases"].items()}


def summary(log):
    matches = re.findall(r"^\s*Summary \[[^\n]*?\]\s+(\d+) tests? run:\s+(\d+) passed(?:\s*\([^\n()]*\))?(?:, (\d+) failed)?(?:, (\d+) skipped)?\s*$", log, re.MULTILINE)
    assert len(matches) == 1, [line for line in log.splitlines() if "Summary [" in line]
    ran, passed, failed, skipped = (int(value or 0) for value in matches[0])
    names = set(outcome.findall(log))
    assert ran == passed == len(names) and failed == 0
    return {"run": ran, "passed": passed, "skipped": skipped}, names


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("archive", type=Path)
    ap.add_argument("--digest", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--prior", type=Path, default=directory / "observed.json")
    args = ap.parse_args()
    assert hashlib.sha256(args.archive.read_bytes()).hexdigest() == args.digest
    prior = json.loads(args.prior.read_text())
    with ZipFile(args.archive) as z:
        manifest = sums(z.read("SHA256SUMS"))
        assert set(manifest) == set(z.namelist()) - {"SHA256SUMS"}
        for name, digest in manifest.items():
            assert hashlib.sha256(z.read(name)).hexdigest() == digest, name
        assert z.read("tested-commit.txt").decode().strip() == args.source
        children = sums(z.read("child-binaries.sha256"))
        assert set(children) == {"codex", "hepta-joint-propose", "agentd-lib.tar.zst", "source-list.json", "nextest-version.txt"}
        assert manifest["source-list.json"] == children["source-list.json"]
        binary, cases = read_cases(z.read("source-list.json"))
        assert (binary, cases) == read_cases(z.read("restored-list.json"))
        expected = {name for name, (ignored, match) in cases.items() if not ignored and match["status"] == "matches"}
        complete, names = summary(z.read(full_log).decode())
        assert names == expected, {"absent": sorted(expected-names)[:10], "extra": sorted(names-expected)[:10]}
        assert complete["skipped"] == len(cases)-len(expected)
        assert set(prior["missing_children"]) <= names
        subgroups = {}
        for name in controls:
            statistics, group = summary(z.read(name).decode())
            assert group and group <= names
            subgroups[name] = statistics
    print(json.dumps({"source": args.source, "artifact_sha256": args.digest, "checked_members": len(manifest),
        "child_checksums": children, "binary_id": binary, "listed": len(cases), "selected_cases_with_named_passes": len(names),
        "full": complete, "previously_failed_now_passed": prior["missing_children"], "controls": subgroups}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
