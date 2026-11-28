"""Evaluate one sealed GPT program in the native graph on new paired inputs."""
import argparse
import json
from pathlib import Path
import resource
import shutil
import time

import numpy as np

from temporal_probe import canonical, encode, previous, save, sha
from late_cue_experiment import compile_sign, historical, metric, native_run, task

ROOT = Path(__file__).resolve().parent
AREA = ROOT/"blind_alias"
PROTOCOL_SHA = "214c06d2d0f141980e2c516b64bbed05382d9dcff7c06ccbf19da409769208ae"
PACKET_SHA = "34315ed9ad41c8faa8effa052cc36c625f464c8f05c3be8148574d2114f8c750"
NATIVE_SHA = "825e5200a83a6ff86485bfa161913440d1d3ea25c10cc4377d480c25c2ce660c"


def decode(case, mapping, candidate):
    a = np.asarray(case["affine"]["values"], dtype=np.float64)
    d = np.asarray(case["affine"]["bias_values"], dtype=np.float64)
    changed = np.asarray(candidate["affine_values"], dtype=np.float64)
    derived = np.asarray(candidate["derived_bias_values"], dtype=np.float64)
    assert changed.shape == a.shape == (4, 9) and derived.shape == d.shape == (4,)
    assert np.isfinite(changed).all() and np.isfinite(derived).all()
    q = mapping["quote_column"]
    other = [k for k in range(9) if k != q]
    assert np.array_equal(changed[:, other], a[:, other]), "outside quote-column scope"
    assert np.array_equal(abs(changed[:, q]), abs(a[:, q])), "magnitude changed"
    expected_bias = d-(changed[:, q]-a[:, q])*mapping["translations"][q]
    bias_error = float(abs(expected_bias-derived).max())
    assert bias_error < 1e-13, "view origin not compensated"
    theta = np.empty(4, dtype=np.float32)
    for j, actual in enumerate(mapping["unit_permutation"]):
        theta[actual] = mapping["unit_signs"][j]*changed[j, q]*mapping["scales"][q]
    status = "KEEP" if np.array_equal(a, changed) else "EDIT"
    assert candidate["status"] == status
    return theta, {"view_bias_max_error": bias_error, "status": status,
                   "canonical_four_word_sha256": sha(theta.astype("<f4").tobytes())}


def wrong_scale(case, mapping):
    """Declared semantic-error control: ignore the sign of the physical unit."""
    affine = case["affine"]
    head = case["signed_readout"]
    h = np.asarray(head["values"])
    contrast = dict(zip(head["column_unit_ids"], h[1]-h[0], strict=True))
    a = np.asarray(affine["values"], dtype=float)
    original = a.copy()
    q = mapping["quote_column"]
    for j, unit in enumerate(affine["row_unit_ids"]):
        if contrast[unit] != 0:
            a[j, q] = -np.sign(contrast[unit])*abs(a[j, q])
    d = np.asarray(affine["bias_values"])-(a[:,q]-original[:,q])*mapping["translations"][q]
    obj = {"affine_values": a.tolist(), "derived_bias_values": d.tolist(),
           "status": "KEEP" if np.array_equal(a,original) else "EDIT"}
    return decode(case,mapping,obj)[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--editor-seal", required=True, type=Path)
    args = parser.parse_args()
    began, cpu = time.perf_counter(), time.process_time()
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    assert sha((ROOT/"BLIND_ALIAS_PROTOCOL.md").read_bytes()) == PROTOCOL_SHA
    assert sha((AREA/"EDITOR_PACKET.json").read_bytes()) == PACKET_SHA
    out = AREA/"results"
    out.mkdir(exist_ok=False)
    native = out/"native-bridge-frozen"
    shutil.copy2(ROOT/"late_results/native-bridge-frozen", native)
    assert sha(native.read_bytes()) == NATIVE_SHA
    packet = json.loads((AREA/"EDITOR_PACKET.json").read_text())
    mapping = json.loads((AREA/"HOST_MAPPING.json").read_text())
    editor_seal = json.loads(args.editor_seal.read_text())
    assert editor_seal["packet_sha256"] == PACKET_SHA
    assert editor_seal["editor_sha256"] == sha(args.program.read_bytes())
    assert editor_seal["candidate_sha256"] == sha(args.candidate.read_bytes())
    assert editor_seal["fresh_test_data_seen"] is False and editor_seal["candidate_generations"] == 1
    submitted = json.loads(args.candidate.read_text())
    assert submitted["schema"] == "hepta.anonymous-affine-edit.v1"
    proposed = {c["case_id"]: c for c in submitted["cases"]}
    cases = {c["case_id"]: c for c in packet["cases"]}
    assert len(proposed) == len(submitted["cases"]) == len(cases) == 3 and proposed.keys() == cases.keys()
    original = previous()
    states = {m["seed"]: original.read_checkpoint(m["seed"]) for m in mapping}
    candidate_rows, chosen = [], {}
    for m in mapping:
        seed, case = m["seed"], cases[m["case_id"]]
        assert original.CHECKPOINT_SHA[seed] == m["canonical_source_pt_sha256"]
        theta, checks = decode(case, m, proposed[m["case_id"]])
        parent = states[seed]["body.input_mark.weight"][:,7].copy()
        direct, _ = compile_sign(states[seed])
        chosen[seed] = {"KEEP": parent, "CANONICAL": direct, "GPT": theta, "WRONG_UNIT_SIGN": wrong_scale(case,m)}
        candidate_rows.append({"seed": seed, "case_id": m["case_id"], "quote_scale": m["scales"][m["quote_column"]],
            "validation": checks, "actual_gpt_changed_words": int((parent != theta).sum()),
            "gpt_ties_canonical_bytes": theta.tobytes() == direct.tobytes(),
            "four_word_sha256": {k:sha(v.astype("<f4").tobytes()) for k,v in chosen[seed].items()},
            "candidate_values": {k:v.tolist() for k,v in chosen[seed].items()}})
    shutil.copyfile(args.program,out/"editor_program.py")
    shutil.copyfile(args.candidate,out/"editor_candidate.json")
    shutil.copyfile(args.editor_seal,out/"editor_seal.json")
    # This seal precedes all new task generation. No candidate is changed below.
    seal = {"schema": "hepta.alias-evaluation-seal.v1", "sealed_unix": time.time(),
        "protocol_sha256": PROTOCOL_SHA, "packet_sha256": PACKET_SHA,
        "editor_program_sha256": sha(args.program.read_bytes()), "editor_candidate_sha256": sha(args.candidate.read_bytes()),
        "editor_seal_sha256": sha(args.editor_seal.read_bytes()), "host_source_sha256": sha(Path(__file__).read_bytes()),
        "native_binary_sha256": NATIVE_SHA, "new_test_generated": False, "candidates": candidate_rows}
    save(out/"CANDIDATES_SEALED_BEFORE_TEST.json",seal)
    test = task(2026112808,40,4.)
    np.savez_compressed(out/"new_test_inputs.npz",x=test["x"],y=test["y"])
    save(out/"TEST_GENERATED.json",{"generated_unix":time.time(),"inputs_sha256":sha((out/"new_test_inputs.npz").read_bytes()),"contexts":40,"queries":80})
    retain = historical("retain")
    records, retention, equivalence = [], [], []
    calls = 0
    for seed in (47,83,137):
        work = out/str(seed)
        work.mkdir()
        parent_path,profile=canonical(states[seed],seed,original.CHECKPOINT_SHA[seed],work,encode(test["x"],test["base"],test["y"]))
        seen = {}
        for arm,theta in chosen[seed].items():
            observed,digest=native_run(native,work,"test_"+arm,parent_path,profile,theta,test,"late-bridge")
            calls += observed["full_model_forward_calls"]
            assert max(observed["physical_residuals"]) <= 2e-9
            scores = np.asarray(observed["scores"],dtype=np.float32).reshape(-1,2)
            seen[arm] = scores.tobytes()
            records.append({"seed":seed,"arm":arm,**metric(scores,test["y"]),"candidate_sha256":digest,
                            "physical_residuals":observed["physical_residuals"],"score_bytes_sha256":sha(scores.tobytes())})
        observed,digest=native_run(native,work,"original_GPT",parent_path,profile,chosen[seed]["GPT"],test,"mark-control")
        calls += observed["full_model_forward_calls"]
        scores = np.asarray(observed["scores"],dtype=np.float32).reshape(-1,2)
        assert np.array_equal(scores[:,0],scores[:,1])
        records.append({"seed":seed,"arm":"ORIGINAL_GRAPH_GPT",**metric(scores,test["y"]),"candidate_sha256":digest,
                        "physical_residuals":observed["physical_residuals"],"score_bytes_sha256":sha(scores.tobytes())})
        normal,digest=native_run(native,work,"retain_GPT",parent_path,profile,chosen[seed]["GPT"],retain,"mark-control")
        calls += normal["full_model_forward_calls"]
        old=json.loads((ROOT/f"late_results/{seed}/retain_PARENT.native.json").read_text())
        equality={key:np.asarray(old[key],dtype="<f4").tobytes()==np.asarray(normal[key],dtype="<f4").tobytes() for key in ("features","heads","scores")}
        equivalence.append({"seed":seed,"gpt_and_canonical_score_bytes_equal":seen["GPT"] == seen["CANONICAL"]})
        retention.append({"seed":seed,"exact_parent_outputs":equality,"correct":normal["correct"],"queries":32,
                          "historical_input":True,"candidate_sha256":digest})
        usage=resource.getrusage(resource.RUSAGE_CHILDREN)
        assert time.process_time()-cpu+usage.ru_utime+usage.ru_stime-children.ru_utime-children.ru_stime <=120
    assert calls==18
    usage=resource.getrusage(resource.RUSAGE_CHILDREN)
    result={"schema":"hepta.alias-transfer-result.v1","status":"COMPLETED","protocol_sha256":PROTOCOL_SHA,
        "records":records,"retention":retention,"equivalence":equivalence,"candidates":candidate_rows,"full_native_forwards":calls,"new_fits":0,
        "new_gradient_steps":0,"fresh_synthetic_contexts":40,"paired_queries":80,"parent_views_share_contexts":True,
        "independent_mechanism_discovery_claimed":False,"native_graph_changed":True,"unlabeled_program_packet":True,
        "editor_feedback_rounds_before_seal":0,"agent_inference_compute_cost":None,
        "packet_to_evaluation_seal_wall_seconds":seal["sealed_unix"]-json.loads((AREA/"PACKET_SEAL.json").read_text())["created_unix"],
        "wall_seconds":time.perf_counter()-began,"python_cpu_seconds":time.process_time()-cpu,
        "native_cpu_seconds":usage.ru_utime+usage.ru_stime-children.ru_utime-children.ru_stime,
        "deployment":"none","quality_conclusion":("GPT view program ties canonical byte edits; semantic sign error is a negative control"
            if all(row["gpt_ties_canonical_bytes"] for row in candidate_rows) else "GPT view program differs from canonical; report all endpoints without revision"),
        "retention_gate_pass":all(all(row["exact_parent_outputs"].values()) for row in retention)}
    save(out/"RESULT.json",result)
    print(json.dumps({k:v for k,v in result.items() if k not in ("records","retention","candidates")}))


if __name__ == "__main__":
    main()
