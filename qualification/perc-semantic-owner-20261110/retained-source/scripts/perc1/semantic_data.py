"""Synthetic visual routing tasks; all confirmation results remain engineering HOLD.

The renderer, controlled grammar and generated source streams are shared methods,
not independent real-world organizations. Candidate grids never consume labels.
"""

import io
import random
from pathlib import Path

from PIL import Image, ImageDraw

from .schema import canonical, require, sha
from .semantic_contract import (
    grid_candidates,
    neutral_capture_id,
    public_packet,
    validate_split_registry,
)

COLORS = {
    "red": (205, 35, 45),
    "green": (25, 155, 65),
    "blue": (40, 90, 210),
    "yellow": (215, 175, 15),
}
SHAPES = ("circle", "square", "triangle", "diamond")
FAMILIES = ("semantic", "occlusion", "layout", "temporal", "text_image")
TILE = 24


def draw_symbol(draw, shape, color, box):
    x0, y0, x1, y1 = box
    middle = (x0 + x1) // 2
    if shape == "circle":
        draw.ellipse(box, fill=color)
    elif shape == "square":
        draw.rectangle(box, fill=color)
    elif shape == "triangle":
        draw.polygon([(middle, y0), (x1, y1), (x0, y1)], fill=color)
    elif shape == "diamond":
        draw.polygon(
            [(middle, y0), (x1, (y0 + y1) // 2), (middle, y1), (x0, (y0 + y1) // 2)],
            fill=color,
        )
    else:
        raise ValueError("unknown symbol")


def _render(cards, grid, boxes, background, occluded):
    image = Image.new("RGB", (grid[0] * TILE, grid[1] * TILE), background)
    draw = ImageDraw.Draw(image)
    for index, card in enumerate(cards):
        ox, oy = index % grid[0] * TILE, index // grid[0] * TILE
        box = [v + (ox if j % 2 == 0 else oy) for j, v in enumerate(boxes[index])]
        draw_symbol(draw, card["shape"], COLORS[card["color"]], box)
        if occluded:
            # Every card receives the same mask: occlusion cannot mark the answer.
            draw.rectangle((ox, oy + 11, ox + TILE - 1, oy + 13), fill=background)
    return image


def make_panel(root, *, seed=20261110, counts=None):
    """Write public inputs, independent source records, and separate evaluator files."""
    root = Path(root)
    counts = counts or {"train": 12, "dev": 4, "confirmation": 6}
    require(set(counts) == {"train", "dev", "confirmation"}, "invalid splits")
    require(
        all(type(n) is int and 1 <= n <= 100 for n in counts.values()),
        "invalid panel size",
    )
    require(not root.exists(), "preserve original synthetic panel")
    root.mkdir(parents=True)
    tasks, records, registry = [], {}, []
    labels = {s: [] for s in counts}
    for split_index, (split, count) in enumerate(counts.items()):
        for family in FAMILIES:
            for ordinal in range(count):
                nonce = sha([seed, split, family, ordinal])
                rng = random.Random(int(nonce, 16))
                colors, shapes = (
                    rng.sample(list(COLORS), 2),
                    rng.sample(list(SHAPES), 2),
                )
                cards = [{"color": c, "shape": s} for c in colors for s in shapes]
                rng.shuffle(cards)
                before = [dict(card) for card in cards]
                selected = rng.randrange(4)
                if family == "temporal":
                    cards[selected]["shape"] = rng.choice(
                        [s for s in SHAPES if s != cards[selected]["shape"]]
                    )
                grid = (
                    ([2, 2], [4, 1], [1, 4])[split_index]
                    if family == "layout"
                    else [2, 2]
                )
                boxes = []
                for _ in cards:
                    offset = (
                        rng.randint(2, 5) if family == "layout" else rng.randint(3, 5)
                    )
                    width = rng.randint(12, 16)
                    boxes.append(
                        (
                            offset,
                            offset,
                            min(22, offset + width),
                            min(22, offset + width),
                        )
                    )
                background = ((246, 246, 246), (227, 235, 242), (244, 232, 218))[
                    split_index
                ]
                target = cards[selected]
                if family == "temporal":
                    instruction = "Read the code for the item whose symbol changed between frames."
                    context = []
                elif family == "text_image":
                    instruction = f"Read the code for the {target['shape']} in the priority color."
                    context = [f"Priority color: {target['color']}."]
                else:
                    instruction = (
                        f"Read the code for the {target['color']} {target['shape']}."
                    )
                    context = []
                task_dir = root / nonce
                task_dir.mkdir()
                captures, paths = [], {}
                versions = [before, cards] if family == "temporal" else [cards]
                for frame, items in enumerate(versions):
                    image = _render(
                        items, grid, boxes, background, family == "occlusion"
                    )
                    buffer = io.BytesIO()
                    image.save(buffer, format="PNG")
                    raw = buffer.getvalue()
                    capture = dict(
                        sha256=sha(raw),
                        width=image.width,
                        height=image.height,
                        frame_index=frame,
                        timestamp_micros=frame * 100_000,
                    )
                    capture["capture_id"] = neutral_capture_id(capture)
                    captures.append(capture)
                    path = task_dir / f"frame-{frame}.png"
                    path.write_bytes(raw)
                    paths[capture["capture_id"]] = str(path.relative_to(root))
                packet = public_packet(
                    dict(
                        schema="perc1.semantic-task.v1",
                        task_id=nonce,
                        instruction=instruction,
                        captures=captures,
                        grid=grid,
                        candidates=grid_candidates(captures, grid),
                        context=context,
                        modalities={
                            "image": "present",
                            "video": "present" if family == "temporal" else "missing",
                            "source_text": "present",
                            "dom": "missing",
                            "ocr": "missing",
                        },
                        read_budget=2,
                    )
                )
                current = captures[-1]["capture_id"]
                source_paths, expected = {}, None
                for candidate in packet["candidates"]:
                    if candidate["capture_id"] != current:
                        continue
                    x, y, _, _ = candidate["rectangle"]
                    index = y // TILE * grid[0] + x // TILE
                    card = cards[index]
                    code = str(rng.randrange(10000, 100000))
                    raw = (
                        f"color={card['color']}\nshape={card['shape']}\n"
                        f"previous_shape={before[index]['shape']}\ncode={code}\n"
                    ).encode()
                    path = task_dir / f"{candidate['candidate_id']}.txt"
                    path.write_bytes(raw)
                    source_paths[candidate["candidate_id"]] = {
                        "path": str(path.relative_to(root)),
                        "sha256": sha(raw),
                    }
                    if index == selected:
                        expected = dict(
                            task_id=nonce,
                            candidate_id=candidate["candidate_id"],
                            answer=code,
                        )
                require(expected is not None, "missing evaluator target")
                tasks.append(dict(split=split, family=family, packet=packet))
                records[nonce] = dict(captures=paths, sources=source_paths)
                labels[split].append(expected)
                registry.append(
                    dict(
                        task_id=nonce,
                        split=split,
                        document_group=sha(["document", nonce]),
                        template_group=sha(
                            ["synthetic-style", split, family, grid, background]
                        ),
                        source_group=sha(["synthetic-generated-stream", seed, split]),
                        parent_task_id=None,
                    )
                )
    validate_split_registry(registry)
    panel = dict(
        schema="perc1.synthetic-semantic-panel.v1",
        seed=seed,
        counts=counts,
        tasks=tasks,
        records=records,
        registry=registry,
        scientific_qualified=False,
        independent_real_sources=False,
        scope="controlled synthetic renderer, grammar and generated source streams",
    )
    (root / "panel.json").write_bytes(canonical(panel) + b"\n")
    for split, values in labels.items():
        (root / f"{split}-targets.json").write_bytes(canonical(values) + b"\n")
    return panel
