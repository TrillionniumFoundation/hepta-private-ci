"""Small, costed source writes and ordinary checkpoint reloads for CI memory."""

import gc
from pathlib import Path
import time

import numpy as np
import torch

from domain_data import TRAIN_TEMPLATES, source_group_ids, write_json
from experience_inference import frozen_adapter_mode
from parametric_model import SourceMemoryCell
from population_partition import source_gradient_sketches
from population_transfer import expand_verified_parent


def grouped_partition(sketches, groups, seed, randomized=False):
    """Two nonempty whole-group shards; odd cohorts need not be equal-sized."""
    matrix = np.asarray(sketches, dtype=np.float64)
    if (
        matrix.ndim != 2
        or not 2 <= len(matrix) <= 64
        or len(groups) != len(matrix)
        or matrix.shape[1] < 2
        or not np.isfinite(matrix).all()
        or any(type(group) is not str or not group for group in groups)
    ):
        raise ValueError("bounded finite sketches and matching source groups required")
    names = sorted(set(groups))
    if len(names) < 2:
        raise ValueError("fission requires two independent source groups")
    indices = [[i for i, name in enumerate(groups) if name == group] for group in names]
    rng = np.random.default_rng(seed)
    if randomized:
        scores = rng.normal(size=len(names))
    else:
        vectors = np.array([matrix[part].mean(axis=0) for part in indices])
        if not np.any(vectors):
            raise ValueError("gradient partition requires a nonzero measured signal")
        vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
        first = int(rng.integers(len(names)))
        second = int(np.argmin(vectors @ vectors[first]))
        scores = vectors @ vectors[second] - vectors @ vectors[first]
    states = {0: (0.0, ())}
    for i, part in enumerate(indices):
        for total, (score, chosen) in list(states.items()):
            new = total + len(part)
            candidate = (score + float(scores[i]) * len(part), chosen + (i,))
            if new not in states or candidate[0] > states[new][0]:
                states[new] = candidate
    size = min(
        (n for n in states if 0 < n < len(groups)),
        key=lambda n: (abs(2 * n - len(groups)), n),
    )
    selected = {names[i] for i in states[size][1]}
    slots = [int(group in selected) for group in groups]
    return dict(
        slots=slots,
        sizes=[slots.count(0), slots.count(1)],
        group_slots={name: int(name in selected) for name in names},
        method="random_balanced_groups"
        if randomized
        else "source_gradient_cosine_groups",
    )


def load_cell(model, version, scope, allowed):
    cell = SourceMemoryCell(model, rank=version["rank"], seed=version["seed"])
    cell.load(
        Path(version["directory"]),
        expected_manifest_sha256=version["manifest_sha256"],
        scope=scope,
        allowed_roots=set(allowed),
        revoked=set(),
    )
    return cell


def train(model, cases, scope, output, seed, visits):
    groups = source_group_ids(cases)
    if len(set(groups)) < 2:
        raise ValueError("fission requires two independent source groups")
    output = Path(output)
    output.mkdir()
    facts = [
        dict(
            scope=scope,
            entity=c["symptom"],
            relation="repair",
            value=c["repair_id"],
            source_digest=c["source_digest"],
        )
        for c in cases
    ]
    allowed = {f["source_digest"] for f in facts}
    versions, receipts = {}, {}

    def save(cell, name, receipt, rank):
        destination = output / name
        manifest = cell.save(destination)
        write_json(output / (name + ".write.json"), receipt)
        receipts[name] = receipt
        return dict(
            directory=str(destination.resolve()),
            manifest_sha256=manifest,
            rank=rank,
            seed=seed,
            roots=sorted(cell.reader.roots),
        )

    parent = SourceMemoryCell(model, rank=4, seed=seed)
    parent.reset(scope)
    parent_facts = facts[: max(1, len(facts) // 2)]
    receipt = parent.fit_sources(
        parent_facts, len(parent_facts) * visits, 0.001, TRAIN_TEMPLATES
    )
    pv = save(parent, "parent", receipt, 4)
    versions["parent"] = [pv]
    parent.load(
        Path(pv["directory"]),
        expected_manifest_sha256=pv["manifest_sha256"],
        scope=scope,
        allowed_roots=allowed,
        revoked=set(),
    )
    sketch = source_gradient_sketches(parent, facts, TRAIN_TEMPLATES[0], width=32)
    write_json(output / "gradient-sketches.json", sketch)
    partitions = {
        name: grouped_partition(
            sketch["sketches"], groups, seed, name == "random_split"
        )
        for name in ("split", "random_split")
    }
    write_json(output / "partitions.json", partitions)
    expanded = SourceMemoryCell(model, rank=8, seed=seed)
    expanded.reset(scope)
    initial = output / "expanded-parent"
    derivation = expand_verified_parent(
        parent, expanded, initial, parent_manifest_sha256=pv["manifest_sha256"]
    )
    write_json(output / "rank-expansion.json", derivation)
    expanded.load(
        initial,
        expected_manifest_sha256=derivation["manifest_sha256"],
        scope=scope,
        allowed_roots=allowed,
        revoked=set(),
    )
    del parent
    gc.collect()
    receipt = expanded.fit_sources(facts, len(facts) * visits, 0.001, TRAIN_TEMPLATES)
    versions["expanded"] = [save(expanded, "expanded", receipt, 8)]
    del expanded
    gc.collect()
    for arm in ("single", "split", "random_split"):
        versions[arm] = []
        shards = (
            [list(range(len(facts)))]
            if arm == "single"
            else [
                [i for i, slot in enumerate(partitions[arm]["slots"]) if slot == s]
                for s in (0, 1)
            ]
        )
        for slot, indices in enumerate(shards):
            cell = load_cell(model, pv, scope, allowed)
            subset = [facts[i] for i in indices]
            receipt = cell.fit_sources(
                subset, len(subset) * visits, 0.001, TRAIN_TEMPLATES
            )
            versions[arm].append(save(cell, f"{arm}-{slot}", receipt, 4))
            del cell
            gc.collect()
    costs = {}
    for arm, vs in versions.items():
        names = [Path(v["directory"]).name for v in vs]
        costs[arm] = {
            key: sum(receipts[name][key] for name in names)
            for key in (
                "steps",
                "input_tokens",
                "supervised_tokens",
                "actual_model_forwards",
                "parameter_bytes",
                "gradient_bytes",
                "optimizer_tensor_bytes",
                "seconds",
            )
        }
        costs[arm]["checkpoint_bytes"] = sum(
            p.stat().st_size
            for v in vs
            for p in Path(v["directory"]).rglob("*")
            if p.is_file()
        )
        costs[arm]["sequential_optimizer_peak_bytes"] = max(
            receipts[name]["optimizer_tensor_bytes"] for name in names
        )
        if arm != "parent" and any(
            set(receipts[name]["fact_visits"]) != {visits}
            or set(receipts[name]["example_visits"]) != {visits // len(TRAIN_TEMPLATES)}
            for name in names
        ):
            raise ValueError("candidate source exposure mismatch")
    for arm in ("split", "random_split"):
        for key in ("steps", "input_tokens", "parameter_bytes"):
            if costs[arm][key] != costs["expanded"][key]:
                raise ValueError("matched expanded/split budget mismatch")
    report = dict(
        versions=versions,
        costs=costs,
        partitions=partitions,
        actual_optimizer_updates=sum(r["steps"] for r in receipts.values()),
        gradient_probe=sketch,
        equal_total_system_cost=False,
    )
    write_json(output / "training.json", report)
    return report


def read(model, version, scope, allowed, questions):
    if not questions:
        return []
    cell = load_cell(model, version, scope, allowed)
    outputs = []
    for offset in range(0, len(questions), 256):
        outputs.extend(cell.generate(questions[offset : offset + 256]))
    del cell
    gc.collect()
    return outputs


def encode(model, version, scope, allowed, questions):
    """Execute frozen base forwards; no source answers enter feature extraction."""
    cell = load_cell(model, version, scope, allowed)
    rows, tokens, start = [], 0, time.perf_counter()
    for question in questions:
        ids = cell.prompt_ids(question)
        x = torch.tensor([ids], dtype=torch.long)
        with frozen_adapter_mode(cell.reader.model, enabled=False):
            result = cell.reader.model(
                input_ids=x,
                attention_mask=torch.ones_like(x),
                output_hidden_states=True,
                use_cache=False,
            )
        rows.append(result.hidden_states[-1][0].float().mean(dim=0).cpu().numpy())
        tokens += len(ids)
    del cell
    gc.collect()
    return np.stack(rows), dict(
        model_forwards=len(questions),
        input_tokens=tokens,
        seconds=time.perf_counter() - start,
    )
