"""Export an immutable research Head for the Rust owner, using stdlib only.

No key or publication authority is supplied here. Runtime inference continues
to use the original P37 loader; this export preserves its exact manifest/NPZ.
"""

import argparse
import ast
import hashlib
import io
import json
import math
from pathlib import Path
import re
import struct
import subprocess
import zipfile

MAGIC = b"HEPTA-CELL-HEAD-BUNDLE-V1\0"
P37 = "dac730dc8ddbd96d87f6dc0c5eb94d3436d90a2b"
BASE = "qa/stem-bakeoff/"
EVIDENCE = BASE + "evidence/20261022-real-model/"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_tensors(weights, report):
    """Reproduce P37's name/shape/dtype/tensor digest without loading pickle."""
    width, config = report["feature_width"], report["config"]
    rank, tasks = config["adapter_rank"], config["task_count"]
    shapes = {"gate.weight": (1, width + config["state_width"]), "gate.bias": (1,),
              "down.weight": (rank, width), "up.weight": (width, rank)}
    for name, count in (("task_head", tasks), ("action_head", 4),
                        ("value_head", 1), ("uncertainty_head", 1)):
        shapes[name + ".weight"], shapes[name + ".bias"] = (count, width), (count,)
    digest = hashlib.sha256()
    with zipfile.ZipFile(io.BytesIO(weights)) as archive:
        entries = archive.infolist()
        require(len(entries) == len(shapes)
                and {entry.filename for entry in entries} == {name + ".npy" for name in shapes}
                and sum(entry.file_size for entry in entries) <= 16 * 1024 * 1024,
                "invalid tensor archive inventory or budget")
        for name, shape in sorted(shapes.items()):
            value = archive.read(name + ".npy")
            require(value[:8] == b"\x93NUMPY\x01\x00", "expected bounded NPY v1")
            header_size = struct.unpack("<H", value[8:10])[0]
            header = ast.literal_eval(value[10:10 + header_size].decode("ascii"))
            require(header == {"descr": "<f4", "fortran_order": False, "shape": shape},
                    "tensor shape/dtype/order mismatch")
            data = value[10 + header_size:]
            require(len(data) == math.prod(shape) * 4
                    and all(math.isfinite(v) for (v,) in struct.iter_unpack("<f", data)),
                    "invalid tensor values")
            digest.update(canonical([name, list(shape), "float32"]))
            digest.update(data)
    require(digest.hexdigest() == report["trained_tensor_sha256"], "trained tensor digest mismatch")


def build_bundle(manifest_bytes, weights, run_bytes, read_source):
    require(0 < len(manifest_bytes) <= 2 * 1024 * 1024
            and 0 < len(weights) <= 16 * 1024 * 1024, "payload budget")
    manifest, run = json.loads(manifest_bytes), json.loads(run_bytes)
    report = manifest["report"]
    # V1 binds only a fresh Head's train/calibration datasets. Warm starts and
    # distillation inherit additional sources that require the full evolution
    # snapshot; exporting just these NPZ bytes would erase that dependency cut.
    require("evolution" not in report,
            "descendant Head requires a complete evolution source closure")
    require(manifest["schema"] == "hepta.cell-head-artifact.v1"
            and manifest["weights_file"] == "weights.npz"
            and manifest["weights_file_sha256"] == sha(weights)
            and report["authority"] == "DENY_ALL" and report["mode"] == "SHADOW_ONLY"
            and report["production_activation_allowed"] is False
            and report["encoder_training_steps"] == 0
            and report["local_state_training"] == "zero_state_only"
            and report["source_groups_disjoint"] is True
            and report["optimizer_steps"] > 0
            and report["initial_tensor_sha256"] != report["trained_tensor_sha256"],
            "Head identity, training, or authority mismatch")
    arm = run["head_artifacts"][report["config"]["mode"]]
    require(arm["manifest_sha256"] == sha(manifest_bytes)
            and arm["weights_file_sha256"] == sha(weights)
            and arm["reload_prediction_exact"] is True
            and run["feature_identity"] == report["feature_identity"], "retained run pins mismatch")
    code = run["plan"]["code_file_sha256"]
    for name, expected in code.items():
        require("/" not in name and "\\" not in name and name not in (".", "..")
                and sha(read_source(BASE + name)) == expected, "recorded training code differs")
    verify_tensors(weights, report)
    source_sets = [set(report["splits"][split]["source_record_digests"])
                   for split in ("train", "calibration")]
    require(source_sets[0].isdisjoint(source_sets[1]), "train/calibration source overlap")
    datasets = []
    for split in ("train", "calibration"):
        cohort = report["splits"][split]
        datasets.append(sha(canonical({key: cohort[key] for key in (
            "labels_sha256", "source_group_sha256", "source_record_digests", "bundle_digests")})))
    identity = report["feature_identity"]
    feature = dict(encoder_digest=identity["encoder_sha256"],
                   checkpoint_digest=sha(identity["checkpoint_revision"].encode()),
                   preprocessing_digest=identity["preprocess_sha256"],
                   scope_digest=sha(identity["scope_id"].encode()),
                   purpose_digest=sha(identity["purpose"].encode()),
                   generation=identity["generation"], revocation_epoch=identity["revocation_epoch"],
                   width=report["feature_width"])
    require(type(feature["generation"]) is int and feature["generation"] > 0
            and type(feature["revocation_epoch"]) is int and feature["revocation_epoch"] >= 0
            and type(feature["width"]) is int and 1 <= feature["width"] <= 4096, "feature bounds")
    runtime = {key: run["runtime"][key] for key in ("python", "platform", "versions", "cuda_used")}
    pins = dict(manifest_digest=sha(manifest_bytes), weights_digest=sha(weights),
                source_frontier_digest=sha(canonical({"schema": "hepta.cell-head-input-frontier.v1",
                                                       "train": datasets[0], "calibration": datasets[1]})),
                training_dataset_digest=datasets[0], calibration_dataset_digest=datasets[1],
                training_code_digest=sha(canonical(code)), runtime_tuple_digest=sha(canonical(runtime)),
                trained_tensor_digest=report["trained_tensor_sha256"])
    feature_bytes = b"".join(bytes.fromhex(feature[key]) for key in (
        "encoder_digest", "checkpoint_digest", "preprocessing_digest", "scope_digest", "purpose_digest"))
    feature_bytes += struct.pack("<QQQ", feature["generation"], feature["revocation_epoch"], feature["width"])
    bundle = (MAGIC + feature_bytes + b"".join(bytes.fromhex(value) for value in pins.values())
              + struct.pack("<QQ", len(manifest_bytes), len(weights)) + manifest_bytes + weights)
    return bundle, dict(feature=feature, **pins, artifact_digest=sha(bundle),
                        compatibility_digest=sha(b"hepta.cell-head-feature.v1\0" + feature_bytes),
                        schema_profile_digest=sha(MAGIC), run_report_digest=sha(run_bytes))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--revision", default=P37)
    parser.add_argument("--mode", choices=("linear", "gated"), default="linear")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(re.fullmatch(r"[0-9a-f]{40}", args.revision) is not None, "immutable full commit required")

    def read_source(path):
        return subprocess.check_output(["git", "-C", str(args.repository), "show", args.revision + ":" + path])

    prefix = EVIDENCE + "granite-heads/" + args.mode + "/"
    manifest, weights = read_source(prefix + "manifest.json"), read_source(prefix + "weights.npz")
    run = read_source(EVIDENCE + "reports/granite97m.json")
    bundle, pins = build_bundle(manifest, weights, run, read_source)
    pins["source_commit"] = args.revision
    args.output.mkdir(parents=True, exist_ok=True)
    for name, value in (("head.bundle", bundle), ("manifest.json", manifest), ("weights.npz", weights),
                        ("pins.json", canonical(pins) + b"\n")):
        (args.output / name).write_bytes(value)
    print(json.dumps({"artifact_digest": pins["artifact_digest"], "bytes": len(bundle),
                      "source_commit": args.revision, "production_authority": False}))


if __name__ == "__main__":
    main()
