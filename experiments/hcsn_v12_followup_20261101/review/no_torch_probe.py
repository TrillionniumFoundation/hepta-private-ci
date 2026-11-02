"""Run a real exported GRU episode while every Torch import is forbidden."""

import argparse
import importlib.abc
import importlib.util
import json
from pathlib import Path
import sys


class RejectTorch(importlib.abc.MetaPathFinder):
    def __init__(self):
        self.attempts = []

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "torch" or fullname.startswith("torch."):
            self.attempts.append(fullname)
            raise ModuleNotFoundError("Torch imports are forbidden in this actual runtime probe")
        return None


def probe(bundle, output):
    output.mkdir(parents=True, exist_ok=False)
    initially_available = importlib.util.find_spec("torch") is not None
    blocker = RejectTorch()
    if "torch" in sys.modules:
        raise RuntimeError("Fresh interpreter already imported Torch")
    sys.meta_path.insert(0, blocker)
    from experiments.hcsn_v12_followup_20261101.model_runtime import numpy_runtime as runtime
    manifest = runtime.verify(bundle)
    item = next(v for v in manifest["models"] if (v["task"], v["family"], v["seed"]) == ("async_av", "gru", 91101))
    with runtime.np.load(bundle / "async_av/test-packets.npz", allow_pickle=False) as source:
        data = {key: source[key].copy() for key in source.files}
    result, updates = runtime.episode(bundle, item, data, 0, "value")
    forbidden = [key for key in sys.modules if key == "torch" or key.startswith("torch.")]
    runtime.write(output / "ACTUAL_EPISODE.json", {"execution": result, "updates": updates})
    payload = {"schema": "hcsn-v12-torch-forbidden-actual-episode.v1",
        "status": "passed" if not initially_available and not blocker.attempts and not forbidden else "failed",
        "torch_discoverable_before_import_guard": initially_available,
        "torch_import_attempts": blocker.attempts, "torch_modules_loaded": forbidden,
        "actual_model": item, "index": 0, "policy": "value", "updates": len(updates),
        "requested_observations": result["requested_observations"], "actual_output": result["output"],
        "python": sys.executable, "bundle_manifest_sha256": runtime.sha(bundle / "MANIFEST.json"),
        "probe_source_sha256": runtime.sha(__file__),
        "scope": "Fresh primary interpreter, source-only PYTHONPATH, Torch unavailable and import-forbidden; actual NumPy GRU/head/scheduler episode"}
    runtime.write(output / "RESULT.json", payload)
    print(json.dumps(payload))
    return payload["status"] == "passed"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if probe(args.bundle, args.out) else 1)
