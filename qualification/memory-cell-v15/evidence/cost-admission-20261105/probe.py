"""Compare actual admission outcomes on pinned old/new modules; synthetic only."""
import hashlib
import json
from dataclasses import replace
from pathlib import Path
import sys

source = Path(sys.argv[1]).resolve()
source_names = ("admission.py", "cohort.py", "admission_test_support.py", "isolated_runner.py")
source_before = {name: hashlib.sha256((source / name).read_bytes()).hexdigest()
                 for name in source_names if (source / name).exists()}
sys.path.insert(0, str(source))
import admission as a
from admission_test_support import fixture_registration


def observe(name):
    cases = tuple(a.Case(str(i), str(i), "retained", str(i), None, True) for i in range(256))
    prices = (("train_cpu_s", 1.0),)
    limits = (("serve_cpu_s", 32.0), ("peak_rss_bytes", 256 * 1024 * 1024))
    if name == "empty_cost_model_and_caps":
        prices, limits = (), ()
    workload = a.digest({"uniform_cluster_fixture": 256})
    extra = {}
    if "cost_model" in a.Protocol.__dataclass_fields__:
        extra = {"cost_model": "resources",
                 "zero_cost_reasons": tuple((k, "Synthetic control: explicitly unpriced resource")
                                             for k in a.COSTS if k not in dict(prices)),
                 "workload_digest": workload}
    changing_protocol = name == "changed_protocol_after_freeze"
    protocol = a.Protocol("cost-probe", True, 256, .05, 1, .5 if changing_protocol else .25, 16, 1.0,
                          ("retained",), prices, limits,
                          planned_looks=10000 if changing_protocol else 1, **extra)
    budget = a.digest({"schema": "hepta.memory.resource-budget.v1", "limits": sorted(limits),
                       "deadline_seconds": 1.0, "worker_cpu_seconds": 30,
                       "worker_wall_seconds": 60.0, "worker_address_space_bytes": 1073741824})
    if name == "matching_arbitrary_budget_label":
        budget = "same-arbitrary-budget"
    candidate = a.Run("new", "memory", "training", "executor", budget,
                      lambda _: True, "encoder", "decoder", "tools")
    control_predict = ((lambda q: int(q) < 192) if changing_protocol else
                       (lambda _: True) if name == "shared_executor_backing_state" else (lambda _: False))
    incumbent = a.Run("old", "memory", "training", "executor", budget, control_predict,
                      "encoder", "decoder", "tools")
    registration = fixture_registration(cases, protocol, candidate, incumbent)
    shared = {"calls": 0}
    def shared_factory():
        def execute(choice, payload):
            shared["calls"] += 1
            return shared["calls"] <= len(cases)
        return execute
    factory = shared_factory if name == "shared_executor_backing_state" else (lambda: (lambda choice, payload: choice))
    evaluator = a.MatchedEvaluator(cases, factory,
                                   protocol, registration=registration)

    def ledger(run):
        binding = (evaluator.cost_binding(run) if hasattr(evaluator, "cost_binding") else {
            "bundle": run.bundle, "protocol": protocol.identity,
            "protocol_settings": a.digest(vars(evaluator.protocol)), "horizon_reads": 256,
            "data": evaluator.data_digest, "cohort_registration": a.digest(registration),
            "memory": run.memory, "training_inputs": run.training_inputs,
            "executor": run.executor, "budget": budget, "workload": workload,
            "encoder": run.encoder, "decoder": run.decoder, "tool_permissions": run.tool_permissions})
        resources = dict.fromkeys(a.COSTS, 0.0)
        resources.update(serve_cpu_s=10.0, peak_rss_bytes=128 * 1024 * 1024)
        return dict(binding, all_searches_and_failures_included=True,
                    synthetic_control_costs=True, resources=resources)

    left, right = ledger(candidate), ledger(incumbent)
    prior_result = None
    if changing_protocol:
        prior_result = evaluator.evaluate(candidate, incumbent, left, right,
                                          manifest={"bundle": candidate.bundle, "memory": candidate.memory})
        evaluator.protocol = replace(evaluator.protocol, planned_looks=1)
        left, right = ledger(candidate), ledger(incumbent)
    if name == "empty_cost_model_and_caps":
        left["resources"] = dict.fromkeys(a.COSTS, 1000000.0)
        right["resources"] = dict.fromkeys(a.COSTS, 1.0)
        left["resources"]["peak_rss_bytes"] = 128 * 1024 * 1024
        right["resources"].update(serve_cpu_s=10.0, peak_rss_bytes=128 * 1024 * 1024)
    elif name == "foreign_dataset_receipt":
        left["data"] = a.digest({"unrelated_dataset": True})
    elif name == "foreign_workload_receipt":
        left["workload"] = a.digest({"unrelated_workload": True})
    elif name == "foreign_input_receipt":
        left["memory"] = "different-memory"
    elif name == "foreign_cohort_receipt":
        left["cohort_registration"] = a.digest({"unrelated_cohort": True})
    result = evaluator.evaluate(candidate, incumbent, left, right,
                                manifest={"bundle": candidate.bundle, "memory": candidate.memory})
    return {"case": name, "expected_approved": name == "positive_control",
            "artificial_resources": {"candidate": left["resources"], "incumbent": right["resources"]},
            "common_caps": list(limits), "logical_budget": budget,
            "prior_frozen_result": ({k: prior_result[k] for k in ("approved", "per_bound_alpha", "paired_lower_bound")}
                                     if prior_result else None),
            "execution": result.get("execution"),
            **{k: result[k] for k in ("approved", "paired_mean", "paired_lower_bound",
                                     "extra_cost_per_read", "reasons")}}


names = ("positive_control", "empty_cost_model_and_caps", "matching_arbitrary_budget_label",
         "foreign_dataset_receipt", "foreign_workload_receipt", "foreign_input_receipt",
         "foreign_cohort_receipt", "shared_executor_backing_state", "changed_protocol_after_freeze")
observations = [observe(name) for name in names]
source_after = {name: hashlib.sha256((source / name).read_bytes()).hexdigest()
                for name in source_names if (source / name).exists()}
report = {"schema": "memory-cost-admission-red-green.v1", "synthetic_control_only": True,
          "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          "source": source_before, "source_unchanged_during_execution": source_before == source_after,
          "observations": observations,
          "failures": sum(row["approved"] != row["expected_approved"] for row in observations)
                      + int(source_before != source_after)}
print(json.dumps(report, indent=2, sort_keys=True))
if len(sys.argv) > 2:
    Path(sys.argv[2]).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
raise SystemExit(bool(report["failures"]))
