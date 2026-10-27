"""Learn bounded residual corrections while retaining a strong OCR rule option."""
import numpy as np

from ...continuation_20261027.natural.document_decoder import candidates, candidate, field_score
from ...repair_20261026.natural.document.ocr import FIELDS, extract
from ...repair_20261026.natural.document.run import normalize


def options(observed):
    lines, width, height = observed["lines"], observed["width"], observed["height"]
    answers, boxes = extract(lines, height)
    output = candidates(lines, width, height)
    for field in FIELDS:
        box = boxes.get(field, [0, 0, width, height])
        relevant = [line for line in lines if line["box"][1] >= box[1] and line["box"][3] <= box[3]]
        if relevant:
            baseline = candidate(answers[field], relevant, field, width, height)
        else:
            baseline = {"value": answers[field], "box": box, "features": [0.] * 31, "context": "", "confidence": 0.}
        baseline.update(is_rule=True, box=box)
        unique = [baseline]
        seen = {normalize(field, baseline["value"])}
        for item in output[field]:
            identity = normalize(field, item["value"])
            if identity not in seen:
                unique.append({**item, "is_rule": False})
                seen.add(identity)
        output[field] = unique
    return output


def feature(candidate_row, baseline):
    difference = np.asarray(candidate_row["features"]) - np.asarray(baseline["features"])
    return np.r_[difference, float(not candidate_row["is_rule"])]


def fit(documents, regularization):
    fitted, diagnostics = {}, {}
    for field in FIELDS:
        x, y, mass = [], [], []
        observed_documents = 0
        for document in documents:
            reference = document["reference"][field]
            choices = document["options"][field]
            quality = field_score(field, reference, choices[0]["value"])
            if not quality["observed_reference"]:
                continue
            observed_documents += 1
            for item in choices[1:]:
                x.append(feature(item, choices[0]))
                y.append(field_score(field, reference, item["value"])["quality"] - quality["quality"])
                mass.append(1 / max(1, len(choices) - 1))
        if not x:
            fitted[field] = {"weights": [0.] * 32, "scale": [1.] * 32}
            diagnostics[field] = {"candidate_pairs": 0, "observed_documents": observed_documents}
            continue
        x, y, mass = np.asarray(x), np.asarray(y), np.asarray(mass)
        scale = np.maximum(.1, np.sqrt(np.average(x * x, axis=0, weights=mass)))
        x = x / scale
        weights = np.linalg.solve(x.T @ (mass[:, None] * x) + regularization * np.eye(x.shape[1]), x.T @ (mass * y))
        fitted[field] = {"weights": weights.tolist(), "scale": scale.tolist()}
        diagnostics[field] = {"candidate_pairs": len(x), "observed_documents": observed_documents,
            "weighted_training_MSE": float(np.average((x @ weights - y) ** 2, weights=mass))}
    return {"fields": fitted, "regularization": regularization,
        "diagnostics": diagnostics, "trainable_parameters": sum(len(p["weights"]) for p in fitted.values()),
        "objective": "Per-observed-document balanced ridge regression to candidate actual quality gain over original rules"}


def select(choices, model, threshold):
    selected, decisions = {}, []
    for field in FIELDS:
        options_for_field = choices[field]
        p = model["fields"][field]
        values = np.asarray([feature(row, options_for_field[0]) for row in options_for_field]) / np.asarray(p["scale"])
        gains = values @ np.asarray(p["weights"])
        gains[0] = threshold
        index = int(np.argmax(gains))
        selected[field] = options_for_field[index]
        decisions.append({"field": field, "selected_index": index, "rule_preserved": index == 0,
            "estimated_gain": float(0 if index == 0 else gains[index]), "threshold": threshold,
            "reference_received": False})
    return selected, decisions
