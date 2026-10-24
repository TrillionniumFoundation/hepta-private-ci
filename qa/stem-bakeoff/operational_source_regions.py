"""Source-only operational regions and bounded readouts of retained window vectors.

Selectors never receive labels, repository IDs, revision roles or observations.
Pooling localizes the weights, not the already contextualized window vectors.
"""

from dataclasses import dataclass
import keyword
from pathlib import Path
import re

import numpy as np

from long_document_sources import canonical, sha


REGRESSION_PREFIX = ("Predict whether the regression command passes on this implementation.\n"
    "Context: the supplied candidate-change region; external dependencies are not fully shown.\n")
CHOICE_PREFIX = ("Choose the diagnostic test that distinguishes the two implementations.\n"
    "A supplied candidate change and two real test actions follow.\nCHANGE\n")
ACTION_PREFIX = "Predict whether this test distinguishes the two supplied implementations.\nCHANGE\n"
MAX_BYTES, MAX_SPANS, MAX_CHUNKS, MAX_WIDTH = 128 * 1024, 4096, 512, 2048
SELECTOR = {"schema": "hepta.operational-source-regions.v1",
    "change": "only +/- source lines inside supplied unified-diff hunks; strip the diff marker",
    "implementation": "supplied implementation body, excluding IMPLEMENTATION path header lines",
    "test": "supplied TEST SOURCE and FIXTURE bodies, excluding their path header lines",
    "pooling": "source-character inverse-window-overlap weights; FP64 weighted mean/L2 then FP32",
    "identifiers": "case-sensitive ASCII Python-shaped names of length 1..64; exclude Python keywords",
    "missing": "unavailable; no zero-filled usable examples", "max_source_bytes": MAX_BYTES,
    "max_spans": MAX_SPANS, "max_chunks": MAX_CHUNKS, "max_width": MAX_WIDTH,
    "boundary_scope": "selected windows retain adjacent unselected text and original position"}


@dataclass(frozen=True)
class SourceRegions:
    family: str
    source_sha256: str
    fields: tuple

    def spans(self, name):
        return dict(self.fields)[name]

    def receipt(self, text):
        if sha(text.encode()) != self.source_sha256:
            raise ValueError("region source changed")
        return {"family": self.family, "source_sha256": self.source_sha256,
            "fields": {name: [{"char_span": [a, b],
                "utf8_span": [len(text[:a].encode()), len(text[:b].encode())],
                "sha256": sha(text[a:b].encode())} for a, b in spans]
                for name, spans in self.fields}}


def _lines(text, start, end):
    cursor = start
    for line in text[start:end].splitlines(keepends=True):
        yield cursor, cursor + len(line), line
        cursor += len(line)


def _body(text, start, end, first):
    if not text[start:end].startswith(first + " "):
        raise ValueError("missing supplied source body")
    spans = []
    for a, b, line in _lines(text, start, end):
        if line.startswith(("IMPLEMENTATION ", "TEST SOURCE ", "FIXTURE ")):
            continue
        if line.startswith(("COMMAND ", "ACTION ")) or line.rstrip("\n") == "CHANGE":
            raise ValueError("ambiguous structural marker inside source body")
        if line.strip():
            spans.append((a, b))
    return tuple(spans)


def _change(text, start, end):
    if not text[start:end].startswith("diff --git "):
        raise ValueError("supplied unified diff is missing")
    spans, in_hunk = [], False
    for a, b, line in _lines(text, start, end):
        if line.startswith("diff --git "):
            in_hunk = False
        elif re.match(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@", line):
            in_hunk = True
        elif in_hunk and line[0] in "+-" and line[1:].strip():
            spans.append((a + 1, b))
    return tuple(spans)


def _action(text, start, end):
    stop = text.find("\n", start, end)
    if stop < 0 or not text[start:stop].startswith("COMMAND ") or stop == start + 8:
        raise ValueError("supplied action command is missing")
    return _body(text, stop + 1, end, "TEST SOURCE")


def parse_regions(text, input_regions=None):
    if type(text) is not str or not 0 < len(text.encode()) <= MAX_BYTES:
        raise ValueError("bounded complete UTF8 predictor required")
    if text.startswith(REGRESSION_PREFIX):
        begin = len(REGRESSION_PREFIX)
        command_end = text.find("\n", begin)
        marker = "\nTEST SOURCE "
        if not text[begin:command_end].startswith("COMMAND ") or text.count(marker) < 1:
            raise ValueError("regression command/test source missing")
        boundary = text.index(marker)
        fields = (("implementation", _body(text, command_end + 1, boundary, "IMPLEMENTATION")),
                  ("test", _body(text, boundary + 1, len(text), "TEST SOURCE")))
        family = "regression"
    elif text.startswith(CHOICE_PREFIX):
        markers = ("\nACTION 0\n", "\nACTION 1\n")
        if any(text.count(marker) != 1 for marker in markers):
            raise ValueError("exactly two unambiguous ordered supplied actions required")
        a, b = (text.index(marker) for marker in markers)
        if a >= b:
            raise ValueError("supplied action order differs")
        fields = (("change", _change(text, len(CHOICE_PREFIX), a)),
            ("action0", _action(text, a + len(markers[0]), b)),
            ("action1", _action(text, b + len(markers[1]), len(text))))
        family = "diagnostic_choice"
    elif text.startswith(ACTION_PREFIX):
        marker = "\nACTION\n"
        if input_regions is None:
            if text.count(marker) != 1:
                raise ValueError("one unambiguous supplied action required")
            a = text.index(marker)
            fields = (("change", _change(text, len(ACTION_PREFIX), a)),
                      ("test", _action(text, a + len(marker), len(text))))
        else:
            if type(input_regions) is not dict or set(input_regions) != {"change", "action"}:
                raise ValueError("exact explicit change/action source spans required")
            spans = [input_regions[name] for name in ("change", "action")]
            if any(type(pair) not in (tuple, list) or len(pair) != 2
                   or any(type(v) is not int for v in pair) for pair in spans):
                raise ValueError("explicit source spans must be integer pairs")
            (a, b), (c, d) = spans
            if (a != len(ACTION_PREFIX) or not a < b < c < d == len(text)
                    or not text[b:c].startswith(marker + "COMMAND ")
                    or text[b:c].count("\n") != 3 or not text[b:c].endswith("\n")):
                raise ValueError("explicit spans differ from the supplied input template")
            fields = (("change", _change(text, a, b)), ("test", _body(text, c, d, "TEST SOURCE")))
        family = "diagnostic_action"
    else:
        raise ValueError("unknown pre-execution input template")
    if any(not spans or len(spans) > MAX_SPANS for _, spans in fields):
        raise ValueError("empty or over-budget region is unavailable")
    if input_regions is not None and family != "diagnostic_action":
        raise ValueError("explicit source fields are defined only for the single-action template")
    return SourceRegions(family, sha(text.encode()), fields)


def identifiers(text, spans):
    words = set(re.findall(r"(?<![A-Za-z_0-9])[A-Za-z_][A-Za-z_0-9]{0,63}(?![A-Za-z_0-9])",
                           "\n".join(text[a:b] for a, b in spans)))
    return words.difference(keyword.kwlist, keyword.softkwlist)


def jaccard(left, right):
    return len(left & right) / len(left | right) if left or right else 0.0


def pool_region(text, spans, document, vectors):
    records = document["chunks"]
    if (document["source_utf8_sha256"] != sha(text.encode())
            or document["source_characters"] != len(text)
            or not 0 < len(text.encode()) <= MAX_BYTES or not 1 <= len(records) <= MAX_CHUNKS
            or vectors.dtype != np.float32 or vectors.ndim != 2
            or vectors.shape[0] != len(records) or not 1 <= vectors.shape[1] <= MAX_WIDTH
            or not np.isfinite(vectors).all() or not 1 <= len(spans) <= MAX_SPANS):
        raise ValueError("bounded source-bound native chunk vectors required")
    selected = np.zeros(len(text), np.bool_)
    coverage = np.zeros(len(text), np.int32)
    last = 0
    for a, b in spans:
        if type(a) is not int or type(b) is not int or not last <= a < b <= len(text):
            raise ValueError("ordered nonoverlapping source intervals required")
        selected[a:b], last = True, b
    for chunk in records:
        a, b = chunk["char_span"]
        if type(a) is not int or type(b) is not int or not 0 <= a < b <= len(text):
            raise ValueError("invalid retained chunk character interval")
        coverage[a:b] += 1
    if not selected.any() or np.any(coverage[selected] == 0):
        raise ValueError("selected source character coverage is incomplete")
    mass = np.zeros(len(text), np.float64)
    mass[selected] = 1.0 / coverage[selected]
    prefix = np.concatenate(([0.0], np.cumsum(mass)))
    weights = np.asarray([prefix[b] - prefix[a] for a, b in (c["char_span"] for c in records)])
    pooled = weights @ vectors.astype(np.float64) / weights.sum()
    norm = np.linalg.norm(pooled)
    if not np.isfinite(norm) or norm <= 1e-12:
        raise ValueError("zero or unstable region pool is unavailable")
    value = np.frombuffer((pooled / norm).astype(np.float32).tobytes(), np.float32)
    union = np.zeros(len(text), np.bool_)
    for i in np.flatnonzero(weights > 0):
        a, b = records[i]["char_span"]
        union[a:b] = True
    receipt = {"selected_characters": int(selected.sum()), "selected_chunks": int((weights > 0).sum()),
        "chunk_weights": weights.tolist(), "selected_window_union_characters": int(union.sum()),
        "unselected_context_characters_in_windows": int((union & ~selected).sum()),
        "character_weight_sum": float(weights.sum()), "pool_sha256": sha(value.tobytes()),
        "largest_numpy_work_array_bytes": max(prefix.nbytes, vectors.size * 8)}
    return value, receipt


def readout_features(regions, pools, text):
    if regions.source_sha256 != sha(text.encode()) or set(pools) != dict(regions.fields).keys():
        raise ValueError("readout source/field binding differs")
    ids = {name: identifiers(text, spans) for name, spans in regions.fields}
    if regions.family == "regression":
        value = np.concatenate([pools["implementation"], pools["test"]])
    else:
        c = pools["change"].astype(np.float64)
        if regions.family == "diagnostic_choice":
            a, b = pools["action0"].astype(np.float64), pools["action1"].astype(np.float64)
            value = np.r_[c * (b - a), np.dot(c, b) - np.dot(c, a),
                jaccard(ids["change"], ids["action1"]) - jaccard(ids["change"], ids["action0"])]
        else:
            a = pools["test"].astype(np.float64)
            value = np.r_[c * a, np.abs(c - a), np.dot(c, a), jaccard(ids["change"], ids["test"])]
    return np.frombuffer(np.asarray(value, np.float32).tobytes(), np.float32)


def feature_definition(parent_identity, width, family):
    if (re.fullmatch(r"[0-9a-f]{64}", parent_identity) is None or type(width) is not int
            or not 1 <= width <= MAX_WIDTH or family not in ("regression", "diagnostic_choice", "diagnostic_action")):
        raise ValueError("pinned parent feature identity and bounded readout required")
    definition = {"selector": SELECTOR, "parent_feature_identity": parent_identity, "width": width,
        "family": family, "readout": {"regression": "concat(implementation,test)",
            "diagnostic_choice": "concat(c*(a1-a0),dot(c,a1)-dot(c,a0),identifier_Jaccard1-Jaccard0)",
            "diagnostic_action": "concat(c*a,abs(c-a),dot(c,a),identifier_Jaccard)"}[family],
        "source_code_sha256": sha(Path(__file__).read_bytes())}
    return definition, sha(canonical(definition))
