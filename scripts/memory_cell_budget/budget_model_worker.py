"""One bounded pretrained operation in a disposable child, never a gold reader."""

import argparse
import gc
import json
from pathlib import Path
import sys

from cohort_contract import file_sha, retain, validate_seal
from workflow_records import (
    FINAL_TEMPLATE,
    SCOPE,
    TRAIN_TEMPLATES,
    extract,
    facts,
    source_partitions,
)


def imports(implementation):
    implementation = Path(implementation).resolve()
    for directory in sorted((implementation / "scripts").glob("memory_cell*")):
        sys.path.insert(0, str(directory))
    import torch

    torch.set_num_threads(2)
    from parametric_model import SourceMemoryCell

    return SourceMemoryCell


def save(cell, directory, receipt, rank):
    directory = Path(directory)
    manifest = cell.save(directory)
    retain(directory.parent / (directory.name + ".training.json"), receipt)
    return dict(
        directory=str(directory.resolve()),
        manifest_sha256=manifest,
        rank=rank,
        seed=2718,
        roots=sorted(cell.reader.roots),
        scope=SCOPE,
    )


def load(model, version, allowed, Cell):
    cell = Cell(model, rank=version["rank"], seed=version["seed"])
    cell.load(
        Path(version["directory"]),
        expected_manifest_sha256=version["manifest_sha256"],
        scope=SCOPE,
        allowed_roots=set(allowed),
        revoked=set(),
    )
    return cell


def parent(request, Cell):
    study, output = Path(request["study"]), Path(request["output"])
    validate_seal(study)
    source_receipt = json.loads((study / "source-command-receipt.json").read_text())
    if (
        file_sha(study / "source-command-records.json")
        != source_receipt["records_sha256"]
    ):
        raise ValueError("source-only command records changed")
    if json.loads((study / "source-command-records.json").read_text()) != extract(
        json.loads((study / "source-documents.json").read_text())
    ):
        raise ValueError("source commands differ from the sealed automatic extraction")
    output.mkdir(exist_ok=False, parents=True)
    cell = Cell(request["model"], rank=4, seed=2718)
    cell.reset(SCOPE)
    rows = json.loads((study / "source-command-records.json").read_text())
    admitted, rejected = [], []
    for row in rows:
        reason = None
        value = cell.reader.tokenizer.encode(row["value"], add_special_tokens=False)
        if not 1 <= len(value) < 16 or cell.reader.tokenizer.eos_token_id in value:
            reason = "source_value_exceeds_fixed_generation_contract"
        if reason is None:
            try:
                for template in TRAIN_TEMPLATES + [FINAL_TEMPLATE]:
                    cell.prompt_ids(template.format(**row))
            except ValueError:
                reason = "source_prompt_exceeds_fixed_input_contract"
        if reason is None and len(admitted) >= 128:
            reason = "source_record_count_budget"
        if reason:
            rejected.append(dict(record_id=row["record_id"], reason=reason))
        else:
            admitted.append(row)
    if len(admitted) < 16:
        raise ValueError("insufficient automatically admitted source records")
    retain(output / "admitted-source-records.json", admitted)
    retain(
        output / "source-filter.json",
        dict(
            considered=len(rows),
            admitted=len(admitted),
            rejected=rejected,
            final_input_used=False,
            curator_repair_labels_used=False,
        ),
    )
    retain(output / "partitions.json", source_partitions(admitted))
    receipt = cell.fit_sources(facts(admitted), 32, 0.001, TRAIN_TEMPLATES)
    version = save(cell, output / "parent", receipt, 4)
    result = dict(
        phase="shared_parent",
        version=version,
        receipts=[receipt],
        updates=receipt["steps"],
        admitted_records_sha256=file_sha(output / "admitted-source-records.json"),
        partitions_sha256=file_sha(output / "partitions.json"),
    )
    retain(output / "result.json", result)
    return result


def train_arm(request, Cell):
    from population_transfer import expand_verified_parent

    output = Path(request["output"])
    output.mkdir(exist_ok=False, parents=True)
    shared = Path(request["shared"])
    validate_seal(request["study"])
    if file_sha(shared / "result.json") != request["parent_result_sha256"]:
        raise ValueError("shared parent identity differs from the reserved request")
    parent_result = json.loads((shared / "result.json").read_text())
    if (
        file_sha(shared / "admitted-source-records.json")
        != parent_result["admitted_records_sha256"]
    ):
        raise ValueError("admitted source records changed")
    if file_sha(shared / "partitions.json") != parent_result["partitions_sha256"]:
        raise ValueError("source-only partition changed")
    rows = json.loads((shared / "admitted-source-records.json").read_text())
    partitions = json.loads((shared / "partitions.json").read_text())
    allowed = {r["source_digest"] for r in rows}
    version = parent_result["version"]
    arm = request["arm"]
    receipts, versions = [], []
    if arm == "expanded":
        inherited = load(request["model"], version, allowed, Cell)
        cell = Cell(request["model"], rank=8, seed=2718)
        cell.reset(SCOPE)
        initial = output / "expanded-parent"
        expansion = expand_verified_parent(
            inherited, cell, initial, parent_manifest_sha256=version["manifest_sha256"]
        )
        retain(output / "expansion.json", expansion)
        del inherited
        gc.collect()
        cell.load(
            initial,
            expected_manifest_sha256=expansion["manifest_sha256"],
            scope=SCOPE,
            allowed_roots=allowed,
            revoked=set(),
        )
        receipt = cell.fit_sources(facts(rows), 96, 0.001, TRAIN_TEMPLATES)
        versions.append(save(cell, output / "cell-0", receipt, 8))
        receipts.append(receipt)
    else:
        slots = [0] * len(rows) if arm == "single" else partitions[arm]["slots"]
        for slot in sorted(set(slots)):
            cell = load(request["model"], version, allowed, Cell)
            selected = [r for r, s in zip(rows, slots) if s == slot]
            receipt = cell.fit_sources(
                facts(selected), 96 if arm == "single" else 48, 0.001, TRAIN_TEMPLATES
            )
            versions.append(save(cell, output / f"cell-{slot}", receipt, 4))
            receipts.append(receipt)
            del cell
            gc.collect()
    result = dict(
        phase="arm",
        arm=arm,
        versions=versions,
        receipts=receipts,
        marginal_updates=sum(x["steps"] for x in receipts),
        standalone_updates=32 + sum(x["steps"] for x in receipts),
        parent_result_sha256=file_sha(shared / "result.json"),
        source_membership_routes_not_decoder_utility=True,
        partition=partitions.get(arm),
        final_inputs_used=False,
    )
    retain(output / "result.json", result)
    return result


def read(request, Cell):
    from parametric_model import SYSTEM
    from parametric_worker import run
    from transformers import AutoTokenizer

    # The tokenizer is used only to reject overlength complete prompts. The
    # underlying reader retains its unchanged no-truncation contract.
    tokenizer = AutoTokenizer.from_pretrained(request["model"], local_files_only=True)
    valid, indices, rejected = [], [], []
    for i, question in enumerate(request["questions"]):
        ids = tokenizer.apply_chat_template(
            [
                dict(role="system", content=SYSTEM),
                dict(role="user", content=f"Scope: {SCOPE}\n{question}"),
            ],
            tokenize=True,
            add_generation_prompt=True,
        )
        if 1 <= len(ids) <= 192 and len(question.encode()) <= 4096:
            valid.append(question)
            indices.append(i)
        else:
            rejected.append(
                dict(
                    index=i,
                    status="input_contract_rejected",
                    complete_input_tokens=len(ids),
                )
            )
    version = request["version"]
    payload = dict(
        model=request["model"],
        snapshot=version["directory"],
        manifest_sha256=version["manifest_sha256"],
        scope=SCOPE,
        allowed_roots=request["allowed_roots"],
        questions=valid,
        rank=version["rank"],
        seed=version["seed"],
        control=request["control"],
    )
    journal = (
        run(payload)
        if valid
        else dict(rows=[], control=request["control"], no_decoder_calls=True)
    )
    return dict(
        journal=journal, indices=indices, rejected=rejected, raw_outputs_unmodified=True
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--implementation", required=True)
    args = parser.parse_args()
    request = json.loads(sys.stdin.read())
    Cell = imports(args.implementation)
    operations = {"parent": parent, "arm": train_arm, "read": read}
    result = operations[request["phase"]](request, Cell)
    io = {
        k: int(v)
        for k, v in (
            line.split(": ") for line in Path("/proc/self/io").read_text().splitlines()
        )
    }
    result["worker_process_io_before_stdout"] = io
    print(json.dumps(result, sort_keys=True))
