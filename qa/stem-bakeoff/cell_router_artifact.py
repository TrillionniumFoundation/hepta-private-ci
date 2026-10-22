"""Bounded NPZ Router artifacts; retained digests prove integrity, not authority."""

from dataclasses import asdict
import hashlib
import io
import json
from pathlib import Path
import re
import stat
import zipfile

import numpy as np
import torch

from cell_head_training import TEMPERATURES, _json_bytes, _state_digest
from cell_router_training import (RouterTrainingConfigV1, RouterTrainingError,
                                  TrainedCellRouterV1, _check_cells, _new_router)
from feature_bundle import FeatureIdentityV1

MAX_WEIGHTS_BYTES = 8 * 1024 * 1024
MAX_MANIFEST_BYTES = 32 * 1024 * 1024


def save_router_artifact(router: TrainedCellRouterV1, directory):
    if (type(router) is not TrainedCellRouterV1
            or _state_digest(router._net) != router._report["trained_tensor_sha256"]):
        raise RouterTrainingError("Router weights changed before serialization")
    stream = io.BytesIO()
    np.savez(stream, **{name: value.detach().cpu().numpy()
                       for name, value in router._net.state_dict().items()})
    weights = stream.getvalue()
    manifest = _json_bytes({"schema": "hepta.cell-router-artifact.v1", "report": router.report,
        "weights_file": "weights.npz", "weights_file_sha256": hashlib.sha256(weights).hexdigest()})
    if len(weights) > MAX_WEIGHTS_BYTES or len(manifest) > MAX_MANIFEST_BYTES:
        raise RouterTrainingError("Router artifact exceeds byte budget")
    target = Path(directory)
    target.mkdir(mode=0o700, parents=False, exist_ok=False)
    for name, data in (("weights.npz", weights), ("manifest.json", manifest)):
        with (target / name).open("xb") as output:
            output.write(data)
    return {"directory": str(target), "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
            "weights_file_sha256": hashlib.sha256(weights).hexdigest()}


def load_router_artifact(directory, *, expected_manifest_sha256: str,
                         expected_identity: FeatureIdentityV1, cells):
    if (not isinstance(expected_manifest_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha256)
            or type(expected_identity) is not FeatureIdentityV1):
        raise RouterTrainingError("retained manifest digest and feature identity required")
    target = Path(directory)
    if target.is_symlink() or not target.is_dir():
        raise RouterTrainingError("Router artifact must be a real directory")
    payloads = {}
    for name, limit in (("manifest.json", MAX_MANIFEST_BYTES), ("weights.npz", MAX_WEIGHTS_BYTES)):
        path = target / name
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or not 0 < metadata.st_size <= limit:
            raise RouterTrainingError("Router artifact member exceeds file/byte boundary")
        payloads[name] = path.read_bytes()
        if len(payloads[name]) != metadata.st_size or len(payloads[name]) > limit:
            raise RouterTrainingError("Router artifact changed while reading")
    if hashlib.sha256(payloads["manifest.json"]).hexdigest() != expected_manifest_sha256:
        raise RouterTrainingError("Router manifest digest mismatch")
    try:
        manifest = json.loads(payloads["manifest.json"])
        report = manifest["report"]
        _, bindings, signature, _ = _check_cells(cells)
        config = RouterTrainingConfigV1(**report["config"])
        config.validate()
        if (manifest["schema"] != "hepta.cell-router-artifact.v1"
                or manifest["weights_file"] != "weights.npz"
                or hashlib.sha256(payloads["weights.npz"]).hexdigest() != manifest["weights_file_sha256"]
                or report["schema"] != "hepta.trained-cell-router.v1"
                or report["feature_identity"] != asdict(expected_identity)
                or signature != (expected_identity, report["feature_width"], report["task_count"])
                or bindings != report["cell_bindings"] or config.top_k > len(bindings)
                or report["authority"] != "DENY_ALL" or report["mode"] != "SHADOW_ONLY"
                or report["production_activation_allowed"] is not False
                or report["temperature"] not in TEMPERATURES or report["fixed_temperature"] not in TEMPERATURES
                or any(k not in {b["cell_id"] for b in bindings} or v not in TEMPERATURES
                       for k, v in report["single_cell_temperatures"].items())):
            raise RouterTrainingError("Router artifact identity, content or research boundary mismatch")
        net = _new_router(report["feature_width"], len(bindings), config)
        expected = net.state_dict()
        with zipfile.ZipFile(io.BytesIO(payloads["weights.npz"])) as archive:
            members = archive.infolist()
            if (len(members) != len(expected) or len({m.filename for m in members}) != len(members)
                    or sum(m.file_size for m in members) > MAX_WEIGHTS_BYTES):
                raise RouterTrainingError("Router tensor archive exceeds expansion budget")
        with np.load(io.BytesIO(payloads["weights.npz"]), allow_pickle=False) as archive:
            if set(archive.files) != set(expected):
                raise RouterTrainingError("Router tensor names differ")
            state = {}
            for name, tensor in expected.items():
                array = archive[name]
                if array.dtype != np.float32 or array.shape != tuple(tensor.shape) or not np.isfinite(array).all():
                    raise RouterTrainingError("Router tensor dtype/shape/finiteness mismatch")
                state[name] = torch.from_numpy(array.copy())
        net.load_state_dict(state, strict=True)
        if _state_digest(net) != report["trained_tensor_sha256"] or bool((net.scale <= 0).any()):
            raise RouterTrainingError("Router tensor digest or feature scaling mismatch")
        return TrainedCellRouterV1(net, expected_identity, report)
    except (KeyError, TypeError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
        if isinstance(error, RouterTrainingError):
            raise
        raise RouterTrainingError("malformed Router artifact") from error
