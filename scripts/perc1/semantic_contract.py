"""Bounded public PERC tasks, exact text evidence and experiment contracts.

This validates byte identities, neutral complete grids and declared split groups.
It does not attest capture authority, the truth/completeness of group metadata,
absence of arbitrary semantic leakage in instructions, or scientific usefulness.
Raster payloads stay out of the public catalog; acquisition must be metered.
"""

import json

from .schema import canonical, digest, exact, identifier, integer, require, sha

MODALITIES = ("image", "video", "source_text", "dom", "ocr")
GROUPS = ("document_group", "template_group", "source_group")


def neutral_capture_id(capture):
    exact(capture, "sha256 width height frame_index timestamp_micros")
    require(digest(capture["sha256"]) != "0" * 64, "capture identity is missing")
    width, height = integer(capture["width"], 1), integer(capture["height"], 1)
    require(width * height * 3 <= 64 * 1024 * 1024, "raster exceeds source bound")
    integer(capture["frame_index"])
    integer(capture["timestamp_micros"])
    return "capture-" + sha(capture)


def grid_candidates(captures, grid):
    """Enumerate every cell from geometry alone; no target/answer is accepted."""
    require(type(captures) is list and len(captures) <= 32, "capture count bound")
    require(type(grid) is list and len(grid) == 2, "grid must be [columns, rows]")
    columns, rows = (integer(v, 1) for v in grid)
    require(columns * rows <= 128, "grid count bound")
    candidates, ids = [], set()
    for capture in captures:
        exact(capture, "capture_id sha256 width height frame_index timestamp_micros")
        source = {k: v for k, v in capture.items() if k != "capture_id"}
        require(
            capture["capture_id"] == neutral_capture_id(source),
            "non-neutral capture ID",
        )
        require(capture["capture_id"] not in ids, "duplicate capture")
        ids.add(capture["capture_id"])
        width, height = capture["width"], capture["height"]
        require(columns <= width and rows <= height, "empty grid cell")
        for column in range(columns):
            for row in range(rows):
                x, y = column * width // columns, row * height // rows
                rectangle = [
                    x,
                    y,
                    (column + 1) * width // columns - x,
                    (row + 1) * height // rows - y,
                ]
                body = {"capture_id": capture["capture_id"], "rectangle": rectangle}
                candidates.append({"candidate_id": "candidate-" + sha(body), **body})
    require(len(candidates) <= 128, "candidate count bound")
    return candidates


def public_packet(value):
    """Validate and detach only public data; bundled private fields are rejected."""
    exact(
        value,
        "schema task_id instruction captures grid candidates context modalities read_budget",
    )
    require(value["schema"] == "perc1.semantic-task.v1", "unknown semantic task")
    identifier(value["task_id"])
    require(
        type(value["instruction"]) is str
        and 0 < len(value["instruction"].encode()) <= 4096,
        "instruction byte bound",
    )
    context = value["context"]
    require(type(context) is list and len(context) <= 16, "context count bound")
    require(
        all(type(s) is str for s in context)
        and sum(len(s.encode()) for s in context) <= 4096,
        "context byte bound",
    )
    exact(value["modalities"], " ".join(MODALITIES))
    require(
        all(
            s in ("present", "missing", "unknown") for s in value["modalities"].values()
        ),
        "unknown modality availability",
    )
    require(integer(value["read_budget"]) <= 128, "read budget bound")
    expected = grid_candidates(value["captures"], value["grid"])
    supplied = value["candidates"]
    require(
        type(supplied) is list and len(supplied) == len(expected),
        "incomplete grid catalog",
    )
    require(
        sorted(canonical(c) for c in supplied)
        == sorted(canonical(c) for c in expected),
        "candidate catalog must be the complete neutral grid",
    )
    if value["captures"]:
        require(
            any(value["modalities"][m] == "present" for m in ("image", "video")),
            "captures require a present visual modality",
        )
    packet = json.loads(canonical(value))
    packet["captures"].sort(
        key=lambda c: (c["frame_index"], c["timestamp_micros"], c["capture_id"])
    )
    order = {c["capture_id"]: i for i, c in enumerate(packet["captures"])}
    packet["candidates"].sort(key=lambda c: (order[c["capture_id"]], c["rectangle"]))
    require(len(canonical(packet)) <= 65536, "public packet byte bound")
    return packet


def validate_text_evidence(value, raw, captures=()):
    """Bind UTF-8 spans to source bytes or unverified OCR's original raster.

    DOM references address a captured UTF-8 DOM/text snapshot, not a live node.
    OCR references locate the image region; they do not prove transcription truth.
    """
    exact(value, "schema kind content_sha256 fidelity spans")
    require(value["schema"] == "perc1.semantic-text.v1", "unknown text evidence")
    kind = value["kind"]
    require(kind in ("source_text", "dom", "ocr"), "unknown exact channel")
    require(type(raw) is bytes and len(raw) <= 8192, "text exceeds native raw bound")
    require(digest(value["content_sha256"]) == sha(raw), "text byte identity changed")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("text evidence is not UTF-8") from error
    fidelity = (
        "ocr_transcription_unverified" if kind == "ocr" else "source_bytes_preserved"
    )
    require(value["fidelity"] == fidelity, "invalid text fidelity claim")
    require(
        type(value["spans"]) is list and len(value["spans"]) <= 128, "span count bound"
    )
    require(
        type(captures) in (list, tuple) and len(captures) <= 32,
        "capture reference count bound",
    )
    capture_list = list(captures)
    grid_candidates(capture_list, [1, 1])
    catalog = {c["capture_id"]: c for c in capture_list}
    ids = set()
    for span in value["spans"]:
        exact(span, "span_id start end references")
        require(identifier(span["span_id"]) not in ids, "duplicate span ID")
        ids.add(span["span_id"])
        start, end = integer(span["start"]), integer(span["end"], 1)
        require(start < end <= len(raw), "span escapes text")
        try:
            raw[:start].decode("utf-8")
            raw[start:end].decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("span splits a UTF-8 code point") from error
        refs = span["references"]
        require(type(refs) is list and 0 < len(refs) <= 8, "reference count bound")
        kinds = set()
        for ref in refs:
            require(type(ref) is dict, "reference must be an object")
            ref_kind = ref.get("kind")
            require(
                ref_kind in ("bytes", "dom", "raster"), "unknown original reference"
            )
            kinds.add(ref_kind)
            if ref_kind in ("bytes", "dom"):
                exact(
                    ref,
                    "kind origin_sha256 start end total"
                    + (" node_id" if ref_kind == "dom" else ""),
                )
                require(
                    digest(ref["origin_sha256"]) == sha(raw), "source snapshot changed"
                )
                require(
                    (integer(ref["start"]), integer(ref["end"]), integer(ref["total"]))
                    == (start, end, len(raw)),
                    "source reference disagrees with exact span",
                )
                if ref_kind == "dom":
                    identifier(ref["node_id"])
            elif ref_kind == "raster":
                exact(
                    ref, "kind capture_id x y width height frame_index timestamp_micros"
                )
                capture = catalog.get(ref["capture_id"])
                require(capture is not None, "raster reference lacks a bound capture")
                x, y = integer(ref["x"]), integer(ref["y"])
                width, height = integer(ref["width"], 1), integer(ref["height"], 1)
                require(
                    x + width <= capture["width"] and y + height <= capture["height"],
                    "raster reference escapes original capture",
                )
                require(
                    (integer(ref["frame_index"]), integer(ref["timestamp_micros"]))
                    == (capture["frame_index"], capture["timestamp_micros"]),
                    "raster frame/time reference changed",
                )
            else:
                require(False, "unknown original reference")
        required = {"source_text": "bytes", "dom": "dom", "ocr": "raster"}[kind]
        require(required in kinds, "exact channel lacks its original reference")
    require(len(canonical(value)) <= 65536, "text evidence metadata bound")
    return json.loads(canonical(value))


def extract_span(value, raw, span_id, captures=()):
    validate_text_evidence(value, raw, captures)
    for span in value["spans"]:
        if span["span_id"] == span_id:
            return raw[span["start"] : span["end"]].decode("utf-8")
    raise ValueError("unknown text span")


def validate_split_registry(rows):
    """Require document/template/source disjointness and inherited augmentation groups."""
    require(type(rows) is list and 0 < len(rows) <= 4096, "split registry count bound")
    tasks, observed, seen = {}, set(), {g: {} for g in GROUPS}
    for row in rows:
        exact(
            row,
            "task_id split document_group template_group source_group parent_task_id",
        )
        task_id = identifier(row["task_id"])
        require(task_id not in tasks, "duplicate split task")
        require(row["split"] in ("train", "dev", "confirmation"), "unknown split")
        observed.add(row["split"])
        for group in GROUPS:
            identity = digest(row[group])
            require(identity != "0" * 64, "split group identity is missing")
            prior = seen[group].setdefault(identity, row["split"])
            require(prior == row["split"], group + " crosses splits")
        if row["parent_task_id"] is not None:
            identifier(row["parent_task_id"])
        tasks[task_id] = row
    require(observed == {"train", "dev", "confirmation"}, "incomplete split registry")
    resolved = set()
    for task_id, row in tasks.items():
        parent = row["parent_task_id"]
        if parent is not None:
            require(parent in tasks, "augmentation parent is absent")
            require(
                all(row[k] == tasks[parent][k] for k in (*GROUPS, "split")),
                "augmentation changed its source lineage",
            )
        chain, current = set(), task_id
        while current is not None and current not in resolved:
            require(current not in chain, "cyclic augmentation lineage")
            require(current in tasks, "augmentation parent is absent")
            chain.add(current)
            current = tasks[current]["parent_task_id"]
        resolved.update(chain)
    return json.loads(canonical(rows))


def validate_arm_budgets(arms):
    """Validate fair acquisition terms; the executing owner must enforce them.

    This does not claim equal runtime cost: encoding, failures, cold startup and
    training must still be measured and reported, including unknown measurements.
    """
    require(
        type(arms) is dict
        and {"rules", "global", "dense"} <= set(arms)
        and len(arms) <= 16,
        "comparison arms missing or excessive",
    )
    baseline = None
    for name, budget in arms.items():
        identifier(name)
        exact(
            budget,
            "public_packet_sha256 maximum_reads maximum_pixels maximum_text_bytes initial_reads",
        )
        digest(budget["public_packet_sha256"])
        for key in (
            "maximum_reads",
            "maximum_pixels",
            "maximum_text_bytes",
            "initial_reads",
        ):
            integer(budget[key])
        require(
            budget["maximum_reads"] <= 128
            and budget["initial_reads"] <= budget["maximum_reads"],
            "initial reads exceed common budget",
        )
        require(budget["maximum_text_bytes"] <= 8192 * 128, "text acquisition bound")
        encoded = canonical(budget)
        require(
            baseline is None or encoded == baseline,
            "arm information or acquisition budgets differ",
        )
        baseline = encoded
    return json.loads(canonical(arms))
