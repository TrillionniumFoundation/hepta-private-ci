"""Export the frozen J program as graph-only native RPC requests, once."""
import argparse
import datetime
import math
from pathlib import Path
import resource
import signal
import sys
import time
import traceback
import numpy as np
from bridge_io import canonical, elapsed, counter, measured_sources, read, sha, write, write_lines
from build_graph import build


def main(args):
    args.output.mkdir(exist_ok=False); started = counter()
    protocol = read(args.protocol)
    assert protocol["status"] == "FROZEN_EXPORT_AND_REPLAY_ACCEPTANCE_BEFORE_NATIVE_EXECUTION"
    def timeout(*unused):
        raise TimeoutError("frozen export resource cap")
    signal.signal(signal.SIGALRM, timeout); signal.signal(signal.SIGXCPU, timeout)
    cap = protocol["resource_caps"]["export_worker_cpu_seconds"]
    resource.setrlimit(resource.RLIMIT_CPU, (cap, cap+5))
    signal.alarm(protocol["resource_caps"]["export_worker_wall_seconds"])
    import bridge_io
    import build_graph
    sources = {"bridge/"+p.name: p for p in (Path(__file__), Path(bridge_io.__file__), Path(build_graph.__file__))}
    source_hashes = measured_sources(sources)
    assert source_hashes == protocol["export_sources_sha256"]
    assert sha((args.science/"PROTOCOL_FROZEN.json").read_bytes()) == protocol["scientific_protocol_sha256"]
    run = args.science/"execution_r1/run"
    assert sha((run/"RESULTS.json").read_bytes()) == protocol["scientific_results_sha256"]
    sys.path.insert(0, str(args.science.resolve())); import planning
    old = read(run/"STARTED.json")["sources"]
    assert sha(Path(planning.__file__).read_bytes()) == old["new/planning.py"]
    for name, expected in old.items():
        if name.startswith("joint/"):
            assert sha((args.joint/name.split("/", 1)[1]).read_bytes()) == expected
    write(args.output/"STARTED.json", dict(schema="hepta-native-own-law-export-start-v1",
        protocol_sha256=sha(args.protocol.read_bytes()), sources=source_hashes,
        frozen_planning_sha256=old["new/planning.py"], frozen_joint_sources={k:v for k,v in old.items() if k.startswith("joint/")},
        scientific_results_sha256=protocol["scientific_results_sha256"],
        started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), python=sys.version, numpy=np.__version__))
    try:
        ctx = planning.load_context(args.joint)
        all_metadata, files, total_nodes, total_edges = [], {}, 0, 0
        for fit in protocol["fits"]:
            model_path = run/f"models/fit_{fit}_C.json.gz"
            model = read(model_path); policy = ctx.NumpyPolicy(model)
            model_compressed_sha256 = sha(model_path.read_bytes())
            for domain in protocol["domains"]:
                public_rows = read(run/f"worlds/test_{fit}_{domain}.json.gz")["worlds"]
                scientific = read(run/f"test_{fit}_{domain}_RESULTS.json.gz")["records"]
                assert len(public_rows) == len(scientific) == protocol["worlds_per_fit_domain"]
                requests, references = [], []
                for index, (public, original) in enumerate(zip(public_rows, scientific)):
                    if elapsed(started)["cpu_seconds"] >= cap:
                        timeout()
                    assert public["id"] == original["world_id"]
                    clock = counter()
                    params, reference, metadata = build(planning, ctx, policy, public, original["own_bellman"], protocol["graph"])
                    assert metadata["nodes"] <= protocol["rpc"]["per_request_node_cap"]
                    assert metadata["edges"] <= protocol["rpc"]["per_request_edge_cap"]
                    assert metadata["graph_params_bytes"] <= protocol["rpc"]["per_request_json_bytes_cap"]
                    request_id = f"own_bellman_fit{fit}_{domain}_{index}"
                    metadata.update(request_id=request_id, world_id=public["id"], fit=fit, domain=domain, index=index,
                        schedule_sha256=original["schedule_sha256"], model_compressed_sha256=model_compressed_sha256,
                        generation_measurement=elapsed(clock), scientific_table_sha256=original["own_bellman"]["table_sha256"])
                    requests.append(dict(request_id=request_id, method=protocol["rpc"]["method"], params=params))
                    references.append(dict(request_id=request_id, public=public, metadata=metadata, states=reference))
                    all_metadata.append(metadata); total_nodes += metadata["nodes"]; total_edges += metadata["edges"]
                request_name = f"requests/fit_{fit}_{domain}.jsonl.gz"
                reference_name = f"references/fit_{fit}_{domain}.jsonl.gz"
                files[request_name] = write_lines(args.output/request_name, requests)
                files[reference_name] = write_lines(args.output/reference_name, references)
                print(canonical(dict(stage="exported", fit=fit, domain=domain, worlds=len(requests), **elapsed(started))), flush=True)
                del requests, references
        assert len(all_metadata) == protocol["world_count"]
        assert total_nodes == protocol["graph"]["expected_total_nodes"]
        assert total_edges <= protocol["graph"]["total_edges_upper_bound"]
        assert source_hashes == measured_sources(sources)
        manifest = dict(schema="hepta-own-law-native-graph-corpus-v1", protocol_sha256=sha(args.protocol.read_bytes()),
            scientific_protocol_sha256=protocol["scientific_protocol_sha256"], scientific_results_sha256=protocol["scientific_results_sha256"],
            worlds=all_metadata, files=files, world_count=len(all_metadata), total_nodes=total_nodes, total_edges=total_edges,
            arithmetic_audit=ctx.arithmetic_audit, internal_elapsed_before_manifest_write=elapsed(started),
            environment_truth_in_requests=False, reference_continuation_Q_or_selected_actions_in_requests=False,
            original_scientific_table_hashes_all_exact=True,
            scope="already-exposed TEST engineering replay; supplied checkpoint law graph, no independent scientific efficacy qualification")
        write(args.output/"EXPORT_MANIFEST.json", manifest)
        print(canonical({k:manifest[k] for k in ("world_count","total_nodes","total_edges","original_scientific_table_hashes_all_exact","internal_elapsed_before_manifest_write")}), flush=True)
    except BaseException as error:
        write(args.output/"FAILED.json", dict(type=type(error).__name__, error=str(error), traceback=traceback.format_exc(),
            planned_world_count=protocol["world_count"], all_partial_records_retained=True, **elapsed(started)))
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("science", "joint", "protocol", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        main(args)
