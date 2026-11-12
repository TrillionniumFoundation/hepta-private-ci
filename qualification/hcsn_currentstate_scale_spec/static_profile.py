"""Integer/header-only scale intent audit; never imports numerical source."""
import ast
import hashlib
import json
from pathlib import Path
import struct
import zipfile


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def npy_header(raw):
    if raw[:6] != b"\x93NUMPY":
        raise ValueError("NPY magic")
    major = raw[6]
    if major == 1:
        length = struct.unpack("<H", raw[8:10])[0]; offset = 10
    elif major in (2, 3):
        length = struct.unpack("<I", raw[8:12])[0]; offset = 12
    else:
        raise ValueError("NPY version")
    header = ast.literal_eval(raw[offset:offset+length].decode("latin1"))
    if header["descr"] != "<f8" or header["fortran_order"] is not False:
        raise ValueError("unexpected binary64 layout")
    count = 1
    for x in header["shape"]:
        count *= x
    if len(raw)-offset-length != 8*count:
        raise ValueError("NPY payload shape")
    return {"shape": list(header["shape"]), "dtype": header["descr"], "array_scalars": count,
            "array_bytes": 8*count, "npy_sha256": hashlib.sha256(raw).hexdigest()}


def table(N):
    n = N-1
    minimum_float_count = 37*n*n+180*n+113
    warm_float_count = 52*n*n+246*n+134
    return {"intervals": N, "interior_nodes": n, "channels": 5,
            "current_authoritative_floats": 10*n+50, "readout_scalars_each": 10*n+80,
            "readouts": 14, "comparison_scalar_denominator": 14*(10*n+80),
            "unique_reference_times": 8, "reference_scalar_denominator": 8*(10*n+80),
            "capsules": 14, "cold_direct_raw_pairs": 3, "planned_reject_controls": 13,
            "main_augmented_dimension_before_feedback": 2*n+9,
            "main_augmented_dimension_after_feedback": 3*n+9,
            "one_dense_augmented_matrix_bytes": 8*(3*n+9)**2,
            "largest_pending_generator_dimension": 2*n+1,
            "largest_pending_generator_dense_bytes": 8*(2*n+1)**2,
            "minimum_singlecall_scenario": {"segments": 15, "pending_packets": 16,
                "persistent_floats": minimum_float_count, "nonempty_hex_arrays": 53,
                "hex_array_payload_lower_bound_bytes": 11*minimum_float_count-53},
            "declared_warm_scenario": {"segments": 21, "pending_packets": 22,
                "persistent_floats": warm_float_count, "nonempty_hex_arrays": 71,
                "hex_array_payload_lower_bound_bytes": 11*warm_float_count-71,
                "static_expm_counter": 244},
            "coarse_scenario": {"segments": 15, "static_expm_counter": 94},
            "cold_scenario": {"segments": 9, "static_expm_counter": 122},
            "static_total_segments": 45, "static_total_expm_counter": 460,
            "runtime_or_peak_RSS_estimate": None,
            "dynamic_execution_admissible": False,
            "hard_blockers": ["legacy_n_only_1_or_2", "legacy_channels_only_3", "legacy_C_dim_64",
                              "legacy_augmented_dim_128", "legacy_snapshot_900000_bytes",
                              "legacy_warm_segments_20_less_than_21", "new_largegrid_core_unimplemented",
                              "independent_fullstate_reference_not_frozen"]
                              + (["n256_mapped_input_missing"] if N == 256 else [])}


def check_intent_request(request):
    """Static protocol admission only, never a large-grid numerical API."""
    N = request["N"]
    if type(N) is not int or N not in (128, 256, 512):
        raise ValueError("OUTSIDE_STAGED_INTENT")
    predecessor = {128: None, 256: 128, 512: 256}[N]
    if predecessor is not None and predecessor not in request["qualified_predecessors"]:
        raise ValueError("PREDECESSOR_NOT_QUALIFIED")
    if N not in (128, 512):
        raise ValueError("MAPPED_INPUT_MISSING")
    if request["channels"] != 5:
        raise ValueError("SIGNED_CHANNELS_MISSING")
    if request["phase_law"] != "full_release_density":
        raise ValueError("PHASE_LAW_MISSING")
    if request["reset"] != .3131468965881033:
        raise ValueError("WRONG_ACTUAL_RESET")
    if request["upper"] != "permanently_active_nonreturning":
        raise ValueError("WRONG_UPPER_SEMANTICS")
    # No large-grid executable/ref source was created in this stage. A caller
    # flag cannot turn a frozen small-mesh implementation into that source.
    raise ValueError("LARGEGRID_SOURCE_AND_REFERENCE_UNFROZEN")


def main():
    import argparse
    p = argparse.ArgumentParser(); p.add_argument("--freeze", required=True); p.add_argument("--output", required=True)
    args = p.parse_args(); root = Path(__file__).resolve().parents[2]; base = Path(__file__).resolve().parent
    f = json.loads(Path(args.freeze).read_text()); out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    def guard():
        return {k: {name: sha(root/name) for name in f[k]} for k in ("source_sha256", "input_sha256", "protocol_sha256")}
    before = guard()
    if any(before[k] != f[k] for k in before):
        raise ValueError("frozen bytes differ")
    if len(f["source_sha256"]) != 10 or len(f["input_sha256"]) != 5:
        raise ValueError("incomplete source/input roster")
    headers = {}; metadata = {}
    for N in (128, 512):
        stem = f"seed37-c0_b1-step24-pos1-n{N}"
        data = json.loads((base/"inputs"/(stem+".json")).read_text())
        if data["intervals"] != N or data["reset_distance"] != .3131468965881033 or len(data["phase"]) != 8:
            raise ValueError("wrong original law/geometry")
        z = zipfile.ZipFile(base/"inputs"/(stem+".npz"))
        if set(z.namelist()) != {"active.npy", "content.npy", "nodes.npy"}:
            raise ValueError("NPZ field set")
        headers[str(N)] = {name: npy_header(z.read(name)) for name in z.namelist()}
        assert headers[str(N)]["active.npy"]["shape"] == [N+1]
        assert headers[str(N)]["content.npy"]["shape"] == [N+1, 4]
        assert headers[str(N)]["nodes.npy"]["shape"] == [N+1]
        metadata[str(N)] = {"reset_distance": data["reset_distance"], "physics": data["physics"],
            "phase_bins": 8, "phase_supports": [[x["start"], x["end"]] for x in data["phase"]],
            "upper_escape_mass": data["migration_report"]["upper_escape_mass"],
            "lower_atom": data["migration_report"]["lower_atom"],
            "source_visit": {k: data["source_visit"][k] for k in ("index", "update_index", "position", "model_sha256")}}
    rows = [table(N) for N in (128, 256, 512)]
    valid_fields = {"N": 128, "qualified_predecessors": [], "channels": 5,
        "phase_law": "full_release_density", "reset": .3131468965881033,
        "upper": "permanently_active_nonreturning"}
    cases = [("N1024", {"N": 1024}, "OUTSIDE_STAGED_INTENT"),
        ("N512 before N128/N256", {"N": 512}, "PREDECESSOR_NOT_QUALIFIED"),
        ("N256 missing export", {"N": 256, "qualified_predecessors": [128]}, "MAPPED_INPUT_MISSING"),
        ("lost signed channels", {"channels": 3}, "SIGNED_CHANNELS_MISSING"),
        ("phase totals only", {"phase_law": "totals_only"}, "PHASE_LAW_MISSING"),
        ("reset=.32", {"reset": .32}, "WRONG_ACTUAL_RESET"),
        ("upper returns", {"upper": "returning_tail"}, "WRONG_UPPER_SEMANTICS"),
        ("raise legacy caps then run", {}, "LARGEGRID_SOURCE_AND_REFERENCE_UNFROZEN")]
    negatives = []
    for label, changes, expected in cases:
        request = dict(valid_fields, **changes)
        try:
            check_intent_request(request)
        except ValueError as error:
            if str(error) != expected:
                raise AssertionError("wrong protocol rejection") from error
            negatives.append({"request": label, "fields": request, "rejected": True, "reason": str(error)})
        else:
            raise AssertionError("static protocol admitted a dynamic request")
    after = guard()
    if before != after:
        raise ValueError("bytes changed")
    result = {"identity": f["identity"], "source_freeze_commit": f["source_commit"], "before": before, "after": after,
              "npz_headers_only": headers, "actual_metadata": metadata, "scale_table": rows,
              "static_protocol_negative_cases": negatives,
              "negative_case_scope": "Declared intent refusals, not executions of a large-grid candidate API",
              "aggregate_if_all_stages_were_later_admitted": {"readouts": 42, "capsules": 42, "cold_raw_pairs": 9,
                  "comparison_scalars": sum(r["comparison_scalar_denominator"] for r in rows),
                  "reference_scalars": sum(r["reference_scalar_denominator"] for r in rows),
                  "segments": 135, "static_expm_counter": 1380, "planned_reject_controls": 39},
              "candidate_imports": 0, "scipy_imports": 0, "numpy_imports": 0, "dynamic_runs": 0,
              "matrix_exponentials_executed": 0, "reference_evaluations": 0, "optimizer_steps": 0,
              "largegrid_qualification": False, "admission": "HOLD_INTENT_ONLY", "all_closed": False}
    encoded = (json.dumps(result, indent=2, allow_nan=False)+"\n").encode()
    if len(encoded) > 100000:
        raise ValueError("static output byte cap exceeded")
    (out/"STATIC_PROFILE.json").write_bytes(encoded)
    print(json.dumps({"identity": result["identity"], "source_files": 10, "input_files": 5,
        "profile_rows": 3, "dynamic_runs": 0, "admission": result["admission"], "all_closed": False}))


if __name__ == "__main__":
    main()
