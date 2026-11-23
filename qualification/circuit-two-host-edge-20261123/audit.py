"""Audit two hosted jobs and reconstruct their three greedy outputs after delivery."""

from datetime import datetime
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile

from cell_experiments import data
from cell_experiments.online_v4 import circuit_bundle

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / "paired-consumer-circuit-20261123"
spec = importlib.util.spec_from_file_location("local_fixture_forward", PRIOR / "verify.py")
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)
RUN = 45189161669
REVISION = "eba6e3ef8e909f627f0f58e095732fb6b6d2fb3e"
REPO = "TrillionniumFoundation/hepta-private-ci"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def only(row, fields):
    return {key: row[key] for key in fields.split()}


def collect(path):
    def api(route):
        return subprocess.check_output(["gh", "api", "repos/" + REPO + "/actions/" + route])

    run = json.loads(api(f"runs/{RUN}"))
    require(run["head_sha"] == REVISION and run["conclusion"] == "success", "original run not complete")
    jobs = []
    for job in json.loads(api(f"runs/{RUN}/jobs?per_page=100"))["jobs"]:
        record = only(job, "id name run_id runner_id runner_name labels created_at started_at completed_at conclusion")
        record["steps"] = [only(step, "name started_at completed_at conclusion") for step in job["steps"]]
        jobs.append(record)
    records = json.loads(api(f"runs/{RUN}/artifacts?per_page=100"))["artifacts"]
    artifacts = [only(a, "id name size_in_bytes digest created_at") for a in records]
    platform = dict(run=only(run, "id run_attempt head_sha created_at run_started_at updated_at conclusion"),
                    jobs=jobs, artifacts=artifacts)
    with zipfile.ZipFile(path, "x", zipfile.ZIP_DEFLATED) as out:
        out.writestr("platform.json", data.canonical(platform))
        for a in artifacts:
            blob = api(f"artifacts/{a['id']}/zip")
            require("sha256:" + sha(blob) == a["digest"] and len(blob) == a["size_in_bytes"],
                    "original Actions artifact differs")
            out.writestr(a["name"] + ".zip", blob)


def load(z, name):
    return json.loads(z.read(name))


def seconds(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def delta(z, before, after):
    return (int(z.read(after)) - int(z.read(before))) / 1e9


def audit(path):
    with zipfile.ZipFile(path) as combined, zipfile.ZipFile(PRIOR / "CONSUMER_CIRCUIT_ORIGINALS.zip") as frozen:
        p = load(combined, "platform.json")
        run = p["run"]
        jobs = {j["name"]: j for j in p["jobs"]}
        inventory = {a["name"]: a for a in p["artifacts"]}
        require(run["head_sha"] == REVISION and run["id"] == RUN and run["conclusion"] == "success"
                and set(jobs) == {"source", "reader"} and all(j["conclusion"] == "success" for j in jobs.values()),
                "wrong original workflow or job set")

        def archive(name):
            raw = combined.read(name + ".zip")
            require("sha256:" + sha(raw) == inventory[name]["digest"] and len(raw) == inventory[name]["size_in_bytes"],
                    "compressed original artifact changed")
            return zipfile.ZipFile(io.BytesIO(raw))

        with (archive("frozen-circuit-edge") as transport, archive("frozen-circuit-source-observation") as a,
              archive("frozen-circuit-reader-observation") as b):
            wire = transport.read("edge.json")
            edge = json.loads(wire)
            answer = transport.read("answer.utf8")
            source, connected, removed = load(a, "source.json"), load(b, "connected.json"), load(b, "removed.json")
            rows = [source, connected, removed]
            binding = edge["binding"]
            info = inventory["frozen-circuit-edge"]
            require(all(item["binding"] == binding for item in rows)
                    and binding["run"] == dict(repository=REPO, revision=REVISION, run_id=str(RUN), attempt=str(run["run_attempt"]))
                    and data.digest(source) == edge["source_observation_sha256"]
                    and edge["answer_sha256"] == sha(answer) and edge["answer_bytes"] == len(answer)
                    and source["prediction"]["answer"].encode() == answer
                    and connected["consumed_edge_sha256"] == removed["consumed_edge_sha256"] == sha(wire)
                    and info["id"] == int(a.read("edge-artifact-id"))
                    and info["digest"].removeprefix("sha256:") == a.read("edge-artifact-sha256").decode().strip().removeprefix("sha256:"),
                    "producer observation, bridge or consumer commitment differs")
            require(source["host"]["boot_sha256"] == edge["source_boot_sha256"]
                    and connected["host"] == removed["host"] and connected["host"]["boot_sha256"] != source["host"]["boot_sha256"]
                    and jobs["source"]["id"] != jobs["reader"]["id"] and jobs["source"]["runner_id"] != jobs["reader"]["runner_id"]
                    and jobs["source"]["labels"] == ["ubuntu-24.04"] and jobs["reader"]["labels"] == ["ubuntu-22.04"]
                    and all(jobs[k]["runner_name"] == item["host"]["runner"]
                            for k, item in (("source", source), ("reader", connected))),
                    "two hosted VM identities required")
            prior = load(frozen, "SUMMARY.json")
            prefix = "original/intake/" + prior["admission"] + "/consumer/" + prior["run"]["operation"] + "/"
            packet = load(frozen, prefix + "worker-input.json")
            old = load(frozen, prefix + "worker-output.json")["prediction"]
            bundle, task = packet["model"], packet["task"]
            trace = old["circuit_trace"]
            graph = trace["graph"]
            require(binding["frozen_archive_sha256"] == sha((PRIOR / "CONSUMER_CIRCUIT_ORIGINALS.zip").read_bytes())
                    and binding["operation"] == prior["run"]["operation"]
                    and binding["circuit_sha256"] == data.digest(bundle) and binding["task_sha256"] == data.digest(task)
                    and binding["router_sha256"] == bundle["router_sha256"] and binding["graph_sha256"] == data.digest(graph)
                    and all(binding[key + "_sha256"] == data.digest(bundle["models"][key]) for key in ("source", "reader")),
                    "original frozen identity differs")
            circuit_bundle.check_prediction(bundle, old, task)
            require([item["mode"] for item in rows] == ["source", "connected", "removed"]
                    and connected["pid"] != removed["pid"], "conditions must use fresh reader processes")
            for item, slot in zip(rows, ("source", "reader", "reader"), strict=True):
                pred = item["prediction"]
                require(item["graph"] == graph and item["actual_slot"] == slot and pred["pid"] == item["pid"]
                        and pred["loaded_model_digest"] == data.digest(bundle["models"][slot])
                        and pred["output_ids"] == [reference.replay_token(frozen, bundle["models"][slot], pred["input_ids"])]
                        and all(item["route"][k] == trace["route"][k] for k in
                                ("graph_id", "router_digest", "features_digest", "scores", "reads")),
                        "frozen route or reconstructed primitive output differs")
            for item, node in zip(rows[:2], trace["nodes"], strict=True):
                require(item["request"] == node["request"] and all(
                    item["prediction"][k] == node["output"][k]
                    for k in ("rendered_input", "input_ids", "output_ids", "answer", "loaded_model_digest")),
                    "connected result differs from archived single-host execution")
            require(source["request"] == removed["request"] and connected["request"]["messages"]
                    == [*removed["request"]["messages"], {"role":"tool", "content":answer.decode()}]
                    and removed["prediction"]["input_ids"] == source["prediction"]["input_ids"],
                    "the control changed another input")
            timings = {item["mode"]: dict(input_ids=item["prediction"]["input_ids"],
                       output_ids=item["prediction"]["output_ids"], answer=item["prediction"]["answer"],
                       preflight_s=item["preflight_ns"]/1e9, cold_load_s=item["cold_load_ns"]/1e9,
                       predict_call_s=item["predict_call_ns"]/1e9, generation_s=item["prediction"]["elapsed_seconds"])
                       for item in rows}
            asub = seconds(run["created_at"])
            aend = seconds(jobs["source"]["completed_at"])
            return dict(raw_bundle_sha256=sha(path.read_bytes()), revision=REVISION, run_id=RUN,
                        hosted_jobs={k:dict(id=jobs[k]["id"], runner_id=jobs[k]["runner_id"], **v["host"])
                                     for k, v in (("source",source),("reader",connected))},
                        conditions=timings, connected_nodes_matching_single_host=2, independent_greedy_forwards=3,
                        edge_artifact_id=info["id"], application_answer_bytes=len(answer), envelope_file_bytes=len(wire),
                        application_files_total_bytes=len(wire)+len(answer), artifact_zip_bytes=info["size_in_bytes"],
                        upload_action_s=delta(a,"upload-before.ns","upload-after.ns"),
                        download_action_s=delta(b,"download-before.ns","download-after.ns"),
                        platform_submission_to_source_start_s=seconds(jobs["source"]["started_at"])-asub,
                        platform_source_end_to_reader_start_s=seconds(jobs["reader"]["started_at"])-aend,
                        submission_to_source_first_user_step_s=int(a.read("job-first-step.ns"))/1e9-asub,
                        source_end_to_reader_first_user_step_s=int(b.read("job-first-step.ns"))/1e9-aend,
                        approximate_cross_vm_upload_start_to_download_completion_s=(
                            int(b.read("download-after.ns"))-int(a.read("upload-before.ns")))/1e9,
                        underlying_physical_hosts_independently_attested=False, real_users=0, payments=0)


if __name__ == "__main__":
    cmd, arg = sys.argv[1:]
    path = Path(arg)
    if cmd == "collect":
        collect(path)
    elif cmd == "verify":
        print(json.dumps(audit(path), indent=2))
    else:
        raise ValueError(cmd)
