"""Direct original-Torch/native logits and typed outputs, with exact input hashes.

The original loader and forward/predict functions are used without rewriting
their formula. Both original batch-one execution and the batch-eight fixture
check are reported; neither is confused with the NumPy fixture error.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True

import numpy as np
import torch


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def decoded(model, kind, features):
    prediction = model.predict(features)
    values = []
    for index in range(len(features)):
        if kind == "semantic":
            fields = [sum(int(prediction["bits"][index, 4 * field + bit]) << bit for bit in range(4)) for field in range(3)]
            values.append({"kind": "semantic", **dict(zip(("reserve", "pack", "limit"), fields, strict=True))})
        else:
            values.append({"kind": "skill", "program": [int(prediction[f"op{step}"][index]) for step in range(4)]})
    return values


def main(args):
    if args.output.exists(): raise FileExistsError(args.output)
    sys.path.insert(0, str(args.source.resolve()))
    from tensor_cell import TensorCell
    torch.set_num_threads(1)
    native_raw = args.native.read_bytes()
    native = json.loads(native_raw)
    if native["schema"] != "hepta.memory.actual-native-residual-logits.v1" or len(native["models"]) != 6:
        raise ValueError("actual native export contract differs")
    seen, results = set(), []
    for entry in native["models"]:
        seed, kind = entry["seed"], entry["kind"]
        if seed not in (731,732,733) or kind not in ("semantic","skill") or (seed,kind) in seen:
            raise ValueError("native model inventory differs")
        seen.add((seed,kind))
        fixture_raw = (args.fixtures / f"seed-{seed}-{kind}.json").read_bytes()
        fixture = json.loads(fixture_raw)
        if sha(fixture_raw) != entry["fixture_sha256"] or fixture["artifact_sha256"] != entry["artifact_sha256"]:
            raise ValueError("native export used different fixture or parameter artifact bytes")
        model = TensorCell.load(args.restored / "models" / f"seed-{seed}" / kind, expected_encoder_sha=fixture["encoder_sha256"])
        if model.parameter_digest() != entry["parameter_sha256"] or model.parameter_digest() != fixture["parameter_sha256"]:
            raise ValueError("original/native parameter identity differs")
        x = np.asarray([row["features"] for row in fixture["cases"]], dtype=np.float32)
        if len(entry["cases"]) != len(x): raise ValueError("native input count differs")
        for index, row in enumerate(entry["cases"]):
            if row["index"] != index or row["features_f32le_sha256"] != sha(x[index].astype("<f4").tobytes()):
                raise ValueError("native/original input bytes differ")
        native_logits = np.asarray([row["logits"] for row in entry["cases"]], dtype=np.float32)
        native_values = [row["value"] for row in entry["cases"]]
        comparisons = []
        for batch in (1, len(x)):
            logits = np.concatenate([model.raw_outputs(x[start:start+batch]) for start in range(0,len(x),batch)])
            values = [value for start in range(0,len(x),batch) for value in decoded(model,kind,x[start:start+batch])]
            if native_logits.shape != logits.shape or not np.isfinite(native_logits).all():
                raise ValueError("native logit dimension or finite bound differs")
            errors = np.abs(native_logits - logits)
            within_tolerance = bool(np.all(errors <= 1e-4 + 1e-5 * np.abs(logits)))
            equal = native_values == values
            comparisons.append({"original_batch_size":batch, "maximum_absolute_logit_error":float(errors.max()),
                                "typed_values_equal":equal, "within_predeclared_tolerance":within_tolerance})
        results.append({"seed":seed,"kind":kind,"cases":len(x),"parameter_sha256":model.parameter_digest(),"comparisons":comparisons})
    source_raw = (args.source / "tensor_cell.py").read_bytes()
    report = {"schema":"hepta.memory.direct-original-torch-native-comparison.v1","native_export_sha256":sha(native_raw),
              "torch_version":torch.__version__,"source_sha256":sha(source_raw),"cases":sum(row["cases"] for row in results),
              "tolerance":{"absolute":1e-4,"relative":1e-5},"results":results,
              "all_passed":all(case["typed_values_equal"] and case["within_predeclared_tolerance"] for row in results for case in row["comparisons"])}
    args.output.write_text(json.dumps(report,sort_keys=True,separators=(",",":")))
    print(json.dumps(report))
    if not report["all_passed"]:
        raise ValueError("direct numeric qualification failed; retain the complete comparison report")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("source","restored","fixtures","native","output"):
        parser.add_argument("--"+name,type=Path,required=True)
    main(parser.parse_args())
