"""Independent stdlib-only byte/NPY/VJP readback; never imports candidate, NumPy or Torch."""
import argparse
import ast
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import stat
import struct
import tarfile
import zipfile

SOURCE = "4962e28c1ffa073e5e994194f3b5785659af236c"
ZIP_SHA = "1dd17c8ac54cab00242af1d7ce88a1cefcde24c7ecaf3ba8634fd1bdcf978e7c"
DEV_SHA = "85e543dc770257e5470af867415d6d1f55e859fac116f37204fc0e5a6bb2348e"
EXPECTED_SHA = "2dcfe03f2911cb0b6c55b2c24f095d7688d150eb84177d1bb7e4970daa8fa305"
ARRAY_SHA = "fd28bcc2244c648ffc9fff10c0fee40cec8b8edbc4158d3ee480a3af53bf1115"
MEMBERS = {
    "initial-amplitudes/ARRAYS.npz": 7682,
    "initial-amplitudes/CALLS.json": 25166,
    "initial-amplitudes/RESULT.json": 31909,
    "initial-source.json": 1945,
}


def need(value, reason):
    if not value:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def object_pairs(pairs):
    value = {}
    for key, item in pairs:
        need(key not in value, "duplicate JSON key")
        value[key] = item
    return value


def json_read(raw):
    def invalid(value):
        raise ValueError("nonfinite JSON constant: " + value)
    return json.loads(raw, object_pairs_hook=object_pairs, parse_constant=invalid)


def zip_bytes(raw):
    rows = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for entry in archive.infolist():
            path = PurePosixPath(entry.filename)
            need(not path.is_absolute() and ".." not in path.parts
                 and str(path) == entry.filename and "\\" not in entry.filename
                 and entry.filename not in rows, "unsafe/duplicate ZIP member")
            mode = stat.S_IFMT(entry.external_attr >> 16)
            need(not entry.is_dir() and mode in (0, stat.S_IFREG), "nonregular ZIP member")
            need(entry.file_size <= 16777216, "member budget")
            rows[entry.filename] = archive.read(entry)
    return rows


def npy(raw):
    need(raw[:6] == b"\x93NUMPY" and len(raw) >= 10, "NPY signature")
    version = tuple(raw[6:8])
    need(version in ((1, 0), (2, 0), (3, 0)), "NPY version")
    offset = 10 if version == (1, 0) else 12
    size = struct.unpack("<H" if offset == 10 else "<I", raw[8:offset])[0]
    need(size <= 65536 and offset + size <= len(raw), "NPY header bounds")
    header = ast.literal_eval(raw[offset:offset + size].decode(
        "utf-8" if version == (3, 0) else "latin1"))
    need(set(header) == {"descr", "fortran_order", "shape"}
         and header["descr"] == "<f8" and header["fortran_order"] is False,
         "only finite C-order little-endian float64 arrays admitted")
    shape = header["shape"]
    need(isinstance(shape, tuple) and 1 <= len(shape) <= 4
         and all(type(n) is int and n > 0 for n in shape), "NPY shape")
    count = math.prod(shape)
    need(count <= 1000000 and len(raw) == offset + size + count * 8, "NPY payload size")
    values = struct.unpack("<" + str(count) + "d", raw[offset + size:])
    need(all(math.isfinite(x) for x in values), "nonfinite NPY payload")
    return {"shape": shape, "values": values, "sha256": sha(raw), "bytes": len(raw)}


def npz(raw):
    return {name[:-4]: npy(value) for name, value in zip_bytes(raw).items()
            if name.endswith(".npy")}


def same_scalar(actual, reported, label):
    need(type(reported) in (int, float) and math.isfinite(reported)
         and math.isclose(actual, reported, rel_tol=1e-10, abs_tol=1e-18), label)


def close_rows(actual, expected, absolute, relative, label):
    need(len(actual) == len(expected), label + " length")
    failures = sum(abs(a - b) > absolute + relative * abs(b)
                   for a, b in zip(actual, expected))
    need(failures == 0, label + " tolerance")
    return max(abs(a - b) for a, b in zip(actual, expected))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", required=True)
    parser.add_argument("--development-tar", required=True)
    parser.add_argument("--source-bundle")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    raw = Path(args.zip).read_bytes()
    need(len(raw) == 11597 and sha(raw) == ZIP_SHA, "frozen original ZIP")
    originals = zip_bytes(raw)
    need(set(originals) == set(MEMBERS)
         and all(len(originals[name]) == size for name, size in MEMBERS.items()),
         "exact four original members")
    result = json_read(originals["initial-amplitudes/RESULT.json"])
    calls = json_read(originals["initial-amplitudes/CALLS.json"])
    manifest = json_read(originals["initial-source.json"])
    need(result["status"] == "PASS" and result["source_commit"] == manifest["source_commit"] == SOURCE,
         "source/result identity")
    need(calls == result["calls"] and len(calls) == 39, "complete CALLS equality")
    for key, expected in (("api_forward_calls", 39), ("basis_ode_forward_calls", 39),
                          ("native_uniform_oracle_forward_calls", 2), ("optimizer_updates", 0)):
        need(type(result[key]) is int and result[key] == expected, "exact counter " + key)
    need(all(type(c["basis_forward_calls"]) is int and type(c["optimizer_updates"]) is int
             and c["optimizer_updates"] == 0 and c["basis_forward_calls"] == len(c["basis_costs"])
             for c in calls), "per-call counters")
    need(sum(c["basis_forward_calls"] for c in calls) == 39, "basis sum")
    sources = manifest["source_sha256"]
    need(len(sources) == 13 and sources == result["source_sha256_before"]
         == result["source_sha256_after"], "thirteen source maps")
    bytes_rehashed = False
    if args.source_bundle:
        bundle = json_read(Path(args.source_bundle).read_bytes())
        need(set(bundle) == set(sources), "source byte-bundle roster")
        need(all(isinstance(bundle[name], str)
                 and sha(bundle[name].encode("utf-8")) == expected
                 for name, expected in sources.items()), "source byte SHA256")
        bytes_rehashed = True
    need(result["fixed_physics_support_only"] is True and result["full_network_ad"] is False,
         "scope")
    array_raw = originals["initial-amplitudes/ARRAYS.npz"]
    need(sha(array_raw) == ARRAY_SHA == result["arrays_sha256"], "original NPZ SHA256")
    actual = npz(array_raw)
    wanted = {"uniform_output", "uniform_oracle_output", "graded_output"}
    wanted |= {prefix + str(i) for prefix in (
        "uniform_gradient", "uniform_oracle_gradient", "graded_gradient") for i in range(4)}
    need(set(actual) == wanted and len(actual) == 15, "exact numeric arrays; no normalized raw vectors")
    development = Path(args.development_tar).read_bytes()
    need(sha(development) == DEV_SHA, "frozen retained development archive")
    prefix = "qualification/hcsn_initial_vjp/evidence/numpy001/"
    with tarfile.open(fileobj=io.BytesIO(development), mode="r:gz") as archive:
        selected = [x for x in archive if x.name in (prefix + "ARRAYS.npz", prefix + "RESULT.json")]
        need(len(selected) == 2 and len({x.name for x in selected}) == 2
             and all(x.isfile() and x.size <= 16777216 for x in selected), "retained data members")
        expected_raw = archive.extractfile(prefix + "ARRAYS.npz").read()
        development_result = json_read(archive.extractfile(prefix + "RESULT.json").read())
    need(sha(expected_raw) == EXPECTED_SHA == development_result["arrays_sha256"]
         == result["expected_arrays_sha256"] == manifest["expected_arrays_sha256"],
         "retained expected-array binding")
    expected = npz(expected_raw)
    fixtures = {row["geometry"]: row for row in result["results"]}
    need(set(fixtures) == {"uniform", "graded"} and all(
        row["raw_gradcheck"] is True for row in fixtures.values()), "retained raw gradcheck flags")
    comparisons, coordinates = [], 0
    for geometry, active_count in (("uniform", 7), ("graded", 12)):
        operator = expected[geometry + "_operator"]
        cotangent = expected[geometry + "_cotangent"]
        stored = expected[geometry + "_vjp"]
        times, states, directions = operator["shape"]
        need(cotangent["shape"][:2] == (times, states), "cotangent dimensions")
        channels = cotangent["shape"][2]
        need(channels == 3 and directions == active_count + 2
             and stored["shape"] == (directions, channels), "fixed fixture dimensions")
        reconstructed = tuple(math.fsum(
            operator["values"][(t * states + state) * directions + d]
            * cotangent["values"][(t * states + state) * channels + channel]
            for t in range(times) for state in range(states))
            for d in range(directions) for channel in range(channels))
        contraction_error = close_rows(reconstructed, stored["values"], 2e-12, 2e-12,
                                       geometry + " retained contraction")
        desired_shapes = ((active_count,), (active_count, 2), (2,), (2, 2))
        block_expected = (
            tuple(stored["values"][d * channels] for d in range(active_count)),
            tuple(stored["values"][d * channels + channel]
                  for d in range(active_count) for channel in (1, 2)),
            tuple(stored["values"][d * channels] for d in range(active_count, directions)),
            tuple(stored["values"][d * channels + channel]
                  for d in range(active_count, directions) for channel in (1, 2)),
        )
        errors = []
        for i in range(4):
            value = actual[geometry + "_gradient" + str(i)]
            need(value["shape"] == desired_shapes[i], "raw VJP block shape")
            errors.append(close_rows(value["values"], block_expected[i], 2e-7, 2e-5,
                                     geometry + " raw gradient" + str(i)))
            coordinates += len(value["values"])
        need(actual[geometry + "_output"]["shape"] == expected[geometry + "_primal_direct"]["shape"],
             "primal shape")
        primal = close_rows(actual[geometry + "_output"]["values"],
                            expected[geometry + "_primal_direct"]["values"], 3e-9, 3e-8,
                            geometry + " primal")
        same_scalar(max(errors), fixtures[geometry]["full_vjp_maximum_error"],
                    geometry + " reported VJP error")
        same_scalar(primal, fixtures[geometry]["primal_maximum_error"],
                    geometry + " reported primal error")
        comparisons.append({"geometry": geometry, "raw_gradient_coordinates": sum(
            len(x) for x in block_expected), "maximum_vjp_error": max(errors),
            "maximum_primal_error": primal, "retained_contraction_error": contraction_error})
    need(coordinates == 69, "all sixty-nine raw gradient coordinates")
    oracle_errors = []
    for i in range(4):
        value, oracle = actual["uniform_gradient" + str(i)], actual["uniform_oracle_gradient" + str(i)]
        need(value["shape"] == oracle["shape"], "oracle block shape")
        oracle_errors.append(close_rows(value["values"], oracle["values"], 2e-7, 2e-5,
                                       "uniform native oracle gradient"))
    need(sum(len(actual["uniform_gradient" + str(i)]["values"]) for i in range(4)) == 27,
         "all twenty-seven oracle gradient coordinates")
    same_scalar(max(oracle_errors), fixtures["uniform"]["uniform_native_graph_vjp_maximum_error"],
                "reported uniform oracle VJP error")
    close_rows(actual["uniform_output"]["values"], actual["uniform_oracle_output"]["values"],
               3e-9, 3e-8, "uniform oracle output")
    need(all(fixtures["uniform"][key] is True for key in (
        "normal_and_unsafe_guards_all_four_inputs", "normalized_client_graph_gradcheck",
        "old_physical_only_rejects_trainable_prior")), "retained uniform guard/client flags")
    receipt = {
        "schema": "hcsn-initial-amplitude-stdlib-readback-v1", "source_commit": SOURCE,
        "passed": True, "zip_bytes": len(raw), "zip_sha256": sha(raw),
        "member_hashes": {name: {"bytes": len(value), "sha256": sha(value)}
                          for name, value in originals.items()},
        "array_members": {name: {k: v for k, v in value.items() if k != "values"}
                          for name, value in actual.items()},
        "source_maps_equal": 13, "source_bytes_rehashed": bytes_rehashed,
        "journal_records": 39, "basis_forwards_recounted": 39,
        "uniform_oracle_forwards_reported": 2, "optimizer_updates": 0,
        "raw_vjp_coordinates_checked": 69, "uniform_oracle_coordinates_checked": 27,
        "retained_operator_contractions_checked": 69, "comparisons": comparisons,
        "uniform_oracle_maximum_error": max(oracle_errors),
        "normalized_raw_vectors_retained": False,
        "probe_wall_seconds": result["wall_seconds"], "probe_cpu_seconds": result["cpu_seconds"],
        "probe_maximum_rss_kib": result["maximum_rss_kib"], "runtime": result["runtime"],
        "new_candidate_calls": 0, "new_dde_calls": 0, "new_torch_calls": 0,
        "new_optimizer_calls": 0, "scientific_admission": "HOLD_NO_GO",
        "inspector_source_sha256": sha(Path(__file__).read_bytes()),
    }
    with Path(args.output).open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(receipt, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
