"""Independent adapter-consumer and causal edge-case regression checks."""

import ast
import hashlib
import inspect
import json
from pathlib import Path
import textwrap

import numpy as np
import torch

from experiments.hcsn_addressed_flow_20261101 import addressed_models, data
from experiments.hcsn_four_stage_flow_20261031.models import ContentModel
from . import audit, fused_addressed


def run():
    torch.set_num_threads(1)
    torch.manual_seed(971490)
    parsed = ast.parse(textwrap.dedent(inspect.getsource(addressed_models.AddressedModel.forward)))
    consumed = {n.slice.value for n in ast.walk(parsed) if isinstance(n, ast.Subscript)
                and isinstance(n.value, ast.Name) and n.value.id == "matrices"
                and isinstance(n.slice, ast.Constant)}
    checks = [dict(name="addressed_consumes_exact_returned_fields",
                   fields=sorted(consumed), passed=consumed == {"initial", "P", "T", "R", "MR"})]
    original = ContentModel._flow_matrices
    for task in ("mqar", "binding"):
        model = addressed_models.AddressedModel("flow").eval()
        model.load_state_dict(torch.load(audit.checkpoint(task), weights_only=True, map_location="cpu"))
        for case in ("missing", "all_unobserved", "zero_time", "no_marks"):
            arrays = data.batch(task, 3, 971490, "dev", "missing")
            if case == "all_unobserved":
                arrays["observed"][:] = False
            if case == "zero_time":
                arrays["dt"][:] = 0
            model.intervention = "no_marks" if case == "no_marks" else None
            result = audit.numerical(model, arrays)
            result.update(name=f"{task}/{case}/logits_and_parameter_gradients")
            checks.append(result)
            x, dt, seen = [torch.from_numpy(arrays[k]) for k in ("x", "dt", "observed")]
            with torch.no_grad():
                encoded = model.encode(x)
                baseline = original(model, encoded, dt, seen)
                fused = fused_addressed.prepare(model, encoded, dt, seen)
            errors = {k: float((baseline[k] - fused[k]).abs().max()) for k in consumed}
            checks.append(dict(name=f"{task}/{case}/all_consumed_matrices",
                               errors=errors, passed=max(errors.values()) <= 1e-6))
        checks.append(dict(name=task + "/context_restoration",
                           passed=ContentModel._flow_matrices is original))
    result = dict(schema="hcsn.addressed-preparation-contract.v1", checks=checks,
                  passed=all(r["passed"] for r in checks),
                  source_sha256={str(p.relative_to(audit.ROOT)): audit.digest(p)
                                 for p in (Path(__file__), Path(fused_addressed.__file__),
                                           Path(audit.__file__), Path(addressed_models.__file__))})
    audit.write(audit.HERE / "CONTRACT_CHECKS.json", result)
    print(json.dumps({"passed": result["passed"], "checks": len(checks)}))


if __name__ == "__main__":
    run()
