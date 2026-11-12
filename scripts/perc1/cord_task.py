"""Actor-only receipt task: choose a view without receiving a target rectangle.

All views derive from an explicitly supplied real image. Derivation and original
bytes remain retained. The deterministic decoder uses acquired OCR only; its
limitations are measured against labels held by the separate evaluation driver.
"""

import io
import re
import shutil
import time
from pathlib import Path

from PIL import Image

from .capture_entry import OwnedProducer, decode_native_wire, model_sha256
from .owner import Owner
from .schema import canonical, require, sha
from .source_capture import (
    configured_capture,
    retain_source_evidence,
    verify_source_evidence,
)
from .source_entry import make_config

TASK = "Read the final total amount printed on this receipt. No target rectangle is supplied."
BANDS = {"upper": (0.0, 0.5), "middle": (0.25, 0.75), "lower": (0.5, 1.0)}


def write(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def normalize_amount(text):
    return re.sub(r"[^0-9]", "", text).lstrip("0") or "0"


def decode(text):
    """Frozen lexical rule; no model output, hidden annotation or ROI enters it."""
    lines = text.splitlines()
    amount = re.compile(r"\d[\d.,]*")
    found = []
    for index, line in enumerate(lines):
        label = line.casefold()
        if ("total" in label or "jumlah" in label or "grand" in label) and not (
            "subtotal" in label
            or "sub total" in label
            or "sub-total" in label
            or "total item" in label
            or "total qty" in label
            or "total quantity" in label
        ):
            values = amount.findall(line)
            if not values and index + 1 < len(lines):
                values = amount.findall(lines[index + 1])
            if values:
                found.append(values[-1])
    return normalize_amount(found[-1]) if found else None


def prepare(item, root, weights, projection):
    """Prepare label-free public views; record their exact source geometry."""
    started = time.perf_counter_ns()
    root.mkdir(parents=True, exist_ok=False)
    raw = Path(item["image_path"]).read_bytes()
    require(sha(raw) == item["image_sha256"], "CORD source changed")
    original = root / "original.image"
    original.write_bytes(raw)
    with Image.open(io.BytesIO(raw)) as opened:
        require(opened.getexif().get(274, 1) == 1, "explicit orientation required")
        image = opened.convert("RGB")
    width, height = image.size
    tesseract = Path(shutil.which("tesseract")).resolve()
    ocr = dict(
        executable=str(tesseract),
        sha256=sha(tesseract.read_bytes()),
        language="eng",
        psm=6,
    )
    sources, requests, transforms = {}, {}, {}
    boxes = {"initial": (0, 0, width, height), "full": (0, 0, width, height)}
    boxes.update(
        {
            name: (0, int(a * height), width, int(b * height))
            for name, (a, b) in BANDS.items()
        }
    )
    for name, box in boxes.items():
        view = image.crop(box)
        view.thumbnail(
            (160, 512) if name == "initial" else (800, 1024), Image.Resampling.BILINEAR
        )
        path = root / (name + ".png")
        view.save(path)
        require(path.stat().st_size <= 4 * 1024 * 1024, "derived image byte bound")
        sources[name] = dict(
            schema="perc1.source-capture.v1",
            kind="document_page",
            image=dict(path=str(path), sha256=sha(path.read_bytes())),
            source_uri=item["source_uri"] + "#" + name,
            source_group=item["id"],
            document=dict(
                path=str(original), sha256=item["image_sha256"], page_index=0
            ),
            text=None,
            ocr=ocr,
        )
        w, h = view.size
        require(w >= 32 and h >= 32, "view too small for fixed neural patches")
        # OCR sees the complete captured view. Native latent transport uses four
        # annotation-free 16x16 patches within its unchanged 8192-byte crop cap.
        regions = [
            dict(
                evidence_id=f"patch-{x}-{y}",
                x=w * x // 4 - 8,
                y=h * y // 4 - 8,
                width=16,
                height=16,
            )
            for y in (1, 3)
            for x in (1, 3)
        ]
        requests[name] = dict(source_id=name, representation="dense", regions=regions)
        transforms[name] = dict(
            original_box=list(box),
            output_size=list(view.size),
            image_sha256=sources[name]["image"]["sha256"],
        )
    projection_raw = Path(projection).read_bytes()
    model = dict(
        weights=str(weights),
        weights_sha256=sha(Path(weights).read_bytes()),
        projection=str(projection),
        projection_sha256=sha(projection_raw),
        device="cpu",
    )
    value = dict(
        schema="perc1.cord-public-task.v1",
        task=TASK,
        task_sha256=sha(TASK.encode()),
        id=item["id"],
        image_sha256=item["image_sha256"],
        split=item["split"],
        target_rectangle_public=False,
        sources=sources,
        requests=requests,
        transforms=transforms,
        model=model,
        preparation_wall_ns=time.perf_counter_ns() - started,
    )
    write(root / "TASK.json", value)
    return value


def config(task, root):
    value = make_config(
        root,
        task["id"] + ":" + root.name,
        1,
        8,
        task["sources"],
        task["model"],
        sha(TASK.encode()),
    )
    return value


def adapter(value, projection):
    grant = value["grant"]
    binding = {
        **{k: grant[k] for k in ("owner_id", "generation", "source_frontier")},
        "grant_sha256": sha(grant),
        "encoder_sha256": model_sha256(value["model"]["weights_sha256"], projection),
    }
    owner = Owner(value["state_dir"], binding, value["budget_units"])
    producer = OwnedProducer(
        owner,
        grant,
        value["model"]["weights"],
        value["model"]["weights_sha256"],
        projection,
    )
    return owner, producer


def text(owner, receipt):
    require(receipt["status"] == "executed", "source observation incomplete")
    if receipt["result"].get("schema") == "perc1.owned-encoding.v2":
        decode_native_wire(receipt["result"], source_root=owner.root)
    else:
        require(
            receipt["result"].get("schema") == "perc1.ocr-only-capture.v1",
            "unknown OCR receipt",
        )
        verify_source_evidence(receipt["result"]["source_evidence"], owner.root)
    metadata = receipt["result"]["source_evidence"]
    artifact = metadata["artifacts"]["ocr_text"]
    raw = (owner.root / artifact["relative_path"]).read_bytes()
    require(sha(raw) == artifact["sha256"], "retained OCR changed")
    return raw.decode("utf-8")


def answer(owner, receipts):
    values = [decode(text(owner, receipt)) for receipt in receipts]
    return next((value for value in reversed(values) if value is not None), None)


def acquire(owner, producer, task, name, *, neural):
    request = task["requests"][name]
    if neural:
        return producer.observe(
            name,
            request,
            lambda admitted: configured_capture(task["sources"][name], admitted),
        )

    def capture(admitted):
        result = configured_capture(task["sources"][name], admitted)
        metadata = retain_source_evidence(
            owner.root,
            sha(name.encode()),
            result["source_evidence"],
            sha(result["image_bytes"]),
            name,
        )
        return {"schema": "perc1.ocr-only-capture.v1", "source_evidence": metadata}

    return owner.execute(name, request, dispatch=capture)


def candidates(task, prefix, initial_text):
    """Public geometry, acquired OCR and retained initial latent; no labels."""
    values = []
    confidence = float(decode(initial_text) is not None)
    for index, (name, (top, bottom)) in enumerate(BANDS.items()):
        features = dict(
            schema="perc1.acquisition-features.v1",
            prefix_sha256=sha(prefix),
            task_goal=[float(index == j) for j in range(3)] + [top, bottom],
            coverage=0.0,
            source_repeat=0.0,
            remaining_budget=4_000_000,
            uncertainty=1.0 - confidence,
            acquired_latent=prefix["latent_summary"],
            acquired_receipt_sha256s=prefix["receipt_sha256s"],
        )
        values.append(
            dict(
                id=name,
                kind="change_view",
                upper_cost=2_000_000,
                features=features,
                request=task["requests"][name],
            )
        )
    return values
