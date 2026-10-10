"""Matched frozen-reader capability experiment, not memory learning or adoption.

Reuse the existing evidence projection, reader answer path, journal and gates.
The reference model is a research-only diagnostic, never an authorized teacher
or a default serving model. Remote revision metadata is fixed BEFORE download.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time

from bundle_reader import FrozenBundleReader, GENERATION, SYSTEM
from bundle_trial import write
from native import digest
from reviewed_diagnostic import DiagnosticInputs, execute

MODELS = {
    "smol-1.7b": (
        "HuggingFaceTB/SmolLM2-1.7B-Instruct",
        "31b70e2e869a7173562077fd711b654946d38674",
    ),
    "qwen-3b": (
        "Qwen/Qwen2.5-3B-Instruct",
        "82f42baa094a9600e39ccd80d34058aeeb3abbc1",
    ),
}
PINS = {
    "plan": "f1edc186065acab9b56a85e9b38e7d585ef5d670293cd95ff0ecc82579aa0725",
    "reviews": "3cc77008c68dae5cc57f468464b9c0b2ca4e700986de01aedfde8b69033daf79",
    "withdrawals": "37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570",
    "labels": "5973e13de088b5973d045db543444ab1050dfe3ede2b843c84642781dfd6232e",
}
FILE_BOUND = 12 * 1024**3
PRECISION = "bfloat16"


def catalogue(info, revision):
    if info.sha != revision:
        raise ValueError("model revision moved")
    entries = {}
    for item in info.siblings:
        name = item.rfilename
        if "/" in name or not (
            name.endswith((".json", ".safetensors"))
            or name in ("merges.txt", "vocab.txt", "LICENSE", "README.md")
        ):
            continue
        lfs = item.lfs
        algorithm, value = ("sha256", lfs.sha256) if lfs else ("git-sha1", item.blob_id)
        if (
            name in entries
            or name in (".", "..")
            or not re.fullmatch(r"[a-zA-Z0-9_.-]+", name)
            or type(item.size) is not int
            or not 0 < item.size <= FILE_BOUND
            or not isinstance(value, str)
            or not re.fullmatch(r"[0-9a-f]{64}" if lfs else r"[0-9a-f]{40}", value)
        ):
            raise ValueError("invalid publisher file metadata")
        entries[name] = dict(bytes=item.size, algorithm=algorithm, digest=value)
    if (
        not 1 <= len(entries) <= 128
        or sum(v["bytes"] for v in entries.values()) > FILE_BOUND
        or not {"config.json", "tokenizer_config.json"}.issubset(entries)
        or not any(n.endswith(".safetensors") for n in entries)
    ):
        raise ValueError("incomplete or oversized model catalogue")
    return entries


def verify_files(root, entries):
    for name, expected in entries.items():
        path = root / name
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size != expected["bytes"]
        ):
            raise ValueError("model file size/type differs from publisher")
        h = hashlib.sha256() if expected["algorithm"] == "sha256" else hashlib.sha1()
        if expected["algorithm"] == "git-sha1":
            h.update(f"blob {expected['bytes']}\0".encode())
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(block)
        if h.hexdigest() != expected["digest"]:
            raise ValueError("model differs from pinned publisher bytes")
    index = root / "model.safetensors.index.json"
    if index.exists():
        from tensor_contract import strict_json

        if index.stat().st_size > 1024 * 1024:
            raise ValueError("tensor index too large")
        names = set(strict_json(index.read_text())["weight_map"].values())
        if (
            not names
            or not names.issubset(entries)
            or any(not n.endswith(".safetensors") for n in names)
        ):
            raise ValueError("unlisted tensor shard")


def stage(tier, output):
    from huggingface_hub import HfApi, snapshot_download
    from pretrained import file_inventory

    repo, revision = MODELS[tier]
    output.mkdir()
    started = time.perf_counter()
    info = HfApi().model_info(repo, revision=revision, files_metadata=True, token=False)
    entries = catalogue(info, revision)
    write(
        output / "publisher.json",
        dict(repository=repo, revision=revision, files=entries),
    )
    snapshot_download(
        repo,
        revision=revision,
        local_dir=output / "reader",
        allow_patterns=list(entries),
        token=False,
        max_workers=2,
    )
    verify_files(output / "reader", entries)
    inventory = file_inventory(output / "reader")
    if set(inventory) != set(entries):
        raise ValueError("unexpected staged model files")
    write(
        output / "inventory.json",
        dict(
            tier=tier,
            repository=repo,
            revision=revision,
            inventory=inventory,
            inventory_digest=digest(inventory),
            model_qualification=False,
        ),
    )
    write(
        output / "stage.json",
        dict(
            tier=tier,
            repository=repo,
            revision=revision,
            inventory_sha256=hashlib.sha256(
                (output / "inventory.json").read_bytes()
            ).hexdigest(),
            publisher_sha256=hashlib.sha256(
                (output / "publisher.json").read_bytes()
            ).hexdigest(),
            seconds=time.perf_counter() - started,
            model_file_bytes=sum(v["bytes"] for v in inventory.values()),
            research_only=True,
            production_accepted=False,
        ),
    )


class ReferenceReader(FrozenBundleReader):
    """Only loading precision differs; inherited answer/validation stay unchanged."""

    def __init__(self, directory, *, expected_inventory):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from pretrained import file_inventory, frozen_digest

        self.inventory = file_inventory(directory)
        if digest(self.inventory) != expected_inventory:
            raise ValueError("reference reader identity mismatch")
        self.identity = expected_inventory
        self.tokenizer = AutoTokenizer.from_pretrained(
            directory, local_files_only=True, trust_remote_code=False
        )
        self.model = AutoModelForCausalLM.from_pretrained(
            directory,
            local_files_only=True,
            trust_remote_code=False,
            use_safetensors=True,
            torch_dtype=torch.bfloat16,
            low_cpu_mem_usage=True,
            attn_implementation="eager",
        ).eval()
        self.model.requires_grad_(False)
        self.base_digest = frozen_digest(self.model)
        self.profile = digest(
            (
                SYSTEM,
                GENERATION,
                self.tokenizer.chat_template,
                PRECISION,
                "eager",
                "reader-reference-v1",
            )
        )


def strict_records(payload):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate reference record field")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(f"nonfinite JSON constant: {value}")

    records = json.loads(
        payload,
        object_pairs_hook=unique,
        parse_constant=invalid_constant,
    )
    if not isinstance(records, list) or any(
        not isinstance(row, dict) or not {"question_id", "arm", "status"}.issubset(row)
        for row in records
    ):
        raise ValueError("reference outcomes array required")
    return records


def summarize(records):
    keys, profiles, summaries = set(), set(), {}
    for row in records:
        key = (row["question_id"], row["arm"])
        if key in keys or row["status"] not in ("succeeded", "failed", "unavailable"):
            raise ValueError("duplicate or invalid reference outcome")
        keys.add(key)
        s = summaries.setdefault(
            row["arm"],
            dict(
                planned=0,
                succeeded=0,
                failed=0,
                unavailable=0,
                input_tokens=0,
                output_tokens=0,
                read_seconds=0.0,
                diagnostic_f1_sum=0.0,
                citation_markers=0,
            ),
        )
        s["planned"] += 1
        s[row["status"]] += 1
        if row["status"] != "succeeded":
            continue
        receipt = row["receipt"]
        profiles.add((receipt["reader_identity"], receipt["reader_profile"]))
        value = row.get("f1")
        if type(value) not in (int, float) or not 0 <= value <= 1:
            raise ValueError("unscored or nonfinite successful reference answer")
        for name in ("input_tokens", "generated_tokens"):
            if type(receipt[name]) is not int or receipt[name] < 0:
                raise ValueError("invalid token cost")
        seconds = receipt["seconds"]
        if type(seconds) not in (int, float) or not 0 <= seconds < 86400:
            raise ValueError("invalid measured cost")
        s["input_tokens"] += receipt["input_tokens"]
        s["output_tokens"] += receipt["generated_tokens"]
        s["read_seconds"] += seconds
        s["diagnostic_f1_sum"] += value
        s["citation_markers"] += len(re.findall(r"\[E[0-9]+\]", row["answer"]))
    if len(profiles) != 1:
        raise ValueError("missing or mixed reader identity/profile")
    for s in summaries.values():
        s["all_planned_f1_lower"] = s["diagnostic_f1_sum"] / s["planned"]
        s["all_planned_f1_upper"] = (
            s["diagnostic_f1_sum"] + s["failed"] + s["unavailable"]
        ) / s["planned"]
        s["semantic_citation_precision"] = None
    return summaries


def run(inputs_dir, model_dir, output, stage_sha):
    import torch
    from reviewed_bundle import strict_read

    torch.set_num_threads(2)
    commit = os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("exact experiment source required")
    staged = strict_read(model_dir / "stage.json", stage_sha, 1024 * 1024)
    if (staged["repository"], staged["revision"]) != MODELS[staged["tier"]]:
        raise ValueError("undeclared reference model")
    publisher = strict_read(
        model_dir / "publisher.json", staged["publisher_sha256"], 1024 * 1024
    )
    if (publisher["repository"], publisher["revision"]) != MODELS[staged["tier"]]:
        raise ValueError("publisher/model mismatch")
    verify_files(model_dir / "reader", publisher["files"])
    paths = {k: inputs_dir / (k + ".json") for k in PINS}
    paths["inventory"] = model_dir / "inventory.json"
    pins = PINS | dict(inventory=staged["inventory_sha256"])
    inputs = DiagnosticInputs(paths, pins)
    output.mkdir()
    write(
        output / "preregistered.json",
        dict(
            source_commit=commit,
            input_pins=pins,
            tier=staged["tier"],
            stage_sha256=stage_sha,
            generation=GENERATION,
            system=SYSTEM,
            dtype=PRECISION,
            attention="eager",
            historical_float32_profile_comparable=False,
            protocol="reader-reference-v1",
            optimization_permitted=False,
            missing_reviews_remain_unavailable=True,
            production_accepted=False,
        ),
    )
    result = execute(
        inputs,
        model_dir / "reader",
        output / "diagnostic",
        reader_factory=ReferenceReader,
    )
    records = strict_records(
        (output / "diagnostic/execution/scored-answers.json").read_text()
    )
    write(
        output / "reference-report.json",
        dict(
            source_commit=commit,
            tier=staged["tier"],
            summaries=summarize(records),
            existing_screen=result,
            stage_seconds=staged["seconds"],
            model_file_bytes=staged["model_file_bytes"],
            training_seconds=0,
            extraction_and_index_seconds=None,
            inherited_costs="original input artifact; not assumed zero",
            model_change_is_not_memory_gain=True,
            selected_reader=None,
            independent_sufficiency_certified=False,
            production_accepted=False,
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("stage")
    s.add_argument("tier", choices=MODELS)
    s.add_argument("output", type=Path)
    r = sub.add_parser("run")
    for field in ("inputs", "model", "output"):
        r.add_argument(field, type=Path)
    r.add_argument("--stage-sha", required=True)
    args = parser.parse_args()
    if args.command == "stage":
        stage(args.tier, args.output)
    else:
        run(args.inputs, args.model, args.output, args.stage_sha)
