"""Inventory exposed Ruff development artifacts without importing model packages."""

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import sysconfig

from receipt_reader import read_receipt, total
from storage_ledger import canonical, compression_gain, deployment, inventory


def save(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def local_sources(start):
    """Conservative static closure of same-directory Python imports, no execution."""
    pending, seen = [Path(start)], set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        for node in ast.walk(ast.parse(path.read_bytes())):
            names = (
                [node.module]
                if isinstance(node, ast.ImportFrom) and node.module
                else [n.name for n in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            for name in names:
                candidate = path.parent / (name.split(".")[0] + ".py")
                if candidate.is_file() and candidate not in seen:
                    pending.append(candidate)
    return sorted(seen)


def build(args):
    args.output.mkdir(parents=True, exist_ok=False)
    dev, repo = args.development.resolve(), args.repo.resolve()
    protocol = json.loads((dev / "protocol.json").read_bytes())
    old_summary = json.loads(
        (repo / "qa/memory-development-20261025/summary.json").read_bytes()
    )
    parts = {}

    def add(name, kind, paths):
        parts[name] = {"name": name, "kind": kind, "paths": [str(p) for p in paths]}

    add("source-observations", "source_evidence", [dev / "teaching"])
    add("source-fixture", "source", [dev / "original"])
    add("source-facts", "source", [dev / "training-spec.json"])
    add("source-policy", "protocol", [dev / "protocol.json"])
    add("source-diagnostic", "source_evidence", [dev / "original-diagnostic"])
    add("base", "base", [args.base.resolve()])
    checkpoints = [
        dev / "runs" / str(seed) / "checkpoint" for seed in protocol["seeds"]
    ]
    for seed, path in zip(protocol["seeds"], checkpoints):
        add("adapter-" + str(seed), "adapter", [path])
    owned = [Path(p) for entry in parts.values() for p in entry["paths"]]
    audit = [
        p
        for p in sorted(dev.rglob("*"))
        if p.is_file()
        and not any(p == root or p.is_relative_to(root) for root in owned)
    ]
    add("retained-research-evidence", "audit", audit)
    add("python-executable", "runtime", [Path(sys.executable).resolve()])
    stdlib = Path(sysconfig.get_path("stdlib")).resolve()
    add(
        "python-stdlib",
        "runtime",
        [p for p in sorted(stdlib.iterdir()) if p.name != "site-packages"],
    )
    add("model-environment-snapshot", "runtime", [args.site_packages.resolve()])
    add("ruff-tool", "tools", [args.ruff.resolve()])
    add(
        "model-source-closure",
        "runtime",
        local_sources(repo / "scripts/memory_cell/parametric_worker.py"),
    )
    add(
        "development-execution-code",
        "runtime",
        sorted((repo / "scripts/memory_cell_development").glob("*.py")),
    )
    add("accounting-load-code", "protocol", [Path(__file__).resolve().parent])
    add(
        "published-development-record",
        "audit",
        [repo / "qa/memory-development-20261025"],
    )
    record = inventory(list(parts.values()))
    actual = {r["path"]: r for r in record["files"]}
    expected = {
        str(dev / "original" / k): v
        for k, v in protocol["source"]["original_fixture_files"].items()
    }
    expected.update(
        {str(args.base.resolve() / k): v for k, v in protocol["base_inventory"].items()}
    )
    expected.update(
        {
            str(dev / "teaching" / fact["entity"].split()[0] / "observation.json"): {
                "sha256": fact["source_digest"]
            }
            for fact in protocol["facts"]
        }
    )
    expected.update(
        {
            str(
                dev / "runs" / str(row["seed"]) / "checkpoint/adapter_model.safetensors"
            ): {"bytes": row["checkpoint_bytes"], "sha256": row["checkpoint_sha256"]}
            for row in old_summary["training"]
        }
    )
    for path, fields in expected.items():
        if any(actual[path][key] != value for key, value in fields.items()):
            raise ValueError("historical immutable input drift: " + path)
    save(args.output / "inventory.json", record)
    common = [k for k in parts if k.startswith("source-")] + [
        "python-executable",
        "python-stdlib",
        "ruff-tool",
        "development-execution-code",
    ]
    memory = common + ["base", "model-environment-snapshot", "model-source-closure"]

    def placement(host, consumer, dependencies):
        return {"host": host, "consumer": consumer, "components": dependencies}

    views = {
        "retrieval_standalone": [placement("retrieval", "retrieval", common)],
        "memory_standalone": [
            placement("memory", "memory", memory + ["adapter-24041"])
        ],
        "three_cells_shared_host": [
            placement("shared", str(seed), memory + ["adapter-" + str(seed)])
            for seed in protocol["seeds"]
        ],
        "three_cells_independent_hosts": [
            placement(str(seed), str(seed), memory + ["adapter-" + str(seed)])
            for seed in protocol["seeds"]
        ],
        "research_retention_shared_host": [
            placement("shared", "whole-retained-study", list(parts))
        ],
    }
    views = {k: deployment(record, v) for k, v in views.items()}
    receipts = [
        read_receipt(
            path, format_name="procedural-v1", attempt_id=str(path.relative_to(dev))
        )
        for path in sorted(dev.rglob("receipt.json"))
    ]
    save(
        args.output / "historical-process-costs.json",
        {"receipts": receipts, "totals": total(receipts)},
    )
    quality = {
        "scope": "independent-future-tasks",
        "minimum_groups": 12,
        "complete_cost_closure": False,
        "rows": [],
    }
    report = {
        "schema": "hepta.memory.historical-cost-review.v2",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "development_only": True,
        "independent_future_groups": 0,
        "inventory_file": {
            "path": "inventory.json",
            "sha256": hashlib.sha256(
                (args.output / "inventory.json").read_bytes()
            ).hexdigest(),
        },
        "component_totals": record["by_component"],
        "all_declared_files": record["totals"],
        "measurement": record["inventory_measurement"],
        "deployments": views,
        "historical_process_cost": total(receipts),
        "original_actual_work": old_summary["actual_work"],
        "quality": {
            "historical_task_groups": 1,
            "adapter_task_successes": 3,
            "seeds_are_not_independent_tasks": True,
            "retrieval_task_successes": 1,
            "original_semantic_tests_each_success": 76,
            "gate": quality,
        },
        "compression": compression_gain(
            views["memory_standalone"]["totals"]["logical_file_bytes"],
            views["retrieval_standalone"]["totals"]["logical_file_bytes"],
            quality,
        ),
        "absence": {
            "persisted_router_bytes": 0,
            "persisted_index_bytes": 0,
            "reason": "one cell per seed; typed source operation intersection has no persisted search index",
            "production_source_journal_implemented_by_this_historical_experiment": False,
        },
        "unknown": {
            "whole_os_bytes": None,
            "dynamic_system_library_closure_bytes": None,
            "retrieval_resident_index_bytes": None,
            "energy_joules": None,
            "billing_usd": None,
            "whole_host_cpu_ns": None,
            "continuous_transient_storage_byte_ns": None,
        },
        "limits": [
            "Observed model site-packages snapshot includes later relay additions; not the historical minimum runtime.",
            "Python stdlib includes its retained cache; OS libraries, mounts, metadata, container and cache closure remain unmeasured.",
            "Declared operational views include source evidence and original fixture retention; audit workspaces are separately charged.",
            "Model package/base costs are absent from retrieval-only deployment. Only consumers with a real shared dependency share costs.",
            "Content equality is a potential dedup bound, not actual reclaimed storage or lossy model compression.",
            "Static Python import closure can overinclude code; dynamic import/dependency completeness is not asserted.",
            "Operational code sizes are the current recovered/published files; historical execution byte identity remains in the earlier publication bridge.",
            "Historical acquisition, earlier experiments and later evaluation are not silently included in this one development-run cost.",
        ],
    }
    save(args.output / "summary.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("repo", "development", "base", "site-packages", "ruff", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    result = build(parser.parse_args())
    print(
        json.dumps(
            {"compression": result["compression"], "measurement": result["measurement"]}
        )
    )
