"""Reconstruct registered captures from original scans without reading labels."""

import argparse
import io
import json
import time
from pathlib import Path

from perc1.schema import Dataset, load, require, sha


def audit(dataset_dir, original_root, output):
    from PIL import Image

    started = time.perf_counter_ns()
    root, originals, output = Path(dataset_dir), Path(original_root), Path(output)
    require(not output.exists(), "retain prior source-audit results")
    dataset = Dataset(load(root / "dataset.json"), root)
    panel, mapping = load(root / "panel.json"), load(root / "capture-mapping.json")
    require(panel["dataset_sha256"] == sha(dataset.value), "panel identity changed")
    require(panel["capture_mapping_sha256"] == sha(mapping), "mapping identity changed")
    require(set(mapping) == set(dataset.sources), "source mapping is incomplete")
    images = {}
    for partition in ("training_data", "testing_data"):
        for path in (originals / partition / "images").glob("*.png"):
            raw = path.read_bytes()
            digest = sha(raw)
            require(digest not in images, "duplicate original scan identity")
            images[digest] = (path, raw)
    results = []
    for source in dataset.sources.values():
        record, loc = mapping[source["id"]], source["locator"]
        require(
            record["original_sha256"] == loc["origin_sha256"],
            "original source mismatch",
        )
        path, raw = images[record["original_sha256"]]
        annotation = path.parent.parent / "annotations" / (path.stem + ".json")
        # Only hash the annotation file. No annotation text or evaluator is loaded.
        require(
            sha(annotation.read_bytes()) == record["annotation_sha256"],
            "annotation identity changed",
        )
        image = Image.open(io.BytesIO(raw)).convert("RGB")
        require(
            list(image.size)
            == record["original_dimensions"]
            == [loc["width"], loc["height"]],
            "original dimensions changed",
        )
        x, y, width, height = record["crop"]
        require(
            (x, y, x + width, y + height)
            == (loc["x0"], loc["y0"], loc["x1"], loc["y1"]),
            "registered crop changed",
        )
        capture = image.crop((x, y, x + width, y + height))
        if record["transform"] == "bilinear downsample by 3 then restore dimensions":
            capture = capture.resize(
                (max(2, width // 3), max(2, height // 3)), Image.Resampling.BILINEAR
            ).resize(capture.size, Image.Resampling.BILINEAR)
        else:
            require(
                record["transform"] == "lossless integer crop",
                "unknown preparation transform",
            )
        encoded = io.BytesIO()
        capture.save(encoded, format="PNG")
        registered = dataset.read(source["id"])
        require(
            encoded.getvalue() == registered
            and sha(registered) == record["capture_sha256"],
            "capture does not reproduce from original scan",
        )
        results.append(
            {
                "source_id": source["id"],
                "split": source["split"],
                "original_sha256": sha(raw),
                "capture_sha256": sha(registered),
                "status": "PASS",
            }
        )
    report = {
        "schema": "perc1.document-source-audit.v1",
        "status": "PASS",
        "dataset_sha256": sha(dataset.value),
        "mapping_sha256": sha(mapping),
        "sources": len(results),
        "original_documents": len({r["original_sha256"] for r in results}),
        "code_sha256": sha(Path(__file__).read_bytes()),
        "wall_ns": time.perf_counter_ns() - started,
        "scope": "original scan bytes to registered PNG captures; annotations hashed but not parsed; no evaluator access",
        "results": results,
    }
    with output.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", required=True)
    parser.add_argument("--original-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = audit(args.dataset_dir, args.original_root, args.output)
    print(
        json.dumps(
            {
                key: result[key]
                for key in ("status", "sources", "original_documents", "dataset_sha256")
            }
        )
    )
