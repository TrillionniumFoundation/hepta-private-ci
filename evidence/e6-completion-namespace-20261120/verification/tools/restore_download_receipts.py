"""Losslessly restore retained MCP-result JSON from archive bytes and templates.

This is reversible encoding, not a claim that the unencoded JSON files were
committed. No fields are omitted: only each base64 data string is factored out
and recovered from its exact donor byte range. Nothing is sent to a host.
"""

import argparse
import base64
import hashlib
import json
from pathlib import Path, PurePosixPath


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main(args):
    plan = json.loads(args.templates.read_bytes())
    assert plan["schema"] == "hepta.e6.lossless-binary-read-receipts.v1"
    donors = {}
    for kind, path in (("archive", args.archive), ("manifest", args.manifest)):
        raw = path.read_bytes()
        expected = plan["donors"][kind]
        assert len(raw) == expected["bytes"] and sha(raw) == expected["sha256"]
        donors[kind] = raw
    args.output.mkdir(exist_ok=False)
    records = []
    names = set()
    for row in plan["receipts"]:
        name = row["name"]
        assert PurePosixPath(name).name == name and name not in names
        names.add(name)
        chunk = donors[row["donor"]][row["offset"]:row["offset"] + row["length"]]
        assert len(chunk) == row["length"] and sha(chunk) == row["chunk_sha256"]
        raw = row["prefix"].encode() + base64.b64encode(chunk) + row["suffix"].encode()
        assert len(raw) == row["response_bytes"] and sha(raw) == row["response_sha256"]
        original_equal = None
        if args.compare_originals:
            assert raw == (args.compare_originals / name).read_bytes()
            original_equal = True
        (args.output / name).write_bytes(raw)
        records.append({"name": name, "bytes": len(raw), "sha256": sha(raw), "byte_equal_to_retained_original": original_equal})
    assert len(records) == 70
    result = {"schema": "hepta.e6.lossless-receipts-reconstruction-result.v1", "status": "PASS", "receipts": records, "count": len(records), "complete_json_fields_preserved": True, "reversible_encoding": True, "unencoded_receipts_present_in_git": False, "originals_compared": args.compare_originals is not None, "host_calls": 0, "native_or_model_runs": 0}
    (args.output / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": "PASS", "count": len(records), "all_originals_byte_equal": args.compare_originals is not None}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--templates", required=True, type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--compare-originals", type=Path)
    main(parser.parse_args())
