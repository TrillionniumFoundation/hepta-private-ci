"""Cross-check native fixtures against the unchanged original TensorCell loader."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import torch

def main(source, restored, fixtures, output):
    if output.exists():
        raise FileExistsError(output)
    sys.path.insert(0, str(source.resolve()))
    from tensor_cell import TensorCell
    torch.set_num_threads(1)
    results = []
    for seed in (731, 732, 733):
        for kind in ("semantic", "skill"):
            fixture = json.loads((fixtures / f"seed-{seed}-{kind}.json").read_bytes())
            checkpoint = restored / "models" / f"seed-{seed}" / kind
            model = TensorCell.load(checkpoint, expected_encoder_sha=fixture["encoder_sha256"])
            if model.parameter_digest() != fixture["parameter_sha256"]:
                raise ValueError("original parameter digest differs from native fixture")
            x = np.asarray([row["features"] for row in fixture["cases"]], dtype=np.float32)
            expected = np.asarray([row["logits"] for row in fixture["cases"]], dtype=np.float32)
            actual = model.raw_outputs(x)
            error = np.abs(actual - expected)
            if not np.all(error <= 1e-4 + 1e-5 * np.abs(expected)):
                raise ValueError("original PyTorch logits differ from frozen numeric tolerance")
            prediction = model.predict(x)
            values = []
            for i in range(len(x)):
                if kind == "semantic":
                    fields = [sum(int(prediction["bits"][i, 4 * field + bit]) << bit for bit in range(4)) for field in range(3)]
                    values.append(dict(kind="semantic", **dict(zip(("reserve", "pack", "limit"), fields))))
                else:
                    values.append({"kind": "skill", "program": [int(prediction[f"op{step}"][i]) for step in range(4)]})
            if values != [row["value"] for row in fixture["cases"]]:
                raise ValueError("original PyTorch typed values differ from native fixtures")
            results.append({"seed": seed, "kind": kind, "cases": len(x), "parameter_sha256": model.parameter_digest(),
                            "checkpoint_manifest_sha256": hashlib.sha256((checkpoint / "manifest.json").read_bytes()).hexdigest(),
                            "maximum_logit_error": float(error.max()), "typed_values_equal": True})
    raw = (source / "tensor_cell.py").read_bytes()
    report = {"schema": "hepta.memory.original-torch-native-fixture-comparison.v1", "torch_version": torch.__version__,
              "source_sha256": hashlib.sha256(raw).hexdigest(), "source_git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
              "cases": sum(row["cases"] for row in results), "results": results}
    with output.open("x") as stream:
        json.dump(report, stream, sort_keys=True, separators=(",", ":"))
    print(json.dumps(report))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("source", "restored", "fixtures", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(); main(args.source, args.restored, args.fixtures, args.output)
