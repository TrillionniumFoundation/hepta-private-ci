"""Public module addressing plus learned heading intent, with matched controls.

Every mode receives the same literal module registry and current source corpus.
This retrieves evidence addresses; it does not claim to store the source content
in model parameters or to provide native owner authority.
"""

from collections import Counter
import hashlib
import json
import re
import time

import numpy as np
from scipy.special import softmax

from categorical import train_categorical
from learned import canonical, features


def normalized(text):
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def encoded_array(array):
    value = np.asarray(array, dtype="<f4", order="C")
    return dict(shape=list(value.shape), f32le_hex=value.tobytes().hex())


class FactorizedAddress:
    def __init__(self, records, phase, dimension=256):
        started = time.perf_counter()
        self.records, self.phase, self.dimension = records, phase, dimension
        self.lookup = {record["id"]: i for i, record in enumerate(records)}
        if len(self.lookup) != len(records):
            raise ValueError("record IDs must be unique")
        latest = {}
        for i, record in enumerate(records):
            if record.get("available_phase", 0) > phase:
                continue
            key = (record["module"], record["heading"])
            previous = latest.get(key)
            if previous is None or record["version"] > records[previous]["version"]:
                latest[key] = i
            elif previous != i and record["version"] == records[previous]["version"]:
                raise ValueError("ambiguous current record")
        self.active = np.zeros(len(records), dtype=bool)
        for i in latest.values():
            record = records[i]
            self.active[i] = not record.get("revoked", False) and phase < record.get("withdrawn_phase", float("inf"))
        self.indices = np.flatnonzero(self.active)
        self.modules = sorted({records[i]["module"] for i in self.indices})
        self.headings = sorted({record["heading"] for record in records})
        self.heading_index = {name: i for i, name in enumerate(self.headings)}
        self.by_module = {name: [i for i in self.indices if records[i]["module"] == name] for name in self.modules}
        self.aliases = {name: normalized(name) for name in self.modules}
        self.bags = {int(i): dict(Counter(normalized(records[i]["text"]).split())) for i in self.indices}
        lengths = [sum(bag.values()) for bag in self.bags.values()]
        self.average_length = max(1., float(np.mean(lengths)))
        frequency = Counter(word for bag in self.bags.values() for word in bag)
        self.idf = {word: float(np.log1p((len(self.indices) - count + .5) / (count + .5)))
                    for word, count in frequency.items()}
        self.models = {}
        self.history_x = self.history_y = None
        self.costs = dict(index_build_seconds=time.perf_counter() - started,
                          source_text_bytes=sum(len(records[i]["text"].encode()) for i in self.indices),
                          registry_bytes=len(canonical([(records[i]["id"], records[i]["module"], records[i]["heading"],
                                                        records[i]["version"]) for i in self.indices])),
                          bm25_index_bytes=len(canonical([self.bags, self.idf])))

    def resolve_module(self, text):
        query = " " + normalized(text) + " "
        matches = []
        for module, alias in self.aliases.items():
            for match in re.finditer(re.escape(" " + alias + " "), query):
                matches.append((match.start(), match.end(), module))
        maximal = [item for item in matches if not any(other[0] <= item[0] and other[1] >= item[1]
                    and other[1] - other[0] > item[1] - item[0] for other in matches)]
        names = {item[2] for item in maximal}
        return next(iter(names)) if len(names) == 1 else None

    def normalize_text(self, text, module=None):
        module = self.resolve_module(text) if module is None else module
        query = " " + normalized(text) + " "
        if module is not None:
            query = query.replace(" " + self.aliases[module] + " ", " module ")
        return query.strip()

    def fit(self, history_queries, seed=31031, hidden=32, steps=240):
        started, cpu = time.perf_counter(), time.process_time()
        texts, full_texts, source_targets, query_ids = [], [], [], []
        for i in self.indices:
            record = self.records[i]
            texts.append(self.normalize_text(record["text"], record["module"]))
            full_texts.append(record["text"])
            source_targets.append([int(i)])
            query_ids.append("canonical:" + record["id"])
        excluded = []
        for row in history_queries:
            target = [self.lookup[key] for key in row["target_ids"] if key in self.lookup]
            if len(target) != len(row["target_ids"]) or any(not self.active[i] for i in target):
                excluded.append(row["id"])
                continue
            if not target:
                continue  # No source-class distribution; negative calibration is separate.
            texts.append(self.normalize_text(row["text"]))
            full_texts.append(row["text"])
            source_targets.append(target)
            query_ids.append(row["id"])
        shared_x = features(texts, dimension=self.dimension)
        single_x = features(full_texts, dimension=self.dimension)
        heading_y = np.zeros((len(texts), len(self.headings)), np.float32)
        source_y = np.zeros((len(texts), len(self.records)), np.float32)
        for row, target in enumerate(source_targets):
            source_y[row, target] = 1 / len(target)
            headings = sorted({self.heading_index[self.records[i]["heading"]] for i in target})
            heading_y[row, headings] = 1 / len(headings)
        self.models["learned"] = train_categorical(shared_x, heading_y, hidden=hidden, steps=steps, seed=seed)
        self.models["single"] = train_categorical(single_x, source_y, hidden=hidden, steps=steps, seed=seed)
        self.history_x, self.history_y = shared_x, heading_y
        self.training_query_ids = query_ids
        self.training_sha256 = hashlib.sha256(canonical([query_ids, source_targets])).hexdigest()
        self.costs.update(fit_wall_seconds=time.perf_counter() - started, fit_cpu_seconds=time.process_time() - cpu,
                          history_index_bytes=shared_x.nbytes + heading_y.nbytes,
                          feature_bytes=shared_x.nbytes + single_x.nbytes,
                          source_target_bytes=source_y.nbytes, heading_target_bytes=heading_y.nbytes,
                          training_rows=len(texts), excluded_stale_queries=excluded,
                          models={name: model.receipt for name, model in self.models.items()})
        return self

    def score(self, texts, mode="learned"):
        if mode not in ("learned", "single", "bm25", "history"):
            raise ValueError("unknown address strategy")
        if mode != "bm25" and not self.models:
            raise ValueError("fit is required")
        result = np.zeros((len(texts), len(self.records)), np.float32)
        modules = [self.resolve_module(text) for text in texts]
        if mode == "learned":
            x = features([self.normalize_text(text, module) for text, module in zip(texts, modules, strict=True)], self.dimension)
            values = softmax(self.models["learned"].predict(x), axis=1)
        elif mode == "single":
            values = self.models["single"].predict(features(texts, self.dimension))
        elif mode == "history":
            x = features([self.normalize_text(text, module) for text, module in zip(texts, modules, strict=True)], self.dimension)
            similarity = x @ self.history_x.T
            nearest = similarity.argmax(axis=1)
            values = self.history_y[nearest] * np.maximum(similarity[np.arange(len(texts)), nearest], 0)[:, None]
        for row, (text, module) in enumerate(zip(texts, modules, strict=True)):
            if module is None:
                continue
            indices = self.by_module[module]
            if mode in ("learned", "history"):
                for i in indices:
                    result[row, i] = values[row, self.heading_index[self.records[i]["heading"]]]
            elif mode == "single":
                result[row, indices] = softmax(values[row, indices])
            else:
                for i in indices:
                    bag = self.bags[i]
                    length = sum(bag.values())
                    denominator = 1.2 * (.25 + .75 * length / self.average_length)
                    score = sum(self.idf.get(word, 0) * bag.get(word, 0) * 2.2
                                / (bag.get(word, 0) + denominator)
                                for word in sorted(set(normalized(text).split())))
                    result[row, i] = score / (1 + score)
        return result

    def export(self):
        return dict(schema="hepta.memory.factorized-address.v12", phase=self.phase,
                    dimension=self.dimension, headings=self.headings,
                    current_record_ids=[self.records[i]["id"] for i in self.indices],
                    record_inventory_sha256=hashlib.sha256(canonical(self.records)).hexdigest(),
                    models={name: model.export(include_optimizer=True) for name, model in self.models.items()},
                    history_features=encoded_array(self.history_x), history_targets=encoded_array(self.history_y),
                    training_query_ids=self.training_query_ids, training_sha256=self.training_sha256,
                    costs=self.costs)

    @classmethod
    def from_export(cls, payload, records):
        from learned import MLP
        if payload["schema"] != "hepta.memory.factorized-address.v12" or hashlib.sha256(canonical(records)).hexdigest() != payload["record_inventory_sha256"]:
            raise ValueError("factorized inventory identity differs")
        result = cls(records, payload["phase"], payload["dimension"])
        if result.headings != payload["headings"] or [records[i]["id"] for i in result.indices] != payload["current_record_ids"]:
            raise ValueError("factorized current view differs")
        result.models = {name: MLP.from_export(model) for name, model in payload["models"].items()}
        for name, field in (("history_x", "history_features"), ("history_y", "history_targets")):
            item = payload[field]
            value = np.frombuffer(bytes.fromhex(item["f32le_hex"]), dtype="<f4").reshape(item["shape"]).copy()
            if not np.isfinite(value).all():
                raise ValueError("nonfinite history index")
            setattr(result, name, value)
        result.training_query_ids, result.training_sha256 = payload["training_query_ids"], payload["training_sha256"]
        result.costs = payload["costs"]
        return result
