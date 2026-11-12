"""Operator-pinned screenshot/document acquisition with exact OCR evidence.

Install this callback behind the owner's reservation. It reads an existing image;
source authenticity, prior screenshot/render costs and OCR correctness remain
unverified. Raw artifacts are retained separately from the bounded native wire.
"""

import csv
import io
import json
import math
import os
import re
import selectors
import stat
import subprocess
import tempfile
import time
from pathlib import Path

from .schema import canonical, digest, exact, identifier, integer, require, sha

LIMITS = {
    "image": 4 * 1024 * 1024,
    "document": 16 * 1024 * 1024,
    "source_text": 2 * 1024 * 1024,
    "dom": 2 * 1024 * 1024,
    "operator_config": 65536,
    "ocr_tsv": 512 * 1024,
    "ocr_text": 65536,
    "ocr_stderr": 16384,
    "browser_receipt": 65536,
    "raw_dom": 2 * 1024 * 1024,
}
ADAPTER_SHA256 = sha(Path(__file__).read_bytes())
TSV_FIELDS = (
    "level page_num block_num par_num line_num word_num left top width height conf text"
).split()


def _pinned(path, expected, limit, *, allow_empty=False):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(before.st_mode)
            and (0 if allow_empty else 1) <= before.st_size <= limit,
            "invalid or oversized source artifact",
        )
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    require(
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
        "source artifact changed during read",
    )
    require(
        len(raw) <= limit and sha(raw) == digest(expected),
        "source artifact digest mismatch",
    )
    return raw


def validate_source_config(source):
    """Check operator configuration without opening sources or starting OCR."""
    exact(source, "schema kind image source_uri source_group document text ocr")
    require(source["schema"] == "perc1.source-capture.v1", "unknown source capture")
    require(source["kind"] in ("screenshot", "document_page"), "unknown source kind")
    require(
        type(source["source_uri"]) is str and 0 < len(source["source_uri"]) <= 2048,
        "source URI bound",
    )
    identifier(source["source_group"])
    exact(source["image"], "path sha256")
    if source["document"] is not None:
        exact(source["document"], "path sha256 page_index")
        integer(source["document"]["page_index"])
        require(source["kind"] == "document_page", "document requires page source")
    if source["text"] is not None:
        exact(source["text"], "kind path sha256")
        require(source["text"]["kind"] in ("source_text", "dom"), "invalid text kind")
    for artifact in (source["image"], source["document"], source["text"]):
        if artifact is not None:
            require(
                type(artifact["path"]) is str and Path(artifact["path"]).is_absolute(),
                "absolute operator source path required",
            )
            digest(artifact["sha256"])
    if source["ocr"] is not None:
        ocr = exact(source["ocr"], "executable sha256 language psm")
        require(
            type(ocr["executable"]) is str and Path(ocr["executable"]).is_absolute(),
            "absolute OCR executable required",
        )
        digest(ocr["sha256"])
        require(
            type(ocr["language"]) is str
            and re.fullmatch(r"[a-zA-Z0-9_]{1,32}", ocr["language"]),
            "invalid OCR language",
        )
        require(
            type(ocr["psm"]) is int and ocr["psm"] in (3, 6, 11, 12),
            "unsupported OCR page mode",
        )
    require(
        len(canonical(source)) <= LIMITS["operator_config"],
        "source configuration bound",
    )
    return source


def parse_tsv(raw, width, height):
    """Preserve recognized tokens, UTF-8 byte intervals and image rectangles."""
    require(type(raw) is bytes and 0 < len(raw) <= LIMITS["ocr_tsv"], "OCR TSV bound")
    reader = csv.DictReader(
        io.StringIO(raw.decode("utf-8", errors="strict")),
        delimiter="\t",
        quoting=csv.QUOTE_NONE,
    )
    require(reader.fieldnames == TSV_FIELDS, "unknown OCR TSV columns")
    words, text, previous = [], bytearray(), None
    for row in reader:
        require(
            set(row) == set(TSV_FIELDS) and all(type(v) is str for v in row.values()),
            "malformed OCR TSV row",
        )
        if row["level"] != "5" or not row["text"]:
            continue
        line = [
            int(row[key]) for key in ("page_num", "block_num", "par_num", "line_num")
        ]
        box = [int(row[key]) for key in ("left", "top", "width", "height")]
        x, y, w, h = box
        score = float(row["conf"])
        require(
            all(v >= 0 for v in line + box)
            and w > 0
            and h > 0
            and x + w <= width
            and y + h <= height
            and math.isfinite(score)
            and -1 <= score <= 100,
            "invalid OCR locator or score",
        )
        require(len(words) < 2048, "OCR word bound")
        if words:
            text.extend(b" " if line == previous else b"\n")
        start = len(text)
        text.extend(row["text"].encode("utf-8"))
        require(len(text) <= LIMITS["ocr_text"], "OCR text bound")
        words.append(
            {
                "text": row["text"],
                "start": start,
                "end": len(text),
                "box": box,
                "confidence": row["conf"],
                "line": line,
            }
        )
        previous = line
    return bytes(text), words


def _run_ocr(ocr, raw):
    """Run one pinned local Tesseract, bounding stdout, stderr and wall time."""
    outputs = {"ocr_tsv": bytearray(), "ocr_stderr": bytearray()}
    with tempfile.TemporaryFile() as input_file:
        input_file.write(raw)
        input_file.seek(0)
        process = subprocess.Popen(
            [
                ocr["executable"],
                "stdin",
                "stdout",
                "-l",
                ocr["language"],
                "--psm",
                str(ocr["psm"]),
                "tsv",
            ],
            stdin=input_file,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 30
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ, "ocr_tsv")
                selector.register(process.stderr, selectors.EVENT_READ, "ocr_stderr")
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    require(remaining > 0, "OCR process deadline exceeded")
                    for key, _ in selector.select(min(remaining, 0.25)):
                        chunk = os.read(key.fileobj.fileno(), 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        outputs[key.data].extend(chunk)
                        require(
                            len(outputs[key.data]) <= LIMITS[key.data],
                            "OCR process output bound exceeded",
                        )
            require(
                process.wait(timeout=max(0.01, deadline - time.monotonic())) == 0,
                "OCR process failed",
            )
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdout.close()
            process.stderr.close()
    return {role: bytes(value) for role, value in outputs.items()}


def configured_capture(source, request):
    """Read pinned inputs and execute OCR only after owner dispatch admission."""
    from PIL import Image

    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    validate_source_config(source)
    require(sha(Path(__file__).read_bytes()) == ADAPTER_SHA256, "capture adapter drift")
    identifier(request["source_id"])
    image = source["image"]
    raw = _pinned(image["path"], image["sha256"], LIMITS["image"])
    with Image.open(io.BytesIO(raw)) as decoded:
        width, height = decoded.size
        require(
            decoded.format in ("PNG", "JPEG") and 0 < width * height <= 16_000_000,
            "unsupported or oversized source raster",
        )
        require(
            decoded.getexif().get(274, 1) == 1, "source orientation must be explicit"
        )
        decoded.load()
    artifacts = {"image": raw, "operator_config": canonical(source)}
    if source["document"] is not None:
        document = source["document"]
        artifacts["document"] = _pinned(
            document["path"], document["sha256"], LIMITS["document"]
        )
    if source["text"] is not None:
        text = source["text"]
        artifacts[text["kind"]] = _pinned(
            text["path"], text["sha256"], LIMITS[text["kind"]]
        )
        artifacts[text["kind"]].decode("utf-8", errors="strict")
    read_ns, ocr_ns, ocr_evidence = time.perf_counter_ns() - started, 0, None
    if source["ocr"] is not None:
        ocr = source["ocr"]
        begin = time.perf_counter_ns()
        _pinned(ocr["executable"], ocr["sha256"], 64 * 1024 * 1024)
        artifacts.update(_run_ocr(ocr, raw))
        _pinned(ocr["executable"], ocr["sha256"], 64 * 1024 * 1024)
        text, words = parse_tsv(artifacts["ocr_tsv"], width, height)
        artifacts["ocr_text"] = text
        ocr_evidence = {
            "engine_sha256": ocr["sha256"],
            "language": ocr["language"],
            "psm": ocr["psm"],
            "confidence_semantics": "engine_score_not_probability",
            "words": words,
        }
        ocr_ns = time.perf_counter_ns() - begin
    role = (
        source["text"]["kind"]
        if source["text"] is not None
        else "ocr_text"
        if ocr_evidence
        else None
    )
    value, native_text = artifacts.get(role, b""), None
    if 0 < len(value) <= 8192:
        native_text = {
            "kind": "ocr" if role == "ocr_text" else role,
            "bytes": value,
            "engine": "tesseract-tsv:" + ocr_evidence["engine_sha256"]
            if role == "ocr_text"
            else "operator-pinned-source",
        }
    metadata = {
        "schema": "perc1.source-evidence.v1",
        "source_id": request["source_id"],
        "kind": source["kind"],
        "source_uri": source["source_uri"],
        "source_group": source["source_group"],
        "page_index": None
        if source["document"] is None
        else source["document"]["page_index"],
        "capture_sha256": sha(raw),
        "dimensions": [width, height],
        "origin_authenticated": False,
        "rendered_from_document_verified": False,
        "ocr_verified": False,
        "config_sha256": sha(artifacts["operator_config"]),
        "adapter_sha256": ADAPTER_SHA256,
        "ocr": ocr_evidence,
        "native_text": {
            "role": role,
            "status": "included"
            if native_text
            else "omitted_over_native_limit"
            if len(value) > 8192
            else "absent_or_empty",
        },
        "measurements": {
            "read_wall_ns": read_ns,
            "ocr_wall_ns": ocr_ns,
            "cpu_ns": time.process_time_ns() - cpu,
            "ocr_subprocess_cpu_ns": None,
            "screenshot_capture_wall_ns": None,
            "document_render_wall_ns": None,
            "scope": "pinned read and OCR; prior capture/render and OCR child CPU unmeasured",
        },
    }
    return {
        "image_bytes": raw,
        "exact_text": native_text,
        "source_evidence": {"metadata": metadata, "artifacts": artifacts},
    }


def retain_source_evidence(root, stem, evidence, image_sha256, source_id):
    """Keep full artifacts before the owner's immutable receipt commit."""
    exact(evidence, "metadata artifacts")
    require(re.fullmatch(r"[0-9a-f]{64}", stem), "invalid artifact stem")
    metadata, artifacts = dict(evidence["metadata"]), evidence["artifacts"]
    require(
        metadata["capture_sha256"] == image_sha256
        and metadata["source_id"] == source_id,
        "source evidence/capture mismatch",
    )
    require(
        type(artifacts) is dict
        and {"image", "operator_config"} <= set(artifacts)
        and set(artifacts) <= set(LIMITS),
        "invalid source artifact roles",
    )
    directory = Path(root) / "captures"
    directory.mkdir(mode=0o700, exist_ok=True)
    require(not directory.is_symlink(), "source artifact directory symlink refused")
    metadata["artifacts"] = {}
    for role, raw in artifacts.items():
        require(
            type(raw) is bytes
            and len(raw) <= LIMITS[role]
            and (len(raw) > 0 or role in ("ocr_text", "ocr_stderr")),
            "source artifact byte bound",
        )
        path = directory / (stem + "." + role)
        if role == "image" and path.exists():
            _pinned(path, sha(raw), LIMITS[role])
        else:
            with path.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        metadata["artifacts"][role] = {
            "relative_path": "captures/" + path.name,
            "sha256": sha(raw),
            "byte_length": len(raw),
        }
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    metadata["evidence_sha256"] = sha(metadata)
    verify_source_evidence(metadata, root)
    return metadata


def verify_source_evidence(metadata, root=None):
    """Validate metadata; with root, read all artifacts and check exact OCR spans."""
    exact(
        metadata,
        (
            "schema source_id kind source_uri source_group page_index capture_sha256 "
            "dimensions origin_authenticated rendered_from_document_verified ocr_verified "
            "config_sha256 adapter_sha256 ocr native_text measurements artifacts evidence_sha256"
        ),
    )
    require(metadata["schema"] == "perc1.source-evidence.v1", "unknown source evidence")
    require(
        digest(metadata["evidence_sha256"])
        == sha({k: v for k, v in metadata.items() if k != "evidence_sha256"}),
        "source evidence digest mismatch",
    )
    for flag in (
        "origin_authenticated",
        "rendered_from_document_verified",
        "ocr_verified",
    ):
        require(metadata[flag] is False, "unsupported source assurance")
    identifier(metadata["source_id"])
    identifier(metadata["source_group"])
    digest(metadata["adapter_sha256"])
    require(
        metadata["kind"] in ("screenshot", "document_page"),
        "invalid retained source kind",
    )
    require(
        type(metadata["source_uri"]) is str and 0 < len(metadata["source_uri"]) <= 2048,
        "retained source URI bound",
    )
    if metadata["page_index"] is not None:
        integer(metadata["page_index"])
    dimensions = metadata["dimensions"]
    require(
        type(dimensions) is list
        and len(dimensions) == 2
        and integer(dimensions[0], 1) * integer(dimensions[1], 1) <= 16_000_000,
        "retained source dimensions bound",
    )
    native_text = exact(metadata["native_text"], "role status")
    require(
        native_text["role"] in (None, "dom", "source_text", "ocr_text")
        and native_text["status"]
        in ("included", "omitted_over_native_limit", "absent_or_empty"),
        "invalid native text disposition",
    )
    measurements = exact(
        metadata["measurements"],
        (
            "read_wall_ns ocr_wall_ns cpu_ns ocr_subprocess_cpu_ns "
            "screenshot_capture_wall_ns document_render_wall_ns scope"
        ),
    )
    for key in ("read_wall_ns", "ocr_wall_ns", "cpu_ns"):
        integer(measurements[key])
    for key in (
        "ocr_subprocess_cpu_ns",
        "screenshot_capture_wall_ns",
        "document_render_wall_ns",
    ):
        require(measurements[key] is None, "unmeasured cost must remain unknown")
    require(
        type(measurements["scope"]) is str and len(measurements["scope"]) <= 256,
        "measurement scope bound",
    )
    artifacts = metadata["artifacts"]
    require(
        type(artifacts) is dict
        and {"image", "operator_config"} <= set(artifacts)
        and set(artifacts) <= set(LIMITS),
        "invalid retained source roles",
    )
    require(
        artifacts["image"]["sha256"] == digest(metadata["capture_sha256"])
        and artifacts["operator_config"]["sha256"] == digest(metadata["config_sha256"]),
        "source/config artifact binding mismatch",
    )
    restored = {}
    for role, artifact in artifacts.items():
        exact(artifact, "relative_path sha256 byte_length")
        size = integer(artifact["byte_length"])
        require(
            size <= LIMITS[role] and (size > 0 or role in ("ocr_text", "ocr_stderr")),
            "retained source artifact bound",
        )
        digest(artifact["sha256"])
        require(
            type(artifact["relative_path"]) is str
            and re.fullmatch(
                r"captures/[0-9a-f]{64}\." + role, artifact["relative_path"]
            ),
            "retained source artifact path refused",
        )
        if root is not None:
            path = Path(root) / artifact["relative_path"]
            require(
                not path.parent.is_symlink(),
                "source artifact directory symlink refused",
            )
            raw = _pinned(
                path,
                artifact["sha256"],
                LIMITS[role],
                allow_empty=role in ("ocr_text", "ocr_stderr"),
            )
            require(len(raw) == size, "source artifact length mismatch")
            restored[role] = raw
    if metadata["ocr"] is not None:
        ocr = exact(
            metadata["ocr"], "engine_sha256 language psm confidence_semantics words"
        )
        digest(ocr["engine_sha256"])
        require(
            ocr["confidence_semantics"] == "engine_score_not_probability"
            and {"ocr_tsv", "ocr_text", "ocr_stderr"} <= set(artifacts),
            "OCR evidence missing",
        )
        require(
            type(ocr["words"]) is list and len(ocr["words"]) <= 2048, "OCR word bound"
        )
        if root is not None:
            text, words = parse_tsv(restored["ocr_tsv"], *dimensions)
            require(
                text == restored["ocr_text"] and words == ocr["words"],
                "OCR spans/TSV mismatch",
            )
    else:
        require(
            not set(artifacts).intersection(("ocr_tsv", "ocr_text", "ocr_stderr")),
            "unexpected OCR artifact",
        )
    if root is not None:
        source = validate_source_config(json.loads(restored["operator_config"]))
        require(
            all(
                source[key] == metadata[key]
                for key in ("kind", "source_uri", "source_group")
            )
            and source["image"]["sha256"] == metadata["capture_sha256"],
            "retained source configuration mismatch",
        )
        for role, config in (
            ("document", source["document"]),
            ("text", source["text"]),
        ):
            if config is not None:
                artifact_role = config["kind"] if role == "text" else role
                require(
                    artifact_role in artifacts
                    and artifacts[artifact_role]["sha256"] == config["sha256"],
                    "retained document/text binding mismatch",
                )
        if source["ocr"] is not None:
            require(
                metadata["ocr"] is not None
                and source["ocr"]["sha256"] == metadata["ocr"]["engine_sha256"]
                and source["ocr"]["language"] == metadata["ocr"]["language"]
                and source["ocr"]["psm"] == metadata["ocr"]["psm"],
                "retained OCR engine binding mismatch",
            )
    return restored
