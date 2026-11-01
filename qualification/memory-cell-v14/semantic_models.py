"""Strong baselines and actual BERT LoRA with a matched 12-class reader."""

import copy
import math
import re
import time
from collections import Counter

import numpy as np

from language_models import make_network, tokens
from semantic_data import SKILLS, evaluate


def normalized(x):
    x = np.asarray(x, dtype=np.float64)
    return x / np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-12)


def make_semantic_network(backbone, kind, seed):
    import torch
    from torch import nn
    network = make_network(backbone, kind, seed)
    torch.manual_seed(seed)
    width = backbone.config.hidden_size
    network.head = nn.Sequential(nn.Linear(width, 32), nn.GELU(), nn.Linear(32, len(SKILLS))) if kind == "feature_mlp" else nn.Linear(width, len(SKILLS))
    return network


class SemanticBaseline:
    def __init__(self, kind):
        self.kind = kind

    def fit(self, train, calibration, x, xc, seed):
        started = time.perf_counter()
        self.history = []
        self.labels = np.array([r["label"] for r in train])
        self.texts = [r["text"] for r in train]
        self.exact = {" ".join(text.lower().split()): int(label) for text, label in zip(self.texts, self.labels)}
        if self.kind in ("exact_kv", "bm25", "kv_bm25"):
            if self.kind != "exact_kv":
                self.docs = [Counter(tokens(text)) for text in self.texts]
                self.lengths = np.array([sum(doc.values()) for doc in self.docs])
                self.average = float(np.mean(self.lengths))
                df = Counter(word for doc in self.docs for word in doc)
                self.idf = {word: math.log(1 + (len(self.docs) - count + .5) / (count + .5)) for word, count in df.items()}
        elif self.kind == "lexical_ridge":
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import RidgeClassifier
            from sklearn.pipeline import FeatureUnion
            self.vectorizer = FeatureUnion([
                ("word", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)),
                ("character", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True))])
            design = self.vectorizer.fit_transform(self.texts)
            cal_design = self.vectorizer.transform([r["text"] for r in calibration])
            best = (-1., -1.)
            for alpha in (.01, .1, 1., 10.):
                candidate = RidgeClassifier(alpha=alpha, solver="lsqr").fit(design, self.labels)
                score = evaluate(calibration, candidate.predict(cal_design))
                self.history.append({"alpha": alpha, "calibration_task_success": score["task_success"], "label_accuracy": score["label_accuracy"]})
                key = (score["task_success"], score["label_accuracy"])
                if key > best:
                    best, self.regressor, self.selected = key, candidate, {"alpha": alpha}
        else:
            features = normalized(x)
            cal_features = normalized(xc)
            targets = np.eye(len(SKILLS))[self.labels]
            if self.kind == "nearest":
                self.matrix = features
            elif self.kind == "centroid":
                self.matrix = normalized(np.stack([features[self.labels == i].mean(0) for i in range(len(SKILLS))]))
            else:
                features = np.c_[features, np.ones(len(features))]
                cal_features = np.c_[cal_features, np.ones(len(cal_features))]
                best = (-1., -1.)
                weights = np.zeros((features.shape[1], len(SKILLS)))
                rng = np.random.default_rng(seed)
                candidates = (.01, .1, 1., 10.) if self.kind == "ridge" else (2, 6, 12)
                previous = 0
                for parameter in candidates:
                    if self.kind == "ridge":
                        weights = np.linalg.solve(features.T @ features + np.eye(features.shape[1]) * parameter, features.T @ targets)
                    elif self.kind == "fast_weights":
                        for _ in range(previous, parameter):
                            for i in rng.permutation(len(features)):
                                error = targets[i] - features[i] @ weights
                                weights += .4 * np.outer(features[i], error) / float(features[i] @ features[i])
                        previous = parameter
                    else:
                        raise ValueError(self.kind)
                    score = evaluate(calibration, np.argmax(cal_features @ weights, axis=1))
                    self.history.append({"parameter": parameter, "calibration_task_success": score["task_success"], "label_accuracy": score["label_accuracy"]})
                    key = (score["task_success"], score["label_accuracy"])
                    if key > best:
                        best, self.matrix, self.selected = key, weights.copy(), {"parameter": parameter}
        self.fit_seconds = time.perf_counter() - started
        return self

    def predict(self, texts, features=None):
        if self.kind == "lexical_ridge":
            return self.regressor.predict(self.vectorizer.transform(texts)).astype(int)
        if self.kind in ("exact_kv", "bm25", "kv_bm25"):
            predictions = []
            for text in texts:
                key = " ".join(text.lower().split())
                literal = [i for i, skill in enumerate(SKILLS) if re.search(r"\b" + re.escape(skill) + r"\b", text)]
                exact = self.exact.get(key, literal[0] if len(literal) == 1 else -1)
                if self.kind == "exact_kv" or (self.kind == "kv_bm25" and exact >= 0):
                    predictions.append(exact)
                    continue
                scores = np.zeros(len(self.docs))
                for word in set(tokens(text)):
                    count = np.array([doc[word] for doc in self.docs])
                    scores += self.idf.get(word, 0.) * count * 2.5 / (count + 1.5 * (.25 + .75 * self.lengths / self.average))
                predictions.append(int(self.labels[int(np.argmax(scores))]))
            return np.array(predictions)
        values = normalized(features)
        if self.kind == "nearest":
            return self.labels[np.argmax(values @ self.matrix.T, axis=1)]
        if self.kind == "centroid":
            return np.argmax(values @ self.matrix.T, axis=1)
        return np.argmax(np.c_[values, np.ones(len(values))] @ self.matrix, axis=1)
