"""Sequential original/candidate diagnostic. Not a bakeoff execution receipt."""
if not __debug__:
    raise SystemExit("optimized Python disables evidence checks; run without -O")

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import tempfile

os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", USE_TF="0", OMP_NUM_THREADS="2", MKL_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", TOKENIZERS_PARALLELISM="false", HF_HUB_DISABLE_TELEMETRY="1")
for name in ("LAYA_CPU_AMP", "LAYA_CUDA_AMP"):
    os.environ.pop(name, None)
if sys.platform != "linux":
    raise SystemExit("this explicit CPU diagnostic profile requires Linux")
os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])

from provenance import validate_workspace

CODE = Path(__file__).resolve().parent
CHECKOUT = CODE.parents[2]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument("profile", choices=("official_reference", "readonly_candidate"))
p.add_argument("--workspace", required=True, type=Path)
p.add_argument("--snapshot", required=True, type=Path)
args = p.parse_args()
ROOT = args.workspace.resolve()
SNAPSHOT = args.snapshot.resolve()
sys.path.insert(0, str(CODE.parent))
from artifact_guard import SnapshotGuard, snapshot_files
from run_models import laya_calibration_identity
manifest = validate_workspace(ROOT)
if args.profile == "readonly_candidate":
    sys.path.insert(0, str(ROOT / "vendor"))
# Reject drift before importing executable SDK modules, not after their top-level code runs.
package_spec = importlib.util.find_spec("laya")
if package_spec is None or package_spec.origin is None:
    raise SystemExit("pinned official SDK is unavailable")
package_path = Path(package_spec.origin).parent
expected = manifest["source_files" if args.profile == "official_reference" else "derived_files"]
preimport = {str(path.relative_to(package_path)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(package_path.rglob("*.py"))}
if preimport != expected:
    raise ValueError("SDK source differs from reviewed pins before import")

import numpy as np
import torch
import laya
import laya.agent

torch.set_num_threads(2)
torch.set_num_interop_threads(1)
torch.manual_seed(0)
OUT = ROOT / args.profile
if OUT.exists():
    raise SystemExit("refuse to overwrite prior probe evidence")
OUT.mkdir()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


cases = json.loads((CODE / "cases.json").read_text())
case_path = ROOT / "cases.json"
if case_path.exists() and case_path.read_bytes() != (CODE / "cases.json").read_bytes():
    raise ValueError("workspace cases differ from the pinned mechanical fixtures")
case_path.write_bytes((CODE / "cases.json").read_bytes())
package = Path(laya.__file__).parent
expected = manifest["source_files" if args.profile == "official_reference" else "derived_files"]
assert {str(p.relative_to(package)): sha(p) for p in sorted(package.rglob("*.py"))} == expected
assert (SNAPSHOT / "encoder/config.json").is_file() and (SNAPSHOT / "tokenizer/tokenizer_config.json").is_file()
assert "auto_map" not in json.loads((SNAPSHOT / "encoder/config.json").read_text())
snapshot_manifest = json.loads((CODE / "snapshot.json").read_text())
if SNAPSHOT.name != snapshot_manifest["revision"]:
    raise ValueError("snapshot directory must identify the pinned revision")
original_inventory = snapshot_files(SNAPSHOT)
if original_inventory != snapshot_manifest["files"]:
    raise ValueError("snapshot differs from pinned observed publisher inventory")
expected_packages = {"laya": "0.4.14", "torch": "2.8.0+cpu", "transformers": "4.57.1", "numpy": "2.2.6", "safetensors": "0.8.0", "tokenizers": "0.22.2", "huggingface_hub": "0.36.2"}
if {name: importlib.metadata.version(name) for name in expected_packages} != expected_packages:
    raise ValueError("runtime package versions differ from the diagnostic profile")
captured = []
active = None


def before_forward(module, positional, keyword):
    names = ("input_ids", "attention_mask", "marker_pos", "marker_mask", "qtype")
    tensors = {name: value.detach().cpu().clone() for name, value in zip(names, positional)}
    tensors.update({name: value.detach().cpu().clone() for name, value in keyword.items() if torch.is_tensor(value)})
    entry = {"case": active, "inputs": {}, "outputs": {}}
    for name, value in tensors.items():
        path = OUT / f"forward-{len(captured):02d}-input-{name}.npy"
        np.save(path, value.numpy(), allow_pickle=False)
        entry["inputs"][name] = {"file": path.name, "shape": list(value.shape), "dtype": str(value.dtype), "sha256": sha(path)}
    captured.append(entry)


def after_forward(module, positional, outputs):
    for name, value in zip(("option_logits", "action_logits"), outputs):
        array = value.detach().cpu().clone().numpy()
        assert np.isfinite(array).all(), f"nonfinite {name}"
        path = OUT / f"forward-{len(captured)-1:02d}-output-{name}.npy"
        np.save(path, array, allow_pickle=False)
        captured[-1]["outputs"][name] = {"file": path.name, "shape": list(array.shape), "dtype": str(array.dtype), "sha256": sha(path)}


def run(path, guard=None):
    global active
    agent = laya.load(str(path), device="cpu", fast=False, compile=False)
    if guard:
        guard.verify("candidate_after_load")
    calibration = laya_calibration_identity(agent)
    assert agent.device.type == "cpu" and not agent.amp_enabled
    assert all(param.dtype == torch.float32 and param.device.type == "cpu" for param in agent.model.parameters())
    assert agent.model.encoder.config.reference_compile is False
    agent.model.register_forward_pre_hook(before_forward, with_kwargs=True)
    agent.model.register_forward_hook(after_forward)
    results = []
    with torch.inference_mode():
        for case in cases:
            active = case["name"]
            results.append(agent.predict_batch(case["states"], case["questions"], batch_size=2))
            if guard:
                guard.verify("candidate_after_inference_" + active)
            assert laya_calibration_identity(agent) == calibration
    assert agent.device.type == "cpu" and agent.cpu_fallback_count == 0
    return {"calibration_identity": calibration, "parameters": sum(x.numel() for x in agent.model.parameters()), "results": results, "raw_temperature": agent.temperature_raw, "effective_temperature": agent.temperature, "raw_buckets": agent.temperature_by_options_raw, "effective_buckets": agent.temperature_by_options, "cpu_fallback_count": agent.cpu_fallback_count}


if args.profile == "readonly_candidate":
    with SnapshotGuard(SNAPSHOT) as guard:
        profile = run(guard.path, guard)
        observed_changes = []
else:
    with tempfile.TemporaryDirectory(prefix="official-laya-diagnostic-") as temp:
        copy = Path(temp) / "snapshot"
        shutil.copytree(SNAPSHOT, copy, symlinks=False)
        profile = run(copy)
        after = snapshot_files(copy)
        observed_changes = sorted(key for key in set(original_inventory) | set(after) if original_inventory.get(key) != after.get(key))
        assert observed_changes == ["tokenizer/tokenizer_config.json"], observed_changes
        mutated = copy / observed_changes[0]
        assert sha(mutated) == "6c6b2d8e3c84ce0e671c129cd6b374b235d6f9863042a5836358d00a89bbb5a1"
        shutil.copy2(mutated, OUT / "sdk-mutated-tokenizer-config.json")
assert snapshot_files(SNAPSHOT) == original_inventory
assert {str(p.relative_to(package)): sha(p) for p in sorted(package.rglob("*.py"))} == expected
result = {"kind": "VERSIONED_READONLY_SDK_PARITY_DIAGNOSTIC_NOT_QUALIFICATION", "profile": args.profile, "derived_profile": manifest["profile"] if args.profile == "readonly_candidate" else None, "driver_sha256": sha(Path(__file__)), "provenance_sha256": sha(CODE / "provenance.py"), "source_manifest_sha256": sha(ROOT / "source-manifest.json"), "cases_sha256": sha(ROOT / "cases.json"), "original_snapshot": original_inventory, "original_snapshot_unchanged": True, "runtime_copy_observed_changes": observed_changes, "source_guard_commit": subprocess.check_output(["git", "-C", str(CHECKOUT), "rev-parse", "HEAD"], text=True).strip(), "source_worktree_dirty": bool(subprocess.check_output(["git", "-C", str(CHECKOUT), "status", "--porcelain"], text=True).strip()), "source_guard_sha256": sha(CHECKOUT / "qualification/neuron-model-bakeoff/artifact_guard.py"), "source_run_models_sha256": sha(CHECKOUT / "qualification/neuron-model-bakeoff/run_models.py"), "packages": {name: importlib.metadata.version(name) for name in ("laya", "torch", "transformers", "numpy", "safetensors", "tokenizers", "huggingface_hub")}, "cpu_threads": torch.get_num_threads(), "cpu_affinity": sorted(os.sched_getaffinity(0)), "device": "cpu", "dtype": "float32", "forward_observations": captured, "forward_calls": len(captured), "process_max_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024, "public_fixture_source": "https://huggingface.co/convaiinnovations/laya-multilingual/blob/1720e3e3357cfe1e281542e223f8273b0890ca34/README.md", "fixture_kind": "public model-card examples plus explicitly mechanical perturbations, no accuracy labels", "calibration_code_changed": False, "original_protocol_changed": False, "independent_acceptance": False, "all_blockers_closed": False, **profile}
(OUT / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({k: v for k, v in result.items() if k not in ("original_snapshot", "forward_observations", "results")}, indent=2))
