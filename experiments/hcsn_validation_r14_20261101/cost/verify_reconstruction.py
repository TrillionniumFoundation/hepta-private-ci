"""Check archive portability using only a freshly reconstructed repository."""

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(output):
    import numpy as np
    import torch
    from experiments.hcsn_validation_r12_20261031.content import study as old
    from experiments.hcsn_validation_r12_20261031.content.data import dataset
    from experiments.hcsn_validation_r14_20261101.cost import study as replay

    root = Path.cwd().resolve()
    if replay.ROOT != root or not old.ROOT.is_relative_to(root):
        raise ValueError("An imported implementation is outside the reconstructed tree")
    old.configure()
    formal = replay.HERE / "results/formal_02"
    plan = replay.verify(formal)
    protocol_path = replay.STUDY / "PROTOCOL.json"
    protocol, study_root = old.verified(protocol_path)
    runtime = protocol["runtime"]
    cfc = Path(importlib.util.find_spec("ncps").origin).parent / "torch/cfc_cell.py"
    if (torch.__version__ != runtime["torch"] or np.__version__ != runtime["numpy"]
            or importlib.metadata.version("ncps") != runtime["ncps"]
            or sha(cfc) != runtime["cfc_cell_sha256"]):
        raise ValueError("Reconstruction runtime differs from the historical pin")
    inputs = replay.read(formal / "INPUT_MANIFEST.json")["files"]
    for name, expected in inputs.items():
        if sha(root / name) != expected:
            raise ValueError("Reconstructed replay input differs: " + name)
    candidates = replay.read(study_root / "CANDIDATE_FREEZE.json")["candidates"]
    for name, entry in candidates.items():
        if sha(study_root / entry["path"] / "selected.pt") != entry["sha256"]:
            raise ValueError("Reconstructed selected checkpoint differs: " + name)
    data_cache, checked, loaded, max_difference = {}, set(), [], 0.0
    with torch.inference_mode():
        for job in protocol["jobs"]:
            if job["kind"] != "fit":
                continue
            model, _, _, _ = old.load_selected(protocol_path, job["id"])
            model.eval()
            loaded.append(job["id"])
            pair = (job["task"], job["family"])
            if pair in checked:
                continue
            data = data_cache.setdefault(job["task"], dataset(job["task"], "test", "iid"))
            expected_path = study_root / "heldout" / job["id"] / "iid.npz"
            with np.load(expected_path, allow_pickle=False) as source:
                if str(source["input_sha256"]) != data["sha256"]:
                    raise ValueError("Reconstructed raw data identity differs")
                expected = source["logits"][:32].copy()
            actual = model(torch.from_numpy(data["x"][:32]), torch.from_numpy(data["dt"][:32])).numpy()
            delta = float(np.max(np.abs(actual - expected)))
            if delta > 1e-6 or not np.array_equal(actual.argmax(-1), expected.argmax(-1)):
                raise ValueError("Reconstructed predictions differ: " + job["id"])
            max_difference = max(max_difference, delta)
            checked.add(pair)
    if len(loaded) != 96 or len(candidates) != 102 or len(checked) != 16 or len(plan["jobs"]) != 720:
        raise ValueError("Reconstruction coverage is incomplete")
    result = dict(passed=True, restored_replay_inputs_verified=len(inputs),
                  selected_checkpoints_verified=len(candidates),
                  selected_fit_models_loaded=len(loaded),
                  joint_fit_models_loaded=sum("_joint_" in name for name in loaded),
                  task_family_iid_batches_replayed=len(checked), batch_size=32,
                  maximum_iid_logit_difference=max_difference,
                  imported_sources_inside_restored_tree=True,
                  runtime_pins_verified=True, verifier_sha256=sha(__file__),
                  protocol_sha256=sha(formal / "PROTOCOL.json"),
                  scope="Archive portability check; no new fit, confirmation sample, or cost benchmark.")
    with output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    verify(parser.parse_args().output.resolve())
