"""A common learned parent, matched adapter budgets and learned fission groups."""

import gc
import json
from pathlib import Path

from native import digest
from grounded_protocol import completion_ids
from parametric_model import SourceMemoryCell
from pretrained import file_inventory
from population_partition import balanced_partition, source_gradient_sketches
from population_transfer import expand_verified_parent


def _version(directory, manifest, rank, seed):
    lineage = json.loads((directory / "lineage.json").read_text())
    return {
        "directory": str(directory.resolve()),
        "manifest_sha256": manifest,
        "roots": lineage["roots"],
        "rank": rank,
        "seed": seed,
    }


def _load(cell, version, scope):
    cell.load(
        Path(version["directory"]),
        expected_manifest_sha256=version["manifest_sha256"],
        scope=scope,
        allowed_roots=set(version["roots"]),
        revoked=set(),
    )


def train_population(model, data, output, *, seed, write_json):
    """Fixed source-only optimizer work; final probe values are never read here."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    facts, templates, scope = (
        data["train_facts"],
        data["train_templates"],
        data["scope"],
    )
    if len(facts) != 64 or len(data["parent_facts"]) != 16 or len(templates) != 4:
        raise ValueError(
            "registered 64-example / 16-parent / four-template protocol required"
        )
    model_seed = seed + 10000
    parent = SourceMemoryCell(model, rank=4, seed=model_seed)
    parent.reset(scope)
    lengths, example_tokens = [], []
    # Template disjointness is checked using actual pretrained tokenizer IDs.
    for index, fact in enumerate(facts):
        queries = [
            t.format(entity=fact["entity"], relation=fact["relation"])
            for t in templates
        ]
        queries.extend(
            [
                data["source_selection"][index]["question"],
                data["retention_final"][index]["question"],
            ]
        )
        tokens = [tuple(parent.prompt_ids(q)) for q in queries]
        if len(set(tokens)) != len(tokens):
            raise ValueError(
                "training, selection and final wording collided after tokenization"
            )
        lengths.extend(map(len, tokens))
        for template_index, prompt in enumerate(tokens[: len(templates)]):
            ids, labels = completion_ids(
                parent.reader.tokenizer,
                list(prompt),
                fact["value"],
                maximum=min(256, parent.reader.model.config.max_position_embeddings),
            )
            example_tokens.append(
                {
                    "source_index": index,
                    "template_index": template_index,
                    "prompt_tokens": len(prompt),
                    "input_tokens": len(ids),
                    "supervised_tokens": sum(label != -100 for label in labels),
                }
            )
    write_json(
        output / "tokenization-admission.json",
        {
            "all_wordings_token_distinct_per_source": True,
            "prompt_min_tokens": min(lengths),
            "prompt_max_tokens": max(lengths),
            "truncation": False,
            "gold_used_for_tokenization": False,
            "source_example_tokens": example_tokens,
        },
    )
    print(
        json.dumps({"seed": seed, "stage": "common-parent", "updates": 512}), flush=True
    )
    receipt = parent.fit_sources(data["parent_facts"], 512, 0.001, templates)
    write_json(output / "parent.write.json", receipt)
    directory = output / "parent"
    parent_version = _version(directory, parent.save(directory), 4, model_seed)
    parent_inventory = file_inventory(directory)
    _load(parent, parent_version, scope)
    print(
        json.dumps({"seed": seed, "stage": "source-gradient-partition", "sources": 64}),
        flush=True,
    )
    sketch = source_gradient_sketches(parent, facts, templates[0], width=32)
    partition = balanced_partition(
        sketch["sketches"], data["partition_groups"], seed=seed
    )
    write_json(output / "gradient-sketches.json", sketch)
    write_json(output / "learned-partition.json", partition)
    if partition["cluster_sizes"] != [32, 32]:
        raise ValueError("registered balanced expert source exposure changed")
    single = SourceMemoryCell(model, rank=8, seed=model_seed)
    single.reset(scope)
    expanded_dir = output / "expanded-parent"
    expansion = expand_verified_parent(
        parent,
        single,
        expanded_dir,
        parent_manifest_sha256=parent_version["manifest_sha256"],
    )
    write_json(output / "rank-expansion.json", expansion)
    expanded_version = _version(
        expanded_dir, expansion["manifest_sha256"], 8, model_seed
    )
    del parent
    gc.collect()
    _load(single, expanded_version, scope)
    print(json.dumps({"seed": seed, "stage": "single", "updates": 1024}), flush=True)
    single_receipt = single.fit_sources(facts, 1024, 0.001, templates)
    write_json(output / "single.write.json", single_receipt)
    single_dir = output / "single"
    single_version = _version(single_dir, single.save(single_dir), 8, model_seed)
    del single
    gc.collect()
    child = SourceMemoryCell(model, rank=4, seed=model_seed)
    versions, receipts = [], []
    for slot in (0, 1):
        _load(child, parent_version, scope)
        indices = [i for i, value in enumerate(partition["slots"]) if value == slot]
        subset = [facts[i] for i in indices]
        print(
            json.dumps({"seed": seed, "stage": f"split-{slot}", "updates": 512}),
            flush=True,
        )
        measured = child.fit_sources(subset, 512, 0.001, templates)
        if measured["inherited_roots"] != sorted(parent_version["roots"]):
            raise ValueError("literal child lost parent ancestry")
        # Source-index mapping is separate from the immutable writer receipt.
        write_json(output / f"split-{slot}.write.json", measured)
        write_json(output / f"split-{slot}.mapping.json", {"source_indices": indices})
        child_dir = output / f"split-{slot}"
        versions.append(_version(child_dir, child.save(child_dir), 4, model_seed))
        receipts.append(measured)
    del child
    gc.collect()
    all_receipts = [single_receipt, *receipts]
    if (
        any(set(r["fact_visits"]) != {16} for r in all_receipts)
        or single_receipt["parameter_bytes"]
        != sum(r["parameter_bytes"] for r in receipts)
        or single_receipt["input_tokens"] != sum(r["input_tokens"] for r in receipts)
        or file_inventory(directory) != parent_inventory
    ):
        raise ValueError(
            "matched exposure/adapter-budget/input-tokens or parent immutability failed"
        )
    snapshots = [parent_version, expanded_version, single_version, *versions]
    report = {
        "schema": "hepta.parametric-memory.population-training.v1",
        "seed": seed,
        "scope": scope,
        "source_ledger_sha256": data["sources_sha256"],
        "train_facts_sha256": digest(facts),
        "versions": {
            "parent": [parent_version],
            "single": [single_version],
            "split": versions,
        },
        "expanded_parent": expanded_version,
        "partition": partition,
        "costs": {
            "common_parent_updates": 512,
            "candidate_optimizer_updates": 2048,
            "total_optimizer_updates": 2560,
            "common_parent_training_seconds": receipt["seconds"],
            "candidate_training_seconds": sum(r["seconds"] for r in all_receipts),
            "common_parent_input_tokens": receipt["input_tokens"],
            "candidate_input_tokens": sum(r["input_tokens"] for r in all_receipts),
            "gradient_probe_seconds": sketch["seconds"],
            "gradient_probe_input_tokens": sketch["input_tokens"],
            "gradient_probe_forwards_backwards": 64,
            "single_private_parameter_bytes": single_receipt["parameter_bytes"],
            "split_private_parameter_bytes": sum(
                r["parameter_bytes"] for r in receipts
            ),
            "same_adapter_budget": True,
            "router_overhead_excluded_from_adapter_budget": True,
            "all_retained_snapshot_bytes": sum(
                item["bytes"]
                for v in snapshots
                for item in file_inventory(Path(v["directory"])).values()
            ),
        },
        "parent_inventory_before_and_after": parent_inventory,
        "parent_unchanged": True,
        "partition_uses_source_gradients_not_type_ids": True,
        "source_dependency_groups_preserved": True,
        "all_sources_have_sixteen_candidate_visits": True,
        "final_labels_used_for_training": False,
        "production_accepted": False,
    }
    write_json(output / "result.json", report)
    return report
