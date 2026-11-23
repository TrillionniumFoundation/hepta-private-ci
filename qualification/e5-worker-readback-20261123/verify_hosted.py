"""Validate the two registered fit-and-cold requests from retained bytes with Python's standard library."""

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import zipfile


REQUESTS = {
    "plain": "e0cd3479b1fa58d00896432c908433434cce9a5a1e3dad0df9e79adf8e35f93f",
    "circuit-fitted-controls-final": "7d60577d12d49a10a6896cdef6c9762f7dd40e8d831cdeaf0597c3d626d50276",
}


def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     allow_nan=False, ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def require(result, context):
    if not result:
        raise ValueError(context)


def verify(raw):
    batches = []
    native_circuit = "0f46f3ffa4b65437e47e4bb16453b96b95a532e3aaeaa34799d43e9b6e7b467b"
    expected = dict(REQUESTS)
    accepted_count = 0
    total_rows = total_calls = material_checks = 0
    all_inputs = set()
    with zipfile.ZipFile(raw) as archive:
        def read(path):
            return json.loads(archive.read(path))

        require(archive.testzip() is None, "ZIP CRC mismatch")
        require(len(archive.namelist()) == len(set(archive.namelist())), "Duplicate ZIP member")
        require(archive.read("network-before.txt") == archive.read("network-after.txt"), "Network changed")
        net = archive.read("network-before.txt").decode().splitlines()[2:]
        require(len(net) == 1 and net[0].split(":")[0].strip() == "lo"
                and all(int(x) == 0 for x in net[0].split(":")[1].split()), "Network bytes present")
        summary = read("run/SUMMARY.json")
        label = "historical_exact"
        if "selection.json" in archive.namelist():
            sel = read("selection.json")
            label = sel["label"]
            require(label in ("historical_exact", "hosted_native_exact") and summary["selection"] == sel,
                    "Invalid declared CPU calibration")
            if label == "hosted_native_exact":
                expected["circuit-fitted-controls-final"] = native_circuit
            require(sel["circuit_request"] == expected["circuit-fitted-controls-final"], "Substituted roster")
            ids = ["native", "baseline", "avx2", "avx512", "compatible"]
            require([p["id"] for p in sel["calibrations"]] == ids[:len(sel["calibrations"])], "Calibration order")
            for probe in sel["calibrations"]:
                if "request" in probe:
                    req = read("calibration/" + probe["id"] + "/circuit-fitted-controls-final/request.json")
                    require(digest(req) == probe["request"], "Calibration request")
            exact = next((p for p in sel["calibrations"] if p.get("request") ==
                          REQUESTS["circuit-fitted-controls-final"]), None)
            if label == "historical_exact":
                require(exact and exact["id"] == sel["profile"]["id"], "Profile priority")
            else:
                require(exact is None and sel["calibrations"][0]["request"] == native_circuit, "Native fallback")
        first = {}
        for index, (block, workers) in enumerate(((1, 1), (1, 2), (2, 2), (2, 1))):
            prefix = f"run/block-{block}-workers-{workers}"
            batch = read(prefix + "/BATCH.json")
            require(batch == summary["runs"][index], "Batch and summary differ")
            jobs = batch["jobs"]
            require(len(jobs) == 2 and {j["request"] for j in jobs} == set(expected.values()),
                    "Incorrect trained job roster")
            seconds = (batch["end_ns"] - batch["start_ns"]) * 1e-9
            require(abs(seconds - batch["seconds"]) < 1e-9 and seconds > 0, "Batch clock")
            require(all(batch["start_ns"] <= j["start_ns"] < j["end_ns"] <= batch["end_ns"] for j in jobs),
                    "Job outside clock")
            overlap_ns = max(0, min(j["end_ns"] for j in jobs) - max(j["start_ns"] for j in jobs))
            require((overlap_ns > 0) == (workers == 2), "Declared worker setting not realized")
            require(batch["job_concurrency_nanoseconds"].get("2", 0) == overlap_ns, "Overlap differs")

            for model_dir, registered in expected.items():
                job = next(j for j in jobs if j["request"] == registered)
                require(job["returncode"] == 0, "Nonzero trainer return code")
                root = prefix + "/" + model_dir + "/"
                request = read(root + "evaluation/REQUEST.json")
                request_sha = digest(request)
                accepted = request_sha == registered
                if not accepted:
                    require("selection.json" not in archive.namelist() and
                            model_dir == "circuit-fitted-controls-final" and request_sha == native_circuit and
                            job.get("inspection_failure") == "archived request changed", "Unexpected material")
                accepted_count += int(accepted)
                result = read(root + "evaluation/RESULT.json")
                require(result["request_sha256"] == request_sha and
                        result["external_teacher_calls_by_runner"] == 0, "Cold result identity")
                output_signature = []
                pids = set()
                arm_rows = []
                for a, arm in enumerate(("parent", "candidate")):
                    model = request[arm]
                    component_models = model["models"].values() if "models" in model else [model]
                    for component in component_models:
                        for entry in component["files"]:
                            member = archive.read(root + entry["path"])
                            require(len(member) == entry["bytes"] and hashlib.sha256(member).hexdigest()
                                    == entry["sha256"], "Bound weight, config or tokenizer differs")
                            material_checks += 1
                    if "models" in model:
                        require(digest(model["router"]) == model["router_sha256"], "Router digest")
                    arm_dir = root + "evaluation/" + arm + "/"
                    end = read(arm_dir + "END.json")
                    require(end == result["cold_receipts"][a] and end["request_sha256"] == request_sha
                            and end["arm"] == arm and end["model_digest"] == digest(model), "Cold receipt")
                    pids.add(end["pid"])
                    require(len(end["row_hashes"]) == 2, "Row count")
                    for row_index, panel in enumerate(("future", "retention")):
                        row = read(arm_dir + f"{row_index:04d}.json")
                        task, = request[panel]
                        require(digest(row) == end["row_hashes"][row_index] and digest(task) == row["task_sha256"]
                                and row["panel"] == panel, "Different raw observation")
                        pred = row["prediction"]
                        require(pred["pid"] == end["pid"] and pred["loaded_model_digest"] == digest(model),
                                "Loaded cold weights")
                        verifier = task["task"]["verifier"]
                        require((verifier["name"], verifier["version"]) == ("json_artifact", "1"), "Verifier")
                        answer = json.loads(pred["answer"])
                        want = verifier["parameters"]["expected"]
                        correct = type(answer) is type(want) and answer == want
                        require(correct == row["outcome"]["success"] == (arm == "candidate" or panel == "retention"),
                                "Independent paired semantic verdict")
                        cost = pred.get("circuit_trace", {}).get("cost", {})
                        calls = cost.get("model_calls", 1)
                        in_tokens = cost.get("input_tokens", pred["input_tokens"])
                        out_tokens = cost.get("output_tokens", pred["output_tokens"])
                        total_rows += 1
                        total_calls += calls
                        input_hash = hashlib.sha256(task["task"]["input"].encode()).hexdigest()
                        if panel == "future":
                            all_inputs.add(input_hash)
                        output_signature.append((arm, panel, pred["answer"], correct, calls, in_tokens, out_tokens))
                        arm_rows.append(dict(arm=arm, panel=panel, model=digest(model), input=input_hash,
                                             answer=hashlib.sha256(pred["answer"].encode()).hexdigest(),
                                             passed=correct, model_calls=calls,
                                             input_tokens=in_tokens, output_tokens=out_tokens))
                require(len(pids) == 2, "Both arms must run in separate processes")
                if accepted:
                    require(job["observation"]["rows"] == arm_rows, "Coordinator and original row data differ")
                else:
                    require("observation" not in job, "Unexpected accepted material")
                baseline = first.setdefault(request_sha, output_signature)
                require(baseline == output_signature, "Different output or work between runs")
            batches.append(dict(block=block, workers=workers, seconds=seconds,
                                overlap_seconds=overlap_ns / 1e9, rate=7200 / seconds))
        require(len(summary["runs"]) == len(batches) and summary["matched_outputs_and_work"] == (accepted_count == 8) and
                summary["requested_overlap_observed"], "Summary gates")
        require(len(all_inputs) == 1 and total_rows == 32 and total_calls == 48, "Experimental units")
        medians = {str(k): statistics.median(b["rate"] for b in batches if b["workers"] == k) for k in (1, 2)}
        if accepted_count == 8:
            require(all(abs(v - summary["median_pairs_per_hour"][k]) < 1e-8 for k, v in medians.items()), "Rates")
        else:
            require(not summary["median_pairs_per_hour"], "Incomplete material cohort has estimated speed")
            for batch in batches:
                batch["rate"] = None
            medians = {}
    return dict(registered_model_pairs_verified=accepted_count, requested_roster=label, native_completed_pairs=8,
                cold_arms=16, semantic_answers=total_rows,
                primitive_model_calls=total_calls, material_byte_checks=material_checks,
                distinct_synthetic_future_inputs=len(all_inputs), batches=batches, median_rates=medians,
                ratio=medians["2"] / medians["1"] if medians else None, worker_admission_overlap_only=True,
                user_count=0, observed_adoptions=0, adopted_candidates_per_hour=None)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.archive), indent=2, ensure_ascii=False))
