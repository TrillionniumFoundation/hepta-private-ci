"""Pinned inputs and fixed development panels for the routing diagnosis."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

SEEDS = (1907, 2719, 4051)


def configure(repo):
    scripts = Path(repo).resolve() / "scripts"
    for name in (
        "memory_cell",
        "memory_cell_growth",
        "memory_cell_catalog",
        "memory_cell_hardening",
        "memory_cell_router",
        "memory_cell_codec",
        "memory_cell_population",
    ):
        sys.path.insert(0, str(scripts / name))


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024):
            result.update(block)
    return result.hexdigest()


def retain(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def identity(repo):
    repo = Path(repo).resolve()
    scripts = repo / "scripts"
    sources = {
        str(path.relative_to(repo)): file_sha(path)
        for directory in sorted(scripts.glob("memory_cell*"))
        if directory.is_dir()
        for path in sorted(directory.glob("*.py"))
    }
    diagnosis = {
        p.name: file_sha(p) for p in sorted(Path(__file__).parent.glob("*.py"))
    }
    tracked = set(
        subprocess.check_output(
            ["git", "ls-files", "--", "scripts"], cwd=repo, text=True
        ).splitlines()
    )
    return {
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True
        ).strip(),
        "tracked_worktree_clean": subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--"], cwd=repo, check=False
        ).returncode
        == 0,
        "untracked_repository_sources": sorted(set(sources) - tracked),
        "repository_sources": sources,
        "diagnosis_sources": diagnosis,
        "repository_source_sha256": digest(sources),
        "diagnosis_source_sha256": digest(diagnosis),
    }


def inputs(historical):
    """Retain model/version pins and historical costs, never old answer utilities."""
    result = {}
    for seed in SEEDS:
        directory = Path(historical).resolve() / f"seed-{seed}"
        selection_path = directory / "selection/precommitted-selection.json"
        training_path = directory / "training/result.json"
        selection = json.loads(selection_path.read_text())
        training = json.loads(training_path.read_text())
        declared = selection["versions"]
        if declared != training["versions"]:
            raise ValueError("historical model version disagreement")
        if set(declared) != {"parent", "single", "split"} or [
            len(declared[name]) for name in ("parent", "single", "split")
        ] != [1, 1, 2]:
            raise ValueError(
                "registered parent/single/two-child checkpoint set required"
            )
        versions = json.loads(json.dumps(declared))
        inventories, original_directories = {}, {}
        for arm, cells in versions.items():
            for slot, version in enumerate(cells):
                label = arm if len(cells) == 1 else f"{arm}-{slot}"
                path = directory / "training" / label
                if Path(version["directory"]).name != label:
                    raise ValueError(
                        "historical checkpoint label differs from registered relative layout"
                    )
                original_directories[f"{arm}-{slot}"] = version["directory"]
                version["directory"] = str(path)
                lineage = json.loads((path / "lineage.json").read_text())
                if (
                    file_sha(path / "lineage.json") != version["manifest_sha256"]
                    or lineage["scope"] != f"population-{seed}"
                    or lineage["roots"] != sorted(version["roots"])
                ):
                    raise ValueError("historical checkpoint version mismatch")
                inventories[f"{arm}-{slot}"] = {
                    p.name: {"sha256": file_sha(p), "bytes": p.stat().st_size}
                    for p in sorted(path.iterdir())
                    if p.is_file()
                }
        router = selection["router_receipt"]
        router_path = directory / "selection/learned-router.bin"
        if file_sha(router_path) != router["sha256"]:
            raise ValueError("historical original router changed")
        result[str(seed)] = {
            "versions": versions,
            "checkpoint_files": inventories,
            "historically_declared_checkpoint_directories": original_directories,
            "artifact_location_policy": "registered relative layout under explicit historical directory; original metadata unchanged",
            "original_router_path": str(router_path),
            "original_router_sha256": router["sha256"],
            "original_router_receipt": router,
            "selection_file_sha256": file_sha(selection_path),
            "training_file_sha256": file_sha(training_path),
            "dataset_file_sha256": file_sha(directory / "dataset.json"),
            "historical_report_files": {
                str(p.relative_to(directory)): file_sha(p)
                for p in sorted(directory.rglob("*.json"))
                if "training" not in p.relative_to(directory).parts
            },
            "historical_training_costs": training["costs"],
            "historical_selection_work": selection["source_work"],
            "historical_final_work": json.loads(
                (directory / "final/result.json").read_text()
            )["work"],
        }
    return result


def panels(seed):
    from population_fixtures import dataset, exact_baseline

    data = dataset(seed)
    rows, balanced = [], []
    for index, (fact, probe) in enumerate(
        zip(data["train_facts"], data["router_training"], strict=True)
    ):
        for wording, template in enumerate(data["train_templates"]):
            rows.append(
                dict(
                    probe,
                    probe_id=f"positive-{index:03d}-{wording}",
                    question=template.format(**fact),
                    reject=False,
                    wording=wording,
                )
            )
            if wording == index % 4:
                balanced.append(len(rows) - 1)
    for index, probe in enumerate(data["router_reject_training"]):
        operation = probe["operation"]
        if operation["kind"] == "semantic":
            entity, relation = operation["entity"], operation["relation"]
        elif operation["kind"] == "event_asof":
            entity, relation = (
                f"{operation['entity']} on day {operation['day']}",
                "location",
            )
        else:
            entity, relation = (
                f"{operation['rule']} with input {operation['input']}",
                "result",
            )
        answer, roots = exact_baseline(data["sources"], operation)
        if answer != "unknown" or roots:
            raise ValueError("negative operation is supported by this source ledger")
        for wording, template in enumerate(data["train_templates"]):
            rows.append(
                dict(
                    probe,
                    probe_id=f"negative-{index:03d}-{wording}",
                    value=answer,
                    source_roots=roots,
                    question=template.format(entity=entity, relation=relation),
                    reject=True,
                    wording=wording,
                )
            )
            if wording == (index // 4 + index % 4) % 4:
                balanced.append(len(rows) - 1)
    final = data["retention_final"] + data["transfer_final"] + data["ood_final"]
    if len(rows) != 304 or len(balanced) != 76 or len(final) != 120:
        raise ValueError("registered diagnosis panel sizes changed")
    for wording in range(4):
        subset = [rows[i] for i in balanced if rows[i]["wording"] == wording]
        if (sum(not r["reject"] for r in subset), sum(r["reject"] for r in subset)) != (
            16,
            3,
        ):
            raise ValueError("counterbalanced source panel class ratio changed")
    return data, rows, balanced, final


def protocol(repo, historical, model):
    return {
        "schema": "hepta.routing-diagnosis.protocol.v1",
        "phase": "causal_development_diagnosis",
        "repo": str(Path(repo).resolve()),
        "historical": str(Path(historical).resolve()),
        "model": str(Path(model).resolve()),
        "seeds": list(SEEDS),
        "held_decoder_weights_fixed": True,
        "old_reports_immutable": True,
        "old_evaluation_cohort_previously_exposed": True,
        "confirmation": False,
        "source_roots_per_seed": 44,
        "source_examples_per_seed": 64,
        "whole_dependency_groups_per_seed": 28,
        "crossed_source_questions_per_seed": 304,
        "counterbalanced_source_questions_per_seed": 76,
        "final_questions_per_seed": 120,
        "decoder_optimizer_updates": 0,
        "new_gradient_probes": 0,
        "new_router_fits_per_seed": 2,
        "router_updates_per_fit": 400,
        "decoder_queries_per_seed": 968,
        "decoder_queries_total": 2904,
        "parent_feature_forwards_per_seed": 424,
        "parent_feature_forwards_total": 1272,
        "router_optimizer_updates_total": 2400,
        "torch_threads": 2,
        "parent_feature_process_isolation": "one fresh short-lived process per seed; exit before final decoder readers",
        "feature_recipe": "verified-trained-parent-adapter-enabled-final-hidden-state-full-prompt-mean",
        "lexical_recipe": "source-only-unigram-bigram-tfidf-cosine-nearest-question",
        "dense_recipe": "actual-parent-hidden-feature-cosine-nearest-source-question",
        "lexical_tfidf": "raw term frequency; smoothed log((1+documents)/(1+document_frequency))+1; L2 normalize",
        "nearest_controls": "all 304 source questions; no tuned similarity threshold; lowest source index on ties",
        "balanced_selection": "positive wording=index%4; negative wording=(index//4+index%4)%4",
        "utility_target": "actual-expert-exact-output-and-source-capability; reject unsupported or both wrong; ties lowest slot for nearest controls",
        "router_configuration": "unchanged original router config; 512 dimensions, 400 updates, original thresholds",
        "policies": [
            "original",
            "full_cross",
            "balanced",
            "lexical",
            "dense",
            "metadata",
            "uniform",
            "oracle",
            "single",
        ],
        "final_routes_frozen_before_decoder_outputs": True,
        "live_dispatch_executed": False,
        "all_expert_reads_are_diagnostic": True,
        "equal_total_budget": False,
        "capacity_advantage_established": False,
        "scientific_phase3_closed": False,
        "general_memory_proven": False,
        "production_accepted": False,
    }


def verify_base(model):
    """Verify publisher bytes without prepare()'s adjacent-receipt write."""
    from prepare_parametric import FILES, REPOSITORY, REVISION

    directory = Path(model)
    if directory.is_symlink():
        raise ValueError("real base model directory required")
    names = set()
    for path in directory.rglob("*"):
        relative = path.relative_to(directory)
        if relative.parts[0] == ".cache":
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError("unexpected publisher model entry")
        names.add(relative.as_posix())
    if names != set(FILES):
        raise ValueError("base model publisher inventory mismatch")
    inventory = []
    for name, (size, expected) in sorted(FILES.items()):
        path = directory / name
        if path.stat().st_size != size:
            raise ValueError("base model publisher size mismatch")
        actual = hashlib.sha256()
        publisher = hashlib.sha256() if len(expected) == 64 else hashlib.sha1()
        if len(expected) == 40:
            publisher.update(f"blob {size}\0".encode())
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                actual.update(block)
                publisher.update(block)
        if publisher.hexdigest() != expected:
            raise ValueError("base model publisher digest mismatch")
        inventory.append({"path": name, "bytes": size, "sha256": actual.hexdigest()})
    return {
        "repository": REPOSITORY,
        "revision": REVISION,
        "files": inventory,
        "total_bytes": sum(row["bytes"] for row in inventory),
        "verification_read_only": True,
        "production_accepted": False,
    }
