"""Prove original parent-plan/report/initial configuration without any forward."""
import json
from pathlib import Path
import resource
import time
from audit_io import construction, require, save, sha
from replay import HERE, frozen


def main():
    start = time.monotonic()
    request = frozen()
    resource.setrlimit(resource.RLIMIT_AS, (request["limits"]["address_space_bytes"],) * 2)
    import torch
    torch.set_num_threads(1)
    snapshot = json.loads((HERE / "ORIGINAL_TERMINAL_SNAPSHOT.json").read_bytes())
    parents = {r["name"]: r for r in snapshot["fits"]}
    proofs, inputs = [], {}
    adapters = {r["name"]: r for r in json.loads((HERE / "CONFIGURATION_ADAPTER.json").read_bytes())}
    for fit in request["fits"]:
        name, adapter = fit["name"], adapters[fit["name"]]
        plan_path = Path(adapter["bound_parent_plan"]["path"])
        report_path = plan_path.with_name("result.json")
        expected_report = parents[name]["artifact_identities"]["result.json"]
        require(sha(report_path) == expected_report["sha256"], "original parent report byte binding")
        report = json.loads(report_path.read_bytes())
        require(report["plan_sha256"] == sha(plan_path) == adapter["bound_parent_plan"]["sha256"], "parent report to plan binding")
        plan = json.loads(plan_path.read_bytes())
        initial_path = Path(fit["initial"]["path"])
        require(sha(initial_path) == fit["initial"]["sha256"] == report["initialization_sha256"], "original initial bytes")
        initial = torch.load(initial_path, weights_only=True, map_location="cpu")
        expected = construction(plan)
        require(expected == report["model_configuration"] == initial["model_configuration"] == fit["model_configuration"], "four independent configuration representations")
        for path in (plan_path, report_path, initial_path):
            inputs[str(path)] = sha(path)
        proofs.append({"name": name, "configuration": expected, "parent_report_sha256": expected_report["sha256"],
                       "parent_plan_sha256": report["plan_sha256"], "initial_sha256": report["initialization_sha256"]})
    for path, expected in inputs.items():
        require(sha(path) == expected, "configuration proof input changed")
    frozen()
    save(HERE / "RUN_OUTPUT/CONFIGURATION_PROOF.json", {"status": "PASSED", "proofs": proofs, "inputs": inputs,
         "wall_seconds": time.monotonic() - start, "model_constructions_forwards_backwards_optimizer_operations": 0, "E_access": False})


if __name__ == "__main__":
    main()
