"""Full-coordinate comparator for fixture candidate and independent oracle."""

import struct


def _candidate_view(capsule):
    coordinates = {}
    for value in capsule.state:
        coordinates[("state", *value.key)] = value.value
    packet_metadata = []
    for packet in capsule.packets:
        packet_metadata.append(packet.key)
        coordinates[("packet", *packet.key)] = packet.coefficient
    for operator in capsule.operators:
        dense = operator.dense()
        for row in range(operator.dimension):
            for column in range(operator.dimension):
                coordinates[("operator", operator.identity, row, column)] = dense[row][
                    column
                ]
    return {
        "bindings": capsule.bindings,
        "interior_nodes": capsule.interior_nodes,
        "reset": capsule.reset,
        "time": capsule.time,
        "schedule": capsule.schedule,
        "upper_mode": capsule.upper_mode,
        "state_metadata": tuple(value.key for value in capsule.state),
        "packet_metadata": tuple(packet_metadata),
        "coordinates": coordinates,
    }


def compare(candidate, oracle):
    left = _candidate_view(candidate)
    metadata_fields = (
        "bindings",
        "interior_nodes",
        "reset",
        "time",
        "schedule",
        "upper_mode",
        "state_metadata",
        "packet_metadata",
    )
    for name in metadata_fields:
        if left[name] != oracle[name]:
            raise ValueError(f"{name} mismatch")
    if left["coordinates"].keys() != oracle["coordinates"].keys():
        raise ValueError("coordinate denominator mismatch")
    mismatches = []
    for key in sorted(left["coordinates"], key=repr):
        if struct.pack("<d", left["coordinates"][key]) != struct.pack(
            "<d", oracle["coordinates"][key]
        ):
            mismatches.append(key)
    return {
        "coordinate_count": len(left["coordinates"]),
        "mismatch_count": len(mismatches),
        "mismatch_keys": tuple(mismatches),
        "passed": not mismatches,
    }
