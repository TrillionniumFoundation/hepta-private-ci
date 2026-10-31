"""Fit every preregistered model; confirmation data must not exist yet."""

import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from .models import RiskModel, save_state, tensor_data

HERE = Path(__file__).resolve().parent


def main():
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    if (HERE / "FREEZE.json").exists() or (HERE / "evidence/data/iid.npz").exists():
        raise RuntimeError("training refuses an existing freeze or confirmation set")
    protocol = json.loads((HERE / "protocol.json").read_text())
    setting = protocol["training"]
    train = tensor_data(np.load(HERE / "evidence/data/train.npz", allow_pickle=False))
    dev = tensor_data(np.load(HERE / "evidence/data/dev.npz", allow_pickle=False))
    output = HERE / "evidence" / "models"
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for name in protocol["models"]:
        for seed in protocol["model_seeds"]:
            path = output / f"{name}_{seed}.json"
            if path.exists():
                raise FileExistsError(path)
            start, wall = time.process_time(), time.perf_counter()
            torch.manual_seed(seed)
            rng = np.random.default_rng(seed)
            model = RiskModel(name)
            optimizer = torch.optim.Adam(model.parameters(), lr=setting["lr"])
            best, checkpoint, trace = float("inf"), None, []
            for step in range(1, setting["steps"] + 1):
                indices = rng.integers(0, len(train[0]), setting["batch"])
                optimizer.zero_grad(set_to_none=True)
                prediction = model(*(v[indices] for v in train[:3]))
                loss = ((prediction - train[3][indices])**2).mean()
                loss.backward()
                gradient = torch.nn.utils.clip_grad_norm_(model.parameters(), setting["gradient_clip"])
                optimizer.step()
                if step == 1 or step % setting["checkpoint_every"] == 0:
                    with torch.no_grad():
                        dev_loss = ((model(*dev[:3]) - dev[3])**2).mean().item()
                    trace.append({"step": step, "train_mse": loss.item(), "dev_mse": dev_loss,
                        "gradient_norm_before_clip": float(gradient)})
                    if dev_loss < best:
                        best, checkpoint = dev_loss, save_state(model)
                        selected_step = step
            artifact = {"model": name, "seed": seed, "selected_step": selected_step,
                "dev_mse": best, "state": checkpoint, "trace": trace,
                "parameter_count": sum(p.numel() for p in model.parameters())}
            path.write_text(json.dumps(artifact, separators=(",", ":")) + "\n")
            records.append({"model": name, "seed": seed, "cpu_seconds": time.process_time() - start,
                "wall_seconds": time.perf_counter() - wall, "selected_step": selected_step,
                "dev_mse": best, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
            print(json.dumps(records[-1]), flush=True)
    (HERE / "evidence/training.json").write_text(json.dumps(records, indent=2) + "\n")
    sources = {}
    for path in sorted(HERE.rglob("*")):
        if path.is_file() and (path.suffix in (".py", ".json", ".npz")):
            sources[str(path.relative_to(HERE))] = hashlib.sha256(path.read_bytes()).hexdigest()
    (HERE / "FREEZE.json").write_text(json.dumps({"rule": "No refit after this manifest",
        "source_and_checkpoint_sha256": sources, "confirmation_generated": False,
        "torch_version": torch.__version__, "numpy_version": np.__version__}, indent=2) + "\n")
    print("All checkpoints frozen before confirmation generation", flush=True)


if __name__ == "__main__":
    main()
