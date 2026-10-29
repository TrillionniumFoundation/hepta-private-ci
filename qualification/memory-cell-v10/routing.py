"""Bounded inference and calibration rules, with no training or target values."""

import re

import numpy as np


CLASSES = ("semantic", "procedure", "apply", "reject")
THRESHOLDS = (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99)
REQUIRED_MARGIN = 0.05


def probabilities(logits):
    shifted = np.asarray(logits, dtype=np.float64) - np.max(logits, axis=-1, keepdims=True)
    values = np.exp(shifted)
    return values / np.sum(values, axis=-1, keepdims=True)


def operation_scores(raw):
    values = probabilities(raw)
    order = np.argsort(values, axis=-1)
    return [{"operation": CLASSES[int(indices[-1])], "score": float(row[indices[-1]]),
             "margin": float(row[indices[-1]] - row[indices[-2]])}
            for row, indices in zip(values, order, strict=True)]


def learned_routes(raw, capacity):
    result = []
    for row in raw:
        groups = [probabilities(row[:4]), probabilities(row[4:5 + capacity]),
                  probabilities(row[5 + capacity:])]
        indices = [int(np.argmax(group)) for group in groups]
        role = CLASSES[indices[0]]
        required = [0] + ([1] if role in ("semantic", "apply") else []) + ([2] if role in ("procedure", "apply") else [])
        values = [groups[i][indices[i]] for i in required]
        margins = [np.sort(groups[i])[-1] - np.sort(groups[i])[-2] for i in required]
        entity = indices[1] if role in ("semantic", "apply") else None
        workflow = indices[2] if role in ("procedure", "apply") else None
        if entity == capacity or workflow == capacity:
            role = "reject"
        result.append({"operation": role, "entity": entity, "workflow": workflow,
                       "score": float(min(values)), "margin": float(min(margins))})
    return result


def expected_route(row):
    return {"operation": {"skill": "procedure", "compose": "apply", "unknown": "reject"}.get(row["role"], row["role"]),
            "entity": row.get("entity"), "workflow": row.get("workflow")}


def nearest_routes(features, train_features, train_rows):
    similarities = np.asarray(features) @ np.asarray(train_features).T
    training = [expected_route(row) for row in train_rows]
    identities = [tuple(row[name] for name in ("operation", "entity", "workflow")) for row in training]
    result = []
    for values in similarities:
        first = int(np.argmax(values))
        alternatives = [float(value) for i, value in enumerate(values) if identities[i] != identities[first]]
        score = float(np.clip(values[first], 0, 1))
        margin = max(0.0, min(1.0, float(values[first]) - max(alternatives, default=-1)))
        result.append({**training[first], "score": score, "margin": margin})
    return result


def same_route(prediction, truth):
    return all(prediction.get(name) == truth.get(name) for name in ("operation", "entity", "workflow"))


def accepted(route, threshold):
    return route["operation"] != "reject" and route["score"] >= threshold and route["margin"] >= REQUIRED_MARGIN


def calibrate(predictions, expected):
    candidates = []
    for threshold in THRESHOLDS:
        accepts = [accepted(row, threshold) for row in predictions]
        unknown = sum(yes and target["operation"] == "reject" for yes, target in zip(accepts, expected, strict=True))
        correct = sum(yes and same_route(row, target) for yes, row, target in zip(accepts, predictions, expected, strict=True))
        candidates.append({"threshold": threshold, "accepted_unknown": unknown, "correct_known": correct,
                           "accepted_total": sum(accepts)})
    eligible = [row for row in candidates if row["accepted_unknown"] == 0]
    choice = max(eligible, key=lambda row: (row["correct_known"], row["threshold"])) if eligible else None
    return {"threshold": choice["threshold"] if choice else 1.01, "required_margin": REQUIRED_MARGIN,
            "candidates": candidates, "selected_using": "calibration only", "reject_all": choice is None}


def matching_entries(text, registry):
    matches = []
    for index, row in enumerate(registry):
        names = [row["key"], *row.get("aliases", [])]
        found = [name for name in names if re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text, re.IGNORECASE)]
        if found:
            matches.append((index, row["key"], found))
    return matches


def deterministic(text, entities, workflows):
    entities, workflows = matching_entries(text, entities), matching_entries(text, workflows)
    reject = {"operation": "reject", "entity": None, "workflow": None, "score": 1.0, "margin": 1.0}
    if re.search(r"\b(erase|rewrite|invent|translate|poem|sell|weather|predict|delete|change|update)\b", text, re.I):
        return reject
    if re.search(r"\b(execute|apply|calculate|run|combine|use)\b", text, re.I):
        operation = "apply"
    elif re.search(r"\b(policy|policies|thresholds|reserve|pack|limit|rules|numbers)\b", text, re.I):
        operation = "semantic"
    elif re.search(r"\b(steps|operations|operation|opcodes|instructions|procedure)\b", text, re.I):
        operation = "procedure"
    else:
        return reject
    if ((operation in ("semantic", "apply") and len(entities) != 1)
            or (operation in ("procedure", "apply") and len(workflows) != 1)):
        return reject
    return {"operation": operation, "entity": entities[0][0] if operation != "procedure" else None,
            "workflow": workflows[0][0] if operation != "semantic" else None, "score": 1.0, "margin": 1.0}


def masked_request(text, entities, workflows):
    """Unique registry binding is explicit; operation itself is learned."""
    entity_matches, workflow_matches = matching_entries(text, entities), matching_entries(text, workflows)
    if len(entity_matches) > 1 or len(workflow_matches) > 1:
        raise ValueError("ambiguous registry address")
    masked = text
    replacements = [(name, marker) for rows, marker in ((entity_matches, "ENTITY"), (workflow_matches, "WORKFLOW"))
                    for _, _, names in rows for name in names]
    for name, marker in sorted(replacements, key=lambda pair: -len(pair[0])):
        masked = re.sub(r"(?<!\w)" + re.escape(name) + r"(?!\w)", marker, masked, flags=re.IGNORECASE)
    return masked, entity_matches, workflow_matches
