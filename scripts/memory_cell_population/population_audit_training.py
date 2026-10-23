"""Independent common-parent, rank-expansion and optimizer-exposure audit."""

from collections import Counter
import math
from pathlib import Path
import random

from population_audit_artifacts import (
    ARMS,
    _checkpoint,
    _digest,
    _hash,
    _json,
    _read,
    _require,
    _same,
)


def _write_receipt(
    receipt, facts, templates, steps, seed, checkpoint, inherited, parent, token_rows
):
    count = len(facts) * len(templates)
    schedule = []
    for epoch in range((steps + count - 1) // count):
        order = list(range(count))
        random.Random(seed + 10000 + epoch).shuffle(order)
        schedule.extend(order[: steps - len(schedule)])
    visits = Counter(schedule)
    roots = sorted({f["source_digest"] for f in facts})
    expected = {
        "steps": steps,
        "objective": "completion_ce",
        "writer_seed": seed + 10000,
        "schedule": "seeded_epoch_permutation_v1",
        "schedule_indices": schedule,
        "schedule_sha256": _digest(schedule),
        "example_visits": [visits[i] for i in range(count)],
        "fact_visits": [
            sum(visits[4 * i + j] for j in range(4)) for i in range(len(facts))
        ],
        "source_facts_sha256": _digest(facts),
        "templates_sha256": _digest(templates),
        "source_digests": [f["source_digest"] for f in facts],
        "inherited_roots": inherited,
        "accessed_roots": roots,
        "roots": sorted(set(roots) | set(inherited)),
        "actual_model_forwards": steps,
        "learning_rate": 0.001,
        "parameter_bytes": checkpoint["private_bytes"],
        "trainable_parameters": checkpoint["private_bytes"] // 4,
        "gradient_bytes": checkpoint["private_bytes"],
        "base_unchanged": True,
        "evaluation_targets_used": False,
        "production_accepted": False,
        "learned_parent_manifest_sha256": parent,
        "negative_fact_visits": [0] * len(facts),
        "negative_fact_indices": [],
    }
    for key, value in expected.items():
        _same(receipt[key], value, f"source writer {key}")
    _same(checkpoint["manifest"]["training"], receipt, "saved raw training receipt")
    _require(
        len(receipt["losses"]) == steps
        and all(math.isfinite(v) and v >= 0 for v in receipt["losses"])
        and receipt["adapter_delta_squared_norm"] > 0,
        "finite real optimization evidence",
    )
    if token_rows is not None:
        _same(
            receipt["input_tokens"],
            sum(token_rows[i]["input_tokens"] for i in schedule),
            "measured source input token accounting",
        )
        _same(
            receipt["supervised_tokens"],
            sum(token_rows[i]["supervised_tokens"] for i in schedule),
            "measured supervised token accounting",
        )


def _training(directory, data, report):
    _same(_json(directory / "training/result.json"), report, "training report copy")
    versions = report["versions"]
    _require(
        set(versions) == set(ARMS) and [len(versions[a]) for a in ARMS] == [1, 1, 2],
        "registered arms",
    )
    _require(
        [v["rank"] for a in ARMS for v in versions[a]] == [4, 8, 4, 4],
        "registered ranks",
    )
    points = {arm: [_checkpoint(v) for v in versions[arm]] for arm in ARMS}
    parent, single = points["parent"][0], points["single"][0]
    expanded = _checkpoint(report["expanded_parent"])
    _require(
        set(parent["tensors"]) == set(expanded["tensors"]),
        "rank expansion preserves target modules",
    )
    _require(
        parent["manifest"]["training"]["initialization"] == "frozen_base"
        and parent["manifest"]["training"]["inherited_roots"] == [],
        "new rank-four parent",
    )
    _require(
        expanded["manifest"]["roots"] == parent["manifest"]["roots"],
        "expansion preserves all source roots",
    )
    for name, (shape, payload) in parent["tensors"].items():
        new_shape, new = expanded["tensors"][name]
        if ".lora_A." in name:
            _require(
                new_shape == [shape[0] * 2, shape[1]]
                and new[: len(payload)] == payload,
                "expansion copies every parent A row",
            )
        else:
            _require(
                ".lora_B." in name and new_shape == [shape[0], shape[1] * 2],
                "expansion B layout",
            )
            width = shape[1] * 4
            for row in range(shape[0]):
                _require(
                    new[row * width * 2 : (row * 2 + 1) * width]
                    == payload[row * width : (row + 1) * width]
                    and new[(row * 2 + 1) * width : (row + 1) * width * 2]
                    == bytes(width),
                    "expansion copies old B and zeroes new B",
                )
    derivation = expanded["manifest"]["training"]
    _require(
        derivation["optimizer_updates"] == 0
        and derivation["parent_manifest_sha256"]
        == versions["parent"][0]["manifest_sha256"],
        "zero-update verified expansion",
    )
    partition = _json(directory / "training/learned-partition.json")
    _same(partition, report["partition"], "raw partition report")
    sketch = _json(directory / "training/gradient-sketches.json")
    slots, groups, facts = (
        partition["slots"],
        data["partition_groups"],
        data["train_facts"],
    )
    _require(
        len(slots) == 64
        and slots.count(0) == slots.count(1) == 32
        and all(
            len({slots[i] for i, g in enumerate(groups) if g == group}) == 1
            for group in set(groups)
        ),
        "balanced intact history/program groups",
    )
    _require(
        partition["sketches_sha256"] == _digest(sketch["sketches"])
        and partition["groups_sha256"] == _digest(groups)
        and partition["memory_family_labels_used"] is False
        and partition["final_queries_used"] is False,
        "source-only partition evidence",
    )
    _require(
        sketch["optimizer_updates"] == 0
        and sketch["model_forwards_and_backwards"] == 64
        and sketch["adapter_before_after_sha256"] == parent["state"]
        and sketch["source_facts_sha256"] == _digest(facts)
        and len(sketch["sketches"]) == 64
        and all(
            len(row) == 32 and all(math.isfinite(v) for v in row)
            for row in sketch["sketches"]
        ),
        "actual source-gradient probe accounting",
    )
    tokenization = _json(directory / "training/tokenization-admission.json")
    tokens = tokenization.get("source_example_tokens")
    _require(
        tokens is not None and len(tokens) == 256,
        "raw tokenized source lengths required",
    )
    template_tokens = tokens
    _require(
        [(r["source_index"], r["template_index"]) for r in tokens]
        == [(i, j) for i in range(64) for j in range(4)],
        "token measurement fact/template alignment",
    )
    _require(
        sketch["input_tokens"] == sum(tokens[4 * i]["input_tokens"] for i in range(64)),
        "gradient-probe measured token charge",
    )
    receipts = {}
    for label, indices, point, steps, inherited, parent_hash, start in (
        ("parent", list(range(16)), parent, 512, [], None, None),
        (
            "single",
            list(range(64)),
            single,
            1024,
            parent["manifest"]["roots"],
            report["expanded_parent"]["manifest_sha256"],
            expanded["state"],
        ),
        *(
            (
                f"split-{slot}",
                [i for i, value in enumerate(slots) if value == slot],
                points["split"][slot],
                512,
                parent["manifest"]["roots"],
                versions["parent"][0]["manifest_sha256"],
                parent["state"],
            )
            for slot in (0, 1)
        ),
    ):
        receipt = _json(directory / f"training/{label}.write.json")
        _write_receipt(
            receipt,
            [facts[i] for i in indices],
            data["train_templates"],
            steps,
            data["seed"],
            point,
            inherited,
            parent_hash,
            [template_tokens[4 * i + j] for i in indices for j in range(4)],
        )
        if start is not None:
            _require(
                receipt["starting_adapter_sha256"] == start
                and receipt["initialization"] == "verified_adapter",
                "literal verified-parent initialization",
            )
        receipts[label] = receipt
    _require(
        single["private_bytes"] == sum(p["private_bytes"] for p in points["split"]),
        "actual matched tensor budget",
    )
    _require(
        receipts["single"]["input_tokens"]
        == sum(receipts[f"split-{i}"]["input_tokens"] for i in (0, 1)),
        "matched candidate input tokens",
    )
    _require(
        sum(r["steps"] for r in receipts.values()) == 2560,
        "all measured parent and candidate updates charged",
    )
    _same(
        report["parent_inventory_before_and_after"],
        {
            p.name: {"bytes": p.stat().st_size, "sha256": _hash(_read(p))}
            for p in Path(versions["parent"][0]["directory"]).iterdir()
            if p.is_file()
        },
        "parent retained unchanged",
    )
    return points, receipts
