"""Full cold state: dense wire identity, sparse restored operators, event resets."""

import gzip
import hashlib
import math
from fractions import Fraction as F
from pathlib import Path

import numpy as np
from scipy import sparse

from qualification.hcsn_currentstate_n256_engineering import candidate as primitive
from qualification.hcsn_currentstate_n256_firststep_serializer_v2 import serializer as wire
from qualification.hcsn_n256_multistep import flow


SHAPES = {"active": (5, 2, 255), "upper": (5, 3), "mass": (5, 2),
          "discounted_hit": (5, 2), "occupation": (5, 3)}
MODEL = "hcsn-n256-multistep-reset-snapshot-v1"


def tensor(array):
    array = np.asarray(array, dtype="<f8", order="C")
    if not np.isfinite(array).all():
        raise ValueError("nonfinite complete-state tensor")
    return wire.Tensor("<f8", array.shape, array.tobytes())


def array(value):
    result = np.frombuffer(value.payload, dtype="<f8").reshape(value.shape).copy()
    if not np.isfinite(result).all():
        raise ValueError("nonfinite restored tensor")
    return result


def from_coordinates(coordinates):
    offset, fields = 0, {}
    for name in ("active", "upper", "mass", "discounted_hit", "occupation"):
        count = math.prod(SHAPES[name])
        fields[name] = np.array(coordinates[offset:offset + count]).reshape(SHAPES[name])
        offset += count
    if offset != len(coordinates):
        raise ValueError("state coordinate denominator")
    return flow.DynamicState(**fields)


def envelope(capsule, physics):
    state = from_coordinates(capsule.state)
    fields = {name: tensor(getattr(state, name)) for name in SHAPES}
    fields["physics_nodes"] = tensor(physics["nodes"])
    fields["physics_reset"] = tensor(physics["reset"])
    packets = []
    for packet in capsule.packets:
        fields["reset_" + packet.source] = tensor(packet.reset)
        generator = flow._csr(packet.operator, sparse).toarray()
        packets.append(wire.Packet(packet.source, packet.generation, packet.origin,
            packet.target, str(packet.start), str(packet.end),
            tensor(np.asarray(packet.alpha).reshape(5, packet.dimension)),
            tensor(generator), tensor(packet.output)))
    metadata = {"model": MODEL, "input_bundle_sha256": flow.INPUT_BUNDLE_SHA256,
        "time": str(capsule.time), "physics": physics["metadata"]["physics"],
        "reset_distance": physics["metadata"]["reset_distance"],
        "packet_order": [packet.source for packet in capsule.packets],
        "delay": str(flow.DELAY), "discount": flow.DISCOUNT}
    return wire.Envelope(metadata,
        tuple(wire.Block(key, value) for key, value in sorted(fields.items())),
        tuple(sorted(packets, key=lambda packet: packet.identity)))


def save(capsule, physics, path):
    item = envelope(capsule, physics)
    payload = wire.encode(item)
    if len(payload) > 32 * 1024**2:
        raise ValueError("32 MiB complete-state envelope cap")
    Path(path).write_bytes(gzip.compress(payload, compresslevel=6, mtime=0))
    counts = wire.coordinate_counts(item)
    return {"path": str(Path(path).name), "time": str(capsule.time),
        "sha256": hashlib.sha256(payload).hexdigest(), "raw_bytes": len(payload),
        "gzip_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "gzip_bytes": Path(path).stat().st_size, "coordinates": counts,
        "base_roster_coordinates": len(capsule.state) + sum(p.dimension**2 + 6*p.dimension for p in capsule.packets),
        "reset_snapshot_coordinates": len(capsule.packets) * 255,
        "physics_coordinates": 512, "packets": len(capsule.packets)}


def load(path, lane="cold", lane_order=0):
    with gzip.open(path, "rb") as stream:
        payload = stream.read(32 * 1024**2 + 1)
    item = wire.decode(payload, 32 * 1024**2)
    metadata = item.metadata
    if metadata["model"] != MODEL or metadata["input_bundle_sha256"] != flow.INPUT_BUNDLE_SHA256:
        raise ValueError("snapshot model/input identity")
    if F(metadata["delay"]) != flow.DELAY or metadata["discount"] != flow.DISCOUNT:
        raise ValueError("snapshot physics identity")
    blocks = {block.name: block.tensor for block in item.blocks}
    expected = set(SHAPES) | {"physics_nodes", "physics_reset"} | {"reset_" + packet.identity for packet in item.packets}
    if set(blocks) != expected or len(item.packets) > 22:
        raise ValueError("complete state/reset denominator")
    for name, shape in {**SHAPES, "physics_nodes": (257,), "physics_reset": (255,)}.items():
        if blocks[name].shape != shape:
            raise ValueError("state/physics tensor shape")
    state = flow.DynamicState(**{name: array(blocks[name]) for name in SHAPES})
    packets = {}
    for packet in item.packets:
        reset = array(blocks["reset_" + packet.identity])
        if reset.shape != (255,) or np.any(reset < 0) or abs(float(reset.sum()) - 1) > 1e-12:
            raise ValueError("event reset law")
        generator = sparse.csr_matrix(array(packet.generator))
        operator = primitive.CSR(generator.shape[0], tuple(map(int, generator.indptr)),
            tuple(map(int, generator.indices)), tuple(map(float, generator.data)))
        packets[packet.identity] = flow.Packet(packet.identity, packet.generation,
            packet.target, packet.origin, F(packet.start), F(packet.end), operator,
            tuple(array(packet.alpha).ravel()), tuple(array(packet.output)), tuple(reset))
    order = metadata["packet_order"]
    if len(order) != len(packets) or set(order) != set(packets):
        raise ValueError("lossless packet ordering")
    pending = tuple(packets[key] for key in order)
    physics = {"metadata": {"physics": metadata["physics"], "reset_distance": metadata["reset_distance"]},
               "nodes": array(blocks["physics_nodes"]), "reset": tuple(array(blocks["physics_reset"]))}
    capsule = flow.Capsule(lane, lane_order, F(metadata["time"]), state.coordinates(), pending)
    if wire.encode(envelope(capsule, physics)) != payload:
        raise ValueError("actual restored full-state bytes differ")
    return capsule, state, pending, physics
