"""Constrained address policies; explicit tables contain names, never values."""

import re

import numpy as np

from runtime_contract import ENTITIES, ROLES, WORKFLOWS


def labels(rows):
    return {"role": np.asarray([ROLES.index(r["role"]) for r in rows]),
            "entity": np.asarray([8 if r["entity"] is None else r["entity"] for r in rows]),
            "workflow": np.asarray([8 if r["workflow"] is None else r["workflow"] for r in rows])}


def oracle(row):
    return {"role": row["role"], "entity": row["entity"], "workflow": row["workflow"],
            "confidence": 1.0}


def deterministic(text):
    lower = text.lower()
    entity = [i for i, name in enumerate(ENTITIES) if name.lower() in lower]
    workflow = [i for i, name in enumerate(WORKFLOWS) if name.lower() in lower]
    reject = re.search(r"weather|poem|delete|credential|shares|medical|flight|\binvent(?:ed|ing|ion|s)?\b|diagnos|translate|password|forecast|recommend|email|schedule|buy|sell|stock price", lower)
    if reject:
        role = "unknown"
    elif len(entity) == len(workflow) == 1 and re.search(r"run|execut|apply|appli|result|calcul|action|current|latest|newest|inventory|observation|stock|today", lower):
        role = "compose"
    elif len(entity) == 1 and not workflow and re.search(r"policy|policies|reserve|pack|limit|stock|setting|parameter|rule|inventory|bound", lower):
        role = "semantic"
    elif len(workflow) == 1 and not entity and re.search(r"program|operation|step|instruction|procedure|sequence|action|process|routine", lower):
        role = "skill"
    else:
        role = "unknown"
    return {"role": role, "entity": entity[0] if role in ("semantic", "compose") else None,
            "workflow": workflow[0] if role in ("skill", "compose") else None, "confidence": 1.0}


def learned(cell, features, threshold):
    probabilities = cell.predict_proba(features)
    result = []
    for i in range(len(features)):
        role = ROLES[int(probabilities["role"][i].argmax())]
        entity = int(probabilities["entity"][i].argmax())
        workflow = int(probabilities["workflow"][i].argmax())
        confidence = float(probabilities["role"][i].max())
        if role in ("semantic", "compose"):
            confidence = min(confidence, float(probabilities["entity"][i].max()))
        if role in ("skill", "compose"):
            confidence = min(confidence, float(probabilities["workflow"][i].max()))
        if (confidence < threshold or role in ("semantic", "compose") and entity == 8
                or role in ("skill", "compose") and workflow == 8):
            role = "unknown"
        result.append({"role": role, "entity": entity if role in ("semantic", "compose") else None,
                       "workflow": workflow if role in ("skill", "compose") else None,
                       "confidence": confidence})
    return result


def address_equal(route, row):
    return all(route[k] == row[k] for k in ("role", "entity", "workflow"))


def calibrate(cell, features, rows):
    trials = []
    for threshold in (0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        routes = learned(cell, features, threshold)
        false_accept = sum(row["role"] == "unknown" and route["role"] != "unknown"
                           for row, route in zip(rows, routes, strict=True))
        known_correct = sum(row["role"] != "unknown" and address_equal(route, row)
                            for row, route in zip(rows, routes, strict=True))
        trials.append({"threshold": threshold, "unknown_false_accept": false_accept,
                       "known_correct": known_correct})
    allowed = [r for r in trials if r["unknown_false_accept"] == 0]
    chosen = max(allowed, key=lambda r: (r["known_correct"], r["threshold"])) if allowed else None
    return {"threshold": chosen["threshold"] if chosen else 1.1, "trials": trials,
            "selection_used_held": False}
