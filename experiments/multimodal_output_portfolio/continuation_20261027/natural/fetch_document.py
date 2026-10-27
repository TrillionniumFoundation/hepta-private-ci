"""Freeze new real document sources, excluding every historical merchant group."""
import argparse
from pathlib import Path
import re
import urllib.parse

from .common import download, read, save, sha


def run(output):
    source = Path(__file__).parent
    spec = read(source / "DOCUMENT_PROTOCOL.json")
    historical = source.parents[1] / "repair_20261026/natural/document/evidence/SOURCE_MANIFEST.json"
    old = read(historical)
    excluded = {r["merchant_group"] for r in old["documents"]}
    used = set(excluded)
    output.mkdir(parents=True, exist_ok=False)
    files, documents = [], []
    card = output / "DATASET_METADATA.json"
    files.append(download("https://huggingface.co/api/datasets/" + spec["dataset"], card, 2000000))
    metadata = read(card)
    if metadata["sha"] != spec["revision"] or "cc-by-4.0" not in metadata["cardData"]["license"]:
        raise ValueError("Dataset version/license differs")
    for split, window, quotas in (("train", spec["selection"]["train_window"],
            [("fit", spec["selection"]["fit_merchants"]), ("validation", spec["selection"]["validation_merchants"])]),
            ("test", spec["selection"]["test_window"], [("test", spec["selection"]["test_merchants"])])):
        queue = []
        for role, count in quotas:
            queue.extend([role]*count)
        cursor = 0
        for offset in range(window[0], window[1], 100):
            query = urllib.parse.urlencode({"dataset": spec["dataset"], "config": "default", "split": split,
                "offset": offset, "length": min(100, window[1]-offset)})
            path = output / "metadata" / f"{split}-{offset}.json"
            files.append(download("https://datasets-server.huggingface.co/rows?" + query, path, 15000000))
            for item in read(path)["rows"]:
                row = item["row"]
                merchant = re.sub(r"[^A-Z0-9]", "", row["entities"]["company"].upper())
                if not merchant or merchant in used:
                    continue
                url = row["image"]["src"]
                if f"/--/{spec['revision']}/--/" not in url:
                    raise ValueError("Image bytes have another revision")
                asset = download(url, output / "images" / (row["key"] + ".jpg"), 8000000)
                files.append(asset)
                documents.append({"id": row["key"], "role": queue[cursor], "split": split,
                    "merchant_group": merchant, "row_index": item["row_idx"], "reference": row["entities"],
                    "reference_words": row["words"], "reference_bboxes": row["bboxes"], "image_size": row["image_size"], **asset})
                used.add(merchant)
                cursor += 1
                if cursor == len(queue):
                    break
            if cursor == len(queue):
                break
        if cursor != len(queue):
            raise ValueError("Insufficient new prespecified merchant groups")
    if len({r["sha256"] for r in documents}) != len(documents):
        raise ValueError("Duplicate actual source images")
    save(output / "MANIFEST.json", {"schema": "hepta.ndu.continuation.natural.document.assets.v1",
        "protocol_sha256": sha(source / "DOCUMENT_PROTOCOL.json"), "historical_manifest_sha256": sha(historical),
        "excluded_historical_merchants": sorted(excluded), "documents": documents, "files": files,
        "group_scope": "Normalized annotated merchant strings and exact images; broader parent-company/template families unresolved"})
    print({"documents": len(documents), "bytes": sum(r["bytes"] for r in files)}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
