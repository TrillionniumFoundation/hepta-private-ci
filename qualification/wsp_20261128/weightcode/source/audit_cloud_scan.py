"""Read-only audit of completed public SCAN cloud artifacts; no model forwards.

Uses cached predictions and exact checkpoint tensors. No fitting, candidate
selection or additional benchmark inference is performed.
"""
from __future__ import annotations
import os
for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[name] = "2"
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import resource
import sys
import time

HERE = Path(__file__).resolve().parent
REPO = HERE / "WeightCode"
sys.path.insert(0, str(REPO))
import numpy as np
import torch
from weightcode.baselines.instance_io import load_instance
from weightcode.baselines.fit import scanrefs as R
from weightcode.common.identity import params_sha256, load_params, count_changed
from weightcode.data import scan as S
torch.set_num_threads(2)
torch.set_num_interop_threads(1)


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def main():
    begin, cpu = time.monotonic(), time.process_time()
    cloud = HERE / "cloud_scan"
    roots = [cloud / name / "unpacked" / "weightcode_rule_to_data" for name in ("chunk01", "chunk02")]
    expected_archives = ["e9d859e79669c88a6d183acfd2b7b626be7e36cf2b3266d1f443838b2d098707",
                         "eb70989a3acd8360b0f29e1ea9cea06ab7210c4e64729257ecf5bd88d9c5ea0e"]
    manifests = []
    for name, expected in zip(("chunk01", "chunk02"), expected_archives):
        p = cloud / name
        m = read(p / "artifact_manifest.json")
        assert m["archive_sha256"] == sha(p / "evidence.tar.gz") == expected
        assert m["archive_bytes"] == (p / "evidence.tar.gz").stat().st_size
        assert m["result_sha256"] == sha(p / "result.json")
        manifests.append(m)
    original, final = roots
    outer = read(cloud / "chunk02" / "result.json")
    summary = read(final / "summary.json")
    assert outer["status"] == "complete" and outer["summary"] == summary
    assert summary["source_commit"] == "297c24db4b63c09a78d3552ac5f90865eaf95c9a"
    protocol = read(HERE / "scan_rule_to_data_protocol.json")
    assert summary["protocol"] == protocol == read(final / "protocol.json")
    assert summary["amendment"] == read(HERE / "colab_rule_to_data_amendment.json") == read(final / "execution_amendment.json")
    assert sha(HERE / "colab_scan_rule_to_data_job.py") == "af167a45ca24cad9cf6a0f1f4e1271f1015a0b918f9f9268eea1a5104f463533"
    download = REPO / "reproduction_scan" / "downloads"
    inst = load_instance(download / "hf" / "weights" / "instances" / protocol["instance"])
    assert params_sha256(inst.params) == protocol["base_sha256"]
    # Read saved experience arrays directly. load_scan_evidence would execute
    # 65 parent forwards, so this auditor deliberately does not call it.
    evidence_x = np.concatenate([inst.evidence["x_prim"], inst.evidence["x_old"]])
    evidence_y = np.concatenate([inst.evidence["y_prim"], inst.evidence["y_old"]])
    generated = R.rulegen_fit_set("addprim_jump", "mixed")
    assert generated["record"]["commands_sha256"] == protocol["data"]["grammar_fit_commands_sha256"]
    xfit = np.concatenate([generated["x"], evidence_x])
    yfit = np.concatenate([generated["y"], evidence_y])
    audit = read(final / "data_audit.json")
    assert params_sha256({"x": xfit, "y": yfit}) == audit["fit_sha256"]
    assert len(xfit) == 4065 and int((yfit != S.IGNORE).sum()) == 195120
    built = S.build_condition_splits(download / "scan", "addprim_jump")
    assert params_sha256(built.sealed) == protocol["data"]["final_sha256"]
    parts = {"check_new": built.private["V_check"], "check_old": built.private["old_check"],
             "final_new": {k: v[built.sealed["part"] == S.PART_NEW] for k, v in built.sealed.items()},
             "final_old": {k: v[built.sealed["part"] == S.PART_OLD] for k, v in built.sealed.items()}}
    program = download / "hf" / "records" / "sessions" / "s9be29c2c302e4daa" / "final" / "centroid_meanrow_floor.py"
    assert sha(program) == "b003c6b9e7a03a3d367633b600cb2ca8cac11cde428ea12b55bdc60362fc5320"
    sp = importlib.util.spec_from_file_location("scan_program_commands_only", program)
    module = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(module)
    commands = module._commands()
    jump = [c for c in commands if "jump" in c.split() and c != "jump"][::8]
    old = [c for c in commands if "jump" not in c.split()]
    reference = []
    for c in jump:
        words = c.split()
        replacement = next(v for v in ("walk", "look", "run") if v not in words)
        reference.append(" ".join(replacement if w == "jump" else w for w in words))
    wsp_probed = set(jump+old+reference+S.decode(evidence_x[1:]))
    fit_commands = set(S.decode(xfit))
    common = np.array([c not in wsp_probed and c not in fit_commands for c in S.decode(parts["final_new"]["x"])])
    assert int(common.sum()) == audit["final_new_neither_fitted_nor_wsp_probed"] == 1658
    assert hashlib.sha256(common.tobytes()).hexdigest() == audit["common_mask_sha256"]
    counts, exact_rows, checkpoint_records = {}, {}, []
    base = inst.params
    readout_sources = {"base": protocol["base_sha256"], "published_wsp": summary["wsp_sha256"]}
    for record in summary["results"]:
        arm = record["arm"]
        d = final / arm["name"]
        child = load_params(d / "fixed_candidate.npz")
        child_hash = params_sha256(child)
        assert child_hash == record["params_sha256"]
        assert count_changed(base, child) == record["n_changed"]
        seal = read(d / "candidate_sealed_before_readouts.json")
        assert seal["params_sha256"] == child_hash and seal["readouts_used_for_selection"] is False
        receipt = read(d / "checkpoint_receipt.json")
        assert sha(d / "optimizer_checkpoint.pt") == receipt["sha256"] == record["checkpoint_sha256"]
        state = torch.load(d / "optimizer_checkpoint.pt", weights_only=True, map_location="cpu")
        assert state["step"] == arm["steps"] == receipt["completed_steps"]
        assert state["base_sha256"] == protocol["base_sha256"]
        actual_model = {k: v.detach().numpy() for k, v in state["model"].items()}
        assert params_sha256(actual_model) == child_hash
        assert all(np.isfinite(v).all() for v in child.values())
        mask_info = None
        if arm["method"] == "sparse19_sal":
            mask = {k: v.numpy().astype(bool) for k, v in state["mask"].items()}
            mask_record = read(d / "mask.json")
            assert params_sha256(mask) == mask_record["mask_sha256"]
            assert sum(int(v.sum()) for v in mask.values()) == mask_record["n_entries"] == 152718
            for k, v in mask.items():
                assert np.array_equal(child[k][~v], base[k][~v])
            mask_info = {"entries": 152718, "unchanged_outside_mask_bit_exact": True,
                         "mask_sha256": mask_record["mask_sha256"]}
        checkpoint_records.append({"name": arm["name"], "params_sha256": child_hash,
                                   "optimizer_checkpoint_sha256": receipt["sha256"],
                                   "completed_steps": state["step"], "changed_scalars": record["n_changed"],
                                   "saved_model_matches_final_candidate": True, "mask": mask_info,
                                   "curve_steps": [x["step"] for x in state["curve"]],
                                   "every_intermediate_optimizer_file_retained": False,
                                   "reference_child_hash_equality": record["exact_published_reference_hash"]})
        readout_sources[arm["name"]] = child_hash
    for name, param_hash in readout_sources.items():
        counts[name], exact_rows[name] = {}, {}
        for split in ("check_new", "check_old", "final_new", "final_old"):
            path = final / (param_hash+"_"+split+".npz")
            if not path.exists():
                assert name == "published_wsp" and split.startswith("check_")
                continue
            with np.load(path, allow_pickle=False) as p:
                pred = p["pred"]
            y = parts[split]["y"]
            assert pred.shape == y.shape
            good = np.all((pred == y) | (y == S.IGNORE), axis=1)
            exact_rows[name][split] = good
            masks = {"all": np.ones(len(y), dtype=bool),
                     "not_in_generated_fit": np.array([c not in fit_commands for c in S.decode(parts[split]["x"])])}
            if split == "final_new":
                masks["neither_fitted_nor_wsp_probed"] = common
            counts[name][split] = {label: {"rows": int(mask.sum()), "correct": int(good[mask].sum()),
                                                "exact_match": float(good[mask].mean())} for label, mask in masks.items()}
            if name != "base":
                original_readout = summary["wsp_same_subsets"][split] if name == "published_wsp" else next(r for r in summary["results"] if r["arm"]["name"] == name)["readout"][split]
                for label, value in counts[name][split].items():
                    reference_record = original_readout if label == "all" else original_readout[label]
                    assert value["rows"] == reference_record["n"]
                    assert abs(value["exact_match"]-reference_record["em_child"]) < 1e-14
    paired = []
    for name in (r["arm"]["name"] for r in summary["results"]):
        for split, mask in [("final_new", np.ones(2568, dtype=bool)), ("final_new", common),
                            ("final_old", np.ones(1000, dtype=bool))]:
            wsp, bp = exact_rows["published_wsp"][split][mask], exact_rows[name][split][mask]
            paired.append({"comparison": "published_wsp_vs_"+name, "split": split,
                           "subset": "neither_fitted_nor_wsp_probed" if int(mask.sum()) == 1658 else "all",
                           "rows": len(wsp), "wsp_only_correct": int((wsp & ~bp).sum()),
                           "bp_only_correct": int((~wsp & bp).sum()), "both_wrong": int((~wsp & ~bp).sum()),
                           "mean_em_difference": float(wsp.mean()-bp.mean()),
                           "independent_random_test_draw": False})
    jobs = read(final / "job_records.json")
    assert len(jobs) == 2 and sum(j["counts"]["optimizer_steps"] for j in jobs) == 400
    member_map = []
    for path in sorted(original.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(original)
        new = final / rel
        member_map.append({"path": str(rel), "sha256": sha(path), "bytes": path.stat().st_size,
                           "source": "chunk02" if new.is_file() and sha(new) == sha(path) else "chunk01_override"})
    assert len(member_map) == 20
    assert [m["path"] for m in member_map if m["source"] == "chunk01_override"] == ["job_records.json"]
    result = {"schema": "hepta.wsp.public-cloud-independent-artifact-audit.v1",
              "created_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "source_sha256": sha(__file__), "archive_manifests": manifests,
              "fixed_configuration_completed": True, "candidate_selection_from_final": False,
              "checkpoint_verification": checkpoint_records, "cached_predictions_recomputed": counts,
              "paired_cached_predictions": paired, "chunk01_member_reconstruction": member_map,
              "data_identity": {"final_sha256": params_sha256(built.sealed), "fit_sha256": params_sha256({"x": xfit, "y": yfit}),
                                "common_subset_mask_sha256": audit["common_mask_sha256"], "fit_rows": len(xfit)},
              "worker_costs": {"total_wall_seconds": sum(j["wall_seconds"] for j in jobs),
                               "reported_process_cpu_seconds_by_job": [j["cpu_seconds"] for j in jobs],
                               "cpu_counter_caveat": "Worker stores process_time() at completion, not a subtracted interval. Do not treat these as pure fit CPU time or infer cross-job process identity.",
                               "counts": {k: sum(j["counts"][k] for j in jobs) for k in jobs[0]["counts"]},
                               "backward_calls_including_one_dense_parity_call": sum(j["counts"]["gradient_microbatches"] for j in jobs)+1,
                               "peak_host_rss_kib": max(j["max_rss_kib"] for j in jobs),
                               "LLM_discovery_and_original_base_training_included": False,
                               "paid_cost_measured": False},
              "preflight": read(final / "parity_before_fit.json"),
              "preflight_limit": "CUDA preflight uses the 65 already-solved original rows; the independent nonzero-loss CPU gradient audit was conducted after job submission. Neither establishes bit-identical reproduction of the authors' GPU trajectory.",
              "hardware_by_job": [read(final / f"hardware_job{i}.json") for i in range(2)],
              "privacy": {"pocket4_or_private_hepta_model_data_read": False, "public_provenance": ["https://github.com/Gen-Verse/WeightCode", "https://huggingface.co/datasets/Boom5426/WeightCode"]},
              "audit_cost": {"new_network_forwards": 0, "backward_calls": 0, "optimizer_steps": 0,
                             "cached_predictions_only": True, "wall_seconds": time.monotonic()-begin,
                             "cpu_seconds": time.process_time()-cpu, "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss},
              "scope": "Public published-data rerun. Neither the original final commands nor the 1658-command overlap-excluded subset are a newly collected independent holdout. One base checkpoint and one author-fixed seed/configuration per method."}
    result["audit_digest"] = digest(result)
    with (cloud / "INDEPENDENT_AUDIT.json").open("x") as f:
        f.write(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(json.dumps({"audit_digest": result["audit_digest"], "counts": counts,
                      "paired": paired, "worker_costs": result["worker_costs"], "audit_cost": result["audit_cost"]}), flush=True)


if __name__ == "__main__":
    main()
