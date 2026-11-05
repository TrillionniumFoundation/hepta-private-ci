"""All-state Rust comparison and already-exposed J trajectory replay.

This creates no new scientific qualification. Native output must come from
the actual frozen MCP execution; no Python-policy fallback is permitted.
"""
import argparse
import datetime
import gzip
import json
import math
from pathlib import Path
import resource
import signal
import statistics
import sys
import traceback
import numpy as np
from bridge_io import canonical, counter, elapsed, lines, raw_bytes, read, sha, write, write_bytes, write_lines


Q_TOLERANCE = 2e-12


def scalar_plan(params):
    """Independent ordinary-scalar DAG recurrence, preserving branch order."""
    result = []
    for index, state in enumerate(params["states"]):
        assert len(state["actions"]) == 6
        q = []
        for action in state["actions"]:
            if action is None:
                q.append(None); continue
            if action["kind"] == "terminal":
                value = action["value"]
            else:
                assert action["kind"] == "continue"
                value, total_probability = 0., 0.
                for branch in action["branches"]:
                    probability = branch["probability"]; successor = branch["successor"]
                    assert 0 <= successor < index and probability >= 0 and branch["fee"] >= 0
                    total_probability += probability
                    if probability != 0:
                        value += probability * ((result[successor]["value"]+branch["reward"])-branch["fee"])
                assert abs(total_probability-1) <= 1e-12
            assert math.isfinite(value); q.append(value)
        best, action = -math.inf, None
        for number, value in enumerate(q):
            if value is not None and value > best:
                best, action = value, number
        assert action is not None
        result.append(dict(q=q, value=best, action=action))
    return result


def compare(params, reference, native_record):
    errors = []
    if native_record["rpc_error"] is not None:
        return dict(passed=False, errors=[dict(kind="native_rpc_error", detail=native_record["rpc_error"])])
    actual = native_record["response"]["states"]
    if len(actual) != len(reference):
        return dict(passed=False, errors=[dict(kind="state_count", expected=len(reference), actual=len(actual))])
    scalar = scalar_plan(params)
    max_reference, max_scalar, max_value, legal_q_count = 0., 0., 0., 0
    query_rows = {}
    for index, (expected, emitted, independent) in enumerate(zip(reference, actual, scalar)):
        q = emitted["q"]
        if len(q) != 6 or [v is not None for v in q] != expected["legal"]:
            errors.append(dict(kind="mask", node=index)); continue
        if not all(isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v)
                   for v in q if v is not None):
            errors.append(dict(kind="nonfinite_or_nonnumeric", node=index)); continue
        best, chosen = -math.inf, None
        for action, legal in enumerate(expected["legal"]):
            if not legal:
                continue
            value = q[action]; legal_q_count += 1
            if value > best:
                best, chosen = value, action
            error = abs(value-expected["q"][action]); max_reference = max(max_reference, error)
            scalar_error = abs(value-independent["q"][action]); max_scalar = max(max_scalar, scalar_error)
            if error > Q_TOLERANCE*(1+abs(expected["q"][action])):
                errors.append(dict(kind="reference_Q", node=index, action=action, reference=expected["q"][action], actual=value, error=error))
            if scalar_error > Q_TOLERANCE*(1+abs(independent["q"][action])):
                errors.append(dict(kind="scalar_graph_Q", node=index, action=action, reference=independent["q"][action], actual=value, error=scalar_error))
        action = emitted["action"]
        if (not isinstance(action, int) or isinstance(action, bool) or action != chosen
                or action != expected["action"] or action != independent["action"]):
            errors.append(dict(kind="exact_action", node=index, reference=expected["action"], scalar=independent["action"], argmax=chosen, actual=action))
        value = emitted["value"]
        if not isinstance(value, (float, int)) or isinstance(value, bool) or not math.isfinite(value) or value != best:
            errors.append(dict(kind="reported_value", node=index))
        else:
            error = abs(value-expected["value"]); max_value = max(max_value, error)
            if error > Q_TOLERANCE*(1+abs(expected["value"])):
                errors.append(dict(kind="reference_value", node=index, error=error))
        if expected["layer"] == "representative_query":
            query_rows[expected["markov_key"]] = dict(q=[0. if v is None else v for v in q],
                legal=expected["legal"], belief=expected["belief"], action=action)
    return dict(passed=not errors, errors=errors, nodes=len(actual), legal_Q_count=legal_q_count,
        max_reference_Q_absolute_error=max_reference, max_scalar_graph_Q_absolute_error=max_scalar,
        max_reference_value_absolute_error=max_value, query_rows=query_rows)


class NativeLookup:
    def __init__(self, planning, ctx, public, rows):
        self.planning, self.ctx, self.public, self.rows = planning, ctx, public, rows

    def scores(self, state, unused_theta, unused_structural):
        row = self.rows[self.planning.markov_key(state)]
        assert row["legal"] == self.ctx.legal(self.public, state)
        return np.asarray(row["q"]), row["belief"]


def main(args):
    args.output.mkdir(exist_ok=False); started = counter()
    protocol = read(args.protocol); freeze = read(Path(__file__).with_name("VERIFIER_FREEZE.json"))
    assert sha(args.protocol.read_bytes()) == freeze["acceptance_protocol_sha256"]
    assert sha(Path(__file__).read_bytes()) == freeze["verifier_source_sha256"]
    import bridge_io
    assert sha(Path(bridge_io.__file__).read_bytes()) == freeze["bridge_io_sha256"]
    assert protocol["acceptance"]["all_legal_Q"] == "absolute error <= 2e-12 * (1 + abs(reference_Q)), on canonical and query nodes"
    def timeout(*unused):
        raise TimeoutError("frozen native comparison/J replay resource cap")
    signal.signal(signal.SIGALRM, timeout); signal.signal(signal.SIGXCPU, timeout)
    cap = protocol["resource_caps"]["verification_and_J_replay_cpu_seconds"]
    resource.setrlimit(resource.RLIMIT_CPU, (cap, cap+5))
    signal.alarm(protocol["resource_caps"]["verification_and_J_replay_wall_seconds"])
    native_manifest = read(args.native/"NATIVE_CORPUS_MANIFEST.json")
    native_protocol = args.native/"EXECUTION_PROTOCOL.json"
    assert sha(native_protocol.read_bytes()) == native_manifest["native_execution_protocol_sha256"] == freeze["native_execution_protocol_sha256"]
    execution_protocol = read(native_protocol)
    native_receipt_path = args.native/native_manifest["whole_process_receipt_file"]
    assert native_receipt_path.name == native_manifest["whole_process_receipt_file"]
    assert sha(native_receipt_path.read_bytes()) == native_manifest["whole_process_receipt_sha256"]
    outer_execution = read(native_receipt_path)
    assert outer_execution["protocol_sha256"] == native_manifest["native_execution_protocol_sha256"]
    assert outer_execution["driver_sha256"] == execution_protocol["script_sha256"]["driver"]
    assert outer_execution["supervisor_sha256"] == execution_protocol["script_sha256"]["supervisor"]
    internal_path = args.native/native_manifest["internal_execution_receipt_file"]
    assert internal_path.name == native_manifest["internal_execution_receipt_file"]
    assert sha(internal_path.read_bytes()) == native_manifest["internal_execution_receipt_sha256"]
    internal_execution = read(internal_path)
    pinned_native = {}
    for label in ("qualified_source_manifest", "local_qualification"):
        path = args.native/native_manifest[label+"_file"]
        assert path.name == native_manifest[label+"_file"]
        assert sha(path.read_bytes()) == native_manifest[label+"_sha256"] == execution_protocol[label+"_sha256"]
        pinned_native[label] = read(path)
    qualification = pinned_native["local_qualification"]
    assert qualification["completed"] and qualification["passed"]
    assert qualification["binary"]["sha256"] == execution_protocol["binary_sha256"]
    assert qualification["source_after_last_command"] == pinned_native["qualified_source_manifest"]
    assert {x["path"]:x["sha256"] for x in pinned_native["qualified_source_manifest"]}["src/mcp/weight_bellman.rs"] == execution_protocol["bellman_module_sha256"]
    assert native_manifest["planned_worlds"] == protocol["world_count"]
    export_manifest = read(args.exported/"EXPORT_MANIFEST.json")
    assert sha(raw_bytes(args.exported/"EXPORT_MANIFEST.json")) == freeze["export_manifest_sha256"]
    assert export_manifest["protocol_sha256"] == sha(args.protocol.read_bytes())
    run = args.science/"execution_r1/run"
    assert sha((run/"RESULTS.json").read_bytes()) == protocol["scientific_results_sha256"]
    sys.path.insert(0, str(args.science.resolve())); import planning
    assert sha(Path(planning.__file__).read_bytes()) == read(args.exported/"STARTED.json")["frozen_planning_sha256"]
    for key, expected in read(args.exported/"STARTED.json")["frozen_joint_sources"].items():
        assert sha((args.joint/key.split("/", 1)[1]).read_bytes()) == expected
    expected_groups = {f"fit_{f}_{d}.jsonl.gz" for f in protocol["fits"] for d in protocol["domains"]}
    assert set(native_manifest["files"]) == expected_groups
    write(args.output/"STARTED.json", dict(schema="hepta-native-bellman-verifier-start-v1", verifier_freeze=freeze,
        native_manifest_sha256=sha(raw_bytes(args.native/"NATIVE_CORPUS_MANIFEST.json")),
        export_manifest_sha256=sha(raw_bytes(args.exported/"EXPORT_MANIFEST.json")),
        started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), python=sys.version, numpy=np.__version__))
    try:
        ctx = planning.load_context(args.joint)
        summaries, comparisons, reevaluated, attempted, rpc_errors = {}, [], [], 0, 0
        for fit in protocol["fits"]:
            model_path = run/f"models/fit_{fit}_C.json.gz"
            model = ctx.NumpyPolicy(read(model_path))
            model_sha256 = sha(raw_bytes(model_path))
            canonical_model_sha256 = sha(canonical(model.artifact).encode())
            for domain in protocol["domains"]:
                name = f"fit_{fit}_{domain}.jsonl.gz"; checks, replay_rows = [], []
                for relative in ("requests/"+name, "references/"+name):
                    blob = raw_bytes(args.exported/relative); identity = export_manifest["files"][relative]
                    assert len(blob) == identity["bytes"] and sha(blob) == identity["sha256"]
                blob = raw_bytes(args.native/name); identity = native_manifest["files"][name]
                assert len(blob) == identity["bytes"] and sha(blob) == identity["sha256"]
                requests, references, responses = lines(args.exported/"requests"/name), lines(args.exported/"references"/name), lines(args.native/name)
                scientific = read(run/f"test_{fit}_{domain}_RESULTS.json.gz")["records"]
                publics = read(run/f"worlds/test_{fit}_{domain}.json.gz")["worlds"]
                assert len(requests) == len(references) == len(scientific) == len(publics) == protocol["worlds_per_fit_domain"]
                by_id = {x["request_id"]: x for x in responses}; assert len(by_id) == len(responses)
                assert set(by_id) <= {x["request_id"] for x in requests}
                attempted += len(responses)
                for request, reference, original, public in zip(requests, references, scientific, publics):
                    identifier = request["request_id"]; expected = reference["metadata"]
                    assert identifier == reference["request_id"] and original["world_id"] == public["id"] == expected["world_id"]
                    assert public == reference["public"]
                    assert sha(canonical(public).encode()) == expected["public_sha256"]
                    assert model_sha256 == expected["model_compressed_sha256"]
                    assert canonical_model_sha256 == expected["checkpoint_sha256"]
                    assert sha(canonical(request["params"]).encode()) == expected["graph_params_sha256"]
                    assert expected["scientific_table_sha256"] == original["own_bellman"]["table_sha256"]
                    response = by_id.get(identifier)
                    if response is None:
                        report = dict(passed=False, errors=[dict(kind="missing_native_response")])
                    else:
                        assert response["graph_params_sha256"] == expected["graph_params_sha256"]
                        rpc_errors += response["rpc_error"] is not None
                        report = compare(request["params"], reference["states"], response)
                        report["native_response_sha256"] = sha(canonical(response).encode())
                        if response["rpc_error"] is None:
                            assert response["response"]["implementation_source_sha256"] == execution_protocol["bellman_module_sha256"]
                            assert response["response"]["state_count"] == len(reference["states"])
                            transport = response["transport"]
                            arguments = json.dumps(request["params"], separators=(",", ":"), allow_nan=False).encode()
                            assert len(arguments) == transport["transport_arguments_bytes"]
                            assert sha(arguments) == transport["transport_arguments_sha256"]
                            message = {"jsonrpc":"2.0", "id":transport["jsonrpc_request_id"], "method":"tools/call",
                                       "params":{"name":protocol["rpc"]["method"], "arguments":request["params"]}}
                            encoded = (json.dumps(message, separators=(",", ":"), allow_nan=False)+"\n").encode()
                            assert len(encoded) == transport["jsonrpc_request_bytes"]
                            assert sha(encoded) == transport["jsonrpc_request_sha256"]
                            digest = response["response"]["request_sha256"]
                            assert len(digest) == 64 and set(digest) <= set("0123456789abcdef")
                            report["native_typed_serde_request_sha256"] = digest
                    query_rows = report.pop("query_rows", None)
                    report.update(request_id=identifier, world_id=public["id"], graph_params_sha256=expected["graph_params_sha256"])
                    checks.append(report); comparisons.append(report)
                    if report["passed"]:
                        assert len(query_rows) == expected["markov_states"]
                        lookup = NativeLookup(planning, ctx, public, query_rows)
                        truth = ctx.Oracle(public, ctx.law, model.confusion)
                        actual = planning.evaluate(ctx, public, lookup, None, "J", truth)
                        error = abs(actual["utility"]-original["arms"]["J"]["utility"])
                        passed = error <= Q_TOLERANCE*(1+abs(original["arms"]["J"]["utility"]))
                        row = dict(request_id=identifier, world_id=public["id"], fit=fit, domain=domain,
                            native_J=actual, scientific_J_utility=original["arms"]["J"]["utility"], utility_absolute_error=error,
                            utility_passed=passed, policy_source="Rust MCP query-node Q output; own-law posterior from frozen export",
                            scope="expected trajectory replay of an already-exposed world; no packet I/O; Rust is not reinvoked during lookup")
                        replay_rows.append(row); reevaluated.append(row)
                    if elapsed(started)["cpu_seconds"] >= cap:
                        timeout()
                summaries[f"{fit}_{domain}"] = dict(planned=32, compared=len(checks), passed=sum(x["passed"] for x in checks),
                    reevaluated=len(replay_rows), native_J_mean=statistics.mean(x["native_J"]["utility"] for x in replay_rows) if len(replay_rows)==32 else None)
                write_lines(args.output/f"comparisons/{name}", checks)
                if replay_rows:
                    write_lines(args.output/f"replay/{name}", replay_rows)
                else:
                    write_bytes(args.output/f"replay/{name}", gzip.compress(b"", compresslevel=9, mtime=0))
                print(canonical(dict(stage="verified_and_replayed", fit=fit, domain=domain, **summaries[f"{fit}_{domain}"], **elapsed(started))), flush=True)
        assert attempted == native_manifest["attempted_worlds"] and rpc_errors == native_manifest["failed_worlds"]
        assert attempted == internal_execution["attempted_worlds"] and rpc_errors == internal_execution["failed_worlds"]
        internal_healthy = (attempted == 320 and rpc_errors == 0 and native_manifest["fatal"] is None
            and internal_execution["fatal"] is None and internal_execution["executed_binary_unchanged"]
            and native_manifest["binary_sha256"] == internal_execution["binary_sha256"] == execution_protocol["binary_sha256"])
        assert native_manifest["all_requests_completed_without_rpc_error"] == internal_healthy
        outer_healthy = outer_execution["exit_code"] == 0 and not outer_execution["timed_out"] and outer_execution["sources_unchanged"]
        assert native_manifest["outer_process_succeeded"] == outer_healthy
        execution_healthy = internal_healthy and outer_healthy
        assert native_manifest["execution_succeeded"] == execution_healthy
        assert sha(Path(__file__).read_bytes()) == freeze["verifier_source_sha256"]
        assert sha(Path(bridge_io.__file__).read_bytes()) == freeze["bridge_io_sha256"]
        passed = execution_healthy and len(comparisons) == len(reevaluated) == 320 and all(x["passed"] for x in comparisons) and all(x["utility_passed"] for x in reevaluated)
        complete = dict(schema="hepta-native-bellman-engineering-replay-result-v1", passed=passed, planned_worlds=320,
            native_attempted_worlds=attempted, native_rpc_errors=rpc_errors, compared_worlds=len(comparisons), reevaluated_worlds=len(reevaluated),
            native_execution_provenance_healthy=execution_healthy,
            total_compared_nodes=sum(x.get("nodes",0) for x in comparisons), total_compared_legal_Q=sum(x.get("legal_Q_count",0) for x in comparisons),
            max_reference_Q_absolute_error=max((x.get("max_reference_Q_absolute_error",0) for x in comparisons),default=None),
            max_scalar_graph_Q_absolute_error=max((x.get("max_scalar_graph_Q_absolute_error",0) for x in comparisons),default=None),
            max_utility_absolute_error=max((x["utility_absolute_error"] for x in reevaluated),default=None),
            groups=summaries, original_scientific_qualification_unchanged=True, new_scientific_efficacy_qualification=False,
            actual_packet_IO_qualified=False, production_qualified=False, full_economic_net_value_qualified=False,
            arithmetic_audit=ctx.arithmetic_audit, internal_elapsed_before_final_write=elapsed(started),
            scope="native graph-program migration and known-world J replay; exporter source binding is not native checkpoint-law authentication")
        write(args.output/"RESULTS.json", complete); print(canonical(complete), flush=True)
        if not passed:
            raise AssertionError("native engineering acceptance failed; all planned worlds remain in denominator")
    except BaseException as error:
        write(args.output/"FAILED.json", dict(type=type(error).__name__, error=str(error), traceback=traceback.format_exc(),
            planned_world_count=protocol["world_count"], all_partial_records_retained=True, **elapsed(started)))
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("science", "joint", "protocol", "output", "exported", "native"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        main(args)
