"""Self-contained Adam checkpoints, bound to an externally retained run plan.

Manifest publication follows a completed synchronous optimizer step. Partial
files are retained but cannot load without the final manifest's external SHA.
This is a single-owner research format, not a power-loss or production claim.
"""

import hashlib
import json
import math
import os
from pathlib import Path
import stat

import numpy as np

from cell_learning_models import NumpyCellHead, canonical
from cell_microbatch_training import FrozenTrainingBank, frozen, identity
from cell_resumable_training import (EMPTY_TRAJECTORY, ResumableMicrobatchAdam,
                                     array_sha, source_pins)
from cell_runtime_bundle import check_npz


SCHEMA = "hepta.private-adam-checkpoint.v1"
MAX_BYTES = 512*1024**2


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def io_pins():
    return {name: file_sha(Path(__file__).with_name(name))
            for name in ("cell_optimizer_checkpoint.py", "cell_runtime_bundle.py")}


def ordinary_root(path):
    result = Path(path).absolute()
    if any(p.is_symlink() for p in (result, *result.parents)):
        raise ValueError("checkpoint paths cannot traverse symlinks")
    return result


def ordinary_file(path, limit):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= limit:
        raise ValueError("bounded independent ordinary checkpoint files required")
    return info.st_size


def layout(plan):
    """Derive exact tensor bounds from checked dimensions before any NPZ load."""
    inputs, model, limits = plan["inputs"], plan["model"], plan["limits"]
    for value, maximum in ((model["width"], 4096), (model["classes"], 256),
            (model["rank"], 32), (limits["max_parameters"], 1000000),
            (limits["max_tensor_bytes"], MAX_BYTES), (plan["optimizer"]["steps"], 100),
            (plan["order"]["microbatch"], 64)):
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError("checkpoint dimensions or optimizer bounds differ")
    if (model["classes"] < 2 or model["mode"] not in ("linear", "gated", "residual")
            or limits["max_tensor_bytes"] < 4096):
        raise ValueError("unsupported private Head schema")
    for key, maximum in (("cell_ids", 1024), ("bank_tasks", 64), ("source_ids", 16384)):
        if type(inputs[key]) is not list or not 1 <= len(inputs[key]) <= maximum:
            raise ValueError("bounded Cell/task/source populations required")
    count, tasks, sources = (len(inputs[k]) for k in ("cell_ids", "bank_tasks", "source_ids"))
    shape = inputs["arrays"]["indices"]["shape"]
    if type(shape) is not list or len(shape) != 2 or type(shape[1]) is not int or not 1 <= shape[1] <= 256:
        raise ValueError("bounded training row count required")
    rows, width, classes, rank = shape[1], model["width"], model["classes"], model["rank"]
    base = {"W": (width, classes), "b": (classes,)}
    if model["mode"] != "linear": base.update(a=(width,), g=(width,))
    if model["mode"] == "residual": base.update(V=(width, rank), U=(rank, width))
    parameters = sum(math.prod(s) for s in base.values())
    if parameters > limits["max_parameters"]:
        raise ValueError("private parameter cap exceeded before allocation")
    result = {prefix+name: ((count, *s), np.dtype("float64"))
              for prefix in ("p_", "m_", "v_") for name, s in base.items()}
    result.update(raw=((sources, width), np.dtype("float64")), normalized=((sources, width), np.dtype("float64")),
        indices=((tasks, rows), np.dtype("int64")), labels=((count, rows), np.dtype("int64")),
        steps=((count,), np.dtype("int64")))
    result.update({name: ((count,), np.dtype("float64")) for name in ("initial_loss", "final_loss", "maximum_norm")})
    for name in ("raw", "normalized", "indices", "labels"):
        if inputs["arrays"][name]["shape"] != list(result[name][0]):
            raise ValueError("input tensor schema disagrees with bound identities")
    total = sum(math.prod(s)*dtype.itemsize for s, dtype in result.values())
    active = min(count, plan["order"]["microbatch"])
    workspace = active*8*(32*rows*width+16*rows*classes+8*rows*rank+20*parameters+128)
    if total > min(MAX_BYTES, limits["max_tensor_bytes"]):
        raise ValueError("total uncompressed checkpoint exceeds the hard tensor cap")
    bank_bytes = sum(math.prod(result[k][0])*result[k][1].itemsize for k in ("raw", "normalized", "indices"))
    label_bytes = count*rows*8
    # Loaded arrays coexist with reconstructed state; normalization and class
    # weights also allocate temporary input tensors. Python/ZIP/BLAS are separate.
    return result, total, 2*total+bank_bytes+4*label_bytes+workspace


def save_optimizer_checkpoint(owner, directory, *, expected_plan_sha256):
    if type(owner) is not ResumableMicrobatchAdam:
        raise ValueError("explicit resumable optimizer owner required")
    owner._check(expected_plan_sha256)
    root = ordinary_root(directory)
    if root.exists():
        raise ValueError("checkpoint destination must be new")
    expected, total, restore_reservation = layout(owner.plan)
    if restore_reservation > MAX_BYTES:
        raise ValueError("checkpoint cannot be restored within the hard tensor reservation")
    metadata, arrays = owner.snapshot()
    if set(arrays) != set(expected) or any((v.shape, v.dtype) != expected[k] for k, v in arrays.items()):
        raise ValueError("optimizer state schema differs")
    pins = io_pins()
    root.mkdir(parents=True, exist_ok=False)
    with (root/"state.npz").open("xb") as stream:
        np.savez_compressed(stream, **arrays)
        stream.flush()
        os.fsync(stream.fileno())
    owner._check(expected_plan_sha256)
    if (owner._cursor != metadata["cursor"] or owner._trajectory != metadata["trajectory_sha256"]
            or pins != io_pins()):
        raise ValueError("owner or checkpoint implementation changed during save")
    metadata.update(schema=SCHEMA, arrays={k: {"shape": list(v.shape), "dtype": v.dtype.str,
        "sha256": array_sha(v)} for k, v in arrays.items()}, archive_sha256=file_sha(root/"state.npz"),
        archive_bytes=(root/"state.npz").stat().st_size, uncompressed_tensor_bytes=total,
        restore_tensor_reservation_bytes=restore_reservation, io_source_sha256=pins,
        authority="DENY_ALL", mode="SHADOW_ONLY", quality_qualified=False, calibration=None,
        optimizer_resume_supported=True, inference_publication=False, power_loss_tested=False)
    with (root/"checkpoint.json").open("xb") as stream:
        stream.write(canonical(metadata)+b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    return {"manifest_sha256": file_sha(root/"checkpoint.json"), "plan_sha256": owner.plan_sha256,
        "input_sha256": owner.input_sha256, "archive_bytes": metadata["archive_bytes"],
        "uncompressed_tensor_bytes": total, "restore_tensor_reservation_bytes": restore_reservation,
        "cursor": metadata["cursor"], "optimizer_updates": 0}


def load_optimizer_checkpoint(directory, *, expected_manifest_sha256, expected_plan_sha256,
                              expected_input_sha256, max_restore_tensor_bytes=MAX_BYTES):
    root = ordinary_root(directory)
    manifest, archive = root/"checkpoint.json", root/"state.npz"
    if not root.is_dir() or {p.name for p in root.iterdir()} != {manifest.name, archive.name}:
        raise ValueError("complete two-file optimizer checkpoint required")
    ordinary_file(manifest, 16*1024**2)
    if file_sha(manifest) != identity(expected_manifest_sha256):
        raise ValueError("external optimizer manifest identity differs")
    meta = json.loads(manifest.read_bytes())
    plan = meta["plan"]
    if (meta.get("schema") != SCHEMA or meta.get("authority") != "DENY_ALL"
            or meta.get("mode") != "SHADOW_ONLY" or meta.get("quality_qualified") is not False
            or meta.get("calibration") is not None or meta.get("optimizer_resume_supported") is not True
            or meta.get("inference_publication") is not False or meta.get("io_source_sha256") != io_pins()
            or meta["plan_sha256"] != identity(expected_plan_sha256)
            or hashlib.sha256(canonical(plan)).hexdigest() != expected_plan_sha256
            or plan["input_sha256"] != identity(expected_input_sha256)
            or hashlib.sha256(canonical(plan["inputs"])).hexdigest() != expected_input_sha256
            or plan["implementation"] != {"source_sha256": source_pins(), "numpy_version": np.__version__}):
        raise ValueError("checkpoint plan, input, implementation or authority differs")
    expected, total, reserve = layout(plan)
    if (type(max_restore_tensor_bytes) is not int or not 4096 <= max_restore_tensor_bytes <= MAX_BYTES
            or reserve > max_restore_tensor_bytes or total != meta["uncompressed_tensor_bytes"]
            or reserve != meta["restore_tensor_reservation_bytes"] or set(meta["arrays"]) != set(expected)
            or ordinary_file(archive, total+4096*len(expected)) != meta["archive_bytes"]
            or file_sha(archive) != meta["archive_sha256"]):
        raise ValueError("checkpoint byte identity or restore tensor reservation differs")
    for name, (shape, dtype) in expected.items():
        if meta["arrays"][name]["shape"] != list(shape) or meta["arrays"][name]["dtype"] != dtype.str:
            raise ValueError("manifest tensor shape or precision differs")
    check_npz(archive, expected)
    with np.load(archive, allow_pickle=False) as saved:
        arrays = {name: saved[name] for name in expected}
    if any(not np.isfinite(v).all() or array_sha(v) != meta["arrays"][k]["sha256"] for k, v in arrays.items()):
        raise ValueError("optimizer tensor bytes or finite state differ")
    if any(np.any(v < 0) for k, v in arrays.items() if k.startswith("v_") or k == "maximum_norm"):
        raise ValueError("negative Adam variance or gradient norm")
    inputs, model, config = plan["inputs"], plan["model"], plan["optimizer"]
    for name in ("raw", "normalized", "indices", "labels"):
        if array_sha(arrays[name]) != inputs["arrays"][name]["sha256"]:
            raise ValueError("restored training input differs from bound plan")
    bank = FrozenTrainingBank(inputs["feature_identity"], tuple(inputs["bank_tasks"]), tuple(inputs["source_ids"]),
        frozen(arrays["raw"]), frozen(arrays["normalized"]), frozen(arrays["indices"]))
    heads = []
    for at in range(len(inputs["cell_ids"])):
        head = NumpyCellHead(model["width"], model["classes"], model["mode"], model["rank"],
            max_parameters=plan["limits"]["max_parameters"])
        head.params = {k[2:]: v[at] for k, v in arrays.items() if k.startswith("p_")}
        head.feature_identity = bank.feature_identity
        heads.append(head)
    owner = ResumableMicrobatchAdam(heads, inputs["cell_ids"], inputs["cell_tasks"], bank, arrays["labels"],
        source_record_digests=inputs["source_record_digests"], steps=config["steps"],
        learning_rate=config["learning_rate"], l2=config["l2"], microbatch=plan["order"]["microbatch"],
        generation=inputs["generation"], **plan["limits"])
    initial = model["initial_parameter_digests"]
    if type(initial) is not list or len(initial) != len(heads):
        raise ValueError("initial private state binding is incomplete")
    for value in initial:
        identity(value)
    rebuilt = owner.plan
    rebuilt["model"]["initial_parameter_digests"] = initial
    if canonical(rebuilt) != canonical(plan):
        raise ValueError("unsupported optimizer, sampling or input plan")
    cursor = meta["cursor"]
    if type(cursor) is not int or not 0 <= cursor <= owner.total_block_steps:
        raise ValueError("checkpoint cursor outside frozen order")
    owner._cursor = cursor
    owner._trajectory = identity(meta["trajectory_sha256"])
    counts = owner.step_counts()
    if any(owner._core.state_digest(i) != initial[i] for i, step in enumerate(counts) if step == 0):
        raise ValueError("unvisited Cell parameters differ from the frozen initial identity")
    if (not np.array_equal(counts, arrays["steps"])
            or (cursor == 0 and owner._trajectory != EMPTY_TRAJECTORY)
            or any(np.any(v[counts == 0]) for k, v in arrays.items() if k.startswith(("m_", "v_"))
                   or k in ("initial_loss", "maximum_norm"))
            or np.any(arrays["final_loss"][counts < config["steps"]])):
        raise ValueError("Adam time, cursor or unvisited state differs")
    for name in owner._core._params:
        owner._core._m[name][:] = arrays["m_"+name]
        owner._core._v[name][:] = arrays["v_"+name]
    owner._initial[:], owner._final[:], owner._maximum_norm[:] = (arrays[k]
        for k in ("initial_loss", "final_loss", "maximum_norm"))
    owner._core.initial_digests = tuple(initial)
    owner._plan_bytes, owner.plan_sha256 = canonical(plan), expected_plan_sha256
    owner._check(expected_plan_sha256)
    if file_sha(manifest) != expected_manifest_sha256 or file_sha(archive) != meta["archive_sha256"]:
        raise ValueError("checkpoint changed during restore")
    return owner
