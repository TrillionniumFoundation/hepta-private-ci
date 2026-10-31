"""Actual OCR and frozen text/layout rules; reference entities are not accepted."""
import csv
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import time

from PIL import Image, ImageDraw


FIELDS = ("company", "date", "address", "total")
DATE = re.compile(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})\b")
MONEY = re.compile(r"\b\d+(?:,\d{3})*\.\d{2}\b")
ADDRESS = re.compile(r"\b(?:JALAN|JLN|TAMAN|LOT|ROAD|STREET|NO[.]?|BAHRU|SELANGOR)\b|\b\d{5}\b")


def union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def lines_from_tsv(path, scale):
    with path.open(newline="") as stream:
        words = [r for r in csv.DictReader(stream, delimiter="\t") if r["level"] == "5" and r["text"].strip() and float(r["conf"]) >= 0]
    lines = []
    for word in sorted(words, key=lambda r: (int(r["top"])+int(r["height"])/2, int(r["left"]))):
        x, y, w, h = [int(word[k])/scale for k in ("left", "top", "width", "height")]
        center = y+h/2
        eligible = [line for line in lines if abs(center-line["center"]) <= .45*min(h, line["height"])]
        item = {"text": word["text"], "box": [x, y, x+w, y+h], "confidence": float(word["conf"])}
        if eligible:
            line = min(eligible, key=lambda r: abs(center-r["center"]))
            line["words"].append(item)
        else:
            lines.append({"center": center, "height": h, "words": [item]})
    result = []
    for line in sorted(lines, key=lambda r: r["center"]):
        ordered = sorted(line["words"], key=lambda r: r["box"][0])
        result.append({"text": " ".join(w["text"] for w in ordered), "box": union([w["box"] for w in ordered]),
                       "confidence": sum(w["confidence"] for w in ordered)/len(ordered)})
    return result, (sum(float(w["conf"]) for w in words)/len(words) if words else 0)


def extract(lines, height):
    answers = {k: "" for k in FIELDS}
    boxes = {}
    companies = []
    for line in lines:
        text = line["text"].upper()
        if line["box"][1] > .35*height or len(re.findall("[A-Z]", text)) < 4 or ADDRESS.search(text):
            continue
        if re.search(r"\b(?:TEL|FAX|GST|REG|INVOICE|RECEIPT|CASH|COPY|ORIGINAL|DATE|WWW)\b", text):
            continue
        commercial = bool(re.search(r"\b(?:SDN|BHD|MART|STORE|TRADING|RESTAURANT|RESTORAN|ENTERPRISE|CAFE|BAKERY)\b", text))
        companies.append((3*commercial-line["box"][1]/height+.001*len(text), line))
    if companies:
        chosen = max(companies, key=lambda r: r[0])[1]
        answers["company"], boxes["company"] = chosen["text"], chosen["box"]
    for line in lines:
        match = DATE.search(line["text"])
        if match:
            answers["date"], boxes["date"] = match.group(), line["box"]
            break
    totals = []
    for i, line in enumerate(lines):
        text = line["text"].upper()
        if not re.search(r"TOTAL|AMOUNT DUE|NET AMOUNT", text) or re.search(r"QTY|QUANTITY|SUBTOTAL|SUB TOTAL|TOTAL GST|TOTAL TAX", text):
            continue
        amounts = MONEY.findall(text)
        target = line
        if not amounts and i+1 < len(lines) and not re.search(r"CASH|CHANGE|GST|TAX", lines[i+1]["text"].upper()):
            target = lines[i+1]
            amounts = MONEY.findall(target["text"])
        if amounts:
            priority = 3*bool(re.search(r"GRAND|ROUND|NET|DUE", text)) + .001*line["box"][1]
            totals.append((priority, amounts[-1], target["box"]))
    if totals:
        _, answers["total"], boxes["total"] = max(totals, key=lambda r: r[0])
    for i, line in enumerate(lines):
        if line["box"][1] > .5*height:
            break
        if ADDRESS.search(line["text"].upper()):
            address = []
            for candidate in lines[i:i+5]:
                text = candidate["text"].upper()
                if re.search(r"\b(?:TEL|FAX|GST|INVOICE|RECEIPT|CASHIER|DATE|CASH)\b", text) or DATE.search(text):
                    break
                address.append(candidate)
            if address:
                answers["address"] = " ".join(r["text"] for r in address)
                boxes["address"] = union([r["box"] for r in address])
            break
    return answers, boxes


def infer(image_path, settings, output):
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter_ns()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    original = Image.open(image_path).convert("RGB")
    scale = settings["scale"]
    prepared = original.resize((original.width*scale, original.height*scale), Image.Resampling.LANCZOS)
    prepared.save(output / "INPUT.png")
    environment = os.environ.copy()
    environment["OMP_THREAD_LIMIT"] = "1"
    subprocess.run(["tesseract", str(output/"INPUT.png"), str(output/"ocr"), "-l", "eng", "--psm", str(settings["psm"]), "tsv", "txt"],
                   check=True, capture_output=True, env=environment)
    lines, confidence = lines_from_tsv(output / "ocr.tsv", scale)
    answers, boxes = extract(lines, original.height)
    public = {"answers": answers, "predicted_boxes": boxes, "mean_word_confidence": confidence,
              "recognized_lines": lines, "reference_entities_supplied": False, "reference_boxes_supplied": False}
    (output / "ANSWERS.json").write_text(json.dumps(public, ensure_ascii=False, sort_keys=True, indent=2)+"\n", encoding="utf-8")
    annotated = original.copy()
    draw = ImageDraw.Draw(annotated)
    for field, box in boxes.items():
        draw.rectangle(box, outline="red", width=2)
        draw.text((box[0], max(0, box[1]-12)), field, fill="blue")
    annotated.save(output / "ANNOTATED.png")
    readback = json.loads((output / "ANSWERS.json").read_text(encoding="utf-8"))
    with Image.open(output / "ANNOTATED.png") as image:
        if image.size != original.size or image.format != "PNG" or readback != public:
            raise ValueError("Actual structured/visual output readback failed")
        image.load()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {**readback, "wall_seconds": (time.perf_counter_ns()-started)/1e9,
        "subprocess_cpu_seconds": (after.ru_utime+after.ru_stime)-(before.ru_utime+before.ru_stime),
        "actual_ocr_calls": 1, "settings": settings}
