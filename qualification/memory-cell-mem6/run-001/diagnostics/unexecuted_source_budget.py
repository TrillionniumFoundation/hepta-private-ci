"""Account for remaining released source groups after the frozen MEM6 cohorts."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path("/home/qq/mem6-attribution-20261110-484c")
SOURCE = ROOT / "source-8cf848ba"
request = json.loads((ROOT / "retention-request.json").read_bytes())
sys.path[:0] = [str(SOURCE), str(SOURCE / "scripts")]
from ndu_real_runtime import run_candidate_retention as legacy
from ndu_real_runtime.candidate_selection_plan import prior_source_groups
materials = Path(request["config"]["material_root"])
catalog = json.loads(legacy.read_pin(request["catalog"], materials))
excluded, _ = legacy.exclusions(request, catalog, materials)
prior, _ = prior_source_groups(request, catalog, materials)
excluded.update(prior)
roles = {}
for case in catalog["cases"]:
    if case["role"] in {"development", "retention_validation"} and case["source_id"] not in excluded:
        if case["source_id"] in roles:
            assert roles[case["source_id"]] == case["role"]
        roles[case["source_id"]] = case["role"]
used, pins = set(), []
for name in ("retention", "selector"):
    path = ROOT / (name + "-run-001/PLAN.json")
    raw = path.read_bytes()
    plan = json.loads(raw)
    groups = {row["source_group_id"] for row in plan["episodes"]}
    assert not used & groups
    used.update(groups)
    pins.append({"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
assert used <= set(roles)
left = sorted(set(roles) - used)
record = {"schema": "hepta.mem6.postrun-source-budget.v1",
          "source_commit": "8cf848babdd897e9f38642d5faf3ba0f72a1303c",
          "catalog": request["catalog"], "completed_plans": pins,
          "before_joint_allocation": dict(Counter(roles.values())),
          "used_this_run": dict(Counter(roles[group] for group in used)),
          "remaining": dict(Counter(roles[group] for group in left)),
          "remaining_source_groups": left, "remaining_total": len(left),
          "newly_exposed_source_groups": sorted(used),
          "minimum_source_groups_for_existing_retention_gate": 20,
          "remaining_registry_meets_existing_source_count": len(left) >= 20,
          "source_independence_authenticated": False,
          "scientific_acceptance": "HOLD", "production_adoption": False}
with (ROOT / "POSTRUN_SOURCE_BUDGET.json").open("x") as stream:
    stream.write(json.dumps(record, sort_keys=True, indent=2) + "\n")
print(json.dumps({k:v for k,v in record.items() if k not in {"remaining_source_groups","newly_exposed_source_groups","catalog","completed_plans"}}), flush=True)
