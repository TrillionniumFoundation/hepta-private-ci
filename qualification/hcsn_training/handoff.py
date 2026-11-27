"""Fixed binary candidate fields for the existing Rust artifact owner adapter.

The owner compares these fields with independently retained admitted job facts.
The diagnostic JSON is hash-bound, not interpreted by the native adapter.
"""

import hashlib
import io
from pathlib import Path
import platform

import numpy
import scipy
import torch
from .joint_graph import digest, integer, sha256, strict_json

MAGIC = b"hepta.hcsn.task-bp-handoff.v1\0"


def execution_sources():
    root = Path(__file__).resolve().parents[1]
    paths = sorted((root/"hcsn").rglob("*.py")) + sorted(
        p for p in (root/"hcsn_training").glob("*.py") if not p.name.startswith("test"))
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def runtime_tuple(dtype):
    return dict(python=platform.python_version(), torch=str(torch.__version__), numpy=numpy.__version__,
                scipy=scipy.__version__, dtype=dtype, device="cpu")


def dataset_digest(request):
    return digest({key: request[key] for key in ("inputs", "targets", "target_time_micros")})


def encode_handoff(request, receipt, diagnostics, payload):
    if strict_json(diagnostics) != receipt or request["mechanism"] != "task_mse_bp_v1":
        raise ValueError("diagnostics/mechanism mismatch")
    saved = torch.load(io.BytesIO(payload), map_location="cpu", weights_only=True)
    source, runtime = execution_sources(), runtime_tuple(saved["dtype"])
    actual = dict(request_digest=digest(request), execution_source_digest=digest(source),
                  runtime_tuple_digest=digest(runtime), graph_digest=digest(saved["spec"]),
                  dataset_digest=dataset_digest(request), checkpoint_sha256=hashlib.sha256(payload).hexdigest())
    if (any(receipt[key] != value for key, value in actual.items()) or receipt["runtime_tuple"] != runtime
            or receipt["execution_sources"] != source):
        raise ValueError("handoff source/runtime/data/payload mismatch")
    hashes = (hashlib.sha256(request["operation_id"].encode()).hexdigest(), actual["request_digest"],
              actual["execution_source_digest"], actual["runtime_tuple_digest"], actual["graph_digest"],
              request["binding"]["profile_digest"], request["base_checkpoint"]["sha256"],
              actual["dataset_digest"], actual["checkpoint_sha256"], receipt["gradient_digest"],
              hashlib.sha256(diagnostics).hexdigest())
    values = (request["binding"]["generation"], request["optimizer_steps"], receipt["logical_cells"],
              receipt["trainable_parameters"], receipt["completed_optimizer_steps"],
              receipt["gradient_cells"], receipt["gradient_parameters"])
    return MAGIC+b"\0"+b"".join(bytes.fromhex(sha256(h)) for h in hashes)+b"".join(
        integer(v).to_bytes(8, "big") for v in values)
