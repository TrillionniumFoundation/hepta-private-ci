"""Create the existing two artifact-sink engineering records; never train."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from cell_experiments import data
from cell_experiments.test_paired_source import capture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    sources = {}
    for path in sorted((ROOT / "scripts/cell_experiments").glob("*.py")):
        raw = path.read_bytes()
        sources[path.relative_to(ROOT).as_posix()] = hashlib.sha256(raw).hexdigest()
    (output / "SOURCES_BEFORE.json").write_text(json.dumps(sources, indent=2) + "\n")
    capture(output, "failure", "0", "a" * 64, {"action": "0"}, 1)
    capture(output, "correction", "1", "b" * 64, {"action": "1"}, 2)
    pins = {}
    for name in ("failure", "correction"):
        raw = (output / (name + ".json")).read_bytes()
        record = data._parse(raw)
        data.validate_record(record)
        pins[name] = dict(
            raw_sha256=hashlib.sha256(raw).hexdigest(),
            raw_bytes=len(raw),
            record_digest=data.record_digest(record),
            declared_success=record["verified_outcome"]["success"],
        )
    values = [
        {"z": [None, True, False, -(2**63), 2**64 - 1], "a": "Hepta 神经元\u2028\n\t\b\f\r\x00"},
        {"record_sha256": "f" * 64, "nested": {"Ω": "é", "A": "\\\"/"}, "zero": 0},
    ]
    vectors = [dict(raw=json.dumps(value, ensure_ascii=False, indent=2), canonical=data.canonical(value).decode("utf-8"), sha256=data.digest(value)) for value in values]
    (output / "canonical-vectors.json").write_bytes(data.canonical(vectors) + b"\n")
    unchanged = all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest for name, digest in sources.items())
    if not unchanged:
        raise ValueError("fixture source changed during generation")
    receipt = dict(schema="hepta.paired-record-identity-fixture.v1", pins=pins, sources_unchanged=unchanged, seconds=time.monotonic()-started, human_participants=0, training_executed=False, source_authentication_claimed=False)
    (output / "FIXTURE.json").write_text(json.dumps(receipt, indent=2) + "\n")
    shutil.copyfile(__file__, output / "GENERATOR.py")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
