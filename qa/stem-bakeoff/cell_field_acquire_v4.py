"""Acquire only byte-pinned source inputs needed to reproduce V4 data cohorts.

Existing exact files are reused. The retention bundle is never extracted: only
its declared source-identity member is read. Historical predictions, scores and
label payloads are not parsed. This helper is post-run reproduction tooling.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile
from urllib.request import Request, urlopen

from cell_field_data import SCHEMA, build_cohorts, sha
from cell_field_data_v4 import ARCHIVES, PRIORS
from prepare_news_cohorts import COUNTS, _read_archive, _read_bounded, canonical, normalized_title, select_rows


RAW = "https://raw.githubusercontent.com/TrillionniumFoundation/hepta-private-ci/"
PINNED = {
    "uci-news.zip": ("https://archive.ics.uci.edu/static/public/359/news+aggregator.zip", ARCHIVES["uci"], 29224203),
    "20news-bydate.tar.gz": ("https://ndownloader.figshare.com/files/5975967", ARCHIVES["newsgroups"], 14464277),
    "v2-sources.json": (RAW + "3372a726affb287b97e531645ccbcc3afc91013f/qa/stem-bakeoff/evidence/"
                        "20261024-cell-parameter-field-v2/data/sources.json", PRIORS["v2"][0], 296017),
    "v3-sources.json": (RAW + "a062749d768ea09838921c7f3bfd8b644541b873/qa/stem-bakeoff/evidence/"
                        "20261024-cell-parameter-field-v3/data/sources.json", PRIORS["v3"][0], 386046),
    "retention-negative.tar.gz": (RAW + "b59c2ac3fbed3a60869c6ccd689867e001f6dc90/qa/stem-bakeoff/evidence/"
        "20261024-retention-census/negative-v1/retention-negative-evidence-final.tar.gz",
        "35ba45b0fcbc3785751cce1188c8849ea49b956895be303a819fc024733baf9f", 622013),
}
RETENTION_MEMBER = "raw/data/sources.json"
DERIVED = {"v1-sources.json": (PRIORS["v1"][0], 315623),
           "retention-sources.json": (PRIORS["retention"][0], 296321)}


def _verify(payload, digest, size):
    if len(payload) != size or hashlib.sha256(payload).hexdigest() != digest:
        raise ValueError("source payload differs from its exact byte pin")
    return payload


def _existing(path, digest, size):
    if path.exists() or path.is_symlink():
        return _verify(_read_bounded(path, size), digest, size)
    return None


def _save(path, payload, digest, size):
    _verify(payload, digest, size)
    if _existing(path, digest, size) is None:
        with path.open("xb") as stream:
            stream.write(payload)
    return payload


def download_pinned(path, url, digest, size):
    """One bounded request, no replacement of a changed cache or unpinned fallback."""
    cached = _existing(path, digest, size)
    if cached is not None:
        return cached
    request = Request(url, headers={"User-Agent": "hepta-cell-field-source-acquisition-v4",
                                   "Accept": "application/octet-stream"})
    with urlopen(request, timeout=30) as response:
        declared = response.headers.get("Content-Length")
        if declared is not None and int(declared) > size:
            raise ValueError("remote source exceeds registered size")
        payload = response.read(size+1)
    return _save(path, payload, digest, size)


def reconstruct_v1(archive):
    """Rebuild historical source identities only; never call the label-writing preparer."""
    rows = _read_archive(archive)
    selected, _ = build_cohorts(rows, select_rows(rows, COUNTS))
    sources = []
    for index, item in enumerate(selected):
        row = item["row"]
        sources.append({"index": index, "source_id": "uci-news:"+row["source_id"], "raw_source_id": row["source_id"],
            "component_id": item["component_id"], "month": item["month"], "role": item["role"],
            "timestamp_ms": row["timestamp_ms"], "source_row_sha256": row["source_row_sha256"],
            "normalized_title_sha256": sha(normalized_title(row["text"]).encode()),
            "publisher_sha256": sha(normalized_title(row["publisher"]).encode()),
            "component_member_count": len(item["members"]), "component_members_sha256": sha(item["members"])})
    return _verify(canonical({"schema": SCHEMA, "rows": sources})+b"\n", *DERIVED["v1-sources.json"])


def retention_sources(payload):
    """Inspect bounded tar headers and read exactly one regular source-identity member."""
    _, digest, size = PINNED["retention-negative.tar.gz"]
    _verify(payload, digest, size)
    found, count, expanded = None, 0, 0
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as bundle:
        for member in bundle:
            count, expanded = count+1, expanded+member.size
            if count > 128 or expanded > 8 << 20:
                raise ValueError("retention archive exceeds bounded header census")
            if member.name != RETENTION_MEMBER:
                continue
            if found is not None or not member.isfile() or member.size != DERIVED["retention-sources.json"][1]:
                raise ValueError("retention source member duplicated or changed")
            with bundle.extractfile(member) as stream:
                found = stream.read(member.size+1)
    if found is None:
        raise ValueError("retention source identity member absent")
    return _verify(found, *DERIVED["retention-sources.json"])


def acquire(output, verify_v1_reconstruction=False):
    root = Path(output).absolute()
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise ValueError("regular acquisition directory required")
    root.mkdir(parents=True, exist_ok=True)
    entries = {}
    for name, (url, digest, size) in PINNED.items():
        download_pinned(root/name, url, digest, size)
        entries[name] = {"sha256": digest, "bytes": size, "url": url, "verified": True}
    v1 = _existing(root/"v1-sources.json", *DERIVED["v1-sources.json"])
    if v1 is None or verify_v1_reconstruction:
        v1 = reconstruct_v1(root/"uci-news.zip")
        _save(root/"v1-sources.json", v1, *DERIVED["v1-sources.json"])
    retention = _read_bounded(root/"retention-negative.tar.gz", PINNED["retention-negative.tar.gz"][2])
    _save(root/"retention-sources.json", retention_sources(retention), *DERIVED["retention-sources.json"])
    for name, (digest, size) in DERIVED.items():
        parsed = json.loads(_read_bounded(root/name, size))
        if len(parsed["rows"]) != PRIORS["v1" if name.startswith("v1") else "retention"][1]:
            raise ValueError("historical source identity census changed")
        entries[name] = {"sha256": digest, "bytes": size, "verified": True}
    entries["v1-sources.json"]["provenance"] = {"method": "deterministic source-only reconstruction matched historical SHA256",
        "historical_commit": "ff5baef731f36420370c5bcc049c50a567cda06a", "input": "uci-news.zip"}
    entries["retention-sources.json"]["provenance"] = {"archive": "retention-negative.tar.gz", "member": RETENTION_MEMBER}
    receipt = {"schema": "hepta.cell-field-source-acquisition.v4", "files": entries,
        "cache_policy": "verify existing exact bytes; otherwise one bounded pinned download or deterministic derivation",
        "payload_access": "source identities only; no historical outcome or label payload parsed",
        "tooling_scope": "post-run reproducibility helper, not retroactively added to executed source closure",
        "recipe_source_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in (Path(__file__).name, "cell_field_data.py", "cell_field_data_v4.py", "prepare_news_cohorts.py")}}
    (root/"acquisition.json").write_bytes(canonical(receipt)+b"\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--verify-v1-reconstruction", action="store_true")
    receipt = acquire(**vars(parser.parse_args()))
    print(json.dumps({"verified": sorted(receipt["files"]), "outcome_payloads_opened": False}))
