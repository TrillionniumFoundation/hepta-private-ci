"""Independent learned-router replay and source-only candidate selection audit."""

import hashlib
import json
import math
import re
import struct

from population_audit_artifacts import (
    ARMS,
    _digest,
    _hash,
    _json,
    _read,
    _require,
    _same,
)


def _router(path, expected_hash):
    raw = _read(path)
    magic = b"HEPTA_ROUTER_V2\n"
    _require(
        raw.startswith(magic) and _hash(raw) == expected_hash, "pinned learned router"
    )
    size = struct.unpack("<I", raw[len(magic) : len(magic) + 4])[0]
    offset = len(magic) + 4 + size
    header, payload = json.loads(raw[len(magic) + 4 : offset]), raw[offset:]
    _require(
        _hash(payload) == header["weight_sha256"]
        and header["weight_shape"] == [header["config"]["dimension"] + 1, 3]
        and len(payload) == math.prod(header["weight_shape"]) * 4,
        "router tensor payload",
    )
    return header, [v[0] for v in struct.iter_unpack("<f", payload)]


def _route(question, router):
    header, weights = router
    cfg = header["config"]
    tokens = re.findall(r"\w+", " ".join(question.casefold().split()))
    pieces = [("w:" + t, 1.0) for t in tokens] + [
        ("b:" + a + "/" + b, 0.5) for a, b in zip(tokens, tokens[1:])
    ]
    padded = " " + " ".join(tokens) + " "
    pieces += [
        (f"c{n}:" + padded[i : i + n], 0.15)
        for n in (3, 4)
        for i in range(len(padded) - n + 1)
    ]
    features = [0.0] * cfg["dimension"]
    for piece, amount in pieces:
        hashed = hashlib.blake2b(
            piece.encode(), key=cfg["seed"].to_bytes(4, "little"), digest_size=8
        ).digest()
        features[int.from_bytes(hashed[:4], "little") % len(features)] += (
            amount if hashed[4] & 1 else -amount
        )
    norm = math.sqrt(sum(v * v for v in features))
    features = [v / norm for v in features] + [1.0]
    logits = [
        sum(value * weights[3 * i + j] for i, value in enumerate(features))
        for j in range(3)
    ]
    exponentials = [math.exp(v - max(logits)) for v in logits]
    probabilities = [v / sum(exponentials) for v in exponentials]
    best = max(range(2), key=lambda i: probabilities[i])
    accepted = (
        probabilities[2] < probabilities[best]
        and sum(probabilities[:2]) >= cfg["min_confidence"]
        and probabilities[best] - probabilities[2] >= cfg["min_margin"]
    )
    return best if accepted else None, probabilities


def _selection(directory, data, report, points):
    path = directory / "selection/precommitted-selection.json"
    _require(
        _hash(_read(path)) == report["selection_sha256"], "frozen source selection"
    )
    _same(
        _json(path),
        {
            k: v
            for k, v in report.items()
            if k not in {"selection_path", "selection_sha256"}
        },
        "selection report copy",
    )
    raw = _json(directory / "selection/source-generations.json")
    assessments = _json(directory / "selection/source-assessments.json")
    router = _router(
        directory / "selection/learned-router.bin", report["router_receipt"]["sha256"]
    )
    router_probes = data["router_training"] + data["router_reject_training"]
    for arm in ARMS:
        for slot, entry in enumerate(raw[arm]):
            _same(
                entry["version"],
                report["versions"][arm][slot],
                "source read version binding",
            )
            expected_probes = (
                router_probes + data["source_selection"]
                if arm == "split"
                else data["source_selection"]
            )
            _same(
                [r["question"] for r in entry["rows"]],
                [p["question"] for p in expected_probes],
                "raw source questions",
            )
            _require(
                entry["adapter_state_sha256"] == points[arm][slot]["state"],
                "raw source read state",
            )
    observations = []
    for i, probe in enumerate(router_probes):
        utilities = [
            float(
                raw["split"][slot]["rows"][i]["text"] == probe["value"]
                and bool(probe["source_roots"])
                and set(probe["source_roots"])
                <= set(report["versions"]["split"][slot]["roots"])
            )
            for slot in (0, 1)
        ]
        observations.append(
            {"question": probe["question"], "utilities": utilities, "reject": i >= 64}
        )
    provenance = {
        "sources_sha256": data["sources_sha256"],
        "expert_manifests": [v["manifest_sha256"] for v in report["versions"]["split"]],
        "observations": observations,
    }
    _same(
        _json(directory / "selection/router-observations.json"),
        provenance,
        "actual utility provenance",
    )
    _require(
        router[0]["source_sha256"] == _digest(provenance)
        and router[0]["training_sha256"] == _digest(observations),
        "router source utility binding",
    )
    scores = {arm: [] for arm in ARMS}
    for index, probe in enumerate(data["source_selection"]):
        slot, probabilities = _route(probe["question"], router)
        _same(assessments[index]["route"]["slot"], slot, "independent source routing")
        _same(
            assessments[index]["route"]["probabilities"],
            probabilities,
            "independent source route probabilities",
        )
        for arm in ARMS:
            chosen = slot if arm == "split" else 0
            source_index = 76 + index if arm == "split" else index
            text = (
                raw[arm][chosen]["rows"][source_index]["text"]
                if chosen is not None
                else "unknown"
            )
            supported = (
                chosen is not None
                and bool(probe["source_roots"])
                and set(probe["source_roots"])
                <= set(report["versions"][arm][chosen]["roots"])
            )
            scores[arm].append(bool(supported and text == probe["value"]))
            _same(
                assessments[index][arm],
                {
                    "raw_text": text,
                    "source_supported": supported,
                    "raw_correct": text == probe["value"],
                    "supported_correct": scores[arm][-1],
                },
                "source assessment",
            )
    _same(report["source_scores"], scores, "source scores recomputed from answers")
    for arm in ARMS:
        _require(
            report["costs"][arm]["private_parameter_bytes"]
            == sum(p["private_bytes"] for p in points[arm]),
            "actual selection parameter cost",
        )
        _require(
            report["costs"][arm]["retained_checkpoint_bytes"]
            == sum(p["retained_bytes"] for p in points[arm]),
            "actual selection retained checkpoint cost",
        )
        _require(
            report["costs"][arm]["optimizer_steps"] == (0 if arm == "parent" else 1024),
            "selection optimizer accounting",
        )
    _require(
        report["costs"]["split"]["router_artifact_bytes"]
        == len(_read(directory / "selection/learned-router.bin")),
        "serialized router overhead",
    )
    counts = {arm: sum(scores[arm]) for arm in ARMS}
    preserve = {
        arm: all(not scores["parent"][i] or scores[arm][i] for i in range(16))
        for arm in ARMS
    }
    parent_ok = sum(scores["parent"][:16]) >= 12
    single_ok = (
        parent_ok and preserve["single"] and counts["single"] >= counts["parent"] + 1
    )
    cheaper = "single" if single_ok else "parent"
    split_ok = (
        parent_ok
        and preserve["split"]
        and counts["split"] >= counts[cheaper] + 4
        and report["costs"]["split"]["router_artifact_bytes"] * 100
        <= report["costs"]["single"]["private_parameter_bytes"]
    )
    _same(
        report["choice"]["chosen_arm"],
        "split" if split_ok else cheaper,
        "independently precommitted arm",
    )
    for key, value in (
        ("parent_recall_gate", parent_ok),
        ("parent_semantic_correct", sum(scores["parent"][:16])),
        ("parent_correct_semantic_preserved", preserve),
        ("source_correct_counts", counts),
        ("single_eligible", single_ok),
        ("split_eligible", split_ok),
        ("best_eligible_cheaper_arm", cheaper),
        ("minimum_split_gain", 4),
        ("split_gain_over_single", counts["split"] - counts["single"]),
        ("same_single_split_adapter_bytes", True),
        ("matched_optimizer_updates", True),
        (
            "router_within_one_percent",
            report["costs"]["split"]["router_artifact_bytes"] * 100
            <= report["costs"]["single"]["private_parameter_bytes"],
        ),
    ):
        _same(report["choice"][key], value, "independent source choice gate")
    _same(
        report["choice"]["selected_cost"],
        report["costs"][report["choice"]["chosen_arm"]],
        "chosen arm actual cost",
    )
    generated = [
        r for entries in raw.values() for entry in entries for r in entry["rows"]
    ]
    work = {
        "queries": len(generated),
        "input_tokens": sum(r["input_tokens"] for r in generated),
        "generated_tokens": sum(r["generated_tokens"] for r in generated),
        "generation_seconds": sum(r["seconds"] for r in generated),
        "model_load_and_generation_wall_seconds": sum(
            entry["wall_seconds"] for entries in raw.values() for entry in entries
        ),
    }
    _same(
        report["source_work"],
        work,
        "all source selection and router expert observations charged",
    )
    _require(
        report["final_scores_used"] is False
        and report["choice"]["final_scores_used"] is False,
        "source-only choice",
    )
    return router
