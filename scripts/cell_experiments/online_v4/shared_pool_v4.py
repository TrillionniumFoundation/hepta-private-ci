"""One admitted base with three separately verified research LoRA adapters."""

import copy
import gc
import os
from pathlib import Path
import re
import threading
import time

from .. import causal_probe_v3 as probe, causal_train_v3 as numeric, data
from ..coding_sft import file_hash, write_new
from .onpolicy_contract import legacy, require


def _note(error, message):
    """Keep cleanup diagnostics without requiring Python 3.11 add_note."""
    add_note = getattr(error, "add_note", None)
    if callable(add_note):
        add_note(message)
    else:
        error.cleanup_notes = [*getattr(error, "cleanup_notes", []), message]


def _release_view(view, torch):
    """Attempt every cleanup stage while preserving the first cleanup exception."""
    failures = []
    if view is not None:
        try:
            view.close()
        except BaseException as error:
            failures.append(("view.close", error))
        finally:
            view.model, view.tokenizer, view.closed = None, None, True
    try:
        gc.collect()
    except BaseException as error:
        failures.append(("garbage collection", error))
    try:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except BaseException as error:
        failures.append(("CUDA cache cleanup", error))
    if failures:
        primary = failures[0][1]
        for stage, error in failures[1:]:
            _note(
                primary, stage + " failed: " + type(error).__name__ + ": " + str(error)
            )
        raise primary


def adapter_parameters(model, label):
    """Normalize only this actual named adapter to the original default names."""
    result = []
    for name, value in model.named_parameters():
        for kind in ("lora_A", "lora_B"):
            marker = "." + kind + "." + label + "."
            if marker in name:
                result.append((name.replace(marker, "." + kind + ".default."), value))
    require(bool(result), "selected adapter has no actual LoRA tensors")
    return result


def verified_entries(manifests, root):
    """Bind all original manifests and their actual completed training records."""
    require(
        isinstance(manifests, dict) and len(manifests) == 3,
        "exactly three explicit research cells required",
    )
    require(
        all(
            isinstance(cell, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", cell)
            for cell in manifests
        ),
        "invalid Cell ID",
    )
    old = legacy()
    entries, base = {}, None
    for index, (cell, manifest) in enumerate(sorted(manifests.items())):
        require(
            manifest.get("schema") == old.MODEL_SCHEMA,
            "shared pool supports the original research adapters only",
        )
        identity = old.verify_model(manifest, root)
        candidate_base = manifest["base_manifest"]
        if base is None:
            base = copy.deepcopy(candidate_base)
        require(
            candidate_base == base
            and manifest["runtime"] == base["runtime"]
            and manifest["backend_versions"] == base["backend_versions"],
            "pool base bundle, runtime, or generation differs",
        )
        directory = probe._base(root, manifest["adapter_directory"])
        path = directory.parent / "TRAINING.json"
        require(
            path.is_file() and not path.is_symlink(),
            "actual adapter training record missing",
        )
        receipt = probe._json(path)
        require(
            receipt.get("status") == "COMPLETE"
            and receipt.get("research_model_digest") == identity
            and receipt.get("steps") == old.TRAINING["steps"]
            and type(receipt.get("trainable_parameters")) is int
            and receipt["trainable_parameters"] > 0,
            "actual training record is not bound to this research candidate",
        )
        after = receipt.get("parameter_after")
        require(
            isinstance(after, str)
            and len(after) == 64
            and all(c in "0123456789abcdef" for c in after),
            "adapter after hash missing",
        )
        entries[cell] = {
            "manifest": copy.deepcopy(manifest),
            "model_digest": identity,
            "adapter_label": "cell_" + str(index),
            "training": {
                "path": path.relative_to(root).as_posix(),
                "sha256": file_hash(path),
                "bytes": path.stat().st_size,
                "parameter_after": after,
                "trainable_parameters": receipt["trainable_parameters"],
            },
        }
    require(
        len({v["model_digest"] for v in entries.values()}) == 3,
        "three distinct candidate identities required",
    )
    return entries, base


class SharedAdapterPool:
    """Serial, process-owned inference. Public construction keeps every native gate."""

    def __init__(self, manifests, artifact_root):
        started, cpu = time.perf_counter(), time.process_time()
        root = Path(artifact_root)
        entries, base = verified_entries(manifests, root)
        runtime = base["runtime"]
        require(
            runtime["device"].startswith("cuda:")
            and runtime["dtype"] == "bfloat16"
            and runtime["min_cuda_free_bytes"] >= probe.MIN_CUDA_FREE_BYTES
            and runtime["max_input_tokens"] == 4096
            and runtime["max_new_tokens"] == 384,
            "frozen GPU resource and token admission required",
        )
        torch, _ = probe._libraries()
        probe.check_device(torch, runtime)
        torch.cuda.set_per_process_memory_fraction(
            0.70, torch.device(runtime["device"])
        )
        view = None
        try:
            view = probe.Predictor.__new__(probe.Predictor)
            probe.Predictor.__init__(view, base, root)
            self._install(view, entries, root, base)
            self.initialization_cost = {
                "wall_seconds": time.perf_counter() - started,
                "cpu_seconds": time.process_time() - cpu,
                "base_load_count": 1,
                "adapter_load_count": 3,
                "scope": "verification and one shared pool load",
                "monetary_cost": None,
                "energy_joules": None,
                "gpu_active_seconds": None,
                "complete": False,
                "shared_cost_do_not_sum_per_call": True,
            }
        except BaseException as error:
            try:
                _release_view(view, torch)
            except BaseException as cleanup_error:
                _note(
                    error,
                    "pool construction cleanup failed: "
                    + type(cleanup_error).__name__
                    + ": "
                    + str(cleanup_error),
                )
                for note in [
                    *getattr(cleanup_error, "__notes__", []),
                    *getattr(cleanup_error, "cleanup_notes", []),
                ]:
                    _note(error, note)
            finally:
                self._view, self._closed = None, True
            raise

    def _install(self, view, entries, root, base):
        """Internal numerical operation; called only after public admission."""
        import peft

        self._view, self._entries, self._root = view, copy.deepcopy(entries), Path(root)
        self._lock, self._owner_pid, self._closed = threading.Lock(), os.getpid(), False
        self._base_object_id = id(view.model)
        self.base_parameters = sum(p.numel() for p in view.model.parameters())
        for index, entry in enumerate(self._entries.values()):
            directory = str(probe._base(root, entry["manifest"]["adapter_directory"]))
            options = {
                "adapter_name": entry["adapter_label"],
                "is_trainable": False,
                "local_files_only": True,
            }
            if index == 0:
                view.model = peft.PeftModel.from_pretrained(
                    view.model, directory, **options
                )
            else:
                # Admitted PEFT 0.18 casts after loading; BF16 targets would lose
                # saved FP32 bits. Promote only this new label before the copy.
                config = peft.PeftConfig.from_pretrained(
                    directory, local_files_only=True
                )
                view.model._check_new_adapter_config(config, is_trainable=False)
                config.inference_mode = True
                view.model.add_adapter(entry["adapter_label"], config)
                view.model.base_model._cast_adapter_dtype(
                    adapter_name=entry["adapter_label"], autocast_adapter_dtype=True
                )
                view.model.load_adapter(directory, **options)
            self._activate(entry)
        self.resident_parameters = sum(p.numel() for p in view.model.parameters())
        require(
            self.resident_parameters
            == self.base_parameters
            + sum(
                e["training"]["trainable_parameters"] for e in self._entries.values()
            ),
            "resident parameter accounting differs from actual tensors",
        )
        self.inventory = {
            "schema": "hepta.shared-research-adapter-pool.v1",
            "base_manifest_digest": data.digest(base),
            "base_bundle_digest": data.digest(base.get("files", [])),
            "source_sha256": file_hash(__file__),
            "original_predictor_sha256": file_hash(probe.__file__),
            "base_parameters": self.base_parameters,
            "resident_parameters": self.resident_parameters,
            "generation_digest": view.generation_digest,
            "cells": {
                cell: {key: value for key, value in entry.items() if key != "manifest"}
                for cell, entry in self._entries.items()
            },
            "base_load_count": 1,
            "base_shared": True,
            "scientific_confirmation_qualified": False,
            "native_cell_adoption": False,
            "independent_sample_increment": 0,
        }
        self.pool_identity = data.digest(self.inventory)

    def _activate(self, entry):
        model = self._view.model
        require(
            id(model.get_base_model()) == self._base_object_id,
            "pool base object was replaced",
        )
        model.set_adapter(entry["adapter_label"])
        model.eval()
        model.requires_grad_(False)
        require(
            model.active_adapters == [entry["adapter_label"]]
            and not any(p.requires_grad for p in model.parameters()),
            "actual active adapter or frozen state differs",
        )
        parameters = adapter_parameters(model, entry["adapter_label"])
        actual = numeric._parameter_hash(parameters, self._view.torch)
        require(
            actual == entry["training"]["parameter_after"],
            "active adapter tensors differ from its actual training after hash",
        )
        count = sum(p.numel() for _, p in parameters)
        require(
            count == entry["training"]["trainable_parameters"],
            "active adapter count differs",
        )
        return actual, count

    def snapshot(self):
        return {
            "pool_identity": self.pool_identity,
            "inventory": copy.deepcopy(self.inventory),
            "initialization_cost": copy.deepcopy(self.initialization_cost),
        }

    def parameter_evidence(self, cell_id):
        entry = self._entries[cell_id]
        count = entry["training"]["trainable_parameters"]
        evidence = {
            "pool_identity": self.pool_identity,
            "model_digest": entry["model_digest"],
            "training": entry["training"],
            "actual_normalized_adapter_hash": entry["training"]["parameter_after"],
            "base_parameters": self.base_parameters,
            "adapter_parameters": count,
        }
        digest = data.digest(evidence)
        return {
            "active_parameters": self.base_parameters + count,
            "resident_parameters": self.resident_parameters,
            "parameter_source_digest": digest,
            "parameter_evidence_digest": digest,
            "parameter_source_evidence": copy.deepcopy(evidence),
        }

    def generate(self, cell_id, request, call_dir):
        with self._lock:
            require(
                not self._closed and os.getpid() == self._owner_pid,
                "pool is closed or used outside its owner process",
            )
            require(cell_id in self._entries, "unknown cell identity")
            entry, directory = self._entries[cell_id], Path(call_dir)
            started = time.perf_counter()
            write_new(
                directory / "POOL_INTENT.json",
                {
                    "pool_identity": self.pool_identity,
                    "cell_id": cell_id,
                    "model_digest": entry["model_digest"],
                    "request_digest": data.digest(request),
                    "automatic_retry": False,
                    "started_at_ns": time.time_ns(),
                },
            )
            write_new(directory / "POOL_REQUEST.json", request)
            try:
                actual, count = self._activate(entry)
                view = self._view
                view.manifest, view.model_digest = (
                    copy.deepcopy(entry["manifest"]),
                    entry["model_digest"],
                )
                output = probe.Predictor.predict(view, copy.deepcopy(request))
                write_new(directory / "POOL_RAW_OUTPUT.json", output)
                require(
                    output["loaded_model_digest"] == entry["model_digest"]
                    and output["generation_config_sha256"]
                    == self.inventory["generation_digest"],
                    "generation output is not bound to the selected actual adapter",
                )
                require(
                    view.model.active_adapters == [entry["adapter_label"]],
                    "active adapter changed during generation",
                )
                result = {
                    **output,
                    **self.parameter_evidence(cell_id),
                    "active_adapter": entry["adapter_label"],
                    "active_adapter_sha256": actual,
                    "pool_identity": self.pool_identity,
                    "base_load_count": 1,
                    "pool_call_wall_seconds": time.perf_counter() - started,
                    "pool_load_cost_is_shared": True,
                    "full_system_cost_complete": False,
                }
                write_new(directory / "POOL_RESULT.json", result)
                return result
            except BaseException as error:
                write_new(
                    directory / "POOL_FAILED.json",
                    {
                        "status": "FAILED_PRESERVED",
                        "error_type": type(error).__name__,
                        "error": str(error),
                        "wall_seconds": time.perf_counter() - started,
                        "token_counts_complete": False,
                        "automatic_retry": False,
                    },
                )
                raise

    def close(self):
        with self._lock:
            require(os.getpid() == self._owner_pid, "only the owner may close the pool")
            if not self._closed:
                view = self._view
                try:
                    _release_view(view, view.torch)
                finally:
                    self._view, self._closed = None, True
