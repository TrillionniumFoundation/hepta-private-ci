"""Execute the frozen original-model development study and retain every output."""

import argparse
import json
from pathlib import Path
import platform
import sys

import torch

from ...v6.data import load_corpus
from ...v6.observer import Recognizer
from ...v6.plan_training import ControlledSnapshot
from .evaluate import analyze, checksum, evaluate, write_json
from .protocol import PROTOCOL as P, freeze
from .train import fit


def run(assets, output):
    assets, output = Path(assets), Path(output)
    protocol_digest = freeze(output)
    if any(path.name != "PROTOCOL.json" for path in output.iterdir()):
        raise FileExistsError("Existing run evidence may not be overwritten; choose a new directory")
    torch.set_num_threads(P["threads"])
    torch.use_deterministic_algorithms(True)
    original_root = assets / "ndu-runs/full-002"
    historical = json.loads((original_root / "protocol.json").read_text())
    corpus = load_corpus(assets / "ndu-data", evaluator_sources=10000)
    if corpus.manifest != historical["dataset_manifest"]:
        raise ValueError("Historical data reconstruction differs")
    restore = json.loads((assets / "RESTORATION.json").read_text())
    if restore["archive_sha256"] != P["base_archive_sha256"]:
        raise ValueError("Historical archive identity differs")
    pins = {row["path"]: row["sha256"] for row in restore["selected_files"]}
    for path, digest in pins.items():
        if checksum(assets / path) != digest:
            raise ValueError("Restored asset changed: " + path)
    write_json(output / "RESTORATION.json", restore)
    write_json(output / "DATA_MANIFEST.json", corpus.manifest)
    source = Path(__file__).resolve().parent
    write_json(output / "RUNTIME.json", {"python": sys.version, "torch": torch.__version__, "platform": platform.platform(),
        "protocol_sha256": protocol_digest, "source_sha256": {p.name: checksum(p) for p in source.glob("*.py")},
        "historical_base_checkpoint_sha256": {str(seed): pins[f"ndu-runs/full-002/seed-{seed}-terminal_entropic_ndu.pt"] for seed in P["seeds"]}})
    reward = Recognizer().eval().requires_grad_(False)
    reward.load_state_dict(torch.load(original_root / "reward-observer.pt", weights_only=True))
    trained, training = {}, []
    for seed in P["seeds"]:
        original = ControlledSnapshot.load(original_root / f"seed-{seed}-terminal_entropic_ndu.pt")
        trained[seed, "frozen"] = original
        for arm in P["arms"][1:]:
            snapshot, evidence = fit(original, corpus, reward, seed, arm)
            checkpoint = output / f"seed-{seed}-{arm}.pt"
            snapshot.save(checkpoint)
            reloaded = ControlledSnapshot.load(checkpoint)
            if snapshot.fingerprint != reloaded.fingerprint:
                raise RuntimeError("Saved joint model failed reload parity")
            trained[seed, arm] = reloaded
            evidence["checkpoint_sha256"] = checksum(checkpoint)
            training.append(evidence)
            write_json(output / "TRAINING.json", training)
        if training[-1]["schedule_sha256"] != training[-2]["schedule_sha256"]:
            raise RuntimeError("Matched arms received different input/noise schedules")
    # The audit observer is not even loaded until all optimization is complete.
    audit = Recognizer().eval().requires_grad_(False)
    audit.load_state_dict(torch.load(original_root / "audit-observer.pt", weights_only=True))
    rows = []
    with (output / "ROWS.jsonl").open("x") as stream:
        for (seed, arm), snapshot in trained.items():
            current = evaluate(snapshot, corpus, {"audit": audit, "reward": reward}, seed, arm, output)
            rows.extend(current)
            for row in current:
                stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            print(f"evaluated seed={seed} arm={arm} delivered={len(current)}", flush=True)
    result = analyze(rows)
    result["protocol_sha256"] = protocol_digest
    result["rows_sha256"] = checksum(output / "ROWS.jsonl")
    write_json(output / "RESULT.json", result)
    print(json.dumps({"acceptance": result["registered_acceptance_passed"], "comparisons": result["comparisons"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.assets, args.output)
