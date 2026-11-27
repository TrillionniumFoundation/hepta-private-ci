"""Freeze source-only workflow corpus, real historical inputs and common ceilings."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from budget_ledger import GAUGES, METERS, digest
from cohort_contract import failure_excerpt, file_sha, load_registration, retain, seal
from workflow_records import extract, source_protocol


SOURCE_HEAD = "f8c9419df6ddeb36ff8b522a50219981fb8d9345"
BASE_HEAD = "429894ac8e0818102cfdea4ad47a56e4583b2902"
ARM_NAMES = ["single", "expanded", "retrieval", "data_split", "random_split"]


def common_budget():
    limits = dict(
        wall_ns=600 * 10**9,
        cpu_ns=1200 * 10**9,
        decoder_updates=128,
        router_updates=400,
        gradient_probes=8,
        train_tokens=32768,
        decoder_queries=64,
        feature_forwards=128,
        input_tokens=32768,
        output_tokens=4096,
        read_bytes=8 * 1024**3,
        write_bytes=2 * 1024**3,
        tx_bytes=1024**3,
        rx_bytes=1024**3,
        storage_byte_ns=4 * 1024**3 * 600 * 10**9,
    )
    unit = 10**30
    return dict(
        limits=limits,
        gauges=dict(
            retained_bytes=4 * 1024**3,
            private_bytes=32 * 1024**2,
            peak_rss_bytes=3 * 1024**3,
        ),
        prices={k: (unit + limits[k] - 1) // limits[k] for k in METERS},
        cost_limit=8 * unit,
        cost_unit="sum of preregistered resource-ceiling fractions; not currency or a provider invoice",
        equal_ceiling_not_equal_consumption=True,
        storage_includes_base_sources_indices_checkpoints_owner_recovery_and_receipts=True,
        unmeasured_costs=[
            "historical research acquisition CPU",
            "transient file byte-time",
            "network stack packet overhead",
        ],
        hard_wall_clock_kill=True,
        host_meter_and_admission_not_an_adversarial_OS_sandbox=True,
        full_total_cost_qualification=False,
    )


def source_corpus(checkout):
    checkout = Path(checkout)
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout, text=True
    ).strip()
    if head != SOURCE_HEAD:
        raise ValueError("only the pre-cutoff original main source is admitted")
    docs = []
    for path in sorted((checkout / ".github/workflows").iterdir()):
        if path.suffix not in (".yml", ".yaml"):
            continue
        text = path.read_text()
        relative = path.relative_to(checkout).as_posix()
        blob = subprocess.check_output(
            ["git", "rev-parse", f"HEAD:{relative}"], cwd=checkout, text=True
        ).strip()
        raw = text.encode()
        if hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() != blob:
            raise ValueError("historical workflow differs from its Git object")
        docs.append(
            dict(
                doc_id=digest([SOURCE_HEAD, relative]),
                group_id="historical-workflow:" + relative,
                path=relative,
                text=text,
                available_at="2026-10-16T00:03:16Z",
                origin=f"https://github.com/TrillionniumFoundation/hepta-private-ci/blob/{SOURCE_HEAD}/{relative}",
                source_sha256=hashlib.sha256(raw).hexdigest(),
            )
        )
    return docs


def actual_inputs(root):
    """Curated before policy execution; these are not prospectively unseen tasks."""
    definitions = [
        (
            "task-head-clippy",
            "rust-toolchain-component",
            "raw/task_failure_log.log",
            [".github/workflows/hepta-research-task-head-owner.yml"],
            "2026-10-24T02:26:20Z",
            "dfa467b5b961f79e25ef6860500ee42607ca2642",
            "d1619f1d2dd433f958d76143309011c73b4c5cf5",
            "original hosted failed/success same-workflow logs; original log already contains the repair hint",
        ),
        (
            "counterfactual-lint",
            "python-lint-contract",
            "raw/lint_original_log.log",
            ["experiments/multimodal_output_portfolio/v4/counterfactual_audit.py"],
            "2026-10-23T23:26:31Z",
            "b168b8d05959b4e9a4956fc3122364f2b59cc1fe",
            "bfe1bf6369055b614e06d15a7b05f15df695898c",
            "published original local Ruff failure and exact-head hosted 76-test pass; hosted success is not itself a Ruff invocation",
        ),
        (
            "execution-lock",
            "cargo-lock-ambiguous-dependency",
            "raw/lock_original_log.log",
            ["codex-rs/Cargo.lock", "codex-rs/execution-core/Cargo.toml"],
            "2026-10-23T15:50:05Z",
            "46dc890e40cf5bb7057012e4de756eab73c21351",
            "2f7ae91c4176896d0b9caf9aea75ed3e030a81f8",
            "published original local locked-build failure; later broader source success cannot transfer to the one-line fix",
        ),
        (
            "media-false-green",
            "codec-zero-execution-acceptance",
            "raw/codec_original_log.log",
            ["qualification/ndu-dmgp-shadow"],
            "2026-10-23T22:26:43Z",
            "a88f2832f2a1a4d3734c1c88f76977dcc9b98ff1",
            "d847bb289159d8857f53cdcf5de79636e18df105",
            "original hosted false green (21 skips); exact-source local 21-codec pass, dedicated hosted success not established",
        ),
    ]
    requests, metadata = [], []
    for task, group, relative, paths, observed, before, after, boundary in definitions:
        path = root / relative
        raw = path.read_text()
        requests.append(dict(task_id=task, text=failure_excerpt(raw), paths=paths))
        metadata.append(
            dict(
                task_id=task,
                root_cause_group=group,
                classification="retrospective_time_holdout",
                observed_at=observed,
                original_input_path=str(path.resolve()),
                original_input_sha256=file_sha(path),
                failed_source_sha=before,
                fixed_source_sha=after,
                evidence_boundary=boundary,
                human_repair_exposure_before_model_execution=True,
                statistical_independence_established=False,
                new_method_repair_execution=False,
            )
        )
    return requests, metadata


def prepare(root, output):
    root, output = Path(root), Path(output)
    registration, registration_receipt = load_registration(root)
    documents = source_corpus(root / "source-main")
    requests, metadata = actual_inputs(root)
    fixture_paths = list(
        sorted((root / "task-fixtures/lint-original").rglob("*.py"))
    ) + [root / "ruff-runtime/bin/ruff"]
    fixture_files = {str(p.relative_to(root)): file_sha(p) for p in fixture_paths}
    protocol = dict(
        schema="hepta.memory-budget.study.v1",
        implementation_base=BASE_HEAD,
        source_head=SOURCE_HEAD,
        source_cutoff="2026-10-23T00:00:00Z",
        prospective_registration_sha256=registration_receipt["protocol_sha256"],
        source_only_retrieval_config=dict(k1=1.2, b=0.75, path_boost=1.5, top_k=5),
        arms=ARM_NAMES,
        common_budget=common_budget(),
        source_command_recipe=source_protocol(),
        task_fixture_files=fixture_files,
        task_action_schema="one direct Ruff check command; only --fix/--unsafe-fixes/--no-cache and confined relative paths; original immutable Ruff gate plus all 76 original tests required",
        task_execution_coverage="only the original Python lint closure is reconstructed; other 3 remain in denominator as unavailable original environments",
        model_arm_order=[
            "shared_parent",
            "single",
            "expanded",
            "data_split",
            "random_split",
        ],
        physical_decoder_update_ceiling=416,
        standalone_decoder_update_ceiling=128,
        shared_parent_accounting="physical 32 once; standalone dependency closure allocates its original receipt to every neural arm",
        model_seed=2718,
        random_partition_seed=4731,
        model_lane_authorization_required=True,
        model_updates_executed_at_preparation=0,
        capacity_views=dict(
            fixed_total_capacity={
                "adapter_values_ceiling": 460800,
                "router_values_ceiling": 1539,
            },
            priced_growth={
                "initial_adapter_values": 230400,
                "maximum_executed_adapter_values": 460800,
            },
        ),
        continuous_load=dict(
            repetitions_per_task=7,
            reopen_every=4,
            repeated_queries_are_independent_tasks=False,
        ),
        end_to_end_neural_arm_timeout_seconds=600,
        model_requests_per_arm=dict(
            adapter=20, base_control=8, shuffled_control=8, continued_load=28, total=64
        ),
        corpus_scale_levels=[16, 32, 64, len(documents)],
        model_outcome_metric="requires actual original-task execution; diagnostic labels or retrieval relevance alone do not qualify",
        source_exact_compression_controls=["raw-json", "zlib-9", "lzma-6"],
        final_gold_policy="scorer-only directory; frozen policy outputs precede score opening",
        unresolved_and_budget_exhausted_remain_in_denominator=True,
        no_post_final_tuning=True,
        blind_confirmation=False,
        independent_natural_groups_established=False,
        preparation_scope="four source-backed historical task inputs; complete benchmark execution gate remains separate",
    )
    paths = [p for p in sorted(root.glob("*.py")) if not p.name.startswith("test_")]
    implementation = root.parent / "hepta-memory-next-20261024"
    paths += sorted(
        p
        for d in (implementation / "scripts").glob("memory_cell*")
        for p in d.glob("*.py")
    )
    external = {str(root / relative): sha for relative, sha in fixture_files.items()}
    external.update(
        {m["original_input_path"]: m["original_input_sha256"] for m in metadata}
    )
    receipt = seal(
        output,
        protocol=protocol,
        source_documents=documents,
        requests=requests,
        task_metadata=metadata,
        code_paths=paths,
        external_inputs=external,
    )
    retain(output / "source-command-records.json", extract(documents))
    # This companion is independently bound because seal.json is immutable.
    retain(
        output / "source-command-receipt.json",
        dict(
            records_sha256=file_sha(output / "source-command-records.json"),
            source_documents_sha256=file_sha(output / "source-documents.json"),
            recipe_sha256=digest(source_protocol()),
        ),
    )
    return dict(
        output=str(output),
        source_documents=len(documents),
        source_bytes=sum(len(x["text"].encode()) for x in documents),
        task_inputs=len(requests),
        prospective_task_results=0,
        seal_sha256=file_sha(output / "seal.json"),
        receipt=receipt,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.root, args.output), sort_keys=True))
