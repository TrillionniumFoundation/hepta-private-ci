"""Replay all frozen confirmation receipts; regenerate inputs and statistics.

This is an audit of recorded causal execution and arithmetic, not a second
hardware timing experiment or a bit-exact optimizer rerun. Oracle reuse is only
across the identical public bytes, law and TRAIN decoder, never hidden outcomes.
"""
import argparse
import copy
import gzip
import hashlib
import json
import math
from pathlib import Path
import tempfile
import time
import traceback

import numpy as np
from scipy.stats import t as student_t
from . import joint_data, joint_task as task
from .joint_compiled_dp import CompiledPolicy, json_bytes
from .joint_deploy import NumpyPolicy
from .joint_deadline_reference import DeadlineOnlyPolicy
from .joint_law import IndependentLaw

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[2]
TEACHER = {"teacher_q", "teacher_regret", "teacher_margin", "teacher_mass", "teacher_bank"}
REFERENCES = ("reference_nominal", "reference_known_environment", "reference_no_read", "reference_deadline_read")


def read(path):
    path = Path(path); raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def close(actual, expected, where=""):
    if isinstance(expected, dict):
        assert set(actual) == set(expected), (where, set(actual)^set(expected))
        for key in expected:
            close(actual[key], expected[key], where+"/"+str(key))
    elif isinstance(expected, (list, tuple)):
        assert len(actual) == len(expected), where
        for index, value in enumerate(expected):
            close(actual[index], value, where+"/"+str(index))
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        assert math.isfinite(actual) and abs(actual-expected) <= 2e-9*(1+abs(expected)), (where, actual, expected)
    else:
        assert actual == expected, (where, actual, expected)


def intervals(aggregate, protocol):
    def interval(values, count):
        a = np.asarray(values); m = float(a.mean())
        h = float(student_t.ppf(1-.05/(2*count), 4)*a.std(ddof=1)/math.sqrt(5))
        return dict(mean=m, lower=m-h, upper=m+h)
    pairs = [(f+":value-fixed", f+"/value", f+"/fixed") for f in protocol["families"]]
    pairs += [("renewal-minus-"+f, "renewal/value", f+"/value") for f in protocol["families"] if f != "renewal"]
    primary, secondary = {}, {}
    assert len(pairs)*2 == 14
    for split in ("iid", "ood"):
        for name, a, b in pairs:
            x, y = aggregate[split+"/"+a], aggregate[split+"/"+b]
            differences = [p["utility"]-n["utility"] for p, n in zip(x, y)]
            row = interval(differences, 14)
            primary[split+"/"+name] = dict(**row, passed=row["lower"]>.02, fit_differences=differences)
        for family in protocol["families"]:
            if family == "renewal":
                continue
            x, y = aggregate[split+"/renewal/value"], aggregate[split+"/"+family+"/value"]
            metrics = {"quality": [p["utility"]-n["utility"] for p, n in zip(x, y)]}
            for name, field in (("log_cpu_ratio", "full_execution_cpu_seconds"),
                                ("log_wall_p95_ratio", "wall_p95_seconds"),
                                ("log_serial_service_throughput_ratio", "serial_service_throughput")):
                metrics[name] = [float(np.log(p[field]/n[field])) for p, n in zip(x, y)]
            rows = {k: dict(**interval(v, 24), fit_values=v) for k, v in metrics.items()}
            gates = dict(quality_noninferior=rows["quality"]["lower"]>-.02,
                         cpu_saving=rows["log_cpu_ratio"]["upper"]<math.log(.9),
                         wall_latency_not_degraded=rows["log_wall_p95_ratio"]["upper"]<math.log(1.05),
                         throughput_not_degraded=rows["log_serial_service_throughput_ratio"]["lower"]>math.log(.95))
            secondary[split+"/renewal-minus-"+family] = dict(**rows, gates=gates, passed=all(gates.values()),
                family="secondary adoption24intervals alpha.05, separate from primary14interval alpha.05")
    return primary, secondary


def audit(root, confirmation, process_receipt):
    protocol = read(HERE/"joint_protocol.json")
    freeze = read(root/"MODEL_FREEZE.json")
    started, summary = read(confirmation/"STARTED.json"), read(confirmation/"SUMMARY.json")
    adapter_provenance = read(confirmation/"ADAPTER.json")
    process = read(process_receipt)
    assert process["returncode"] == 0
    close(process["cpu_seconds"], process["user_cpu_seconds"]+process["system_cpu_seconds"])
    assert process["wall_seconds"] >= summary["wall_seconds"]
    assert process["cpu_seconds"]+1e-5 >= sum(summary["complete_process_usage"].values())
    assert "tools.hcsn.digital_joint_20261102.joint_confirmation_runner" in process["argv"]
    for flag, expected in (("--model-commit",started["published_model_commit"]),("--adapter-commit",adapter_provenance["published_adapter_commit"])):
        assert process["argv"][process["argv"].index(flag)+1] == expected
    assert adapter_provenance["status"] == "completed"
    assert adapter_provenance["before_guard"] and adapter_provenance["after_guard"]
    assert adapter_provenance["identities"] == dict(runner=sha(HERE/"joint_confirmation_runner.py"),protocol=sha(HERE/"joint_confirmation_runner_protocol.json"))
    assert adapter_provenance["protocol"] == read(HERE/"joint_confirmation_runner_protocol.json")
    assert adapter_provenance["published_model_commit"] == started["published_model_commit"]
    assert len(adapter_provenance["published_adapter_commit"]) == 40
    assert started["model_freeze_sha256"] == sha(root/"MODEL_FREEZE.json")
    assert started["sources"] == freeze["sources"]
    assert started["published_model_commit"] == summary["published_model_commit"]
    assert len(started["published_model_commit"]) == 40
    assert freeze["protocol_sha256"] == sha(HERE/"joint_protocol.json")
    for relative, digest in freeze["sources"].items():
        assert sha(REPOSITORY/relative) == digest
    for relative, digest in freeze["models"].items():
        assert sha(root/relative) == digest
    assert len(freeze["models"]) == 20
    for record in freeze["data"].values():
        assert sha(root/record["path"]) == record["sha256"]
    assert len(list(confirmation.glob("fit_*.json.gz"))) == 120
    law = IndependentLaw(protocol["truth_raw"])
    adapter, decoded, all_inputs, all_missing = task.ContentAdapter(), {}, {}, {}
    aggregate, references, counts, reference_counts = {}, {}, {}, {}
    totals = dict(episodes=0, decisions=0, due_read_attempts=0, successful_content_decodes=0,
                  failed_content_reads=0, compiled_states=0, wire_bytes=0,
                  complete_request_cpu_seconds=0., postexecution_audit_cpu_seconds=0.,
                  compiled_argmax_numerical_ties=0, max_compiled_stored_action_oracle_gap=0.)
    training_payloads, confirmation_payloads, calibration_inputs = set(), set(), {}
    model_load_cpu = {}; full_cpu = {}; input_files = {}
    for fit in protocol["fits"]:
        prepared = read(root/freeze["data"][str(fit)]["path"])
        calibration = prepared["calibration"]
        rng = np.random.default_rng(protocol["data_seed_base"]+fit*1000000+900000)
        calibration_counts = np.zeros((2,2),dtype=int)
        assert len(calibration["rows"]) == protocol["calibration_count"] == 64
        for index, row in enumerate(calibration["rows"]):
            path = (root/freeze["data"][str(fit)]["path"]).parent/Path(row["path"]).parent.name/Path(row["path"]).name
            expected_packet = task.packet(index%2,int(rng.integers(0,2**63-1)),protocol["packet_length"])
            digest = hashlib.sha256(joint_data.bytes_json(expected_packet)).hexdigest()
            assert sha(path) == row["payload_sha256"] == digest and row["symbol"] == index%2
            result = adapter.read(path)
            close(result["logits"],row["logits"])
            assert result["observation"] == row["observation"]
            calibration_counts[row["symbol"],result["observation"]] += 1
            training_payloads.add(digest)
            calibration_inputs[str(path.relative_to(root))] = dict(sha256=digest,bytes=path.stat().st_size)
        close(calibration["counts"],calibration_counts.tolist())
        close(prepared["confusion"],((calibration_counts+.5)/(calibration_counts.sum(1,keepdims=True)+1.)).tolist())
        for split in ("train", "validation"):
            training_payloads.update(prepared[split+"_cohort"]["payload_sha256"])
        confusion = freeze["data"][str(fit)]["confusion"]
        close(prepared["confusion"],confusion)
        models = {f: NumpyPolicy(read(root/f"fit_{fit}/model_{f}/model.json")) for f in protocol["families"]}
        assert all(m.artifact["confusion"] == confusion for m in models.values())
        assert all(m.artifact["nominal_raw"] == models["renewal"].artifact["nominal_raw"] for m in models.values())
        nominal = IndependentLaw(models["renewal"].artifact["nominal_raw"])
        setup = summary["decoder_setup"][str(fit)]
        setup_totals = dict(cpu=0., wall=0.)
        requests = 2*protocol["confirmation_worlds_per_fit_split"]*(2*len(models)+len(REFERENCES))
        assert requests == 960
        for split in ("iid", "ood"):
            cohort_file = confirmation/f"cohort_{fit}_{split}.json"
            cohort = read(cohort_file)
            input_files[str(cohort_file.relative_to(confirmation))] = dict(sha256=sha(cohort_file), bytes=cohort_file.stat().st_size)
            assert len(cohort["records"]) == protocol["confirmation_worlds_per_fit_split"] == 40
            with tempfile.TemporaryDirectory(prefix="joint-independent-cohort-") as temporary:
                regenerated = joint_data.cohort(Path(temporary), split, fit, 40, protocol, IndependentLaw(protocol["truth_raw"]), started["published_model_commit"])
                for field in ("files", "expected_missing", "payload_sha256", "law", "published_source_commit"):
                    close(cohort[field], regenerated[field], "cohort/"+field)
                assert [{k:v for k,v in r.items() if k != "folder"} for r in cohort["records"]] == [{k:v for k,v in r.items() if k != "folder"} for r in regenerated["records"]]
            for relative, digest in cohort["files"].items():
                path = confirmation/relative
                assert sha(path) == digest
                all_inputs[relative] = dict(sha256=digest, bytes=path.stat().st_size)
            for relative, digest in cohort["expected_missing"].items():
                assert not (confirmation/relative).exists()
                all_missing[relative] = dict(expected_payload_sha256=digest, absent=True)
            confirmation_payloads.update(cohort["payload_sha256"])
            records = {r["id"]: r for r in cohort["records"]}
            # Archived absolute folder strings are provenance. All actual file
            # reads relocate through the supplied root and public world id.
            assert all(Path(r["folder"]).name == r["id"] for r in records.values())
            publics = {i: read(confirmation/i/"public.json") for i in records}
            # These two caches depend exclusively on public information and the
            # named supplied law; no episode outcome can change a cached answer.
            oracles = {i: task.Oracle(p, law, confusion) for i,p in publics.items()}
            nominal_oracles = {i: task.Oracle(p, nominal, confusion) for i,p in publics.items()}
            arms = [(f,c) for f in protocol["families"] for c in protocol["controllers"]]+[(f,"value") for f in REFERENCES]
            rng = np.random.default_rng(protocol["execution_order_seed"]+fit*1000000+(0 if split == "iid" else 100000))
            expected_order = [dict(world=r["id"], family=arms[int(j)][0], controller=arms[int(j)][1]) for r in cohort["records"] for j in rng.permutation(len(arms))]
            assert read(confirmation/f"execution_order_{fit}_{split}.json") == expected_order
            for family, controller in arms:
                name = f"fit_{fit}_{split}_{family}"+("" if family in REFERENCES else "_"+controller)+".json.gz"
                group = read(confirmation/name)
                assert [e["world"] for e in group["episodes"]] == list(records)
                episodes = group["episodes"]
                for episode in episodes:
                    world = episode["world"]; public = publics[world]; oracle = oracles[world]
                    evaluator = read(confirmation/world/"evaluator.json")
                    predictor = models.get(family)
                    if family in REFERENCES:
                        reference_path = confirmation/"reference_tables"/(world+"_"+family+".json.gz")
                        assert sha(reference_path) == episode["reference"]["sha256"]
                        assert reference_path.stat().st_size == episode["reference"]["bytes"]
                        reference = read(reference_path)
                        if family in ("reference_nominal", "reference_known_environment"):
                            artifact = reference["artifact"]
                            assert artifact["public"] == public and artifact["decoder_confusion"] == confusion
                            assert hashlib.sha256(json_bytes(artifact)).hexdigest() == reference["payload_sha256"]
                            declared = nominal_oracles[world] if family == "reference_nominal" else oracle
                            assert artifact["law"] == declared.law.export()
                            predictor = CompiledPolicy(artifact)
                            assert len(artifact["states"]) == artifact["state_count"]
                            for key, row in artifact["states"].items():
                                s = declared._state(tuple(json.loads(key)))
                                mask = np.asarray(task.legal(public, s)); q = declared.q(s)
                                close({k:v for k,v in row.items() if k != "action"},
                                      dict(q=np.where(mask,q,0.).tolist(), legal=mask.tolist(), belief=declared.posterior(s)))
                                assert row["action"] == int(np.argmax(np.where(mask,row["q"],-np.inf)))
                                gap = float(max(q)-q[row["action"]])
                                assert mask[row["action"]] and gap <= 1e-12
                                totals["max_compiled_stored_action_oracle_gap"] = max(totals["max_compiled_stored_action_oracle_gap"],gap)
                                totals["compiled_argmax_numerical_ties"] += int(row["action"] != int(np.argmax(q)))
                            totals["compiled_states"] += artifact["state_count"]
                        elif family == "reference_deadline_read":
                            assert reference["policy_source_sha256"] == sha(HERE/"joint_deadline_reference.py")
                            predictor = DeadlineOnlyPolicy(public, confusion)
                    state = task.initial(public)
                    regret, brier, return_error = [], [], []
                    attempts, successes, inner_cpu, inner_wall = 0, 0, 0., 0.
                    for decision in episode["decisions"]:
                        receipt = decision["receipt"]; action = decision["action"]
                        assert receipt["before"] == state and receipt["action"] == action
                        mask = np.asarray(task.legal(public, state)); assert mask[action]
                        if family == "reference_no_read":
                            p = oracle.posterior(state)
                            expected_scores = dict(q=[0.,-1e100,-1e100,-1e100,1-2*p,2*p-1], belief=p)
                        else:
                            expected_scores = predictor.predict(public, state)
                        close(decision["scores"], expected_scores, family+"/scores")
                        expected_action = task.fixed_action(state, mask, expected_scores["belief"]) if controller == "fixed" else int(np.argmax(np.where(mask, expected_scores["q"], -np.inf)))
                        assert action == expected_action
                        close(decision["chosen_q"], expected_scores["q"][action])
                        close(decision["charges_before"], state["charges"])
                        q = oracle.q(state); legal_q = q[mask]
                        close(decision["teacher_q"], np.where(mask,q,0.).tolist())
                        close(decision["teacher_mass"], oracle.belief(state).tolist())
                        close(decision["teacher_bank"], oracle.bank(state).tolist())
                        regret.append(float(max(q)-q[action]))
                        close(decision["teacher_regret"], regret[-1])
                        close(decision["teacher_margin"], float(np.sort(legal_q)[-1]-np.sort(legal_q)[-2]))
                        due = task.due_request(public, state, action)
                        assert receipt["source_opened"] == (None if due is None else due-1) and receipt["observation_tick"] == due
                        if due is None:
                            assert receipt["content"] is None and receipt["completion"] is None
                        else:
                            attempts += 1
                            path = confirmation/world/public["packets"][due-1]
                            assert receipt["completion"]["observation_tick"] == due
                            if receipt["completion"].get("failure", False):
                                assert not path.exists() and evaluator["injected_missing"][due-1]
                                assert receipt["content"]["failure"] == "FileNotFoundError"
                            else:
                                assert not evaluator["injected_missing"][due-1]
                                if str(path) not in decoded:
                                    decoded[str(path)] = adapter.read(path)
                                result = decoded[str(path)]; content = receipt["content"]
                                for field in ("observation", "payload_sha256", "payload_bytes", "logits", "numerical"):
                                    close(content[field], result[field], "content/"+field)
                                assert result["payload_sha256"] == public["packet_sha256"][due-1]
                                assert result["observation"] == receipt["completion"]["observation"]
                                successes += 1
                        after = task.successor(public, state, action, receipt["completion"])
                        assert receipt["after"] == after
                        brier.append((expected_scores["belief"]-evaluator["label"])**2)
                        for clock in ("cpu", "wall"):
                            assert decision["control_"+clock+"_seconds"] >= 0 and receipt[clock+"_seconds"] >= 0
                        inner_cpu += decision["control_cpu_seconds"]+receipt["cpu_seconds"]
                        inner_wall += decision["control_wall_seconds"]+receipt["wall_seconds"]
                        state = after; totals["decisions"] += 1
                    assert state == episode["final_state"]
                    actual = episode["outcome"]; expected = task.evaluate_terminal(state, evaluator["label"])
                    for d in episode["decisions"]:
                        target = expected["reward"]-state["charges"]+d["charges_before"]
                        return_error.append((d["chosen_q"]-target)**2)
                    expected.update(belief_brier=float(np.mean(brier)), chosen_q_return_mse=float(np.mean(return_error)),
                        fitted_teacher_regret=float(np.mean(regret)), due_read_attempts=attempts, successful_content_decodes=successes,
                        execution_cpu_seconds=inner_cpu, execution_wall_seconds=inner_wall)
                    for key, value in expected.items():
                        close(actual[key], value, "outcome/"+key)
                    for clock in ("cpu", "wall"):
                        share = setup["load_"+clock+"_seconds"]/requests
                        close(actual["decoder_setup_amortized_"+clock+"_seconds"], share)
                        setup_totals[clock] += share
                        full = actual["full_execution_"+clock+"_seconds"]-share
                        assert full+1e-8 >= actual["execution_"+clock+"_seconds"]+actual["model_load_"+clock+"_seconds"]
                        assert actual["instrumented_"+clock+"_seconds"]+1e-8 >= full+actual["audit_"+clock+"_seconds"]
                    wire = dict(world=world, decisions=[{k:v for k,v in d.items() if k not in TEACHER} for d in episode["decisions"]], final_state=state)
                    assert len(json.dumps(wire,separators=(",",":"),allow_nan=False).encode()) == actual["wire_bytes"]
                    totals["episodes"] += 1; totals["due_read_attempts"] += attempts
                    totals["successful_content_decodes"] += successes; totals["failed_content_reads"] += attempts-successes
                    totals["wire_bytes"] += actual["wire_bytes"]
                    totals["complete_request_cpu_seconds"] += actual["full_execution_cpu_seconds"]
                    totals["postexecution_audit_cpu_seconds"] += actual["audit_cpu_seconds"]
                means = {k:float(np.mean([e["outcome"][k] for e in episodes])) for k in episodes[0]["outcome"]}
                key = split+"/"+family+("" if family in REFERENCES else "/"+controller)
                if family not in REFERENCES:
                    means["wall_p95_seconds"] = float(np.quantile([e["outcome"]["full_execution_wall_seconds"] for e in episodes],.95))
                    means["serial_service_throughput"] = len(episodes)/sum(e["outcome"]["full_execution_wall_seconds"] for e in episodes)
                close(group["means"], means, "groupmeans/"+key)
                destination, count_destination = (references,reference_counts) if family in REFERENCES else (aggregate,counts)
                destination.setdefault(key,[]).append(dict(fit=fit,**means)); count_destination[key] = count_destination.get(key,0)+len(episodes)
                model_load_cpu.setdefault(key,[]).append(means["model_load_cpu_seconds"])
                full_cpu.setdefault(key,[]).append(means["full_execution_cpu_seconds"])
            print(json.dumps(dict(audit_fit=fit, split=split, verified_episodes=totals["episodes"])),flush=True)
        close(setup_totals, dict(cpu=setup["load_cpu_seconds"],wall=setup["load_wall_seconds"]), "decoder_setup_total")
    assert not training_payloads.intersection(confirmation_payloads)
    assert len(confirmation_payloads) == 2400 and totals["episodes"] == 4800
    assert summary["internal_cpu_seconds"]+1e-5 >= totals["complete_request_cpu_seconds"]+totals["postexecution_audit_cpu_seconds"]
    assert summary["complete_process_usage"]["self_cpu_seconds"] >= summary["internal_cpu_seconds"]
    close(summary["fit_means"],aggregate); close(summary["reference_fit_means"],references)
    close(summary["counts"],counts); close(summary["reference_counts"],reference_counts)
    primary, secondary = intervals(aggregate, protocol)
    close(summary["contrasts"],primary); close(summary["adoption"],secondary)
    # End guard also records every intentionally absent packet, not just packets
    # actually requested by some policy or the runner's existing-file guard.
    assert all(sha(confirmation/p)==v["sha256"] for p,v in all_inputs.items())
    assert all(not (confirmation/p).exists() for p in all_missing)
    assert all(sha(REPOSITORY/p)==h for p,h in freeze["sources"].items())
    assert all(sha(root/p)==h for p,h in freeze["models"].items())
    manifest = dict(schema="joint-confirmation-independent-input-manifest-v1",files=all_inputs,
                    expected_missing=all_missing, cohort_manifests=input_files,
                    training_calibration_files=calibration_inputs,
                    regenerated_worlds=400, training_confirmation_payloads_disjoint=True)
    return dict(passed=True, **totals, unique_packets_independently_redecoded=len(decoded),
        verified_input_files=len(all_inputs), verified_absent_packets=len(all_missing),
        training_calibration_packets_regenerated_and_redecoded=len(calibration_inputs),
        source_sha256=freeze["sources"], model_freeze_sha256=sha(root/"MODEL_FREEZE.json"),
        published_model_commit=started["published_model_commit"], primary=primary, secondary=secondary,
        published_adapter_commit=adapter_provenance["published_adapter_commit"],
        complete_process_receipt_sha256=sha(process_receipt), complete_process_cpu_seconds=process["cpu_seconds"],
        complete_process_wall_seconds=process["wall_seconds"], complete_process_peak_resident_kib=process["maximum_resident_kib"],
        primary_passes=sum(r["passed"] for r in primary.values()), secondary_comparison_passes=sum(r["passed"] for r in secondary.values()),
        inference_frame_model_load_cpu_fraction={k:float(np.mean(model_load_cpu[k])/np.mean(full_cpu[k])) for k in model_load_cpu},
        scope="All raw episodes, regenerated inputs, supplied-law Q, actual FullHX redecode, costs arithmetic and separate14/24 CI families; not independent hardware timing, continuous-law optimum, lifecycle adoption or optimizer rerun"), manifest


def main():
    p = argparse.ArgumentParser(); p.add_argument("--root",type=Path,required=True)
    p.add_argument("--confirmation",type=Path,required=True); p.add_argument("--out",type=Path,required=True)
    p.add_argument("--process-receipt",type=Path)
    p.add_argument("--input-manifest",type=Path,required=True); a = p.parse_args()
    wall, cpu = time.perf_counter(),time.process_time()
    try:
        receipt = a.process_receipt or a.confirmation.with_name(a.confirmation.name+".process.json")
        result, manifest = audit(a.root,a.confirmation,receipt)
        with a.input_manifest.open("x") as stream:
            json.dump(manifest,stream,sort_keys=True,indent=2,allow_nan=False); stream.write("\n")
        result["input_manifest_sha256"] = sha(a.input_manifest)
    except Exception:
        result = dict(passed=False,error=traceback.format_exc())
    result.update(audit_source_sha256=sha(__file__), audit_cpu_seconds=time.process_time()-cpu,
                  audit_wall_seconds=time.perf_counter()-wall)
    with a.out.open("x") as stream:
        json.dump(result,stream,sort_keys=True,indent=2,allow_nan=False); stream.write("\n")
    print(json.dumps({k:v for k,v in result.items() if k not in ("primary","secondary","source_sha256")},sort_keys=True))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
