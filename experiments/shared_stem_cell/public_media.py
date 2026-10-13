"""Public ScienceQA image/text execution and a separate text-only Reader control.

Uses the existing staged CLIP/connector and causal-generator execution paths.
Public release splits are not independent future windows. No answers, lectures
or solutions enter selection, tokenization, model inputs or generation prompts.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import time

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell import media_execution as media
from experiments.shared_stem_cell.public_smoke import publisher_file, stage_model

DATASET = "lmms-lab/ScienceQA-IMG"
VISION = "openai/clip-vit-base-patch32"
READER = "Qwen/Qwen2.5-0.5B-Instruct"
PUBLIC_COLUMNS = ("image", "question", "choices", "hint")
SIZES = {"train": 64, "validation": 16, "test": 32}
SYSTEM = "Answer the multiple-choice question with exactly one letter A, B, C, or D. No image is provided."


def revision(value):
    if not isinstance(value, str) or len(value) != 40 or any(c not in "0123456789abcdef" for c in value):
        raise e.InputError("immutable public revision required")
    return value


def prompt(row):
    if not isinstance(row, dict) or set(row) != set(PUBLIC_COLUMNS):
        raise e.InputError("selection accepts public question fields only")
    choices = row["choices"]
    if not isinstance(choices, list) or len(choices) != 4:
        return None  # preregistered four-choice cohort, not label filtering
    if (not isinstance(row["question"], str) or not row["question"]
            or not isinstance(row["hint"], str)
            or any(not isinstance(c, str) or not c for c in choices)):
        raise e.InputError("malformed question text")
    text = row["question"] + ("\n" + row["hint"] if row["hint"] else "")
    text += "\n" + "\n".join(f"{letter}. {choice}" for letter, choice in zip("ABCD", choices))
    return text if len(text.encode()) <= 4096 else None


def source_image(row):
    image = row["image"]
    if (not isinstance(image, dict) or not isinstance(image.get("bytes"), bytes)
            or not 0 < len(image["bytes"]) <= media.MAX_MEDIA_BYTES):
        raise e.InputError("embedded bounded image bytes required; no external path download")
    return image["bytes"]


def choose(public, tokenizer, *, sizes=SIZES):
    """No label mapping is accepted. All cohort decisions precede answer access."""
    if set(public) != set(SIZES) or set(sizes) != set(SIZES):
        raise e.InputError("original train/validation/test splits required")
    selected, seen_text, seen_pixels = {}, set(), set()
    for split in SIZES:
        wanted = e.integer(sizes[split], 1, 128, "cohort size")
        rows = public[split]
        if not 1 <= len(rows) <= 10000:
            raise e.InputError("public source row limit")
        candidates = []
        for i in range(len(rows)):
            row = rows[i]
            text = prompt(row)
            if text is None:
                continue
            ids = tokenizer(text, truncation=False)["input_ids"]
            if not isinstance(ids, list) or not 1 <= len(ids) <= 64:
                continue
            raw = source_image(row)
            candidates.append((e.sha(e.canonical([text, e.sha(raw)])), i))
        chosen = []
        for fingerprint, i in sorted(candidates):
            row = rows[i]
            text, raw = prompt(row), source_image(row)
            image = media.image_bytes(raw)
            pixel = e.sha(e.canonical([image.size, image.mode]) + image.tobytes())
            text_id = e.sha(text.encode())
            if pixel in seen_pixels or text_id in seen_text:
                continue
            seen_pixels.add(pixel)
            seen_text.add(text_id)
            chosen.append({"source_split": split, "source_index": i, "input_sha256": fingerprint,
                           "image_sha256": e.sha(raw), "pixel_sha256": pixel, "text": text})
            if len(chosen) == wanted:
                break
        if len(chosen) != wanted:
            raise e.InputError(f"insufficient eligible {split} records: {len(chosen)}/{wanted}")
        selected[split] = chosen
    return selected


def write_bytes(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def stage_cases(root, public, answers, tokenizer, *, sizes=SIZES):
    selected = choose(public, tokenizer, sizes=sizes)
    seal = e.write_once(root / "cohort-before-labels.json", selected)
    rows = []
    for source_split, choices in selected.items():
        for item in choices:
            index = item["source_index"]
            row = public[source_split][index]
            text, raw = prompt(row), source_image(row)
            if e.sha(e.canonical([text, e.sha(raw)])) != item["input_sha256"]:
                raise e.InputError("public source changed after cohort sealing")
            identity = f"scienceqa:{source_split}:{index}"
            image_path = root / f"{source_split}-{index}.image"
            write_bytes(image_path, raw)  # original image bytes, not a target-dependent repair
            label = answers(source_split, index)  # first label access, AFTER full cohort seal
            e.integer(label, 0, 3, "answer")
            rows.append({"case_id": identity, "group": item["pixel_sha256"],
                "split": {"train": "train", "validation": "calibration", "test": "holdout"}[source_split],
                "scope": "public-scienceqa-research", "observed_at": None,
                "inputs": {"text": text, "image": {"path": image_path.name, "sha256": e.sha(raw)}},
                "label": label})
    raw = b"".join(e.canonical(row) for row in rows)
    write_bytes(root / "dataset.jsonl", raw)
    return {"path": "dataset.jsonl", "sha256": e.sha(raw)}, seal


def stage_dataset(root, dataset_revision):
    """Acquire only bounded immutable Parquet files, then read local columns."""
    from datasets import Image, load_dataset
    from huggingface_hub import HfApi, hf_hub_download

    info = HfApi().dataset_info(DATASET, revision=dataset_revision, files_metadata=True)
    if info.sha != dataset_revision:
        raise e.InputError("dataset revision drift")
    files = {s.rfilename: s for s in info.siblings if s.rfilename.endswith(".parquet")}
    if not 1 <= len(files) <= 16 or any(type(s.size) is not int or s.size < 1 for s in files.values()):
        raise e.InputError("bounded known-size parquet inventory required")
    if sum(s.size for s in files.values()) > 1024**3:
        raise e.InputError("public dataset download exceeds 1 GiB")
    by_split = {split: sorted(n for n in files if Path(n).name.startswith(split + "-")) for split in SIZES}
    if any(not v for v in by_split.values()) or set(sum(by_split.values(), [])) != set(files):
        raise e.InputError("unexpected original Parquet split mapping")
    e.write_once(root / "dataset-source.json", {"dataset": DATASET, "revision": dataset_revision,
        "files": {n: files[n].size for n in sorted(files)}, "split_files": by_split})
    local, verified = {}, {}
    for split, names in by_split.items():
        local[split] = []
        for n in names:
            raw = Path(hf_hub_download(DATASET, n, repo_type="dataset", revision=dataset_revision,
                                      cache_dir=root / "dataset-cache")).read_bytes()
            target = root / f"source-{len(verified)}.parquet"
            write_bytes(target, raw)
            verified[n] = publisher_file(target, files[n])
            local[split].append(str(target))
    e.write_once(root / "dataset-publisher-verified.json", verified)
    source = load_dataset("parquet", data_files=local, cache_dir=str(root / "arrow-cache"))
    public = {s: source[s].select_columns(list(PUBLIC_COLUMNS)).cast_column("image", Image(decode=False)) for s in SIZES}
    answers = {s: source[s].select_columns(["answer"]) for s in SIZES}
    return public, lambda split, index: int(answers[split][index]["answer"])


def text_reader(generator, cases, output):
    """Generate on selected public questions; targets are not an argument."""
    output.mkdir(parents=True, exist_ok=False)
    selected = [c for c in cases if c.split == "holdout"][:16]
    prompts = [generator.tokenizer.apply_chat_template(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": c.inputs["text"]}],
        tokenize=False, add_generation_prompt=True) for c in selected]
    e.write_once(output / "inputs.json", {"case_ids": [c.case_id for c in selected], "prompts": prompts,
        "input_digests": [c.input_digest for c in selected], "model_digest": generator.identity,
        "image_provided": False, "maximum_new_tokens": 32})
    rows = []
    for i, (case, text) in enumerate(zip(selected, prompts)):
        e.write_once(output / f"started-{i:03d}.json", {"case_id": case.case_id, "input_sha256": e.sha(text.encode())})
        result = generator.generate([text], maximum_new_tokens=32)
        if len(result["outputs"]) != 1 or result["model_digest"] != generator.identity:
            raise e.InputError("Reader output coverage/model drift")
        row = {"case_id": case.case_id, **result["outputs"][0]}
        e.write_once(output / f"answer-{i:03d}.json", row)
        rows.append(row)
    seal = e.write_once(output / "predictions.json", {"rows": rows})
    return seal


def main(root, *, allow_conversion=False):
    import torch
    from huggingface_hub import HfApi
    from transformers import AutoTokenizer

    started = time.perf_counter_ns()
    root.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(2)
    api = HfApi()
    pins = {"dataset": revision(api.dataset_info(DATASET).sha),
            "clip": revision(api.model_info(VISION).sha), "reader": revision(api.model_info(READER).sha)}
    e.write_once(root / "acquisition.json", {"pins": pins, "sizes": SIZES,
        "selection": "four choices; full question+hint+choices <=64 CLIP tokens; SHA order; pixel/text dedup",
        "public_release_not_future": True, "independent_evaluation": False, "production_accepted": False})
    try:
        vision_root = root / "vision"
        vision_root.mkdir()
        model = stage_model(vision_root, VISION, pins["clip"], kind="clip", allow_conversion=allow_conversion)
        model["path"] = "vision/model"
        tokenizer = AutoTokenizer.from_pretrained(root / model["path"], local_files_only=True, trust_remote_code=False)
        public, labels = stage_dataset(root, pins["dataset"])
        descriptor, cohort = stage_cases(root, public, labels, tokenizer)
        config = {"schema": "hepta.shared-stem-media.v1", "classes": 4, "steps": 20,
                  "seed": 20261013, "temporal": False, "dataset": descriptor, "models": {"clip": model}}
        e.write_once(root / "manifest.json", config)
        result = media.run(root / "manifest.json", root / "media-execution")
        reader_root = root / "reader"
        reader_root.mkdir()
        reader_model = stage_model(reader_root, READER, pins["reader"], kind="causal_lm", allow_conversion=False)
        generator = e.LocalTextGenerator(reader_root / "model", reader_model, maximum_tokens=512)
        cases, targets = media.read_cases(root, descriptor, 4)
        output = root / "text-execution"
        seal = text_reader(generator, cases, output)
        media.read_cases(root, descriptor, 4)
        rows = e.decode(e.bound_file(output / "predictions.json", seal))["rows"]
        hits = sum(r["text"].strip() == "ABCD"[targets[r["case_id"]]] for r in rows)
        report = {"whole_wall_ns_including_acquisition": time.perf_counter_ns() - started,
            "energy_joules": None, "peak_rss_bytes": None, "cohort_sha256": cohort, "media_prediction_sha256": result["prediction_sha256"],
            "text_prediction_sha256": seal, "text_cases": len(rows), "exact_letter_correct": hits,
            "text_only_not_multimodal_reader": True, "independent_evaluation": False,
            "general_generation_quality": None, "audio_video_generation_completed": False,
            "production_accepted": False}
        e.write_once(root / "report.json", report)
        return report
    except Exception as error:
        e.write_once(root / "failure.json", {"elapsed_wall_ns": time.perf_counter_ns() - started,
                                               "error": type(error).__name__, "message": str(error),
                                               "production_accepted": False})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-weights-only-conversion", action="store_true")
    args = parser.parse_args()
    main(args.output, allow_conversion=args.allow_weights_only_conversion)
