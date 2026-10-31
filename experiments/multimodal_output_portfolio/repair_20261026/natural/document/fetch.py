"""Freeze a bounded SROIE subset with distinct annotated merchant groups."""
import argparse
import json
from pathlib import Path
import re
import urllib.parse

from ..fetch import download


REPOSITORY = "jsdnrs/ICDAR2019-SROIE"
REVISION = "bffe40c26759f3376ec2b3ae9031dbba54cd587c"


def group(text):
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def main(output):
    output.mkdir(parents=True, exist_ok=False)
    files, selected, used = [], [], set()
    metadata = output / "DATASET_METADATA.json"
    files.append(download(f"https://huggingface.co/api/datasets/{REPOSITORY}", metadata, 2000000))
    card = json.loads(metadata.read_text())
    if card["sha"] != REVISION or "cc-by-4.0" not in card["cardData"]["license"]:
        raise ValueError("Dataset identity or documented license differs")
    for role, split, count in (("fit", "train", 6), ("test", "test", 12)):
        query = urllib.parse.urlencode(dict(dataset=REPOSITORY, config="default", split=split, offset=0, length=100))
        path = output / f"{role}-source-metadata.json"
        files.append(download("https://datasets-server.huggingface.co/rows?" + query, path, 15000000))
        chosen = 0
        for item in json.loads(path.read_text())["rows"]:
            row = item["row"]
            identity = group(row["entities"]["company"])
            if not identity or identity in used:
                continue
            url = row["image"]["src"]
            if f"/--/{REVISION}/--/" not in url:
                raise ValueError("Image content revision mismatch")
            asset = download(url, output / "images" / (row["key"] + ".jpg"), 8000000)
            files.append(asset)
            selected.append({"role": role, "split": split, "row_index": item["row_idx"], "id": row["key"],
                "merchant_group": identity, "reference": row["entities"], "reference_words": row["words"],
                "reference_bboxes": row["bboxes"], "image_size": row["image_size"], **asset})
            used.add(identity)
            chosen += 1
            if chosen == count:
                break
        if chosen != count:
            raise ValueError("Frozen source window has insufficient distinct merchant groups")
    if len({r["sha256"] for r in selected}) != len(selected):
        raise ValueError("Duplicate scanned image across source allocation")
    manifest = {"schema": "hepta.repair.natural.document.assets.v1", "repository": REPOSITORY, "revision": REVISION,
        "license_from_dataset_card": "CC-BY-4.0", "documents": selected, "files": files,
        "selection": "First 6 distinct normalized merchant labels in train[0:100], then first 12 new labels in test[0:100]",
        "scope": "Normalized annotated merchant strings and exact image hashes are disjoint; parent companies/template families are not exhaustively resolved"}
    (output / "MANIFEST.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"documents": len(selected), "bytes": sum(r["bytes"] for r in files)}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args().output)
