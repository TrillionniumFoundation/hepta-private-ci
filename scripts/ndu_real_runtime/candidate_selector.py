"""Paired, label-free selectors on one exact actor-visible candidate support.

The caller supplies logits from the actual frozen model. The public rule is a
fixed engineering baseline. Digests record consistency, not execution identity.
Both alternatives use the same ordered roster and original OCR features.
"""

from dataclasses import asdict
import json
import math
import re
import time

from .candidate_memory import CandidateScope
from .objective import canonical_sha


FIELDS = ("company", "date", "address", "total")
MODES = {"frozen_neural", "public_rule"}
ORIGINS = {"pixel_ocr", "registered_public_text", "no_recognized_text"}
BINDINGS = {
    "weights_sha256",
    "parameters_sha256",
    "control_profile_sha256",
    "public_case_sha256",
}
PROFILE = {
    "schema": "ndu.real.candidate-selector-profile.v1",
    "policies": ["frozen_neural_argmax", "public_field_rules_v1"],
    "feature_contract": "ocr.candidate_features.126.v1",
    "rule_coefficients": {
        "date": [8, 4, 1, -0.1],
        "total": [8, 4, 2, -3, 1, 0.1],
        "company": [4, 3, 2, -3, 1],
        "address": [4, 3, 1, 1, -2],
    },
    "tie_break": "public: canonical content; neural: first maximum",
    "max_candidates": 128,
    "max_support_bytes": 2 * 1024**2,
}
MONEY = re.compile(r"(?:RM\s*)?[-+]?\d[\d,]*\.\d{2}", re.I)
DATE = re.compile(r"\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}")


def validate_profile(value):
    """Admit only an explicit mode bound to this frozen rule implementation."""
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "mode", "profile_sha256"}
        or value["schema"] != PROFILE["schema"]
        or not isinstance(value["mode"], str)
        or value["mode"] not in MODES
        or value["profile_sha256"] != canonical_sha(PROFILE)
    ):
        raise ValueError("explicit frozen candidate selector profile required")
    return dict(value)


def _real(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _score(field, candidate, vector):
    text = candidate["text"].strip()
    lower = text.casefold()
    money, date = bool(MONEY.fullmatch(text)), bool(DATE.fullmatch(text))
    if field == "date":
        return 8 * date + 4 * vector[105] + vector[100] - 0.1 * vector[97]
    if field == "total":
        return (
            8 * money
            + 4 * vector[107]
            + 2 * vector[106]
            - 3 * vector[111]
            + vector[100]
            + 0.1 * vector[97]
        )
    company = any(word in lower for word in ("sdn", "bhd", "enterprise"))
    address = any(word in lower for word in ("jalan", "taman", "street"))
    if field == "company":
        return (
            4 * company
            + 3 * vector[108]
            + 2 * (1 - vector[97])
            - 3 * (vector[104] + vector[105])
            + vector[100]
        )
    return (
        4 * address
        + 3 * vector[109]
        + vector[102]
        + vector[100]
        - 2 * (vector[104] + vector[105])
    )


def paired_selection(
    *, mode, field, scope, candidates, features, neural_logits, bindings
):
    """Return two indices and the actual-mode index without accepting labels.

    Cost fields cover this comparison only; prior model/OCR work must still be
    paid by the caller. Caller-provided logits do not authenticate model use.
    """
    wall, cpu = time.perf_counter(), time.process_time()
    if (
        not isinstance(mode, str)
        or mode not in MODES
        or not isinstance(field, str)
        or field not in FIELDS
        or type(scope) is not CandidateScope
    ):
        raise ValueError(
            "explicit selector mode, public field and source scope required"
        )
    if (
        not isinstance(bindings, dict)
        or set(bindings) != BINDINGS
        or any(
            not isinstance(v, str) or re.fullmatch(r"[0-9a-f]{64}", v) is None
            for v in bindings.values()
        )
    ):
        raise ValueError("complete public/model bindings required")
    if (
        not isinstance(candidates, (list, tuple))
        or not isinstance(features, (list, tuple))
        or not isinstance(neural_logits, (list, tuple))
        or not 1 <= len(candidates) <= PROFILE["max_candidates"]
        or len(candidates) != len(features)
        or len(candidates) != len(neural_logits)
    ):
        raise ValueError(
            "one bounded shared roster, feature matrix and logits required"
        )
    roster, vectors, seen = [], [], set()
    for candidate, values in zip(candidates, features):
        if not isinstance(candidate, dict) or set(candidate) != {
            "text",
            "bbox",
            "origin",
        }:
            raise ValueError("only public text/bbox/origin metadata accepted")
        text, box, origin = (candidate[k] for k in ("text", "bbox", "origin"))
        if (
            not isinstance(text, str)
            or len(text.encode()) > 8192
            or not isinstance(origin, str)
            or origin not in ORIGINS
            or (not text and origin != "no_recognized_text")
            or not isinstance(box, (list, tuple))
            or len(box) != 4
            or any(type(v) is not int for v in box)
            or not 0 <= box[0] < box[2] <= scope.source_width
            or not 0 <= box[1] < box[3] <= scope.source_height
        ):
            raise ValueError("invalid original-image public candidate")
        if (
            not isinstance(values, (list, tuple))
            or len(values) != 126
            or any(not _real(v) for v in values)
            or any(not -1 <= v <= 1 for v in values[:96])
            or any(not 0 <= v <= 1 for v in values[96:])
        ):
            raise ValueError("finite bounded original 126-feature encoding required")
        if any(values[i] not in (0, 1) for i in (*range(104, 112), *range(114, 120))):
            raise ValueError("public feature flags must be exact zero/one")
        if origin == "no_recognized_text":
            if text or any(values):
                raise ValueError("empty OCR requires its original zero vector")
        elif tuple(values[116:120]) != tuple(float(field == f) for f in FIELDS):
            raise ValueError("public field differs from original feature encoding")
        row = {"text": text, "bbox": list(box), "origin": origin}
        key = canonical_sha(row)
        if key in seen:
            raise ValueError("duplicate candidate identity in shared support")
        seen.add(key)
        roster.append(row)
        vectors.append(list(map(float, values)))
    if any(not _real(v) for v in neural_logits):
        raise ValueError("actual finite frozen-model logits required")
    if (
        len(json.dumps([roster, vectors], ensure_ascii=False).encode())
        > PROFILE["max_support_bytes"]
    ):
        raise ValueError("shared support exceeds serialized byte bound")
    logits = list(map(float, neural_logits))
    scores = [_score(field, c, v) for c, v in zip(roster, vectors)]
    neural = max(range(len(roster)), key=lambda i: logits[i])
    public = min(
        range(len(roster)),
        key=lambda i: (
            -scores[i],
            roster[i]["text"].casefold(),
            tuple(roster[i]["bbox"]),
            roster[i]["origin"],
            roster[i]["text"],
        ),
    )
    shared = {
        "scope": asdict(scope),
        "field": field,
        "bindings": dict(bindings),
        "candidates": roster,
        "features": vectors,
    }
    return {
        "schema": "ndu.real.candidate-paired-selection.v1",
        "profile_sha256": canonical_sha(PROFILE),
        "support_sha256": canonical_sha(shared),
        "candidate_metadata_sha256": canonical_sha(roster),
        "candidate_features_sha256": canonical_sha(vectors),
        "neural_logits_sha256": canonical_sha(logits),
        "public_rule_scores_sha256": canonical_sha(scores),
        "scope": asdict(scope),
        "field": field,
        "bindings": dict(bindings),
        "candidate_count": len(roster),
        "mode": mode,
        "frozen_neural_index": neural,
        "public_rule_index": public,
        "selected_index": neural if mode == "frozen_neural" else public,
        "same_support_for_both": True,
        "selection_cpu_seconds": time.process_time() - cpu,
        "selection_wall_seconds": time.perf_counter() - wall,
        "upstream_model_and_ocr_cost_included": False,
        "execution_authentication_established": False,
        "scientific_acceptance": "HOLD",
    }
