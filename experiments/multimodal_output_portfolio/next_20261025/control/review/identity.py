"""Bind all closed actual control requests to the registered source writers."""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024): value.update(block)
    return value.hexdigest()


def run(directory, output):
    registration = json.loads((directory / "registration.json").read_text())
    specification = registration["spec"]
    allocation_path = Path(specification["source"]["allocation"])
    if sha(allocation_path) != specification["source_allocation_sha256"]:
        raise ValueError("Registered allocation identity changed")
    allocation = json.loads(allocation_path.read_text())
    source = allocation["roles"]["control"]
    writers = source["pair_writer_ids"]
    if (len(writers), len(set(writers)), len(source["source_ids"])) != (512, 128, 1024):
        raise ValueError("Wrong registered control census")
    if set(Counter(writers).values()) != {4}:
        raise ValueError("The paired writer clusters changed")
    count = 0
    seen = Counter()
    with gzip.open(directory / "requests.jsonl.gz", "rt") as stream:
        for row in map(json.loads, stream):
            case = row["case"]
            if not 0 <= case < 512 or row["source_ids"] != source["source_ids"][2 * case:2 * case + 2]:
                raise ValueError("Actual source identities differ from writer allocation")
            seen[case] += 1
            count += 1
    if count != 147456 or set(seen.values()) != {288} or len(seen) != 512:
        raise ValueError("Wrong repeated-request source census")
    result = {"schema": "hepta.next.control-source-identity-audit.v1", "status": "passed",
        "actual_request_identities_verified": count, "source_pairs": 512, "writer_clusters": 128,
        "pairs_per_writer": 4, "requests_per_pair": 288,
        "source_allocation_sha256": sha(allocation_path),
        "registration_sha256": sha(directory / "registration.json"),
        "requests_sha256": sha(directory / "requests.jsonl.gz"), "audit_source_sha256": sha(__file__),
        "scope": "Secondary identity audit only; no changes to frozen candidates, primary estimands or thresholds"}
    with output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2); stream.write("\n")
    print(json.dumps(result))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--directory", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(); run(a.directory, a.output)
