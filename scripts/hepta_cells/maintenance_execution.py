"""Per-version candidate binding for controlled maintenance, with optional HIA.

Every wrapper identity names the current inner model, exact compiled image,
compiler record, numeric runtime, task plan and loaded Cell module sources.
The hosted compiler is identified, not promoted to a self-hosted compiler.
"""

from dataclasses import asdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

import numpy as np
import numpy._core._multiarray_umath as numpy_backend

from .bundle import Bundle, OPTIONAL, REQUIRED
from .component_types import ComponentIdentity, StepResult, digest
from .hia_component import HiaCellComponent
from .maintenance_tasks import TOKENS, save
from .temporal_component import TemporalComponent


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def numeric_identity():
    return {
        "python": sys.version,
        "python_binary_sha256": file_hash(Path(sys.executable).resolve()),
        "python_cache_tag": sys.implementation.cache_tag,
        "numpy": np.__version__,
        "numpy_backend_sha256": file_hash(numpy_backend.__file__),
        "numpy_vendor_libraries": {
            p.name: file_hash(p)
            for p in sorted(
                (Path(np.__file__).resolve().parent.parent / "numpy.libs").glob("*")
            )
            if p.is_file()
        },
        "dtype": "numpy.float64",
        "machine": platform.machine(),
        "threads": {
            name: os.environ.get(name)
            for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
        },
    }


def load_transport(path, expected):
    if file_hash(path) != expected:
        raise ValueError("native transport source changed")
    name = "controlled_maintenance_native_transport"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def read_runtime_pins(raw):
    def unique(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate runtime pin")
            value[key] = item
        return value

    def invalid_constant(_):
        raise ValueError("non-finite runtime pin")

    pins = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)
    lengths = dict(source_commit=40, source_tree=40, binary_sha256=64, config_sha256=64)
    if not isinstance(pins, dict) or not lengths.keys() <= pins.keys():
        raise ValueError(
            "runtime pins require source commit/tree and binary/config digests"
        )
    if "origin_candidate_sha256" in pins:
        lengths["origin_candidate_sha256"] = 64
    for name, length in lengths.items():
        if not isinstance(pins[name], str) or not re.fullmatch(
            "[0-9a-f]{" + str(length) + "}", pins[name]
        ):
            raise ValueError("runtime pin has invalid digest: " + name)
    return pins


def freeze_runtime_pins(root, path):
    """Bind copied identity metadata; the outer owner must prove actual transport."""
    if path is None:
        return None
    raw = Path(path).resolve(strict=True).read_bytes()
    pins = read_runtime_pins(raw)
    copied = root / "RUNTIME_PINS.json"
    with copied.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return dict(
        identity=pins,
        path=str(copied.resolve()),
        sha256=hashlib.sha256(raw).hexdigest(),
        scope="identity binding only; actual runtime transport requires outer owner evidence",
    )


def freeze_native(root, record_path):
    """Copy and identify existing native artifacts before the task plan is sealed."""
    if record_path is None:
        return None
    record_path = Path(record_path).resolve(strict=True)
    raw = record_path.read_bytes()
    record = json.loads(raw)
    hepta = Path(record["hepta_root"]).resolve(strict=True)
    worker = hepta / "tools/cell_bridge_native.py"
    image = Path(record["image_path"]).read_bytes()
    source = (hepta / record["source_path"]).read_bytes()
    if (
        hashlib.sha256(image).hexdigest() != record["image_sha256"]
        or hashlib.sha256(source).hexdigest() != record["source_sha256"]
    ):
        raise ValueError("native build record does not match original bytes")
    destination = root / "native"
    destination.mkdir()
    copies = {
        "cell_bridge.so": image,
        "continuation.hepta": source,
        "transport.py": worker.read_bytes(),
        "build.json": raw,
    }
    for name, content in copies.items():
        with (destination / name).open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    worker_hash = file_hash(destination / "transport.py")
    module = load_transport(destination / "transport.py", worker_hash)
    if (
        record["compiler_commit"] != module.COMPILER_COMMIT
        or record["source_path"] != module.SOURCE_PATH
    ):
        raise ValueError("native source/compiler contract differs")
    subprocess.run(
        [
            "git",
            "-C",
            str(hepta),
            "diff",
            "--quiet",
            module.COMPILER_COMMIT,
            "--",
            "hepta",
            "docs/HIA_CORE_LOWERING_ABI.json",
            "docs/HIA_CORE_EMITTER_ABI.json",
            "docs/HIA_BYTE_WRAPPER_ABI.json",
            "docs/HIA_MACHINE_OBJECT_ABI.json",
        ],
        check=True,
    )
    return {
        "hepta_root": str(hepta),
        "worker_path": str((destination / "transport.py").resolve()),
        "worker_sha256": worker_hash,
        "image_path": str((destination / "cell_bridge.so").resolve()),
        "image_sha256": record["image_sha256"],
        "source_path": record["source_path"],
        "source_sha256": record["source_sha256"],
        "compiler_commit": record["compiler_commit"],
        "compiler_implementation_sha256": record["compiler_implementation_sha256"],
        "build_record_sha256": hashlib.sha256(raw).hexdigest(),
        "original_compile_wall_ns": record["compile_wall_ns"],
        "compile_cost_scope": "prior shared build, not repeated in this run",
    }


def bundle(kernel, plan_hash):
    components = {
        key: digest(["controlled-fixture", plan_hash, key]) for key in REQUIRED
    }
    components.update({key: None for key in OPTIONAL})
    components.update(
        base=kernel.kernel_sha256,
        heads=kernel.heads_sha256,
        composition=kernel.config.sha256,
    )
    return Bundle(kernel.cell_id + "-parent", 1, components)


class DiagnosticComponent:
    def __init__(self, cell, plan_hash):
        self.identity = ComponentIdentity(
            "maintenance.diagnostic.v1", digest([cell, plan_hash, list(TOKENS)])
        )

    def initial_state(self):
        return {"diagnostics": 0}

    def step(self, payload, state, context):
        if context.identity != self.identity or set(payload) != {"diagnostic"}:
            raise ValueError("diagnostic Cell input/identity mismatch")
        start, cpu = time.perf_counter_ns(), time.process_time_ns()
        action = next(
            i for i, token in enumerate(TOKENS) if token in payload["diagnostic"]
        )
        return StepResult(
            {
                "action": action,
                "wall_ns": time.perf_counter_ns() - start,
                "cpu_ns": time.process_time_ns() - cpu,
            },
            {"diagnostics": state["diagnostics"] + 1},
            len(TOKENS),
        )


class RuntimeBinding:
    """One immutable experiment context, separate manifests for actual versions."""

    def __init__(
        self, root, plan_hash, source_hashes, numeric, native, runtime_pins=None
    ):
        self.root, self.plan_hash = Path(root), plan_hash
        self.sources, self.numeric, self.native_spec = source_hashes, numeric, native
        self.runtime_pins = runtime_pins
        if runtime_pins is not None:
            raw = Path(runtime_pins["path"]).read_bytes()
            if (
                hashlib.sha256(raw).hexdigest() != runtime_pins["sha256"]
                or read_runtime_pins(raw) != runtime_pins["identity"]
            ):
                raise ValueError("retained runtime identity binding changed")
        if numeric_identity() != numeric:
            raise ValueError("numeric runtime differs from frozen plan")
        self.native = None
        if native is not None:
            module = load_transport(native["worker_path"], native["worker_sha256"])
            self.native = module.NativeCellBridge(
                Path(native["hepta_root"]),
                Path(native["image_path"]),
                native["image_sha256"],
                expected_source_sha256=native["source_sha256"],
            )
        (self.root / "versions").mkdir(exist_ok=True)

    def close(self):
        if self.native is not None:
            self.native.close()

    def spec(self):
        return dict(
            root=str(self.root.resolve()),
            plan_hash=self.plan_hash,
            source_hashes=self.sources,
            numeric=self.numeric,
            native=self.native_spec,
            runtime_pins=self.runtime_pins,
        )

    def wrap(self, owner, inner, kernel=None, bound=None, *, expected_manifest=None):
        model = (
            {
                "kind": "gru",
                "cell_id": kernel.cell_id,
                "config": asdict(kernel.config),
                "weights_sha256": kernel.weights_sha256,
                "kernel_sha256": kernel.kernel_sha256,
                "heads_sha256": kernel.heads_sha256,
                "optimizer_sha256": kernel.optimizer_sha256,
                "bundle": asdict(bound),
                "bundle_sha256": bound.digest(),
            }
            if kernel is not None
            else {"kind": "deterministic", "rules": list(TOKENS)}
        )
        manifest = dict(
            schema="hepta.controlled-maintenance-candidate.v1",
            plan_sha256=self.plan_hash,
            source_sha256=self.sources,
            numeric=self.numeric,
            native=self.native_spec,
            runtime_pins=self.runtime_pins,
            inner_identity=asdict(inner.identity),
            model=model,
        )
        raw = (
            json.dumps(manifest, sort_keys=True, indent=2, allow_nan=False) + "\n"
        ).encode()
        candidate_hash = hashlib.sha256(raw).hexdigest()
        if expected_manifest is not None and candidate_hash != expected_manifest:
            raise ValueError("cold candidate manifest differs from original version")
        path = self.root / "versions" / (candidate_hash + ".json")
        if path.exists():
            if path.read_bytes() != raw:
                raise ValueError("retained candidate manifest changed")
        else:
            if expected_manifest is not None:
                raise ValueError("original cold candidate manifest is missing")
            save(path, manifest)
        if self.native is None:
            return inner, candidate_hash
        return HiaCellComponent(
            owner,
            inner,
            self.native,
            candidate_sha256=candidate_hash,
            image_sha256=self.native_spec["image_sha256"],
        ), candidate_hash

    def component(self, owner, kernel, bound, run, *, expected_manifest=None):
        return self.wrap(
            owner,
            TemporalComponent(kernel, bound, run),
            kernel,
            bound,
            expected_manifest=expected_manifest,
        )


def cell_output(receipt):
    output = receipt["output"]
    return output["cell"] if "hia" in output else output
