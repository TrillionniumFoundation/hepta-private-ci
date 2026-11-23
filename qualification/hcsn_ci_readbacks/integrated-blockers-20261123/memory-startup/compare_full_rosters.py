"""Compare rosters, selected passes, build identities, and actual process artifacts across two sources."""

import json
import re
import sys
from pathlib import Path
from zipfile import ZipFile


def roster(z, name):
    data = json.loads(z.read(name))["rust-suites"]["codex-hepta-agentd"]["testcases"]
    return {case: (entry["ignored"], entry["filter-match"]) for case, entry in data.items()}


def inspect(base, current):
    with ZipFile(base) as old, ZipFile(current) as new:
        prior, fresh = roster(old, "source-list.json"), roster(new, "source-list.json")
        if prior != roster(old, "restored-list.json") or fresh != roster(new, "restored-list.json"):
            raise ValueError("archived and restored roster mismatch")
        for name in ("all-agentd-unit-tests.log", "bootstrap.log", "readiness.log", "process.log", "fleet.log"):
            if not new.read(name).strip():
                raise ValueError(f"missing test log {name}")
        lines = new.read("all-agentd-unit-tests.log").decode().splitlines()
        retry = [line.strip() for line in lines if re.search(r"\b(?:RETR(?:Y|IES)|TRY\s+[2-9][0-9]*|FLAKY)\b", line)]
        child_hash = lambda archive: {name: digest for digest, name in (line.split() for line in archive.read("child-binaries.sha256").decode().splitlines())}
        a, b = child_hash(old), child_hash(new)
        return {
            "prior_source": old.read("tested-commit.txt").decode().strip(),
            "current_source": new.read("tested-commit.txt").decode().strip(),
            "normalized_roster_added": sorted(fresh.keys() - prior.keys()),
            "normalized_roster_removed": sorted(prior.keys() - fresh.keys()),
            "normalized_roster_changed": sorted(k for k in prior.keys() & fresh.keys() if prior[k] != fresh[k]),
            "current_retry_or_flaky_records": retry,
            "prior_and_current_manifest_sha256": {k: {"prior": a[k], "current": b[k], "same": a[k] == b[k]} for k in sorted(a.keys() | b.keys())},
        }


if __name__ == "__main__":
    print(json.dumps(inspect(Path(sys.argv[1]), Path(sys.argv[2])), sort_keys=True, indent=2))
