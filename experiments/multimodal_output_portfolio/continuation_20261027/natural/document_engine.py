"""Real OCR evidence, neural field selection, conditional region OCR and delivery."""
import os
from pathlib import Path
import resource
import subprocess
import time

from PIL import Image, ImageDraw

from ...repair_20261026.natural.document.ocr import FIELDS, extract, lines_from_tsv
from .common import read, save, sha
from .document_decoder import candidates


def cpu_now():
    child = resource.getrusage(resource.RUSAGE_CHILDREN)
    return time.process_time() + child.ru_utime + child.ru_stime


def ocr(image_path, output, scale=1, box=None):
    output.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter(), cpu_now()
    with Image.open(image_path) as source:
        original = source.convert("RGB")
    width, height = original.size
    x0, y0 = 0, 0
    prepared = Path(image_path)
    if box is not None:
        padding = max(6, round(.15*(box[3]-box[1])))
        x0, y0 = max(0, int(box[0])-padding), max(0, int(box[1])-padding)
        x1, y1 = min(width, int(box[2])+padding), min(height, int(box[3])+padding)
        crop = original.crop((x0, y0, max(x0+1, x1), max(y0+1, y1)))
        crop = crop.resize((crop.width*scale, crop.height*scale), Image.Resampling.LANCZOS)
        prepared = output / "REGION.png"
        crop.save(prepared)
    environment = os.environ.copy()
    environment["OMP_THREAD_LIMIT"] = "1"
    subprocess.run(["tesseract", str(prepared), str(output / "ocr"), "-l", "eng",
        "--psm", "6" if box is not None else "3", "tsv", "txt"],
        check=True, capture_output=True, env=environment)
    lines, confidence = lines_from_tsv(output / "ocr.tsv", scale)
    for line in lines:
        line["box"] = [line["box"][0]+x0, line["box"][1]+y0, line["box"][2]+x0, line["box"][3]+y0]
    public = {"lines": lines, "mean_word_confidence": confidence, "width": width, "height": height,
        "requested_region": box, "scale": scale, "annotation_box_received": False,
        "wall_seconds": time.perf_counter()-wall, "cpu_seconds": cpu_now()-cpu}
    save(output / "PUBLIC_OCR.json", public)
    return public


def deliver(image_path, selected, output):
    answers = {field: selected[field]["value"] for field in FIELDS}
    public = {"answers": answers, "selected_fields": selected, "reference_received": False}
    save(output / "DELIVERED.json", public)
    with Image.open(image_path) as source:
        image = source.convert("RGB")
    draw = ImageDraw.Draw(image)
    for field, item in selected.items():
        if item["value"]:
            draw.rectangle(item["box"], outline="red", width=2)
            draw.text((item["box"][0], max(0, item["box"][1]-12)), field, fill="blue")
    image.save(output / "DELIVERED.jpg", quality=90)
    observed = read(output / "DELIVERED.json")
    with Image.open(output / "DELIVERED.jpg") as reopened:
        reopened.load()
        if reopened.size != image.size or observed != public:
            raise ValueError("Actual answer/image readback differs")
    return {"answers": observed["answers"], "answer_sha256": sha(output / "DELIVERED.json"),
        "image_sha256": sha(output / "DELIVERED.jpg"), "delivered_ns": time.time_ns()}


def episode(image_path, decoder, arm, threshold, output):
    output.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter(), cpu_now()
    first = ocr(image_path, output / "first")
    width, height = first["width"], first["height"]
    calls, selected, decisions = 1, {}, []
    if arm == "original_rules":
        answers, boxes = extract(first["lines"], height)
        selected = {field: {"value": answers[field], "box": boxes.get(field, [0, 0, width, height])} for field in FIELDS}
    else:
        choices = candidates(first["lines"], width, height)
        for field in FIELDS:
            base = decoder.select(choices[field], field, width, height)
            gate_wall, gate_cpu = time.perf_counter(), cpu_now()
            proceed = arm == "learned_all_refine" or (arm == "learned_selective" and base["predicted_quality"] < threshold)
            decision = {"field": field, "base_value": base["value"], "predicted_quality": base["predicted_quality"],
                "refine": proceed, "gate_wall_seconds": time.perf_counter()-gate_wall,
                "gate_cpu_seconds": cpu_now()-gate_cpu}
            if proceed:
                refined = ocr(image_path, output / ("refine-" + field), 2, base["box"])
                choices[field].extend(candidates(refined["lines"], width, height)[field])
                calls += 1
            selected[field] = decoder.select(choices[field], field, width, height)
            decisions.append(decision)
    delivered = deliver(image_path, selected, output)
    public = {"arm": arm, "threshold": threshold, "decisions": decisions, "actual_OCR_calls": calls,
        "selected_fields": selected, "output_directory": str(output), **delivered,
        "whole_cpu_seconds": cpu_now()-cpu, "whole_wall_seconds": time.perf_counter()-wall}
    save(output / "PUBLIC_RESULT.json", public)
    return public
