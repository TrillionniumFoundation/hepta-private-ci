#!/usr/bin/env python3
"""Post-freeze inventory and bounded archives; never edits study/candidate bytes."""
import argparse
from dataclasses import asdict
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import time

LIMIT = 512000


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def archive(root, output, paths):
    members = []
    with output.open("xb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode="w") as tar:
            for path in sorted(paths):
                data = path.read_bytes()
                name = str(path.relative_to(root))
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(data))
                members.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    if output.stat().st_size > LIMIT:
        raise ValueError(f"Archive exceeds policy: {output.name}")
    return {"path": str(output.relative_to(root)), "bytes": output.stat().st_size,
            "sha256": digest(output), "members": members}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    cap, run = root / "capsule", root / "run_v1"
    before = {str(p): digest(p) for p in run.rglob("*") if p.is_file()}
    sys.path.insert(0, str(cap))
    spec = importlib.util.spec_from_file_location("isolated_actual_study", cap / "study.py")
    study = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(study)
    if study.DEPENDENCY_ERROR:
        raise RuntimeError(study.DEPENDENCY_ERROR)
    study.validate_sources()
    torch = study.torch
    torch.set_num_threads(1)
    result = json.loads((run / "RESULT.json").read_text())
    rows = []
    start = time.perf_counter()
    for item in result["parents"]:
        n = item["width"]
        parent_path = (run / "n16/new_parent.pt" if n == 16 else
                       cap / f"parents/training/n{n}-qvi_full-s1101/checkpoint.pt")
        if digest(parent_path) != item["parent_sha256"]:
            raise ValueError("Parent identity changed")
        saved = torch.load(parent_path, map_location="cpu", weights_only=True)
        model = study.SmallHCSN(study.ModelConfig(**saved["config"]))
        model.load_state_dict(saved["selected_model"])
        allocated = model.recurrent.weight.numel()
        active = int(torch.count_nonzero(model.synaptic_mask))
        parameters = [{"name": name, "shape": list(p.shape), "count": p.numel(),
                       "requires_grad": p.requires_grad, "dtype": str(p.dtype)}
                      for name, p in model.named_parameters()]
        checks = {}
        for bank in ("value_risk", "tanh"):
            candidate_path = run / f"n{n}/{bank}_candidate.pt"
            expected = next(r["sha256"] for r in result["results"] if r["width"] == n and r["bank"] == bank)
            if digest(candidate_path) != expected:
                raise ValueError("Frozen candidate identity changed")
            candidate = torch.load(candidate_path, map_location="cpu", weights_only=True)
            checks[bank] = all(torch.equal(value, candidate["weights"][name])
                               for name, value in saved["selected_model"].items()
                               if not name.startswith("readout."))
        rows.append({"width": n, "parent_sha256": digest(parent_path),
                     "total_parameters": sum(p.numel() for p in model.parameters()),
                     "requires_grad_parameters": sum(p.numel() for p in model.parameters() if p.requires_grad),
                     "active_trainable_parameters": sum(p.numel() for p in model.parameters() if p.requires_grad) - allocated + active,
                     "recurrent_allocated": allocated, "recurrent_active_mask_entries": active,
                     "readout_parameters_updated_per_candidate": sum(p.numel() for p in model.readout.parameters()),
                     "physical_parent_tensors_unchanged_by_readout_fit": checks,
                     "config": asdict(model.config), "named_parameters": parameters})
    inventory = {"scope": "post-freeze tensor inventory; no training, selection or candidate mutation",
                 "source_sha256": digest(__file__), "study_sha256": digest(cap / "study.py"),
                 "rows": rows, "wall_s": time.perf_counter() - start,
                 "trainable_flags_are_capacity_not_an_assertion_all_parameters_updated": True,
                 "active_connections_are_fixed_mask_not_learned_topology": True}
    dump(root / "MODEL_PARAMETER_INVENTORY.json", inventory)
    freeze = subprocess.run([sys.executable, "-m", "pip", "freeze", "--all"],
                            check=True, capture_output=True, text=True)
    (root / "installed-packages.txt").write_text(freeze.stdout)
    if before != {str(p): digest(p) for p in run.rglob("*") if p.is_file()}:
        raise ValueError("Study evidence changed during inventory")
    out = root / "evidence_archives"
    out.mkdir(exist_ok=False)
    groups = {}
    for n in (8, 16, 32, 64):
        groups[f"n{n}"] = list((run / f"n{n}").glob("*.pt"))
    names = ["RUNTIME_DISCOVERY.json", "DEPENDENCY_INSTALL_RESULT.json", "EXECUTION_RECEIPT.json",
             "MODEL_PARAMETER_INVENTORY.json", "numpy-pip-report.json", "torch_cpu-pip-report.json",
             "numpy-install.log", "torch_cpu-install.log", "study.stdout.log", "study.stderr.log",
             "installed-packages.txt", "collect_evidence.py"]
    groups["metadata"] = [root / name for name in names] + list(run.glob("*.json"))
    bundles = [archive(root, out / f"{name}.tar.gz", paths) for name, paths in groups.items()]
    index = {"scope": "complete run_v1 candidate/replay evidence; runtime capsule separately pinned",
             "runtime_capsule_sha256": digest(root / "runtime_capsule.tar.gz"),
             "policy_blob_limit_bytes": LIMIT, "run_files_unchanged_after_collection": True,
             "bundles": bundles}
    dump(out / "ARCHIVE_INDEX.json", index)
    print(json.dumps({"inventory": inventory, "bundles": [{k: b[k] for k in ("path", "bytes", "sha256")} for b in bundles]}))


if __name__ == "__main__":
    main()
