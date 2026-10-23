"""Deterministic, training-only source/target-balanced calibration selection.

Selection reads source classes, target classes and content identities. It never
reads image tensors, predictions, validation data or held-out data. A class-wise
bipartite matching keeps physical sources unique while balancing both margins.
"""

import hashlib
import json

import numpy as np


CLASSES = 12
DEFAULT_SALT = "hepta-efficient-r2-calibration-v1"


def _metadata(data):
    if data.get("split", "train") != "train":
        raise ValueError("calibration requires train-only metadata")
    labels, scenes = np.asarray(data["labels"]), np.asarray(data["source_scenes"])
    if (labels.ndim != 1 or scenes.shape != labels.shape or not 1 <= len(labels) <= 65536
            or labels.dtype.kind not in "iu" or scenes.dtype.kind not in "iu"
            or np.any(labels >= CLASSES) or np.any(scenes >= CLASSES)
            or np.any(labels < 0) or np.any(scenes < 0)):
        raise ValueError("bounded twelve-class training metadata required")
    sources, hashes = list(data["source_ids"]), list(data["input_hashes"])
    if len(sources) != len(labels) or len(hashes) != len(labels):
        raise ValueError("calibration metadata row counts differ")
    if any(not isinstance(source, str) or not 1 <= len(source) <= 256 for source in sources):
        raise ValueError("bounded physical-source identities required")
    if any(not isinstance(value, str) or len(value) != 64
           or any(char not in "0123456789abcdef" for char in value) for value in hashes):
        raise ValueError("canonical input SHA256 identities required")
    if len(set(hashes)) != len(hashes):
        raise ValueError("calibration input identities must be unique")
    source_classes = {}
    for scene, source in zip(scenes, sources):
        if source in source_classes and source_classes[source] != int(scene):
            raise ValueError("physical source has conflicting semantic classes")
        source_classes[source] = int(scene)
    return labels, scenes, sources, hashes, source_classes


def stratified_indices(data, per_class=6, salt=DEFAULT_SALT):
    """Select 12*per_class distinct training sources with balanced targets.

    Source class s requests target (s-round) mod 12 in each round. Candidate
    sources are sorted by salted source SHA, then their canonical identity. A
    source/target pair uses its smallest input SHA. Matching failures are explicit;
    neither class proportions nor source-uniqueness constraints are relaxed.
    """
    if type(per_class) is not int or not 1 <= per_class <= 64:
        raise ValueError("bounded positive calibration count required")
    if not isinstance(salt, str) or not 1 <= len(salt) <= 256:
        raise ValueError("bounded nonempty calibration salt required")
    labels, _, sources, hashes, source_classes = _metadata(data)
    best = {}
    for index, (source, target, digest) in enumerate(zip(sources, labels, hashes)):
        pair = (source, int(target))
        if pair not in best or digest < hashes[best[pair]]:
            best[pair] = index
    source_rank = {source: (hashlib.sha256((salt + "\0" + source).encode()).hexdigest(), source)
                   for source in source_classes}
    matches = {}
    for scene in range(CLASSES):
        candidates = sorted((source for source, value in source_classes.items() if value == scene),
                            key=source_rank.__getitem__)
        if len(candidates) < per_class:
            raise ValueError(f"source class {scene} cannot provide {per_class} distinct sources")
        edges = {round_: [source for source in candidates
                          if (source, (scene - round_) % CLASSES) in best]
                 for round_ in range(per_class)}
        assigned, selected = {}, {}

        def augment(round_, visited):
            for source in edges[round_]:
                if source in visited:
                    continue
                visited.add(source)
                previous = assigned.get(source)
                if previous is None or augment(previous, visited):
                    assigned[source] = round_
                    selected[round_] = source
                    return True
            return False

        # Deterministic scarcity-first order limits rematching but preserves a
        # complete matching when greedy source choices would exhaust a rare pair.
        for round_ in sorted(edges, key=lambda value: (len(edges[value]), (scene - value) % CLASSES, value)):
            if not augment(round_, set()):
                target = (scene - round_) % CLASSES
                raise ValueError(f"training source/target matching failed: source class {scene}, target {target}")
        matches[scene] = selected
    ordered = []
    for round_ in range(per_class):
        for target in range(CLASSES):
            scene = (target + round_) % CLASSES
            ordered.append(best[(matches[scene][round_], target)])
    return np.asarray(ordered, dtype=np.int64)


def global_balanced_indices(data, per_class=6, salt=DEFAULT_SALT):
    """Match both margins globally, then interleave regular-graph matchings.

    Source classes and target classes each receive exactly ``per_class`` rows.
    Every physical source has capacity one. No source/target joint cell is
    prescribed. Only TRAIN metadata and salted identity ordering are read.
    """
    if type(per_class) is not int or not 1 <= per_class <= 64:
        raise ValueError("bounded positive calibration count required")
    if not isinstance(salt, str) or not 1 <= len(salt) <= 256:
        raise ValueError("bounded nonempty calibration salt required")
    labels, _, sources, hashes, source_classes = _metadata(data)
    best = {}
    for index, (source, target, digest) in enumerate(zip(sources, labels, hashes)):
        pair = source, int(target)
        if pair not in best or digest < hashes[best[pair]]:
            best[pair] = index
    rank = {source: (hashlib.sha256((salt + "\0" + source).encode()).hexdigest(), source)
            for source in source_classes}
    identities = sorted(source_classes, key=rank.__getitem__)
    target_order = sorted(range(CLASSES), key=lambda target: (
        hashlib.sha256((salt + "\0target:" + str(target)).encode()).hexdigest(), target))
    available = {source: [] for source in identities}
    for source, target in best:
        available[source].append(target)
    target_rank = {target: index for index, target in enumerate(target_order)}
    for scene in range(CLASSES):
        if sum(value == scene for value in source_classes.values()) < per_class:
            raise ValueError(f"source class {scene} cannot provide {per_class} distinct sources")

    # Residual edges are [destination, capacity, reverse-index]. Numeric class
    # order and salted source/target order fix every augmenting-path tie.
    target_start, sink = 1 + CLASSES + len(identities), 1 + 2 * CLASSES + len(identities)
    graph = [[] for _ in range(sink + 1)]

    def edge(left, right, capacity):
        forward = [right, capacity, len(graph[right])]
        graph[left].append(forward)
        graph[right].append([left, 0, len(graph[left]) - 1])
        return forward

    for scene in range(CLASSES):
        edge(0, 1 + scene, per_class)
    arcs = {}
    for offset, source in enumerate(identities):
        node = 1 + CLASSES + offset
        edge(1 + source_classes[source], node, 1)
        for target in sorted(available[source], key=target_rank.__getitem__):
            arcs[source, target] = edge(node, target_start + target, 1)
    for target in target_order:
        edge(target_start + target, sink, per_class)

    required, flow = CLASSES * per_class, 0
    while flow < required:
        previous = [None] * len(graph)
        previous[0] = (-1, -1)
        queue, cursor = [0], 0
        while cursor < len(queue) and previous[sink] is None:
            node = queue[cursor]
            cursor += 1
            for index, (destination, capacity, _) in enumerate(graph[node]):
                if capacity and previous[destination] is None:
                    previous[destination] = node, index
                    queue.append(destination)
        if previous[sink] is None:
            raise ValueError(f"global training source/target margins infeasible: matched {flow} of {required}")
        node = sink
        while node:
            parent, index = previous[node]
            arc = graph[parent][index]
            arc[1] -= 1
            graph[node][arc[2]][1] += 1
            node = parent
        flow += 1

    cells = {}
    for source in identities:
        for target in sorted(available[source], key=target_rank.__getitem__):
            if arcs[source, target][1] == 0:
                cells.setdefault((source_classes[source], target), []).append(best[source, target])
    # A per_class-regular bipartite multigraph has a perfect matching. Removing
    # one preserves regularity, so all rounds can cover both twelve-class sets.
    ordered = []
    for _ in range(per_class):
        assigned = {}

        def augment(scene, visited):
            for target in target_order:
                if not cells.get((scene, target)) or target in visited:
                    continue
                visited.add(target)
                owner = assigned.get(target)
                if owner is None or augment(owner, visited):
                    assigned[target] = scene
                    return True
            return False

        if not all(augment(scene, set()) for scene in range(CLASSES)):
            raise RuntimeError("regular calibration graph decomposition failed")
        for target in range(CLASSES):
            ordered.append(cells[assigned[target], target].pop(0))
    return np.asarray(ordered, dtype=np.int64)


def calibration_manifest(data, indices):
    """Describe the selected training identities and both balance margins."""
    labels, scenes, sources, hashes, _ = _metadata(data)
    indices = np.asarray(indices)
    if (indices.ndim != 1 or indices.dtype.kind not in "iu" or not len(indices)
            or np.any(indices < 0) or np.any(indices >= len(labels))
            or len(set(indices.tolist())) != len(indices)):
        raise ValueError("unique in-range calibration row indices required")
    selected_sources = [sources[index] for index in indices]
    selected_hashes = [hashes[index] for index in indices]
    source_counts = {source: selected_sources.count(source) for source in sorted(set(selected_sources))}
    encoded_sources = json.dumps(selected_sources, separators=(",", ":")).encode()
    encoded_inputs = json.dumps(selected_hashes, separators=(",", ":")).encode()
    return {
        "schema": "hepta.joint-generation.stratified-calibration.v1",
        "split": "train", "rows": len(indices), "indices": indices.astype(int).tolist(),
        "selected_input_hashes": selected_hashes, "selected_source_ids": selected_sources,
        "selected_source_hashes": [hashlib.sha256(value.encode()).hexdigest() for value in selected_sources],
        "inputs_sha256": hashlib.sha256(encoded_inputs).hexdigest(),
        "source_ids_sha256": hashlib.sha256(encoded_sources).hexdigest(),
        "source_class_counts": {str(value): int(np.sum(scenes[indices] == value)) for value in range(CLASSES)},
        "target_class_counts": {str(value): int(np.sum(labels[indices] == value)) for value in range(CLASSES)},
        "physical_source_count": len(source_counts), "source_counts": source_counts,
    }
