"""Repeat one frozen authored Circuit edge using only the local slot on each runner."""

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import time
import zipfile

from cell_experiments import coding_sft, data
from cell_experiments.online_v4 import circuit_bundle

HERE = Path(__file__).resolve().parent
FROZEN = HERE.parent / "paired-consumer-circuit-20261123" / "CONSUMER_CIRCUIT_ORIGINALS.zip"
FROZEN_SHA = "08640f268030dbb74b97cc63f1631e510848c99b8522231314b1f2a9b5c83099"
ADMISSION = "7fafbcb1bbde28f78282709bd3a3f5f23644a1856a4af3a151bf84c21f38bdd4"
OPERATION = "1430e35c73c8da0006282ca07a291617558cdbd3112e571072ac51b9a0f34eb0"
MODEL = "cbd4d49e8950fbc9b237210d176b9cfe8c8ff0967ba8cdd345f22a7143abbcb0"
TASK = "289b87da4dec4648c37aaa91c405bc0b01b8bb607ae16e7e2bf470e4454a79fa"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write(path, value):
    with path.open("xb") as f:
        f.write(data.canonical(value) + b"\n")


def read(path):
    return json.loads(path.read_bytes())


def host():
    os_info = platform.freedesktop_os_release()
    cpu = Path("/proc/cpuinfo").read_text()
    return dict(runner=os.environ["RUNNER_NAME"], job=os.environ["GITHUB_JOB"],
                kernel=platform.release(), os_release=os_info["PRETTY_NAME"], hostname=platform.node(),
                boot_sha256=sha(Path("/proc/sys/kernel/random/boot_id").read_bytes().strip()),
                image_os=os.environ.get("ImageOS"), image_version=os.environ.get("ImageVersion"),
                cpu=next(x.split(":", 1)[1].strip() for x in cpu.splitlines() if x.startswith("model name")))


def run_ref():
    return dict(repository=os.environ["GITHUB_REPOSITORY"], revision=os.environ["GITHUB_SHA"],
                run_id=os.environ["GITHUB_RUN_ID"], attempt=os.environ["GITHUB_RUN_ATTEMPT"])


def materialize(slot, root):
    require(coding_sft.file_hash(FROZEN) == FROZEN_SHA, "different original frozen fixture")
    with zipfile.ZipFile(FROZEN) as source:
        key = "original/intake/" + ADMISSION + "/consumer/" + OPERATION + "/worker-input.json"
        original = json.loads(source.read(key))
        bundle, task = original["model"], original["task"]
        require(data.digest(bundle) == MODEL and data.digest(task) == TASK, "original study inputs differ")
        model = bundle["models"][slot]
        for item in model["files"]:
            path = Path(item["path"])
            require(not path.is_absolute() and ".." not in path.parts, "invalid bound artifact path")
            data_bytes = source.read("original/materials/" + str(path))
            require(len(data_bytes) == item["bytes"] and sha(data_bytes) == item["sha256"], "weight bytes differ")
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data_bytes)
    require(coding_sft.verify_model(model, root) == data.digest(model), "failed local slot verification")
    router, _, budget = circuit_bundle._components(bundle)
    visible = circuit_bundle._task(task)
    graph, route = router.route({"record_id": "visible", "task": visible})
    require(graph.graph_id == "connected" and graph.path == ("source", "reader") and graph.edges == ("answer",),
            "different frozen route")
    return bundle, model, visible, graph, route, budget


def binding(bundle, graph):
    return dict(run=run_ref(), frozen_archive_sha256=FROZEN_SHA, operation=OPERATION, task_sha256=TASK,
                circuit_sha256=MODEL, router_sha256=bundle["router_sha256"], graph_sha256=data.digest(asdict(graph)),
                source_sha256=data.digest(bundle["models"]["source"]), reader_sha256=data.digest(bundle["models"]["reader"]))


def verify_edge(folder, expected, boot):
    raw = (folder / "edge.json").read_bytes()
    require(sha(raw) == os.environ["EXPECTED_ENVELOPE_SHA"], "edge envelope differs from producer job output")
    edge = json.loads(raw)
    answer = (folder / "answer.utf8").read_bytes()
    require(edge["schema"] == "hepta.research.two-host-edge.v1" and edge["binding"] == expected
            and edge["source_boot_sha256"] != boot and edge["answer_sha256"] == sha(answer)
            and edge["answer_bytes"] == len(answer), "incoming edge, execution identity or bytes differ")
    return edge, answer.decode("utf-8")


def process(mode, out, transfer):
    slot = "source" if mode == "source" else "reader"
    observer = host()
    require(observer["job"] == slot, "wrong hosted job for requested slot")
    with tempfile.TemporaryDirectory() as temp:
        start = time.perf_counter_ns()
        bundle, model, task, graph, route, budget = materialize(slot, Path(temp))
        preflight_ns = time.perf_counter_ns() - start
        spec = binding(bundle, graph)
        edge = None
        if slot == "source":
            visible = circuit_bundle._request(task, graph, 0, [], budget)
        else:
            edge, answer = verify_edge(transfer, spec, observer["boot_sha256"])
            if mode == "connected":
                visible = circuit_bundle._request(task, graph, 1, [{"output": {"answer": answer}}], budget)
            else:
                # Remove only the answer edge. Both cold arms use the same reader and budget.
                visible = dict(input=task["input"], messages=list(task["messages"]))
        t0 = time.perf_counter_ns()
        model_reader = coding_sft.load_predictor(model, Path(temp))
        load_ns = time.perf_counter_ns() - t0
        try:
            t0 = time.perf_counter_ns()
            raw = model_reader.predict({"task": visible}, retain_encoding=True)
            call_ns = time.perf_counter_ns() - t0
        finally:
            model_reader.close()
        require(raw["loaded_model_digest"] == data.digest(model)
                and coding_sft.verify_model(model, Path(temp)) == data.digest(model), "local model differs")
    observation = dict(schema="hepta.research.two-host-observation.v1", mode=mode, binding=spec, host=observer,
                       graph=asdict(graph), route=route, request=visible, prediction=raw, actual_slot=slot,
                       pid=os.getpid(), preflight_ns=preflight_ns, cold_load_ns=load_ns, predict_call_ns=call_ns,
                       finished_wall_ns=time.time_ns(), consumed_edge_sha256=None if edge is None else os.environ["EXPECTED_ENVELOPE_SHA"])
    write(out / (mode + ".json"), observation)
    if slot == "source":
        transfer.mkdir()
        answer = raw["answer"].encode("utf-8")
        edge = dict(schema="hepta.research.two-host-edge.v1", binding=spec, source_boot_sha256=observer["boot_sha256"],
                    source_observation_sha256=data.digest(observation), answer_sha256=sha(answer), answer_bytes=len(answer))
        with (transfer / "answer.utf8").open("xb") as stream:
            stream.write(answer)
        write(transfer / "edge.json", edge)
        with open(os.environ["GITHUB_OUTPUT"], "a") as outputs:
            outputs.write("edge_sha=" + coding_sft.file_hash(transfer / "edge.json") + "\n")


if __name__ == "__main__":
    mode, out, edge = sys.argv[1:]
    require(mode in ("source", "connected", "removed"), "unknown mode")
    process(mode, Path(out), Path(edge))
