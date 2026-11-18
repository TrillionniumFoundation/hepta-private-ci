"""Admit the frozen parent and verified-credit student without changing either schema."""

import copy
import importlib.util
from pathlib import Path
import sys
import time

from .. import causal_probe_v3 as probe, data, matched_info_sft_v4 as matched
from ..coding_sft import file_hash
from .matched_pool_v4 import runtime_sources, saved_parameter_count
from .onpolicy_contract import require
from .shared_pool_v4 import SharedAdapterPool

MODELS = {
    "P": "430f4051d47672d121a5d790aca0e489804b0d8419c101e3c1171b3d17157786",
    "C": "785bc1cea2996e33cfe02c9c51a5a3802c931b010060369fc659b47fde4440a1",
}
PARAMETERS = {
    "P": "e5da16c3256c27f06f42ecac69880ce8802a0eb3a87c05830d11c09477aa817f",
    "C": "549ac578447c41d1ddc975f14468c54eeae12ba431f47bcd1a3da46fbc17ce8f",
}


def load_current(candidate_source, manifest):
    """Import only the original trainer's manifest-bound admission and cold loader."""
    require(
        data.digest(manifest) == MODELS["C"],
        "only the frozen verified-credit manifest may select an admission loader",
    )
    source = Path(candidate_source).resolve(strict=True)
    path = source / "current_credit.py"
    require(
        path.is_file()
        and not path.is_symlink()
        and file_hash(path) == manifest["candidate_files"]["current_credit.py"],
        "original current-credit loader differs from the frozen training source",
    )
    name = "_frozen_current_credit_e4"
    if name in sys.modules:
        module = sys.modules[name]
        require(
            Path(module.__file__).resolve(strict=True) == path,
            "current-credit import was redirected",
        )
        return module
    spec = importlib.util.spec_from_file_location(name, path)
    require(
        spec is not None and spec.loader is not None,
        "current-credit loader cannot be imported",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
    return module


def admit_credit(manifests, artifact_root, training_source, candidate_source):
    """Preserve original source, model, completed-training and numerical identities."""
    require(
        isinstance(manifests, dict) and set(manifests) == set(MODELS),
        "exactly the frozen parent P and verified-credit C are required",
    )
    require(
        all(data.digest(manifests[cell]) == MODELS[cell] for cell in MODELS),
        "only the two frozen manifest identities are admitted",
    )
    root, training_source = Path(artifact_root), Path(training_source)
    parent, candidate = manifests["P"], manifests["C"]
    require(
        matched.verify_manifest(parent, root, training_source) == MODELS["P"]
        and parent["objective"] == "all_actions"
        and parent["parameter_after"] == PARAMETERS["P"],
        "frozen matched parent identity differs",
    )
    actual_runtime = runtime_sources(parent)
    credit = load_current(candidate_source, candidate)
    require(
        credit.verify_manifest(candidate, root, training_source, candidate_source)
        == MODELS["C"]
        and candidate["objective"] == "verified_credit"
        and candidate["parent_manifest"] == parent
        and candidate["parameter_before"] == PARAMETERS["P"]
        and candidate["parameter_after"] == PARAMETERS["C"],
        "frozen verified-credit identity or parent differs",
    )
    base = parent["base_manifest"]
    entries = {}
    for index, cell in enumerate(MODELS):
        manifest = manifests[cell]
        require(
            data.digest(manifest) == MODELS[cell]
            and manifest["base_manifest"] == base
            and manifest["runtime"] == parent["runtime"]
            and manifest["backend_versions"] == parent["backend_versions"],
            "parent/credit base, runtime, backend or manifest differs",
        )
        directory = probe._base(root, manifest["adapter_directory"])
        receipt_path = directory.parent / "TRAINING.json"
        require(
            receipt_path.is_file() and not receipt_path.is_symlink(),
            "completed original training receipt required",
        )
        receipt = probe._json(receipt_path)
        require(
            receipt.get("status") == "COMPLETE"
            and receipt.get("model_digest") == MODELS[cell]
            and receipt.get("steps") == 64
            and all(
                receipt.get(key) == manifest[key]
                for key in (
                    "objective",
                    "parameter_before",
                    "parameter_after",
                    "train_records_digest",
                    "encoded_groups_digest",
                )
            ),
            "completed training does not bind the selected adapter",
        )
        count = saved_parameter_count(directory)
        require(count == 544768, "frozen adapter parameter count differs")
        entries[cell] = {
            "manifest": copy.deepcopy(manifest),
            "model_digest": MODELS[cell],
            "adapter_label": "cell_" + str(index),
            "training": {
                "path": receipt_path.relative_to(root).as_posix(),
                "sha256": file_hash(receipt_path),
                "bytes": receipt_path.stat().st_size,
                "parameter_after": PARAMETERS[cell],
                "trainable_parameters": count,
                "parameter_count_source": "hash-admitted saved FP32 matrices; actual load checked separately",
                "actual_runtime_sources": actual_runtime,
                "original_training_source_digest": data.digest(
                    parent["source_inventory"]
                ),
                "original_credit_candidate_digest": data.digest(
                    candidate["candidate_files"]
                ),
                "current_credit_loader_sha256": file_hash(credit.__file__),
                "admission_source_sha256": file_hash(__file__),
                "scope": "fixed parent and its verified-credit update; not independent teachers",
            },
        }
    return entries, copy.deepcopy(base)


class CurrentCreditAdapterPool(SharedAdapterPool):
    """Use the existing active-adapter and exact FP32 tensor checks for two Cells."""

    def __init__(self, manifests, artifact_root, training_source, candidate_source):
        started, cpu = time.perf_counter(), time.process_time()
        root = Path(artifact_root)
        entries, base = admit_credit(manifests, root, training_source, candidate_source)
        self._initialize(entries, base, root, started, cpu)
