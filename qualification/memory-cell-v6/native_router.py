"""Standard-library inference for frozen compact Cell address parameters.

The model is trained by sklearn; this process imports no numpy, scipy or
sklearn. It is a Python reference executor, not a Rust/native-agent integration.
"""

import argparse
import base64
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time
import zlib

from semantic_cues import concept_features, deterministic_label

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "memory-cell-v5"))
from v5.contracts import INTENTS, LABELS, REJECT, normalized_request

TOKENS = re.compile(r"(?u)\b\w+\b|[%+\-/]")


class FrozenRouter:
    def __init__(self, path, expected_sha256):
        path = Path(path)
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("model exceeds 2 MiB")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise ValueError("model hash differs from frozen artifact")
        envelope = json.loads(raw)
        size = envelope["decoded_bytes"]
        if envelope["encoding"] != "zlib-base64" or type(size) is not int or not 0 < size <= 8 * 1024 * 1024:
            raise ValueError("invalid or excessive envelope")
        decoder = zlib.decompressobj()
        data = decoder.decompress(base64.b64decode(envelope["payload"], validate=True), size + 1)
        if len(data) != size or not decoder.eof or decoder.unused_data or hashlib.sha256(data).hexdigest() != envelope["decoded_sha256"]:
            raise ValueError("invalid model payload identity")
        state = json.loads(data)
        if state["schema"] != "hepta.compact-cell-router.v1" or state["labels"] != list(LABELS):
            raise ValueError("unsupported model contract")
        self.encoder = state["encoder"]
        self.weights = state["coefficients"]
        self.bias = state["intercept"]
        self.calibration = state["calibration"]
        self.identity = state["identity"]
        if self.encoder["mode"] not in ("word", "semantic", "combined"):
            raise ValueError("invalid encoder mode")
        dimensions = 0
        for key in ("word_vocabulary", "semantic_vocabulary"):
            vocabulary = self.encoder[key]
            if vocabulary is not None:
                if not isinstance(vocabulary, dict) or not vocabulary or len(vocabulary) > 4096 or any(not isinstance(k, str) or type(v) is not int for k, v in vocabulary.items()) or sorted(vocabulary.values()) != list(range(len(vocabulary))):
                    raise ValueError("invalid encoder vocabulary")
                dimensions += len(vocabulary)
        if dimensions > 4096 or dimensions == 0 or len(self.weights) != len(LABELS) or any(len(row) != dimensions for row in self.weights) or len(self.bias) != len(LABELS):
            raise ValueError("invalid model dimensions")
        if any(type(x) not in (int, float) or not math.isfinite(x) for row in [*self.weights, self.bias] for x in row):
            raise ValueError("nonfinite or invalid model number")
        idf = self.encoder["word_idf"]
        if idf is not None and (len(idf) != len(self.encoder["word_vocabulary"]) or any(not math.isfinite(x) or x < 1 for x in idf)):
            raise ValueError("invalid learned IDF")
        for key in ("minimum_confidence", "minimum_margin"):
            if not 0 <= self.calibration[key] <= 1:
                raise ValueError("invalid threshold")
        if type(self.calibration["reject_all"]) is not bool:
            raise ValueError("invalid reject-all flag")

    def features(self, request):
        text = normalized_request(request)
        output = {}
        word = self.encoder["word_vocabulary"]
        offset = 0
        if word is not None:
            tokens = TOKENS.findall(text)
            counts = Counter(" ".join(tokens[i:i + n]) for n in (1, 2, 3) for i in range(len(tokens) - n + 1))
            idf = self.encoder["word_idf"]
            output = {word[token]: (1 + math.log(count)) * idf[word[token]] for token, count in counts.items() if token in word}
            length = math.sqrt(math.fsum(value * value for value in output.values()))
            if length:
                output = {index: value / length for index, value in output.items()}
            offset = len(word)
        semantic = self.encoder["semantic_vocabulary"]
        if semantic is not None:
            output.update({offset + semantic[name]: value for name, value in concept_features(text).items() if name in semantic})
        return sorted(output.items())

    def linear_scores(self, features, groups=None):
        # Splitting these rows into local Cells changes scheduling, not weights
        # or the number of scalar products. Used by the structural control.
        groups = groups or (tuple(range(len(LABELS))),)
        scores = [None] * len(LABELS)
        for group in groups:
            for index in group:
                if type(index) is not int or not 0 <= index < len(LABELS) or scores[index] is not None:
                    raise ValueError("Cell ownership must partition the label heads")
                scores[index] = math.fsum(self.weights[index][column] * value for column, value in features) + self.bias[index]
        if any(score is None for score in scores):
            raise ValueError("Cell topology omitted a label head")
        return scores

    def decide(self, request, groups=None):
        scores = self.linear_scores(self.features(request), groups)
        values = [math.exp(score - max(scores)) for score in scores]
        total = math.fsum(values)
        normalized = [value / total for value in values]
        order = sorted(range(len(LABELS)), key=lambda i: -normalized[i])
        top, second = order[:2]
        confidence, margin = normalized[top], normalized[top] - normalized[second]
        raw = LABELS[top]
        accepted = raw != REJECT and not self.calibration["reject_all"] and confidence >= self.calibration["minimum_confidence"] and margin >= self.calibration["minimum_margin"]
        return {"raw_label": raw, "accepted_intent": raw if accepted else None,
            "accepted": accepted, "confidence": confidence, "margin": margin,
            "normalized_scores": normalized, "linear_scores": scores,
            "reason": "accepted" if accepted else "learned-reject-class" if raw == REJECT else "selection-calibrated-abstention"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--model", type=Path)
    mode.add_argument("--deterministic", action="store_true")
    parser.add_argument("--sha256")
    args = parser.parse_args()
    router = None
    if args.model:
        if not args.sha256:
            parser.error("--sha256 is required for a frozen model")
        router = FrozenRouter(args.model, args.sha256)
    # Bound input before JSON parsing; after one oversized line, stop rather
    # than accidentally treating its remaining bytes as a second request.
    while line := sys.stdin.buffer.readline(32769):
        tick = time.perf_counter_ns()
        try:
            if len(line) > 32768:
                raise ValueError("request exceeds 32 KiB")
            request = json.loads(line)
            if router:
                decision = router.decide(request)
            else:
                label = deterministic_label(normalized_request(request))
                decision = {"raw_label": label, "accepted_intent": label if label in INTENTS else None,
                    "accepted": label in INTENTS, "confidence": 1.0, "margin": 1.0,
                    "reason": "hand-authored contract parser, confidence is an indicator"}
            decision["inference_ns"] = time.perf_counter_ns() - tick
            decision["contract"] = "memory-cell-v5.six-operations"
            print(json.dumps(decision, sort_keys=True), flush=True)
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            print(json.dumps({"error": type(exc).__name__, "message": str(exc), "accepted": False, "accepted_intent": None}), flush=True)
            if len(line) > 32768:
                break


if __name__ == "__main__":
    main()
