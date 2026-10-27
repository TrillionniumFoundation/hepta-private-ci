"""Freeze further untouched SROIE merchant groups before any model output."""
import argparse
from pathlib import Path
import re
import urllib.parse

from ...continuation_20261027.natural.common import download
from .common import read, save, sha


def run(previous, output):
    source = Path(__file__).parent
    protocol = read(source / "DOCUMENT_PROTOCOL.json")
    old = read(previous / "MANIFEST.json")
    excluded = set(old["excluded_historical_merchants"]) | {r["merchant_group"] for r in old["documents"]}
    hashes = {r["sha256"] for r in old["documents"]}
    used = set(excluded)
    output.mkdir(parents=True, exist_ok=False)
    files, documents = [], []
    for offset in range(0, 347, 100):
        query = urllib.parse.urlencode({"dataset": protocol["dataset"], "config": "default", "split": "test",
            "offset": offset, "length": min(100, 347 - offset)})
        path = output / "metadata" / f"test-{offset}.json"
        files.append(download("https://datasets-server.huggingface.co/rows?" + query, path, 15000000))
        for item in read(path)["rows"]:
            row = item["row"]
            merchant = re.sub(r"[^A-Z0-9]", "", row["entities"]["company"].upper())
            if not merchant or merchant in used:
                continue
            url = row["image"]["src"]
            if f"/--/{protocol['dataset_revision']}/--/" not in url:
                raise ValueError("Image revision differs")
            asset = download(url, output / "images" / (row["key"] + ".jpg"), 8000000)
            if asset["sha256"] in hashes:
                raise ValueError("New merchant duplicates previous source bytes")
            files.append(asset)
            documents.append({"id": row["key"], "role": "test", "split": "test", "merchant_group": merchant,
                "row_index": item["row_idx"], "reference": row["entities"], "reference_words": row["words"],
                "reference_bboxes": row["bboxes"], "image_size": row["image_size"], **asset})
            used.add(merchant)
            hashes.add(asset["sha256"])
            if len(documents) == protocol["test_merchants"]:
                break
        if len(documents) == protocol["test_merchants"]:
            break
    if len(documents) != protocol["test_merchants"]:
        raise ValueError("Insufficient prespecified fresh merchant groups")
    save(output / "MANIFEST.json", {"schema": "hepta.ndu.closure-v2.natural.document.assets.v1",
        "protocol_sha256": sha(source / "DOCUMENT_PROTOCOL.json"), "previous_manifest_sha256": sha(previous / "MANIFEST.json"),
        "excluded_merchants": sorted(excluded), "documents": documents, "files": files,
        "group_scope": "Normalized annotated merchant strings; no claim of unseen corporate families or receipt templates"})
    print({"new_merchants": len(documents), "bytes": sum(r["bytes"] for r in files)}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.previous, args.output)
