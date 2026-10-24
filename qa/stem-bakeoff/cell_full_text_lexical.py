"""Exact/BM25 controls on complete bounded text, with the frozen BM25 formula."""

import re
import time

import numpy as np

from cell_learning_baselines import retained_state_bytes
from operational_head_view import full_normalized_text


class FullTextLexical:
    def __init__(self, labels, rows):
        began, cpu = time.perf_counter_ns(), time.process_time_ns()
        self.labels = np.asarray(labels).copy()
        self.rows = [dict(row) for row in rows]
        if (self.labels.dtype.kind not in "iu" or self.labels.shape != (len(rows),)
                or not 2 <= len(rows) <= 128 or set(self.labels.tolist()) != {0, 1}
                or any(set(row) != {"source_id", "group_id", "text"} for row in rows)):
            raise ValueError("bounded binary training sources without extra fields required")
        self.texts = [full_normalized_text(row["text"]) for row in rows]
        self.exact, postings, lengths = {}, {}, []
        for i, text in enumerate(self.texts):
            self.exact.setdefault(text, set()).add(int(self.labels[i]))
            counts = {}
            tokens = re.findall(r"\w+", text)
            lengths.append(len(tokens))
            for token in tokens:
                counts[token] = counts.get(token, 0)+1
            for token, count in counts.items():
                postings.setdefault(token, []).append((i, count))
        lengths = np.asarray(lengths)
        penalty = 1.2*(0.25+0.75*lengths/max(float(lengths.mean()), 1.0))
        self.postings = {}
        for token, entries in postings.items():
            indices = np.array([entry[0] for entry in entries], dtype=np.int32)
            tf = np.array([entry[1] for entry in entries])
            idf = np.log(1+(len(rows)-len(indices)+0.5)/(len(indices)+0.5))
            self.postings[token] = (indices, idf*tf*2.2/(tf+penalty[indices]))
        self.fit_cost = {"wall_ns": time.perf_counter_ns()-began,
                         "cpu_ns": time.process_time_ns()-cpu}
        self.memory = retained_state_bytes(vars(self))

    def predict(self, arm, rows):
        if (arm not in ("exact", "bm25") or not 1 <= len(rows) <= 16384
                or any(set(row) != {"source_id", "group_id", "text"} for row in rows)):
            raise ValueError("bounded lexical queries without gold fields required")
        began, cpu = time.perf_counter_ns(), time.process_time_ns()
        texts = [full_normalized_text(row["text"]) for row in rows]
        eligible, logits = np.ones(len(rows), dtype=bool), np.zeros((len(rows), 2))
        selected = [None]*len(rows)
        if arm == "exact":
            for i, text in enumerate(texts):
                targets = self.exact.get(text, set())
                eligible[i] = len(targets) == 1
                if eligible[i]:
                    logits[i, next(iter(targets))] = 20
                    selected[i] = self.rows[self.texts.index(text)]["source_id"]
        else:
            similarity = np.zeros((len(rows), len(self.rows)))
            for i, text in enumerate(texts):
                for token in set(re.findall(r"\w+", text)):
                    posting = self.postings.get(token)
                    if posting is not None:
                        indices, contribution = posting
                        similarity[i, indices] += contribution
            eligible = similarity.max(axis=1) > 0
            logits = np.stack([similarity[:, self.labels == label].max(axis=1)
                               for label in range(2)], axis=1)
            selected = [self.rows[j]["source_id"] if eligible[i] else None
                        for i, j in enumerate(similarity.argmax(axis=1))]
        return {"logits": logits, "eligible": eligible, "retrieved_source_ids": selected,
            "cost": {"wall_ns": time.perf_counter_ns()-began, "cpu_ns": time.process_time_ns()-cpu,
                "queries": len(rows), "training_sources": len(self.rows),
                "retained_source_utf8_bytes": sum(len(r["text"].encode()) for r in self.rows),
                "query_source_utf8_bytes": sum(len(r["text"].encode()) for r in rows),
                "fit_once_cost": self.fit_cost, **self.memory,
                "encoder_forward_calls": 0, "optimizer_steps": 0,
                "maximum_source_utf8_bytes": 131072,
                "python_measurement": "recursive reachable object size, not exclusive RSS"}}
