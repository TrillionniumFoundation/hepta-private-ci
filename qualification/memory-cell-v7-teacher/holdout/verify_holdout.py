#!/usr/bin/env python3
"""Verify frozen request/label binding without reading or calling a candidate."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def main():
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "MANIFEST.json").read_text())
    for name in ("requests", "labels"):
        identity = manifest[name]
        raw = (root / identity["file"]).read_bytes()
        assert len(raw) == identity["bytes"]
        assert hashlib.sha256(raw).hexdigest() == identity["sha256"]
    assert hashlib.sha256((root / "create_holdout.py").read_bytes()).hexdigest() == manifest["generator_sha256"]
    assert hashlib.sha256((root / "SOURCES.json").read_bytes()).hexdigest() == manifest["sources_manifest_sha256"]
    requests = [json.loads(line) for line in (root / "requests.jsonl").read_text().splitlines()]
    labels = [json.loads(line) for line in (root / "labels.jsonl").read_text().splitlines()]
    assert len(requests) == len(labels) == manifest["rows"] == 180
    identities = set()
    for index, (request, label) in enumerate(zip(requests, labels, strict=True)):
        assert set(request) == {"utterance", "series_name", "date"}
        assert all(isinstance(value, str) and value.strip() for value in request.values())
        assert re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", request["date"])
        assert len(request["utterance"]) <= 4096 and len(request["series_name"]) <= 256
        digest = hashlib.sha256(canonical(request)).hexdigest()
        assert label["index"] == index and label["request_sha256"] == digest
        assert digest not in identities
        identities.add(digest)
    assert dict(Counter(row["expected_intent"] for row in labels)) == manifest["by_intent"]
    assert dict(Counter(row["family"] for row in labels)) == manifest["by_family"]
    sources = json.loads((root / "SOURCES.json").read_text())["sources"]
    for source in sources:
        raw = (root / "source/v5" / Path(source["path"]).name).read_bytes()
        digest = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        assert digest == source["git_blob"]
    print(json.dumps({"passed": True, "requests": len(requests), "public_source_blobs": len(sources),
                      "request_sha256": manifest["requests"]["sha256"],
                      "label_sha256": manifest["labels"]["sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
