"""Register fresh synthetic authority and exact token panels without a model."""

import argparse
from dataclasses import asdict
from pathlib import Path
import time

from fitting_common import (
    BASE_IDENTITY,
    base_inventory,
    digest,
    file_digest,
    read_json,
    require,
    retain,
    resource_state,
    runtime_versions,
    sources,
    two_cpus,
)

SYSTEM = (
    "Answer using stored memory in the specified scope. Return only the value. "
    "If unknown, say 'unknown'. Do not cite sources."
)


def prepare(output, screen, base):
    from memory_service import MemoryService
    from tokenizers import Tokenizer

    output, screen, base = (Path(p).resolve() for p in (output, screen, base))
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    two_cpus()
    require(
        digest(read_json(screen / "protocol.json"))
        == "373ef27c4450a5afb80adad16d12fedfba4d5e3f68ea5692fd2deab3c71c7f3d",
        "only the exposed completed screen is a registered data origin",
    )
    old = screen / "s24029-ce_001"
    old_snapshot, panels = (
        read_json(old / "snapshot.json"),
        read_json(old / "panels.json"),
    )
    old_training = read_json(old / "train-result.json")["write_receipt"]
    old_rows = read_json(old / "adapter.journal.json")["rows"][:40]
    require(
        old_training["writer_seed"] == 24029
        and old_training["steps"] == 256
        and old_training["objective"] == "completion_ce"
        and old_training["learning_rate"] == 0.001,
        "reference method changed",
    )
    inventory = base_inventory(base)
    require(digest(inventory) == BASE_IDENTITY, "fixed pretrained base bytes changed")
    service = MemoryService(
        output / "source-owner",
        old_snapshot["scope"],
        "retention-fitting-diagnostic-v1",
        old_snapshot["role"],
    )
    writes = [
        asdict(
            service.write(
                "fitting-" + f["entity"], f["entity"], f["relation"], f["value"]
            )
        )
        for f in old_snapshot["facts"]
    ]
    snapshot = service.snapshot()
    old_roots = set(old_snapshot["roots"]) | set(old_snapshot["revoked"])
    require(
        len(snapshot["facts"]) == 10
        and not snapshot["conflicts"]
        and not snapshot["revoked"]
        and not old_roots.intersection(snapshot["roots"])
        and service.parameter_binding() is None,
        "fresh live synthetic roots and empty new owner required",
    )
    tokenizer = Tokenizer.from_file(str(base / "tokenizer.json"))
    eos = tokenizer.token_to_id(read_json(base / "tokenizer_config.json")["eos_token"])
    examples = []
    for fact in snapshot["facts"]:
        for template in panels["train_templates"]:
            question = template.format(**fact)
            rendered = (
                "<|im_start|>system\n" + SYSTEM + "<|im_end|>\n"
                "<|im_start|>user\nScope: "
                + snapshot["scope"]
                + "\n"
                + question
                + "<|im_end|>\n<|im_start|>assistant\n"
            )
            prompt = tokenizer.encode(rendered, add_special_tokens=False).ids
            target = tokenizer.encode(fact["value"], add_special_tokens=False).ids + [
                eos
            ]
            index = len(examples)
            require(
                question == old_rows[index]["question"]
                and prompt == old_rows[index]["prompt_token_ids"]
                and 1 <= len(prompt) <= 192
                and 2 <= len(target) <= 16,
                "reference prompt/value encoding changed",
            )
            examples.append(
                dict(
                    question=question,
                    entity=fact["entity"],
                    relation=fact["relation"],
                    value=fact["value"],
                    source_root=fact["source_digest"],
                    prompt_ids=prompt,
                    target_ids=target,
                    input_ids=prompt + target,
                    labels=[-100] * len(prompt) + target,
                )
            )
    source = sources()
    protocol = dict(
        schema="hepta.fitting-diagnostic.protocol.v1",
        frozen_unix_ns=time.time_ns(),
        source_identity_sha256=digest(source),
        base=str(base),
        base_identity=BASE_IDENTITY,
        scope=snapshot["scope"],
        cell_id=snapshot["cell_id"],
        role=snapshot["role"],
        source_snapshot_sha256=digest(snapshot),
        examples_sha256=digest(examples),
        templates=panels["train_templates"],
        seed=24029,
        rank=8,
        learning_rate=0.001,
        objective="completion_ce",
        stages={
            "training": 256,
            "memory_teacher": 40,
            "reload_teacher": 40,
            "reload_prefill": 40,
        },
        limits={"seconds": 600, "threads": 2, "artifact_bytes": 5_000_000},
        expected_training_order=old_training["schedule_indices"],
        expected_starting_adapter_sha256=old_training["starting_adapter_sha256"],
        reference_final_adapter_sha256=old_training["adapter_state_sha256"],
        source_origin={
            name: file_digest(old / name)
            for name in (
                "snapshot.json",
                "panels.json",
                "train-result.json",
                "adapter.journal.json",
            )
        },
        old_roots=sorted(old_roots),
        old_checkpoint_read_as_memory=False,
        source_policy="Fresh source IDs and cell/owner; original textual scope retained only to match token inputs; no withdrawal rollback.",
        no_autoregressive_generation=True,
        maximum_actual_model_forwards=376,
        retry=False,
        budget_refund=0,
        training_wordings_only=True,
        classification="exact save/reload logits; paired teacher/prefill first-token predictions; then fitted/not fitted at this budget",
        prefill_comparison="record full-vector max absolute difference and exact argmax; numerical differences alone do not prove a cache defect",
        teacher_targets_are_diagnostic_not_parameter_recall=True,
        intrinsic_capacity_limit_claim=False,
        future_gate_satisfied=False,
        production_accepted=False,
    )
    for name, value in (
        ("source-identity.json", source),
        ("base-inventory.json", inventory),
        ("runtime-versions.json", runtime_versions()),
        ("snapshot.json", snapshot),
        ("source-writes.json", writes),
        ("examples.json", examples),
        ("protocol.json", protocol),
        ("preparation-resources.json", resource_state(output)),
    ):
        retain(output / name, value)
    retain(
        output / "freeze.json",
        dict(
            protocol_sha256=digest(protocol),
            model_forwards_started=0,
            explicit_root_lane_release_required=True,
        ),
    )
    return digest(protocol)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("out", "screen", "base"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    existed = args.out.exists()
    try:
        print(prepare(args.out, args.screen, args.base))
    except BaseException as error:
        if not existed and args.out.is_dir():
            retain(
                args.out / "preparation-failure.json",
                dict(
                    error=f"{type(error).__name__}: {error}"[:3000],
                    observed_unix_ns=time.time_ns(),
                    model_forwards_started=0,
                    retry=False,
                ),
            )
        raise
