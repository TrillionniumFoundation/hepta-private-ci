"""Prepare one controlled field-transcription panel from local FUNSD scans.

The selected rectangle is part of the task, not an inferred answer location.
Annotations only create sealed evaluator targets. Images are not redistributed.
"""

import argparse
import io
import json
from pathlib import Path

from PIL import Image

from .schema import canonical, integer, require, sha


def write_json(path, value):
    Path(path).write_bytes(canonical(value) + b"\n")


def prepare(root, output, train_count=64, dev_count=16, test_count=32):
    for count in (train_count, dev_count, test_count):
        require(integer(count, 1) <= 199, "invalid document count")
    root, output = Path(root), Path(output)
    require(not output.exists(), "output already exists; preserve previous attempts")
    output.mkdir(parents=True)
    (output / "captures").mkdir()
    candidates = {}
    for partition in ("training_data", "testing_data"):
        candidates[partition] = []
        for annotation in sorted((root / partition / "annotations").glob("*.json")):
            form = json.loads(annotation.read_text())["form"]
            words = [
                w
                for e in form
                if e["label"] == "answer"
                for w in e["words"]
                if 4 <= len(w["text"].strip()) <= 20
                and 0
                < (w["box"][2] - w["box"][0]) * (w["box"][3] - w["box"][1])
                <= 2400
                and w["box"][2] - w["box"][0] >= 8
                and w["box"][3] - w["box"][1] >= 8
            ]
            if words:
                chosen = min(words, key=lambda w: sha([annotation.stem, w["box"]]))
                candidates[partition].append((annotation, chosen))
    require(
        len(candidates["testing_data"]) >= test_count, "insufficient held-out documents"
    )
    pool = sorted(candidates["training_data"], key=lambda x: sha(x[0].stem))
    require(len(pool) >= train_count + dev_count, "insufficient training/dev documents")
    selected = [("train", *x) for x in pool[:train_count]]
    selected += [("dev", *x) for x in pool[train_count : train_count + dev_count]]
    selected += [("confirmation", *x) for x in candidates["testing_data"][:test_count]]
    sources, episodes, targets, mapping, origins = [], [], [], {}, set()
    content_splits = {}
    for split, annotation, word in selected:
        image_path = annotation.parent.parent / "images" / (annotation.stem + ".png")
        original = image_path.read_bytes()
        origin = sha(original)
        require(origin not in origins, "duplicate document across source groups")
        origins.add(origin)
        image = Image.open(io.BytesIO(original)).convert("RGB")
        x, y, right, bottom = word["box"]
        width, height = right - x, bottom - y
        target = image.crop((x, y, right, bottom))
        initial = target.resize(
            (max(2, width // 3), max(2, height // 3)), Image.Resampling.BILINEAR
        ).resize(target.size, Image.Resampling.BILINEAR)
        dx = (x + image.width // 2) % max(1, image.width - width)
        dy = (y + image.height // 2) % max(1, image.height - height)
        for attempt in range(1000):
            distractor = image.crop((dx, dy, dx + width, dy + height))
            encoded = io.BytesIO()
            distractor.save(encoded, format="PNG")
            capture_id = sha(encoded.getvalue())
            if content_splits.get(capture_id, split) == split:
                break
            dx = (dx + 37) % max(1, image.width - width)
            dy = (dy + 23) % max(1, image.height - height)
        else:
            raise ValueError("no independent distractor crop available")
        episode_id = "funsd-" + annotation.stem
        source_ids = []
        # Fixed schedules are counterbalanced independently of terminal labels.
        extras = [("read", target, (x, y)), ("other", distractor, (dx, dy))]
        if int(sha(episode_id)[:8], 16) % 2:
            extras.reverse()
        for suffix, capture, position in [("initial", initial, (x, y)), *extras]:
            source_id = episode_id + "-" + suffix
            source_ids.append(source_id)
            path = "captures/" + source_id + ".png"
            capture.save(output / path, format="PNG")
            raw = (output / path).read_bytes()
            require(
                content_splits.get(sha(raw), split) == split,
                "capture content crosses splits",
            )
            content_splits[sha(raw)] = split
            px, py = position
            loc = {
                "kind": "image",
                "origin_sha256": origin,
                "x0": px,
                "y0": py,
                "x1": px + width,
                "y1": py + height,
                "width": image.width,
                "height": image.height,
            }
            sources.append(
                {
                    "id": source_id,
                    "episode_id": episode_id,
                    "group": origin,
                    "split": split,
                    "description": f"Registered rectangle {px},{py},{width},{height}; "
                    + (
                        "degraded initial capture"
                        if suffix == "initial"
                        else "original scan resolution"
                    ),
                    "uri": "https://guillaumejaume.github.io/FUNSD/",
                    "path": path,
                    "sha256": sha(raw),
                    "byte_length": len(raw),
                    "locator": loc,
                    "available_ns": 0,
                }
            )
            mapping[source_id] = {
                "original_sha256": origin,
                "annotation_sha256": sha(annotation.read_bytes()),
                "original_dimensions": list(image.size),
                "crop": [px, py, width, height],
                "transform": "bilinear downsample by 3 then restore dimensions"
                if suffix == "initial"
                else "lossless integer crop",
                "capture_sha256": sha(raw),
            }
        task = f"Transcribe the selected word at rectangle ({x},{y},{width},{height}) in this scanned form. Preserve case, digits and punctuation exactly; return an empty string if unreadable."
        episodes.append(
            {
                "id": episode_id,
                "group": origin,
                "split": split,
                "family": "blurred_screenshot",
                "task": task,
                "source_ids": source_ids,
                "initial_ids": source_ids[:1],
            }
        )
        targets.append(
            {
                "episode_id": episode_id,
                "answer": word["text"].strip(),
                "fields": {"selected_word": word["text"].strip()},
                "required_evidence": [episode_id + "-read"],
            }
        )
    dataset = {"schema": "perc1.dataset.v1", "sources": sources, "episodes": episodes}
    write_json(output / "dataset.json", dataset)
    training_episode_ids = {e["id"] for e in episodes if e["split"] != "confirmation"}
    write_json(
        output / "training-targets.json",
        [t for t in targets if t["episode_id"] in training_episode_ids],
    )
    write_json(output / "sealed-targets.json", targets)
    write_json(output / "capture-mapping.json", mapping)
    receipt = {
        "schema": "perc1.document-panel.v1",
        "dataset_sha256": sha(dataset),
        "targets_sha256": sha(targets),
        "capture_mapping_sha256": sha(mapping),
        "source": "FUNSD official local dataset; noncommercial research",
        "code_sha256": sha(Path(__file__).read_bytes()),
        "split_counts": {
            s: sum(e["split"] == s for e in episodes)
            for s in ("train", "dev", "confirmation")
        },
        "task_scope": "explicit-ROI single-word transcription with controlled quality recovery",
        "source_independence": "document SHA groups; template/organization independence unverified",
        "scientific_qualified": False,
        "status": "HOLD",
    }
    write_json(output / "panel.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--train", type=int, default=64)
    parser.add_argument("--dev", type=int, default=16)
    parser.add_argument("--test", type=int, default=32)
    args = parser.parse_args()
    print(
        json.dumps(
            prepare(args.dataset_root, args.output, args.train, args.dev, args.test)
        )
    )
