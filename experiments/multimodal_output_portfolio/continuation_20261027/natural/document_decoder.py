"""Trainable field-value selection over public OCR text and layout evidence."""
import hashlib
import re

import numpy as np

from ...repair_20261026.natural.document.ocr import ADDRESS, DATE, FIELDS, MONEY, union
from ...repair_20261026.natural.document.run import normalize


def field_score(field, target, prediction):
    if target is None or not normalize(field, str(target)):
        return {"observed_reference": False, "exact": None, "similarity": None, "quality": None}
    truth, observed = normalize(field, target), normalize(field, prediction)
    previous = list(range(len(observed)+1))
    for i, char in enumerate(truth, 1):
        current = [i]
        for j, other in enumerate(observed, 1):
            current.append(min(current[-1]+1, previous[j]+1, previous[j-1]+(char != other)))
        previous = current
    similarity = max(0.0, 1-previous[-1]/max(len(truth), len(observed), 1))
    exact = truth == observed
    return {"observed_reference": True, "exact": exact, "similarity": similarity, "quality": .5*exact+.5*similarity}


def candidate(value, lines, field, width, height):
    context = " ".join(line["text"] for line in lines).upper()
    box = union([line["box"] for line in lines])
    confidence = float(np.mean([line["confidence"] for line in lines]))/100
    letters = sum(c.isalpha() for c in context)/max(1, len(context))
    digits = sum(c.isdigit() for c in context)/max(1, len(context))
    lexical = [bool(re.search(pattern, context)) for pattern in (
        r"\b(?:SDN|BHD|MART|STORE|TRADING|RESTAURANT|RESTORAN|ENTERPRISE|CAFE|BAKERY)\b",
        r"\b(?:JALAN|JLN|TAMAN|LOT|ROAD|STREET|NO|BAHRU|SELANGOR)\b", r"\b\d{5}\b",
        r"\bTEL|PHONE|FAX", r"GST|REG|TAX|INVOICE|RECEIPT|CASHIER", r"TOTAL|AMOUNT DUE|NET AMOUNT",
        r"SUBTOTAL|SUB TOTAL|TOTAL GST|TOTAL TAX|TOTAL QTY", r"GRAND|ROUND|NET|DUE", r"CASH|CHANGE",
        r"DATE|TIME", r"WWW|HTTP|@", r"MALAYSIA|KUALA|JOHOR|SELANGOR|PENANG")]
    features = [float(field == name) for name in FIELDS] + [box[0]/width, box[1]/height, box[2]/width,
        box[3]/height, (box[2]-box[0])/width, (box[3]-box[1])/height, len(lines)/4,
        min(1, len(context)/150), min(1, len(value)/120), confidence, letters, digits,
        bool(DATE.search(context)), bool(ADDRESS.search(context)), min(1, len(MONEY.findall(context))/4)] + lexical
    return {"value": value.strip(), "box": box, "context": context, "confidence": confidence,
        "features": list(map(float, features))}


def candidates(lines, width, height):
    result = {field: [] for field in FIELDS}
    upper = [line for line in lines if line["box"][1] < .55*height][:18]
    for i, line in enumerate(lines):
        if line["box"][1] < .4*height and len(re.findall("[A-Za-z]", line["text"])) >= 4:
            result["company"].append(candidate(line["text"], [line], "company", width, height))
            stripped = re.sub(r"\s*\([^)]*\d[^)]*\)\s*$", "", line["text"])
            if stripped != line["text"]:
                result["company"].append(candidate(stripped, [line], "company", width, height))
        for match in DATE.finditer(line["text"]):
            result["date"].append(candidate(match.group(), [line], "date", width, height))
        for value in MONEY.findall(line["text"]):
            context = lines[max(0, i-1):i+1]
            item = candidate(value, context, "total", width, height)
            item["box"] = line["box"]
            result["total"].append(item)
    for i in range(len(upper)):
        for count in range(1, 5):
            group = upper[i:i+count]
            if len(group) == count:
                result["address"].append(candidate(" ".join(r["text"] for r in group), group, "address", width, height))
    for field in FIELDS:
        seen, unique = set(), []
        for item in result[field]:
            identity = (item["value"], tuple(item["box"]))
            if identity not in seen:
                unique.append(item)
                seen.add(identity)
        result[field] = unique
    return result


class FieldDecoder:
    """A fitted two-layer neural quality score, shared by all field selectors."""

    def __init__(self, parameters):
        self.parameters = parameters

    def predict(self, features):
        p = self.parameters
        x = (np.asarray(features, dtype=np.float64)-p["mean"])/p["scale"]
        hidden = np.tanh(x @ p["w1"] + p["b1"])
        z = hidden @ p["w2"] + p["b2"]
        return 1/(1+np.exp(-np.clip(z, -35, 35)))

    def select(self, options, field, width, height):
        if not options:
            box = [0, 0 if field != "total" else .4*height, width, .4*height if field == "company" else height]
            return {"value": "", "box": box, "predicted_quality": 0.0, "margin": 0.0, "confidence": 0.0}
        predictions = self.predict([row["features"] for row in options]).reshape(-1)
        order = np.argsort(-predictions, kind="stable")
        chosen = options[int(order[0])]
        margin = predictions[order[0]] - (predictions[order[1]] if len(order) > 1 else 0)
        return {**chosen, "predicted_quality": float(predictions[order[0]]), "margin": float(margin)}

    def save(self, path):
        np.savez(path, **self.parameters)

    @classmethod
    def load(cls, path):
        with np.load(path, allow_pickle=False) as data:
            return cls({key: data[key] for key in data.files})


def fit_decoder(documents, spec):
    features, targets, weights = [], [], []
    missing = 0
    for document in documents:
        valid_fields = [field for field in FIELDS if field_score(field, document["reference"][field], "")["observed_reference"]]
        missing += len(FIELDS)-len(valid_fields)
        for field in FIELDS:
            if field not in valid_fields:
                continue
            options = document["candidates"][field]
            for item in options:
                features.append(item["features"])
                targets.append(field_score(field, document["reference"][field], item["value"])["quality"])
                weights.append(1/(len(documents)*len(valid_fields)*max(1, len(options))))
    x, y, weight = np.asarray(features), np.asarray(targets)[:, None], np.asarray(weights)[:, None]
    weight /= weight.sum()
    mean, scale = x.mean(0), np.maximum(.1, x.std(0))
    x = (x-mean)/scale
    rng = np.random.default_rng(spec["seed"])
    p = {"w1": rng.normal(0, .15, (x.shape[1], spec["hidden"])), "b1": np.zeros(spec["hidden"]),
        "w2": rng.normal(0, .15, (spec["hidden"], 1)), "b2": np.zeros(1)}
    initial = hashlib.sha256(b"".join(value.tobytes() for value in p.values())).hexdigest()
    first = {key: np.zeros_like(value) for key, value in p.items()}
    second = {key: np.zeros_like(value) for key, value in p.items()}
    losses = []
    for step in range(1, spec["steps"]+1):
        hidden = np.tanh(x @ p["w1"] + p["b1"])
        prediction = 1/(1+np.exp(-np.clip(hidden @ p["w2"]+p["b2"], -35, 35)))
        loss = float(np.sum(weight * np.square(prediction-y)))
        dz = 2*weight*(prediction-y)*prediction*(1-prediction)
        dh = (dz @ p["w2"].T)*(1-hidden*hidden)
        gradient = {"w1": x.T @ dh, "b1": dh.sum(0), "w2": hidden.T @ dz, "b2": dz.sum(0)}
        for key in p:
            first[key] = .9*first[key]+.1*gradient[key]
            second[key] = .999*second[key]+.001*gradient[key]*gradient[key]
            p[key] -= spec["learning_rate"]*(first[key]/(1-.9**step))/(np.sqrt(second[key]/(1-.999**step))+1e-8)
        if step == 1 or step % 100 == 0:
            losses.append({"step": step, "weighted_MSE": loss})
    final = hashlib.sha256(b"".join(value.tobytes() for value in p.values())).hexdigest()
    p.update(mean=mean, scale=scale)
    return FieldDecoder(p), {"initial_parameter_sha256": initial, "final_parameter_sha256": final,
        "parameter_update_observed": initial != final, "candidate_rows": len(x),
        "missing_reference_fields_masked": missing,
        "fit_source_documents": len(documents), "optimizer_steps": spec["steps"], "losses": losses,
        "trainable_parameters": sum(p[k].size for k in ("w1", "b1", "w2", "b2"))}
