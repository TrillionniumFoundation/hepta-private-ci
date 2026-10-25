"""Archive all actual sealed warmup/terminal checkpoints without reading labels.

Stopped candidates retain their actual parameters and execution metadata. This
conversion does not turn an incomplete run into scientific or serving approval.
Complete optimizer tensors are included; controller-plan files remain separately
bound by their sealed hashes and are not embedded native serving state.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(run, protocol, research_code, output):
    root, protocol, code, output = map(Path, (run, protocol, research_code, output))
    sys.path.insert(0, str(code.resolve()))
    from cell_field_evaluate_v4 import verify_pre_label_seal
    from cell_learning_models import canonical

    seal = verify_pre_label_seal(root, protocol)
    plan = json.loads(protocol.read_bytes())
    if (len(plan["tasks"]) != 2 or plan["head_modes"] != ["linear", "gated"]
            or plan["seeds"] != [7, 17, 29] or plan["mpc"]["steps"] != 32):
        raise ValueError("the frozen all-12 32-update family is required")
    projection = None
    for task in plan["tasks"]:
        with np.load(root / task / "projected.npz", allow_pickle=False) as archive:
            value = archive["projection"]
        if value.shape != (384, 8) or value.dtype != np.float64 or not np.isfinite(value).all():
            raise ValueError("frozen shared float64 projection differs")
        if projection is None:
            projection = value
        elif not np.array_equal(projection, value):
            raise ValueError("cross-task projection differs")
    output.mkdir(parents=True, exist_ok=False)
    summaries = []
    for role in ("predecessor", "candidate"):
        rows = []
        for task in plan["tasks"]:
            for head in plan["head_modes"]:
                for seed in plan["seeds"]:
                    directory = root / task / f"seed{seed}-{head}"
                    policy = directory / "mpc" / plan["mpc"]["candidate"]
                    checkpoint = policy / "terminal" if role == "candidate" else directory / "warmup/checkpoint"
                    manifest = json.loads((checkpoint / "manifest.json").read_bytes())
                    if digest(checkpoint / "state.npz") != manifest["payload_sha256"]:
                        raise ValueError("sealed checkpoint payload mismatch")
                    execution = {"role": "warmup", "optimizer_step_count": manifest["step_count"]}
                    controller = {}
                    if role == "candidate":
                        result = json.loads((policy / "result.json").read_bytes())
                        if (result["policy"] != plan["mpc"]["candidate"]
                                or result["registered_steps"] != 32
                                or result["terminal_state_sha256"] != manifest["state_sha256"]):
                            raise ValueError("candidate terminal state or registration differs")
                        execution = {key: result[key] for key in (
                            "status", "policy", "completed_steps", "registered_steps", "terminal_state_sha256")}
                        for path in policy.rglob("*"):
                            if path.is_file() and path.parts[-2] != "terminal":
                                relative = path.relative_to(root).as_posix()
                                controller[relative] = seal["files"][relative]["sha256"]
                    with np.load(checkpoint / "state.npz", allow_pickle=False) as archive:
                        tensors = {name: {"dtype": str(archive[name].dtype), "shape": list(archive[name].shape),
                                          "values": archive[name].tolist()} for name in sorted(archive.files)}
                    rows.append({"task": task, "head": head, "seed": seed, "checkpoint_manifest": manifest,
                        "tensors": tensors, "origin": checkpoint.relative_to(root).as_posix(),
                        "execution": execution, "controller_artifact_sha256": controller})
        bundle = {"schema": "research-numpy-float64-bundle.v1", "candidate": plan["mpc"]["candidate"] if role == "candidate" else "warmup",
            "fits": rows, "projection": projection.tolist(), "encoder": plan["encoder"], "encoder_revision": plan["encoder_revision"],
            "protocol_sha256": digest(protocol), "pre_evaluation_seal_sha256": digest(root / "pre_evaluation_seal.json"),
            "optimizer_state_included": True, "serving_compatible": False, "scientific_acceptance": False,
            "controller_state_scope": "separate controller and trajectory archive identities retained; native payload serves theta only",
            "authority": "DENY_ALL", "production_authority": False}
        target = output / f"{role}-parameters.json"
        target.write_bytes(canonical(bundle) + b"\n")
        summaries.append({"role": role, "sha256": digest(target), "fits": len(rows),
                          "execution": [r["execution"] for r in rows]})
    receipt = {"schema": "hepta.sealed-research-source-bundles.v5", "protocol_sha256": digest(protocol),
        "pre_evaluation_seal_sha256": digest(root / "pre_evaluation_seal.json"), "bundles": summaries,
        "heldout_labels_read": False, "scientific_acceptance": False, "production_authority": False}
    (output / "source-bundle-receipt.json").write_bytes(canonical(receipt) + b"\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "protocol", "research-code", "output"):
        parser.add_argument("--" + name, required=True)
    result = build(**vars(parser.parse_args()))
    print(json.dumps({"bundles": [{k: b[k] for k in ("role", "sha256", "fits")} for b in result["bundles"]]}))
