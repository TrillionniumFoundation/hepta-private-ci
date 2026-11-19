"""Independent immutable-input decoding, exact RNE assembly and capsule reader."""

import ast
import base64
from fractions import Fraction as F
import hashlib
import io
import json
import math
from pathlib import Path
import struct
import zipfile

from interval import exact_from_bits, require, rn, rounded_fraction


BUNDLE = "17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95"
EXPORT = "qualification/hcsn_n256_new_export/evidence/attempt001/"
DENSE = "qualification/hcsn_currentstate_n256_firststep_dense_oracle_hosted/evidence/attempt001-20261119/originals/N256_WARM1.bin"
SPARSE_ZIP = "qualification/hcsn_currentstate_n256_warm1_sparse/evidence/attempt001-20261119/artifact-14501927547.zip"


def fraction_hex(value):
    number = float.fromhex(value)
    require(math.isfinite(number) and number.hex() == value, "canonical finite FP64 hex")
    return exact_from_bits(struct.unpack("<Q", struct.pack("<d", number))[0])


def float_fraction(value):
    require(type(value) is float and math.isfinite(value), "finite metadata FP64")
    return exact_from_bits(struct.unpack("<Q", struct.pack("<d", value))[0])


def fp_bytes(values):
    return b"".join(struct.pack("<Q", rounded_fraction(x)) for x in values)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def source_id(kind, start, end, target, origin, parents=()):
    return hashlib.sha256(canonical({"bundle": BUNDLE, "kind": kind,
        "start": [start.numerator, start.denominator], "end": [end.numerator, end.denominator],
        "target": target, "origin": origin, "parents": sorted(parents)})).hexdigest()


def load_inputs(repo):
    directory = repo/EXPORT
    state = json.loads((directory/"N256_STATE.json").read_text())
    phase = json.loads((directory/"N256_PHASE.json").read_text())
    metadata = json.loads((directory/"METADATA.json").read_text())
    require(state["active_shape"] == state["nodes_shape"] == [257]
            and state["content_shape"] == [257, 4] and state["dtype"] == "<f8", "input shapes")
    nodes = list(map(fraction_hex, state["nodes_fp64_hex"]))
    probability = list(map(fraction_hex, state["active_probability_fp64_hex"]))
    flat = list(map(fraction_hex, state["signed_content_fp64_hex_row_major"]))
    channels = [probability]+[[flat[4*i+c] for i in range(257)] for c in range(4)]
    require(len(nodes) == 257 and all(len(v) == 257 for v in channels)
            and all(a < b for a, b in zip(nodes, nodes[1:])), "strict original nodes")
    # Check independently decoded JSON values against the actual NPZ payload.
    payload = base64.b64decode((directory/"N256_STATE.npz.b64").read_bytes())
    require(hashlib.sha256(payload).hexdigest() == metadata["npz"]["sha256"], "NPZ identity")
    expected = {"nodes.npy": ([257], fp_bytes(nodes)), "active.npy": ([257], fp_bytes(probability)),
                "content.npy": ([257, 4], fp_bytes(flat))}
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        require(set(archive.namelist()) == set(expected), "NPZ field set")
        for name, (shape, wanted) in expected.items():
            data = archive.read(name)
            require(data[:8] == b"\x93NUMPY\x01\x00", "NPY v1")
            length = struct.unpack("<H", data[8:10])[0]
            header = ast.literal_eval(data[10:10+length].decode())
            require(header == {"descr": "<f8", "fortran_order": False, "shape": tuple(shape)}, "NPY layout")
            require(data[10+length:] == wanted, "JSON/NPZ exact input bits")
    require(phase["packet_count"] == len(phase["packets"]) == 8, "eight initial packets")
    packets = []
    for p in phase["packets"]:
        start, end = F(p["start"]), F(p["end"])
        require(start < end and len(p["signed_content"]) == 4, "initial packet law")
        rates = [rn(F(v)/(end-start)) for v in [p["mass"], *p["signed_content"]]]
        packets.append({"kind": p["identity"], "start": start, "end": end, "rates": rates,
                        "identity": source_id(p["identity"], start, end, 1, 0)})
    return {"nodes": nodes, "channels": channels, "packets": packets,
            "mu": float_fraction(metadata["physics"]["mu"]), "sigma": float_fraction(metadata["physics"]["sigma"]),
            "rho": float_fraction(metadata["physics"]["discount"]), "reset": float_fraction(metadata["reset_distance"]),
            "duration": fraction_hex(float(F(1, 1000)).hex())}


def assemble(inputs):
    """Replicate the declared scalar FP64 operation order using exact RNE.

No candidate/oracle output is consulted. All subsequent matrix entries are
exact binary64 rationals, including diagonal shifting and time scaling.
"""
    nodes, mu, sigma = inputs["nodes"], inputs["mu"], inputs["sigma"]
    gaps = [rn(b-a) for a, b in zip(nodes, nodes[1:])]
    square = rn(sigma*sigma)
    down, up = [], []
    for left, right in zip(gaps, gaps[1:]):
        down.append(rn(rn(square-rn(mu*right))/rn(left*rn(left+right))))
        up.append(rn(rn(square+rn(mu*left))/rn(right*rn(left+right))))
    require(min(down+up) >= 0, "nonnegative spatial rates")
    reset = inputs["reset"]
    j = next(i for i, value in enumerate(nodes) if value > reset)
    require(2 <= j <= 255, "interior reset support")
    theta = rn(rn(reset-nodes[j-1])/rn(nodes[j]-nodes[j-1]))
    weights = [F(0)]*255
    weights[j-2], weights[j-1] = rn(1-theta), theta
    core = [{j+1: v for j, v in enumerate(weights) if v}]+[{} for _ in range(255)]
    for i in range(255):
        row = core[i+1]
        row[i+1] = -rn(down[i]+up[i])
        if i:
            row[i] = down[i]
        if i < 254:
            row[i+2] = up[i]
    output = [F(0), down[0]]+[F(0)]*254
    extended = [dict(row) for row in core]+[{}]
    extended[255][256] = up[-1]
    parent = [p for p in inputs["packets"] if p["start"] == 0 and p["end"] >= F(1, 1000)]
    require(len(parent) == 1, "one releasing parent")
    alpha = [[parent[0]["rates"][c], *inputs["channels"][c][1:-1]] for c in range(5)]
    operators = []
    for discount, count in ((F(0), 1), (inputs["rho"], 2)):
        rows = [dict(row) for row in extended]+[{} for _ in range(count)]
        for i in range(257):
            rows[i][i] = rn(rows[i].get(i, F(0))-discount)
            if i == 1:
                rows[i][257] = down[0]
            if count == 2 and i:
                rows[i][258] = F(1)
        rows = [{j: v for j, v in row.items() if v} for row in rows]
        scaled = [{j: rn(v*inputs["duration"]) for j, v in row.items() if v} for row in rows]
        seed = [v+[F(0)]*(1+count) for v in alpha]
        operators.append({"unscaled": rows, "scaled": scaled, "initial": seed})
    return {"core": core, "output": output, "alpha": alpha, "reset_weights": weights,
            "parent": parent[0], "operators": operators}


def decode_capsule(payload):
    """Independent bounded parser of the frozen HCSNFSP2 wire layout."""
    require(len(payload) <= 8*1024**2 and payload[:8] == b"HCSNFSP2", "capsule format/size")
    body, trailer = payload[:-32], payload[-32:]
    require(hashlib.sha256(body).digest() == trailer, "capsule checksum")
    cursor = 8

    def take(n):
        nonlocal cursor
        require(0 <= n <= len(body)-cursor, "capsule bounds")
        data = body[cursor:cursor+n]
        cursor += n
        return data

    def integer(size):
        return int.from_bytes(take(size), "big")

    def record():
        raw = take(integer(4))
        value = json.loads(raw)
        require(canonical(value) == raw, "canonical metadata")
        return value

    def tensor():
        dimensions = integer(4)
        require(1 <= dimensions <= 3, "tensor dimensions")
        shape = tuple(integer(8) for _ in range(dimensions))
        size = integer(8)
        require(size == 8*math.prod(shape) and 0 < size <= 8*1024**2, "tensor payload size")
        raw = take(size)
        values = [exact_from_bits(v[0]) for v in struct.iter_unpack("<Q", raw)]
        return {"shape": shape, "values": values, "raw": raw}

    metadata = record()
    require(metadata["schema"] == "hcsn-fullstate-packet-v2", "wire schema")
    blocks = {}
    count = integer(4)
    require(count == 5, "five state blocks")
    for _ in range(count):
        name = take(integer(4)).decode("ascii")
        require(name not in blocks, "unique block")
        blocks[name] = tensor()
    require(list(blocks) == sorted(blocks), "canonical block order")
    packets = []
    count = integer(4)
    require(count == 9, "nine packets")
    for _ in range(count):
        packet = {"metadata": record()}
        for name in ("alpha", "generator", "output"):
            packet[name] = tensor()
        packets.append(packet)
    require(cursor == len(body), "no trailing bytes")
    require([p["metadata"]["identity"] for p in packets] == sorted({p["metadata"]["identity"] for p in packets}), "packet order")
    return {"metadata": metadata, "blocks": blocks, "packets": packets}


def archived_outputs(repo):
    dense = (repo/DENSE).read_bytes()
    require(hashlib.sha256(dense).hexdigest() == "b2a6e204e613fead7c0735b12a335a88d2394c8f4da99cab798133443c55dc18", "dense archive")
    raw = (repo/SPARSE_ZIP).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == "8f6a75afafeedaa5cfe6ad2b8b80af6b7d2b54f102f75d406ac1d92eb4b36629", "sparse archive")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = [name for name in archive.namelist() if name.endswith("N256_WARM1_SPARSE.bin")]
        require(len(names) == 1, "single sparse capsule")
        sparse = archive.read(names[0])
    require(hashlib.sha256(sparse).hexdigest() == "248cfc56d575b15d4a8340267e8b668fd0b6dc94be71b61e2b0cec8b913981b1", "sparse capsule")
    return {"dense": decode_capsule(dense), "sparse": decode_capsule(sparse)}


def source_geometry_check(assembly, outputs):
    """Check independently assembled static fields only after assembly."""
    core = [row.get(j, F(0)) for row in assembly["core"] for j in range(256)]
    alpha = [v for row in assembly["alpha"] for v in row]
    for name, capsule in outputs.items():
        emitted = [p for p in capsule["packets"] if p["metadata"]["origin"] == 1]
        require(len(emitted) == 1, "one emitted lower-flux packet")
        packet = emitted[0]
        for field, expected, shape in (("generator", core, (256, 256)), ("alpha", alpha, (5, 256)),
                                       ("output", assembly["output"], (256,))):
            require(packet[field]["shape"] == shape and packet[field]["raw"] == fp_bytes(expected),
                    "independent assembly differs from archived "+name+" "+field)
    return {"generator_coordinates": 65536, "initial_emitted_alpha_coordinates": 1280,
            "output_coordinates": 256, "both_archives_match_independent_assembly_bits": True,
            "candidate_or_dense_values_used_for_assembly": False}
