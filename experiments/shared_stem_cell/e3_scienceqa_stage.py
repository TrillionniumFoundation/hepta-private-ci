"""Exact-public-revision ScienceQA-IMG staging, without touching selected Hepta state.

Only source fields are inspected when selecting a fixed cohort. The original
answer column is read only AFTER source membership/identity has been sealed.
Train+validation labels are materialized in the predictor mode; TEST answer
callbacks, label bytes and label digests are omitted in that mode. The label
owner can separately use the original default mode after predictions seal.
One dataset source owner can still access original Parquet labels, so this is
not cryptographic independent label ownership.
"""
from __future__ import annotations
import argparse
import io
from pathlib import Path
from e3_source_target_partition import partition_source_labels

from e3_scienceqa_contract import (
    DATASET, DATASET_REVISION, SIZES, E3Error, canonical, revision,
    sha, validate_source, write_new, write_jsonl,
)


def source(raw):
    from PIL import Image
    if type(raw) is not dict or type(raw.get("bytes")) is not bytes:
        raise E3Error("physical embedded image bytes required")
    data = raw["bytes"]
    if not 0 < len(data) <= 8 * 1024 * 1024:
        raise E3Error("source image byte bound")
    try:
        img = Image.open(io.BytesIO(data))
    except (OSError, ValueError) as error:
        raise E3Error("malformed source image") from error
    with img:
        if img.format not in ("JPEG", "PNG") or img.width * img.height > 4_194_304:
            raise E3Error("noncanonical original image")
        if getattr(img, "n_frames", 1) != 1:
            raise E3Error("animated image unsupported")
        img.load()
        rgb = img.convert("RGB")
        group = sha(canonical([rgb.size, "RGB"]) + rgb.tobytes())
    return data, group


def public_record(row):
    if type(row) is not dict or set(row) != {"question", "hint", "choices", "image"}:
        raise E3Error("only declared source columns admitted")
    q, h, choices = row["question"], row["hint"], row["choices"]
    if (type(q) is not str or not 1 <= len(q.encode()) <= 4096
            or type(h) is not str or len(h.encode()) > 2048
            or type(choices) is not list or len(choices) != 4
            or any(type(c) is not str or not 1 <= len(c.encode()) <= 1024 for c in choices)):
        return None  # four-choice pre-label eligibility; never filter by answer
    blob, group = source(row["image"])
    return {"question": q, "hint": h, "choices": choices}, blob, group


def select(public, *, sizes=SIZES):
    """Accepts ONLY public fields, never `answer`, `lecture`, or `solution`."""
    if set(public) != set(SIZES) or set(sizes) != set(SIZES):
        raise E3Error("original dataset splits required")
    selected, seen_groups, seen_questions = {}, set(), set()
    for split in SIZES:
        scored = []
        for index, row in enumerate(public[split]):
            candidate = public_record(row)
            if candidate is not None:
                fields, blob, group = candidate
                text_hash = sha(canonical(list(fields.values())))
                token = sha(canonical(["e3-granite-dino-v1", split, index, group, text_hash]))
                scored.append((token, index, fields, blob, group, text_hash))
        rows = []
        for token, index, fields, blob, group, txt in sorted(scored):
            if group in seen_groups or txt in seen_questions:
                continue
            seen_groups.add(group)
            seen_questions.add(txt)
            rows.append((index, fields, blob, group, token))
            if len(rows) == sizes[split]:
                break
        if len(rows) != sizes[split]:
            raise E3Error("not enough independent image/question source rows")
        selected[split] = rows
    return selected


def prepare(selected, answer, output, *, include_test_labels: bool = True):
    if output.exists():
        raise E3Error("create-only output required")
    output.mkdir(parents=True)
    (output / "images").mkdir()
    (output / "inputs").mkdir()
    if type(include_test_labels) is not bool:
        raise E3Error("explicit target-visibility mode required")
    if include_test_labels:
        (output / "private_labels").mkdir()
    cases, images, label_lookups = [], {}, []
    for split in SIZES:
        if len(selected[split]) != SIZES[split]:
            raise E3Error("split count drift")
        for index, fields, blob, group, token in selected[split]:
            image_sha = sha(blob)
            rid = sha(canonical([DATASET_REVISION, split, index, token, image_sha]))
            cases.append({"id": rid, "group": group, "split": split,
                          "image": image_sha, "scope": "public-scienceqa-e3-research", **fields})
            label_lookups.append((rid, group, split, index))
            images.setdefault(image_sha, blob)
    validate_source(cases)
    # Membership and source input digests exist BEFORE the first label read.
    source_sha = write_jsonl(output / "inputs" / "sources.jsonl", cases)
    prelabel = write_new(output / "inputs" / "cohort-before-labels.json", {
        "schema": "hepta.e3-source-membership.v1", "dataset": DATASET,
        "revision": DATASET_REVISION, "source_sha256": source_sha,
        "counts": SIZES, "source_only": True, "chronological_future": False,
        "production_accepted": False})
    for digest, raw in images.items():
        p = output / "images" / digest
        with p.open("xb") as f:
            f.write(raw)
    # The model-facing mode never invokes the answer callback for TEST.
    fit, held = partition_source_labels(
        label_lookups, answer, include_test_labels=include_test_labels)
    train_sha = write_jsonl(output / "inputs" / "fit_labels.jsonl", fit)
    held_sha = (write_jsonl(output / "private_labels" / "test_labels.jsonl", held)
                if include_test_labels else None)
    write_new(output / "source-seals.json", {"dataset": DATASET,
        "dataset_revision": DATASET_REVISION, "source_sha256": source_sha,
        "cohort_sha256": prelabel, "fit_labels_sha256": train_sha,
        "private_test_labels_sha256": held_sha, "raw_image_count": len(images),
        "model_inference_completed": False, "externally_independent_labels": False,
        "production_accepted": False})
    return source_sha, train_sha, held_sha


def acquire_public():
    """Original parquet inventory with publisher LFS or source-byte checks."""
    from datasets import Image, load_dataset
    from huggingface_hub import HfApi, hf_hub_download
    info = HfApi().dataset_info(DATASET, revision=revision(DATASET_REVISION), files_metadata=True)
    if info.sha != DATASET_REVISION:
        raise E3Error("dataset upstream commit drift")
    inventory = {x.rfilename: x for x in info.siblings if x.rfilename.endswith(".parquet")}
    if not 3 <= len(inventory) <= 12 or sum(x.size or 0 for x in inventory.values()) > 1024**3:
        raise E3Error("unexpected bounded parquet inventory")
    names = {split: sorted(x for x in inventory if Path(x).name.startswith(split + "-"))
             for split in SIZES}
    if any(len(v) != 1 for v in names.values()) or set(sum(names.values(), [])) != set(inventory):
        raise E3Error("unsupported exact source shards")
    data_files = {}
    for split, [filename] in names.items():
        f = inventory[filename]
        if not isinstance(f.size, int) or not 0 < f.size < 512 * 1024**2:
            raise E3Error("unknown publisher file size")
        path = Path(hf_hub_download(repo_id=DATASET, filename=filename,
                                    repo_type="dataset", revision=DATASET_REVISION))
        if path.stat().st_size != f.size:
            raise E3Error("publisher parquet size mismatch")
        actual = sha(path.read_bytes())
        if getattr(f, "lfs", None) is not None:
            expected = getattr(f.lfs, "sha256", None)
            if expected and actual != expected:
                raise E3Error("publisher parquet LFS identity mismatch")
        data_files[split] = str(path)
    data = load_dataset("parquet", data_files=data_files)
    public = {split: data[split].select_columns(["question", "hint", "choices", "image"])
                 .cast_column("image", Image(decode=False)) for split in SIZES}
    # Answer column is deliberately accessed ONLY by the callback after cohort sealed.
    labels = {split: data[split].select_columns(["answer"]) for split in SIZES}
    return public, lambda split, index: int(labels[split][index]["answer"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--predictor-source-only", action="store_true",
                        help="do not read, hash or write original TEST labels")
    args = parser.parse_args()
    public, labels = acquire_public()
    selection = select(public)
    prepare(selection, labels, args.output,
            include_test_labels=not args.predictor_source_only)

if __name__ == "__main__":
    main()
