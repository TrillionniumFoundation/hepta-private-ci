"""Train-only sparse encoders; serving uses the separate stdlib runner."""

import numpy as np
from scipy import sparse
from sklearn.feature_extraction import DictVectorizer
from sklearn.feature_extraction.text import TfidfVectorizer

from semantic_cues import concept_features, concepts, deterministic_label


class Encoder:
    """Train-only vocabularies; bounded 2048 word ngrams plus concept pairs."""

    def __init__(self, mode):
        self.mode = mode
        self.word = None
        self.semantic = None

    def fit(self, texts):
        if self.mode in ("word", "combined"):
            self.word = TfidfVectorizer(ngram_range=(1, 3), max_features=2048,
                sublinear_tf=True, token_pattern=r"(?u)\b\w+\b|[%+\-/]",
                lowercase=False, dtype=np.float64)
            self.word.fit(texts)
        if self.mode in ("semantic", "combined"):
            self.semantic = DictVectorizer(sparse=True, dtype=np.float64)
            self.semantic.fit([concept_features(text) for text in texts])
        return self

    def transform(self, texts):
        blocks = []
        if self.word:
            blocks.append(self.word.transform(texts).tocsr())
        if self.semantic:
            blocks.append(self.semantic.transform([concept_features(text) for text in texts]).tocsr())
        return sparse.hstack(blocks, format="csr") if len(blocks) > 1 else blocks[0]

    def descriptor(self):
        return {"mode": self.mode,
            "word_vocabulary": {key: int(value) for key, value in self.word.vocabulary_.items()} if self.word else None,
            "word_idf": self.word.idf_.tolist() if self.word else None,
            "semantic_vocabulary": {key: int(value) for key, value in self.semantic.vocabulary_.items()} if self.semantic else None}

    @classmethod
    def restore(cls, value):
        instance = cls(value["mode"])
        if value["word_vocabulary"] is not None:
            instance.word = TfidfVectorizer(ngram_range=(1, 3), max_features=2048,
                sublinear_tf=True, token_pattern=r"(?u)\b\w+\b|[%+\-/]",
                lowercase=False, dtype=np.float64, vocabulary=value["word_vocabulary"])
            instance.word.idf_ = np.asarray(value["word_idf"], dtype=np.float64)
        if value["semantic_vocabulary"] is not None:
            instance.semantic = DictVectorizer(sparse=True, dtype=np.float64)
            instance.semantic.vocabulary_ = value["semantic_vocabulary"]
            instance.semantic.feature_names_ = [name for name, _ in sorted(value["semantic_vocabulary"].items(), key=lambda item: item[1])]
        return instance

