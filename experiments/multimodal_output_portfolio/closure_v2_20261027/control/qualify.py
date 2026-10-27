"""Seal new source identity and execute the five fixed continuation arms once."""

import argparse
import gzip
import json
from pathlib import Path
import shutil

import numpy as np
import torch

from ...v6.data import SourceCorpus, SourceSplit, _parse_images, _parse_labels
from ...continuation_20261027.joint.run import reference_observer
from .adapter import Generator, scalar_feedback
from .binding import BoundCritic
from .execute import episode
from .protocol import PROTOCOL as P, digest, preserve_sources, sha, write
from .statistics import analyze
from .tasks import make_tasks, persist_tasks


def new_sources(assets, allocation):
    record = json.loads(allocation.read_text())
    source = assets / "ndu-data"
    image_path = source / "t10k-images-idx3-ubyte.gz"
    if sha(image_path) != record["official_test_image_sha256"]:
        raise ValueError("Official source file identity differs from allocation")
    images, hashes = _parse_images(gzip.decompress(image_path.read_bytes()))
    labels = _parse_labels(gzip.decompress((source / "t10k-labels-idx1-ubyte.gz").read_bytes()))
    identifiers = record["splits"]["control_test"]["source_ids"]
    indices = [int(value.split(":")[2]) for value in identifiers]
    if len(indices) != 2 * P["qualification_pairs"] or len(indices) != len(set(indices)):
        raise ValueError("Control source grid changed")
    for index, identifier in zip(indices, identifiers):
        if identifier != f"mnist:test:{index}:{hashes[index]}":
            raise ValueError("Allocated source identity mismatch")
    other = {identity for name, split in record["splits"].items() if name != "control_test" for identity in split["source_ids"]}
    if set(identifiers) & other:
        raise ValueError("Current joint/control source overlap")
    split = SourceSplit(images[indices], labels[indices], tuple(identifiers), tuple(hashes[i] for i in indices))
    return SourceCorpus({"test": split}, {"allocation_sha256": sha(allocation), "source_ids": identifiers})


def run(assets, generator_path, binary, development, allocation, output):
    frozen = json.loads((development / "FROZEN.json").read_text())
    pins = {"MODEL.json": "model_sha256", "READOUT_FIT.json": "readout_fit_sha256",
            "FIT.json": "fit_sha256", "CRITIC_SELECTION.json": "critic_selection_sha256", "PROTOCOL.json": "protocol_sha256"}
    for name, key in pins.items():
        if sha(development / name) != frozen[key]:
            raise ValueError("A frozen development artifact changed")
    if json.loads((development / "PROTOCOL.json").read_text()) != P:
        raise ValueError("Qualification protocol differs from development")
    if sha(binary) != P["native_binary_sha256"] or sha(generator_path) != P["generator_sha256"]:
        raise ValueError("An executed model or original owner binary changed")
    forecast_model = BoundCritic(development, generator_path, binary)
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(P["threads"])
    torch.use_deterministic_algorithms(True)
    corpus = new_sources(assets, allocation)
    tasks = make_tasks(corpus, "test", P["qualification_pairs"])
    persist_tasks(tasks, output / "inputs")
    fit = json.loads((development / "FIT.json").read_text())
    heads = json.loads((development / "READOUT_FIT.json").read_text())
    selection = json.loads((development / "CRITIC_SELECTION.json").read_text())
    sources = preserve_sources(output / "executed-source")
    write(output / "QUALIFICATION_SEAL.json", {"protocol": P, "source_sha256": sources,
        "allocation_sha256": sha(allocation), "development_freeze_sha256": sha(development / "FROZEN.json"),
        "generator_sha256": sha(generator_path), "binary_sha256": sha(binary),
        "input_files_sha256": {p.name: sha(p) for p in (output / "inputs").iterdir()},
        "test_outputs_computed": False, "audit_observer_loaded": False,
        "selected_critic_shrinkage": selection["selected_shrinkage"]})
    shutil.copyfile(allocation, output / "SOURCE_ALLOCATION.json")
    # No model selection or protocol choice occurs beyond this point.
    generator, audit = Generator(generator_path), reference_observer(assets, "audit")
    references = []
    for task in tasks:
        delivery, _ = generator.deliver(task["public"], 0, output / "permutation-reference" / f"pair-{task['index']:03}")
        references.append({"index": task["index"], "delivery": delivery,
            "feedback": scalar_feedback(delivery["caption"], task["private"].labels[0].tolist())})
    order = np.random.default_rng(P["seed"] + 7).permutation(len(tasks))
    donors = np.empty(len(tasks), dtype=int)
    for position, index in enumerate(order):
        donors[index] = order[(position + 1) % len(order)]
    if any(i == int(donor) for i, donor in enumerate(donors)):
        raise ValueError("Permutation intervention retained a fixed point")
    write(output / "PERMUTATION_REFERENCE.json", {"reference": references, "donor_indices": donors.tolist(),
        "administrative_generation_calls": len(references), "charged_to_deployed_policy": False,
        "scope": "Preregistered shuffle intervention preparation; all reference CPU/wall/media retained separately"})
    rows = []
    with (output / "ROWS.jsonl").open("x") as stream:
        for task in tasks:
            for arm in P["arms"]:
                row = episode(task, arm, references[task["index"]], references[int(donors[task["index"]])], generator,
                    audit, binary, development, output, fit, heads, selection["selected_shrinkage"], forecast_model=forecast_model)
                stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
                stream.flush()
                rows.append(row)
            if (task["index"] + 1) % 16 == 0:
                print(f"actual semantic source pairs {task['index'] + 1}/{len(tasks)}", flush=True)
    result = analyze(rows)
    result.update(qualification_seal_sha256=sha(output / "QUALIFICATION_SEAL.json"), rows_sha256=sha(output / "ROWS.jsonl"),
        administrative_generation_calls=len(references), administrative_media_files=2 * len(references),
        administrative_cpu_ns=sum(r["delivery"]["generation_and_delivery_cpu_ns"] for r in references),
        administrative_wall_ns=sum(r["delivery"]["generation_and_delivery_wall_ns"] for r in references))
    write(output / "RESULT.json", result)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("assets", "generator", "binary", "development", "allocation", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.assets, args.generator, args.binary, args.development, args.allocation, args.output)
