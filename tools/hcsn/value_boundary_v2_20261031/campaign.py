"""Frozen preparation and separately authorized actual-effect confirmation.

prepare never creates confirmation episodes. confirm requires the exact prepared
manifest digest and a parent-supplied immutable remote freeze reference.
"""
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import shutil
import time

import numpy as np
from scipy.stats import t as student_t

from .deployment import load_policy, preparation_io_cpu, write_policy
from .learn import fit_region
from .model import Contract, Model
from .owner import ContentAdapter, PayloadBank, execute, save, semantic_trace, sha
from .qualification import independent_linear_program

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[2]
FIT_SEEDS = (74031, 74037, 74043, 74049, 74057)
POLICIES = ("fixed_analytic", "direct_hard_analytic", "direct_soft_analytic",
            "qvi_analytic", "qvi_ordinary")


def declared_protocol():
    common = dict(time_cost=.02, fire_cost=.01, recovery_phases=2, minimum_confidence=.75)
    parameters = [
        ("nominal_1", (.80, .86), (2., 2.5), (.03, .04), .10, 5., 4),
        ("nominal_2", (.68, .88), (2.5, 2.), (.02, .04), .08, 6., 6),
        ("nominal_3", (.88, .78), (1.2, 3.), (.06, .02), .18, 4., 4),
        ("nominal_4", (.72, .82), (3., 1.5), (.025, .05), .15, 3., 6),
        ("stress_1_stop_control", (.62, .64), (.7, .8), (.10, .10), .30, 2., 4),
        ("stress_2", (.62, .90), (3.5, .7), (.01, .10), .05, 8., 6),
        ("stress_3", (.90, .80), (.7, 3.5), (.10, .01), .30, 2., 6),
        ("stress_4", (.82, .64), (3.5, 3.5), (.10, .01), .05, 8., 6),
    ]
    contracts = [dict(name=name, contract=Contract(reliability=q, arrival_rate=rate,
        query_cost=cost, deadline_rate=delta, recovery_rate=gamma, budget=budget,
        **common).serializable()) for name, q, rate, cost, delta, gamma, budget in parameters]
    return dict(schema="hcsn.regenerative-evidence.frozen-campaign.v1", contracts=contracts,
        fit_seeds=list(FIT_SEEDS), updates=600, optimizer="mirror", learning_rate=1.,
        fixed_boundary_threshold=2., sessions_per_contract_fit=128,
        episode_seed_base=587103100, contract_seed_stride=100000, fit_seed_stride=1000,
        execution_order_seed_offset=9000000, soft_policy_seed_offset=17000000,
        policies=list(POLICIES), primary_comparisons=["direct_hard_analytic-minus-fixed_analytic",
                                                    "qvi_analytic-minus-fixed_analytic"],
        secondary_comparisons=["direct_hard_analytic-minus-direct_soft_analytic",
                               "qvi_analytic-minus-qvi_ordinary"],
        matching="Five policies share each real packet/clock tape; each contract-fit has 128 distinct episode seeds",
        inference="Per-contract paired episode t intervals conditional on five frozen fits; also five-fit cluster intervals; equal-weight finite-contract aggregation",
        confidence_level=.95, multiplicity="Two primary effects reported separately; intervals are unadjusted descriptive 95% intervals",
        cpu_accounting=dict(primary_kappa=1., primary_deployment_sessions=1000,
            kappa_sensitivity=[0., .1, 1., 10.], deployment_sessions_sensitivity=[128, 1000, 10000],
            formula="paired utility difference minus kappa times paired enclosing execution CPU difference and preparation CPU difference divided by deployment sessions",
            common_costs="Shared generation, decoder/support setup and common verification recorded separately and cancel in matched alternative-policy contrasts; nested component timers are not added to enclosing CPU"),
        policy_artifacts="Each deployable table is serialized, hashed and load-validated during preparation; confirmation loads each policy separately and charges that measured setup to its deployment alternative",
        quality_metrics=["correct_jobs/2", "incorrect_jobs/2", "completed_jobs/2", "accuracy_among_submitted"],
        quality_noninferiority_claim=False,
        expected_sessions=8*5*128, expected_rollouts=8*5*128*5,
        workload="Known-model per-contract replanning; nominal/stress are public parameter scenarios, not amortized IID/OOD generalization",
        analytic_attribution="Same-policy ordinary/analytic task effects must be pathwise identical; analytic CDF work can add measured cost",
        complete_cost="Record setup, generation, fit, solve, CDF, actual decoder, support validation and enclosing runtime separately; measured CPU/wall are not energy or task-clock time",
        negative_control="stress_1_stop_control is declared before preparation and retained whatever its result",
        failure_policy="Preserve every failed rollout and partial event receipt; any execution failure invalidates campaign qualification; never retry or tune on confirmation",
        promotion="No automatic production enrollment, architecture-superiority claim or hardware-energy claim")


def dump_gzip(path, value):
    path = Path(path)
    with path.open("xb") as stream:
        stream.write(gzip.compress(json.dumps(value, sort_keys=True, allow_nan=False).encode(), mtime=0))


def load_gzip(path):
    return json.loads(gzip.decompress(Path(path).read_bytes()))


def source_manifest():
    paths = list(HERE.glob("*.py"))
    if (HERE/"README.md").exists():
        paths.append(HERE/"README.md")
    old = HERE.parent/"task_value_factorial_20261030"
    paths.extend((old/"task.py", old/"UPSTREAM_FILES.json"))
    upstream = json.loads((old/"UPSTREAM_FILES.json").read_text())
    paths.extend(REPOSITORY/item["path"] for item in upstream["files"])
    return {str(path.relative_to(REPOSITORY)): sha(path) for path in sorted(set(paths))}


def certificate(model, probabilities, optimal):
    evaluated = model.solve(probabilities)
    residual = np.max(evaluated["q"], axis=1)-evaluated["value"]
    legal = model.solve(model.valid/model.valid.sum(1, keepdims=True))["occupation"] > 0
    reached = evaluated["occupation"] > 0
    gap = optimal["value"]-evaluated["value"]
    return dict(initial_value=evaluated["initial_value"], values=evaluated["value"].tolist(),
        occupation=evaluated["occupation"].tolist(), bellman_residual=residual.tolist(),
        state_optimality_gap=gap.tolist(), legal_reachable=legal.tolist(), policy_reachable=reached.tolist(),
        initial_gap=float(gap[model.start]), maximum_envelope_residual=float(residual.max()),
        maximum_legal_reachable_residual=float(residual[legal].max()),
        maximum_policy_reachable_residual=float(residual[reached].max()))


def prepare(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter(), time.process_time()
    protocol, sources = declared_protocol(), source_manifest()
    save(out/"PROTOCOL.json", protocol)
    for relative in sources:
        destination = out/"source"/relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPOSITORY/relative, destination)
    adapter = ContentAdapter()
    rows = []
    for index, declaration in enumerate(protocol["contracts"]):
        contract = Contract(**declaration["contract"])
        start_wall, start_cpu = time.perf_counter(), time.process_time()
        model = Model(contract)
        model_cost = dict(cpu_seconds=time.process_time()-start_cpu, wall_seconds=time.perf_counter()-start_wall)
        start_wall, start_cpu = time.perf_counter(), time.process_time()
        optimal = model.solve()
        qvi_cost = dict(cpu_seconds=time.process_time()-start_cpu, wall_seconds=time.perf_counter()-start_wall)
        start_wall, start_cpu = time.perf_counter(), time.process_time()
        independent = independent_linear_program(contract, model.states)
        lp_cost = dict(cpu_seconds=time.process_time()-start_cpu, wall_seconds=time.perf_counter()-start_wall)
        error = float(np.max(np.abs(optimal["value"]-independent)))
        start_wall, start_cpu = time.perf_counter(), time.process_time()
        fixed = model.fixed_boundary(protocol["fixed_boundary_threshold"])
        fixed_certificate = certificate(model, model.deterministic(fixed), optimal)
        fixed_cost = dict(cpu_seconds=time.process_time()-start_cpu, wall_seconds=time.perf_counter()-start_wall)
        start_wall, start_cpu = time.perf_counter(), time.process_time()
        qvi_certificate = certificate(model, optimal["policy"], optimal)
        qvi_certificate_cost = dict(cpu_seconds=time.process_time()-start_cpu, wall_seconds=time.perf_counter()-start_wall)
        fixed_artifact = write_policy(out, f"contract{index}_fixed", model, actions=fixed)
        qvi_artifact = write_policy(out, f"contract{index}_qvi", model,
                                    actions=np.argmax(optimal["policy"], axis=1))
        fits = []
        for seed in FIT_SEEDS:
            fit = fit_region(contract, seed, updates=protocol["updates"],
                             learning_rate=protocol["learning_rate"], optimizer=protocol["optimizer"])
            start_wall, start_cpu = time.perf_counter(), time.process_time()
            fit["hard_certificate"] = certificate(model, model.deterministic(fit["hard_actions"]), optimal)
            fit["soft_certificate"] = certificate(model, np.asarray(fit["probabilities"]), optimal)
            fit["additional_certificate_timing"] = dict(cpu_seconds=time.process_time()-start_cpu,
                                                        wall_seconds=time.perf_counter()-start_wall)
            fit["deployment_artifacts"] = dict(
                hard=write_policy(out, f"contract{index}_seed{seed}_hard", model, actions=fit["hard_actions"]),
                soft=write_policy(out, f"contract{index}_seed{seed}_soft", model,
                                  probabilities=np.asarray(fit["probabilities"])))
            fits.append(fit)
        rows.append(dict(index=index, name=declaration["name"], contract=contract.serializable(),
            states=model.states, qvi_actions=np.argmax(optimal["policy"], axis=1).tolist(),
            fixed_actions=fixed.tolist(), qvi_certificate=qvi_certificate,
            fixed_certificate=fixed_certificate, independent_lp_values=independent.tolist(),
            independent_lp_maximum_error=error, fits=fits,
            deployment_artifacts=dict(fixed=fixed_artifact, qvi=qvi_artifact),
            timing=dict(model=model_cost, qvi=qvi_cost, qvi_certificate=qvi_certificate_cost,
                        independent_lp=lp_cost, fixed=fixed_cost)))
        print(json.dumps(dict(stage="prepare", contract=declaration["name"], lp_error=error,
            hard_gaps=[fit["hard_optimality_gap"] for fit in fits],
            full_state_residuals=[fit["hard_bellman_residual"] for fit in fits])), flush=True)
    unchanged = sources == source_manifest()
    valid = unchanged and all(row["independent_lp_maximum_error"] < 2e-10 for row in rows)
    bundle = dict(schema="hcsn.regenerative-evidence.prepared.v1", protocol=protocol, sources=sources,
        contracts=rows, adapter_setup=adapter.setup, adapter_upstream=adapter.upstream,
        source_unchanged=unchanged, preparation_valid=valid,
        cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall,
        confirmation_episodes_generated=0)
    dump_gzip(out/"PREPARED.json.gz", bundle)
    artifacts = {str(path.relative_to(out)): sha(path) for path in sorted(out.rglob("*")) if path.is_file()}
    stage = dict(cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall,
        scope="Outer preparation including source copying, deployable artifacts, all fits/certificates, bundle serialization and artifact hashing; excludes writing these final small receipts")
    save(out/"PREPARE_STAGE_RECEIPT.json", stage)
    artifacts["PREPARE_STAGE_RECEIPT.json"] = sha(out/"PREPARE_STAGE_RECEIPT.json")
    manifest = dict(schema="hcsn.regenerative-evidence.freeze-manifest.v1", sources=sources,
        artifacts=artifacts,
        preparation_valid=valid, confirmation_episodes_generated=0)
    save(out/"FREEZE_MANIFEST.json", manifest)
    if not valid:
        raise ArithmeticError("Preparation qualification failed; all outputs retained")
    return dict(prepared=str(out.resolve()), manifest_sha256=sha(out/"FREEZE_MANIFEST.json"),
                contracts=len(rows), fits=len(rows)*len(FIT_SEEDS), confirmation_episodes_generated=0)


def paired_interval(values):
    values = np.asarray(values, float)
    count = len(values)
    mean = float(values.mean()) if count else None
    se = float(values.std(ddof=1)/math.sqrt(count)) if count > 1 else None
    half = float(student_t.ppf(.975, count-1)*se) if count > 1 else None
    return dict(n=count, mean=mean, standard_error=se,
                confidence_interval=None if half is None else [mean-half, mean+half])


def equal_weight_interval(reports, key):
    valid = [report[key] for report in reports if report[key]["n"] > 1]
    if len(valid) != len(reports):
        return dict(valid=False, reason="Incomplete strata; failed samples retained elsewhere")
    count = len(valid)
    mean = sum(row["mean"] for row in valid)/count
    variances = [row["standard_error"]**2/count**2 for row in valid]
    variance = sum(variances)
    denominator = sum(v*v/(row["n"]-1) for v, row in zip(variances, valid))
    degrees = variance*variance/denominator if denominator else None
    half = float(student_t.ppf(.975, degrees)*math.sqrt(variance)) if degrees else 0.
    return dict(valid=True, contract_count=count, mean=mean, standard_error=math.sqrt(variance),
                degrees_of_freedom=degrees, confidence_interval=[mean-half, mean+half],
                scope="Equal weighting of exactly the eight public contracts; no random-contract population inference")


def policy_metrics(result):
    if "score" not in result:
        return None
    score = result["score"]
    return dict(utility=score["utility"], reward=score["reward"], completed_jobs=score["completed_jobs"],
        correct_jobs=score["correct_jobs"], task_elapsed=result["task_elapsed"],
        correct_fraction=score["correct_jobs"]/2,
        error_fraction=(score["completed_jobs"]-score["correct_jobs"])/2,
        completion_fraction=score["completed_jobs"]/2,
        cpu_seconds=result["cpu_seconds"], wall_seconds=result["wall_seconds"],
        query_charge=score["query_charge"], time_charge=score["time_charge"], fire_charge=score["fire_charge"],
        **{f"count_{key}": value for key, value in result["counts"].items()},
        **result["components"])


def preparation_cpu(contract_row, fit):
    timing = contract_row["timing"]
    model = timing["model"]["cpu_seconds"]
    fixed = model+timing["fixed"]["cpu_seconds"]+preparation_io_cpu(contract_row["deployment_artifacts"]["fixed"])
    qvi = (model+timing["qvi"]["cpu_seconds"]+timing["qvi_certificate"]["cpu_seconds"]
           +preparation_io_cpu(contract_row["deployment_artifacts"]["qvi"]))
    direct = fit["cpu_seconds"]+fit["additional_certificate_timing"]["cpu_seconds"]
    direct += sum(preparation_io_cpu(descriptor) for descriptor in fit["deployment_artifacts"].values())
    return dict(fixed_analytic=fixed, direct_hard_analytic=direct, direct_soft_analytic=direct,
                qvi_analytic=qvi, qvi_ordinary=qvi)


def accounting_scenarios(protocol):
    accounting = protocol["cpu_accounting"]
    return [(f"kappa={kappa:g};H={horizon}", kappa, horizon)
            for kappa in accounting["kappa_sensitivity"]
            for horizon in accounting["deployment_sessions_sensitivity"]]


def confirm(prepared, out, freeze_sha256, freeze_reference):
    wall, cpu = time.perf_counter(), time.process_time()
    prepared, out = Path(prepared), Path(out)
    if not freeze_reference.strip() or sha(prepared/"FREEZE_MANIFEST.json") != freeze_sha256:
        raise ValueError("Exact prepared digest and immutable remote freeze reference required")
    manifest = json.loads((prepared/"FREEZE_MANIFEST.json").read_text())
    if not manifest["preparation_valid"] or manifest["sources"] != source_manifest():
        raise ValueError("Unqualified preparation or source changed after preparation")
    for name, digest in manifest["artifacts"].items():
        if sha(prepared/name) != digest:
            raise ValueError(f"Frozen preparation artifact changed: {name}")
    bundle = load_gzip(prepared/"PREPARED.json.gz")
    preparation_stage = json.loads((prepared/"PREPARE_STAGE_RECEIPT.json").read_text())
    protocol = bundle["protocol"]
    out.mkdir(parents=True, exist_ok=False)
    save(out/"CONFIRMATION_START.json", dict(freeze_sha256=freeze_sha256,
         freeze_reference=freeze_reference, protocol=protocol, sources=manifest["sources"]))
    bank = PayloadBank(out/"finite_support")
    save(out/"SUPPORT_RECEIPT.json", bank.receipt)
    reports, failures, null_failures = [], [], []
    actual_sessions, actual_rollouts = 0, 0
    generation_cpu, generation_wall = 0., 0.
    for contract_row in bundle["contracts"]:
        c = contract_row["index"]
        contract = Contract(**contract_row["contract"])
        metrics = {name: [] for name in POLICIES}
        effects = {name: [] for name in protocol["primary_comparisons"]+protocol["secondary_comparisons"]}
        fit_effects = {name: [] for name in effects}
        net_effects = {name: {key:[] for key, _, _ in accounting_scenarios(protocol)}
                       for name in protocol["primary_comparisons"]}
        net_fit_effects = {name: {key:[] for key in scenarios} for name, scenarios in net_effects.items()}
        expected = []
        for f, fit in enumerate(contract_row["fits"]):
            fit_rows = []
            per_fit_effects = {name: [] for name in effects}
            per_fit_net = {name: {key:[] for key in scenarios} for name, scenarios in net_effects.items()}
            preparation_cost = preparation_cpu(contract_row, fit)
            descriptors = dict(fixed_analytic=contract_row["deployment_artifacts"]["fixed"],
                qvi_analytic=contract_row["deployment_artifacts"]["qvi"],
                qvi_ordinary=contract_row["deployment_artifacts"]["qvi"],
                direct_hard_analytic=fit["deployment_artifacts"]["hard"],
                direct_soft_analytic=fit["deployment_artifacts"]["soft"])
            loaded, load_receipts = {}, {}
            for name, descriptor in descriptors.items():
                loaded[name], load_receipts[name] = load_policy(prepared, descriptor)
                preparation_cost[name] += load_receipts[name]["cpu_seconds"]
            expected.append(dict(seed=fit["seed"], fixed_analytic=contract_row["fixed_certificate"]["initial_value"],
                direct_hard_analytic=fit["hard_value"], direct_soft_analytic=fit["soft_value"],
                qvi_analytic=contract_row["qvi_certificate"]["initial_value"],
                qvi_ordinary=contract_row["qvi_certificate"]["initial_value"], preparation_cpu=preparation_cost,
                deployment_load_receipts=load_receipts))
            for index in range(protocol["sessions_per_contract_fit"]):
                seed = protocol["episode_seed_base"]+c*protocol["contract_seed_stride"]+f*protocol["fit_seed_stride"]+index
                identifier = f"contract{c}_fit{f}_session{index:03d}"
                episode = bank.make_episode(out/"episodes", contract, identifier, seed)
                actual_sessions += 1
                generation_cpu += episode["cpu_seconds"]
                generation_wall += episode["wall_seconds"]
                order = np.random.default_rng(seed+protocol["execution_order_seed_offset"]).permutation(POLICIES).tolist()
                results = {}
                for name in order:
                    arguments = dict(mode="ordinary_gate" if name == "qvi_ordinary" else "analytic_boundary",
                                     capture_failure=True)
                    if name == "direct_soft_analytic":
                        arguments.update(probabilities=loaded[name]["probabilities"], rng_seed=seed+protocol["soft_policy_seed_offset"])
                    else:
                        arguments["actions"] = loaded[name]["actions"]
                    try:
                        result = execute(episode, contract, bank, **arguments)
                    except Exception as exc:
                        result = dict(failure=dict(type=type(exc).__name__, message=str(exc)),
                                      stage="before captured action result", episode=identifier)
                    results[name] = result
                    actual_rollouts += 1
                    if result.get("failure"):
                        failures.append(dict(episode=identifier, policy=name, failure=result["failure"]))
                    metric = policy_metrics(result)
                    if metric is not None:
                        metrics[name].append(metric)
                if ("score" not in results["qvi_ordinary"] or "score" not in results["qvi_analytic"]
                        or semantic_trace(results["qvi_ordinary"]) != semantic_trace(results["qvi_analytic"])):
                    null_failures.append(identifier)
                for comparison in effects:
                    left, right = comparison.split("-minus-")
                    if "score" in results[left] and "score" in results[right]:
                        difference = results[left]["score"]["utility"]-results[right]["score"]["utility"]
                        effects[comparison].append(difference)
                        per_fit_effects[comparison].append(difference)
                        if comparison in net_effects:
                            cpu_difference = results[left]["cpu_seconds"]-results[right]["cpu_seconds"]
                            setup_difference = preparation_cost[left]-preparation_cost[right]
                            for key, kappa, horizon in accounting_scenarios(protocol):
                                net = difference-kappa*(cpu_difference+setup_difference/horizon)
                                net_effects[comparison][key].append(net)
                                per_fit_net[comparison][key].append(net)
                fit_rows.append(dict(episode=episode, execution_order=order, results=results))
            for comparison in effects:
                if per_fit_effects[comparison]:
                    fit_effects[comparison].append(float(np.mean(per_fit_effects[comparison])))
            for comparison, scenarios in per_fit_net.items():
                for key, differences in scenarios.items():
                    if differences:
                        net_fit_effects[comparison][key].append(float(np.mean(differences)))
            dump_gzip(out/f"contract{c}_fit{f}_RAW.json.gz", dict(contract=contract_row["name"],
                      fit_seed=fit["seed"], expected=expected[-1], episodes=fit_rows))
            print(json.dumps(dict(stage="confirm", contract=contract_row["name"], fit=fit["seed"],
                completed=len(fit_rows), failures=len(failures), null_failures=len(null_failures))), flush=True)
        summary = {name: {key: float(np.mean([row[key] for row in rows])) for key in rows[0]} if rows else {}
                   for name, rows in metrics.items()}
        for name, rows in metrics.items():
            submitted = sum(row["completed_jobs"] for row in rows)
            summary[name]["accuracy_among_submitted"] = (sum(row["correct_jobs"] for row in rows)/submitted
                                                         if submitted else None)
        reports.append(dict(name=contract_row["name"], contract=contract.serializable(), expected=expected,
            sampled_means=summary, sampled_counts={name:len(rows) for name, rows in metrics.items()},
            comparisons={name:dict(conditional_episode=paired_interval(effects[name]),
                fit_cluster=paired_interval(fit_effects[name])) for name in effects},
            net_comparisons={name: {key:dict(conditional_episode=paired_interval(differences),
                fit_cluster=paired_interval(net_fit_effects[name][key])) for key, differences in scenarios.items()}
                for name, scenarios in net_effects.items()}))
    aggregate = {comparison: {key: equal_weight_interval([row["comparisons"][comparison] for row in reports], key)
                 for key in ("conditional_episode", "fit_cluster")} for comparison in protocol["primary_comparisons"]}
    net_aggregate = {comparison: {scenario: {key: equal_weight_interval(
        [row["net_comparisons"][comparison][scenario] for row in reports], key)
        for key in ("conditional_episode", "fit_cluster")} for scenario, _, _ in accounting_scenarios(protocol)}
        for comparison in protocol["primary_comparisons"]}
    source_unchanged = manifest["sources"] == source_manifest()
    complete = (actual_sessions == protocol["expected_sessions"]
                and actual_rollouts == protocol["expected_rollouts"])
    result = dict(schema="hcsn.regenerative-evidence.confirmation.v1", reports=reports,
        primary_equal_weight_aggregate=aggregate, failures=failures, null_failures=null_failures,
        net_equal_weight_aggregate=net_aggregate,
        primary_net_aggregate={name: scenarios["kappa=1;H=1000"] for name, scenarios in net_aggregate.items()},
        cpu_accounting=protocol["cpu_accounting"], quality_noninferiority_claim=False,
        source_unchanged=source_unchanged, actual_sessions=actual_sessions, actual_rollouts=actual_rollouts,
        complete=complete, qualified=not failures and not null_failures and source_unchanged and complete,
        support=bank.receipt, generation_cpu_seconds=generation_cpu, generation_wall_seconds=generation_wall,
        confirmation_cpu_seconds=time.process_time()-cpu, confirmation_wall_seconds=time.perf_counter()-wall,
        preparation_cpu_seconds=preparation_stage["cpu_seconds"],
        preparation_wall_seconds=preparation_stage["wall_seconds"],
        preparation_before_bundle_serialization_cpu_seconds=bundle["cpu_seconds"],
        preparation_stage_scope=preparation_stage["scope"],
        freeze_sha256=freeze_sha256, freeze_reference=freeze_reference,
        main_enrollment=False, independent_analytic_task_gain=False,
        limitation="Qualification is execution/model consistency, not a positive task-benefit or production-promotion verdict")
    save(out/"SUMMARY.json", result)
    artifacts = {str(path.relative_to(out)):sha(path) for path in sorted(out.rglob("*")) if path.is_file()}
    save(out/"CONFIRM_STAGE_RECEIPT.json", dict(cpu_seconds=time.process_time()-cpu,
        wall_seconds=time.perf_counter()-wall,
        scope="Outer confirmation including prepared/source validation and bundle loading, all policy loading, generation, execution, raw result serialization, summary and evidence hashing; excludes writing these final small receipts"))
    artifacts["CONFIRM_STAGE_RECEIPT.json"] = sha(out/"CONFIRM_STAGE_RECEIPT.json")
    receipt = dict(artifacts=artifacts,
                   qualified=result["qualified"], freeze_sha256=freeze_sha256, freeze_reference=freeze_reference)
    save(out/"EVIDENCE_MANIFEST.json", receipt)
    return dict(output=str(out.resolve()), qualified=result["qualified"], failures=len(failures),
                null_failures=len(null_failures), summary_sha256=sha(out/"SUMMARY.json"))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    preparation = sub.add_parser("prepare")
    preparation.add_argument("--out", type=Path, required=True)
    confirmation = sub.add_parser("confirm")
    confirmation.add_argument("--prepared", type=Path, required=True)
    confirmation.add_argument("--out", type=Path, required=True)
    confirmation.add_argument("--freeze-sha256", required=True)
    confirmation.add_argument("--freeze-reference", required=True)
    arguments = vars(parser.parse_args())
    command = arguments.pop("command")
    result = prepare(**arguments) if command == "prepare" else confirm(**arguments)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
