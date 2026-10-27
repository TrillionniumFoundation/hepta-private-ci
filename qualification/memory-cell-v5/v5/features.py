"""Training-only vocabularies and an explicit, pickle-free TF-IDF transform."""

from dataclasses import dataclass

import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer

from .config import FEATURES


TOKEN_PATTERN = r"(?u)\b\w+\b|[%+\-/]"


def vectorizer(config, vocabulary=None):
    return TfidfVectorizer(
        analyzer=config["analyzer"],
        ngram_range=tuple(config["ngram_range"]),
        max_features=config["max_features"],
        token_pattern=TOKEN_PATTERN if config["analyzer"] == "word" else None,
        lowercase=False,
        strip_accents=None,
        sublinear_tf=True,
        norm="l2",
        smooth_idf=True,
        dtype=np.float64,
        vocabulary=vocabulary,
    )


@dataclass
class FeatureBlock:
    name: str
    model: TfidfVectorizer

    @classmethod
    def fit(cls, name, texts):
        model = vectorizer(FEATURES[name])
        matrix = model.fit_transform(texts).tocsr()
        return cls(name, model), matrix

    def transform(self, texts):
        return self.model.transform(texts).tocsr()

    def descriptor(self):
        return {
            "name": self.name,
            "config": FEATURES[self.name],
            "vocabulary": {
                str(key): int(value) for key, value in self.model.vocabulary_.items()
            },
            "idf_array": "idf_" + self.name,
            "token_pattern": TOKEN_PATTERN
            if FEATURES[self.name]["analyzer"] == "word"
            else None,
            "sublinear_tf": True,
            "norm": "l2",
            "lowercase": False,
            "smooth_idf": True,
        }

    @classmethod
    def load(cls, descriptor, arrays):
        name = descriptor["name"]
        if name not in FEATURES or descriptor["config"] != FEATURES[name]:
            raise ValueError("unknown frozen feature configuration")
        vocabulary = descriptor["vocabulary"]
        if not isinstance(vocabulary, dict) or not vocabulary:
            raise ValueError("feature vocabulary must be nonempty")
        if any(
            not isinstance(k, str) or type(v) is not int for k, v in vocabulary.items()
        ):
            raise ValueError("invalid vocabulary entries")
        if sorted(vocabulary.values()) != list(range(len(vocabulary))):
            raise ValueError("vocabulary indices are not contiguous and unique")
        if len(vocabulary) > FEATURES[name]["max_features"]:
            raise ValueError("feature vocabulary exceeds the declared budget")
        idf = arrays[descriptor["idf_array"]]
        if idf.dtype != np.float64 or idf.shape != (len(vocabulary),):
            raise ValueError("idf dimensions or numeric type differ")
        if not np.isfinite(idf).all() or (idf < 1.0).any():
            raise ValueError("invalid learned inverse document frequency")
        model = vectorizer(FEATURES[name], vocabulary=vocabulary)
        model.idf_ = idf.copy()
        block = cls(name, model)
        if block.descriptor() != descriptor:
            raise ValueError("saved feature configuration drift")
        return block


def combine(matrices):
    if len(matrices) == 1:
        return matrices[0]
    scale = len(matrices) ** -0.5
    return sparse.hstack([m * scale for m in matrices], format="csr")


def sparse_numeric_bytes(matrix):
    return int(matrix.data.nbytes + matrix.indices.nbytes + matrix.indptr.nbytes)
