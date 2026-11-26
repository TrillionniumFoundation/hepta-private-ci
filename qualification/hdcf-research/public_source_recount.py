"""Independent historical BANKING77 label-source and ModernBERT prediction recount.

Consumes the ORIGINAL publisher CSV bytes and the original source-locked Actions ZIP.
Never runs a model, selects a new model, grants a capability, or claims independent
future/out-of-publisher generalization. Separate from the prospective HDCF producer.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import stat
from pathlib import Path
import unicodedata
import zipfile

from original_canary_audit import ARMS, ROOT, Denied, _json, audit_bytes, EXPECTED_ZIP_SHA256
from physical_cli import write_once

SOURCE_REVISION = "57ec275d8078af65b7731c2a98be812d844a6d6b"
SOURCE_SHA256 = {
    "train": "b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b",
    "test": "d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d",
}
INTENTS = (
    "card_arrival", "cash_withdrawal_not_recognised", "exchange_rate", "lost_or_stolen_phone",
)
SELECTION_DOMAIN = "hepta-banking77-subset-v1\0"
MAX_CSV_BYTES = 2_000_000


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def parse_source(raw: bytes) -> dict[str, dict[str, str]]:
    """Independent CSV parser matching the source author's normalization rules."""
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_CSV_BYTES:
        raise Denied("bounded original CSV required")
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise Denied("invalid source UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    if reader.fieldnames != ["text", "category"]:
        raise Denied("unexpected source columns")
    result: dict[str, dict[str, str]] = {}
    try:
        for ix, row in enumerate(reader):
            if (ix >= 20_000 or type(row) is not dict
                    or set(row) != {"text", "category"}
                    or any(type(v) is not str or not v for v in row.values())):
                raise Denied("invalid source row or row bound")
            string, category = row["text"], row["category"]
            if len(string.encode("utf-8")) > 4096 or not normalize(string):
                raise Denied("invalid utterance")
            key = normalize(string)
            if key in result:
                if result[key]["category"] != category:
                    raise Denied("conflicting source labels")
                string = min(string, result[key]["text"])
            result[key] = {"text": string, "category": category}
    except (csv.Error, UnicodeError, ValueError) as exc:
        if isinstance(exc, Denied):
            raise
        raise Denied("invalid CSV encoding or syntax") from exc
    return result


def reconstruct(train_raw: bytes, test_raw: bytes) -> dict:
    for scope, data in (("train", train_raw), ("test", test_raw)):
        if sha256(data) != SOURCE_SHA256[scope]:
            raise Denied(f"original {scope} CSV bytes differ from fixed source")
    train = parse_source(train_raw)
    test = parse_source(test_raw)
    cases: dict[str, list[dict]] = {"fit": [], "heldout": []}
    for split, pool, wanted in (("fit", train, 16), ("heldout", test, 8)):
        for label, category in enumerate(INTENTS):
            candidates = [key for key, row in pool.items()
                          if row["category"] == category and (split == "fit" or key not in train)]
            candidates.sort(key=lambda key: sha256((SELECTION_DOMAIN + key).encode("utf-8")))
            if len(candidates) < wanted:
                raise Denied("insufficient original source rows; no denominator shrink")
            for key in candidates[:wanted]:
                cases[split].append({
                    "id": ("fit:" if split == "fit" else "heldout:") + sha256(key.encode("utf-8")),
                    "label": label,
                })
    if len(cases["fit"]) != 64 or len(cases["heldout"]) != 32:
        raise Denied("unexpected source population")
    all_ids = [r["id"] for rows in cases.values() for r in rows]
    if len(set(all_ids)) != 96:
        raise Denied("selected original case ID repeated")
    return cases


def score_logits(predictions: list[dict], held: list[dict], key: str) -> dict:
    if type(predictions) is not list or len(predictions) != len(held) or len(held) != 32:
        raise Denied("incomplete original prediction census")
    nll = []
    brier = []
    correct = []
    for row, target in zip(predictions, held, strict=True):
        if type(row) is not dict or set(row) != {"id", "before_logits", "after_logits"}:
            raise Denied("invalid original prediction shape")
        if row["id"] != target["id"]:
            raise Denied("prediction/source selection mismatch")
        values = row.get(key)
        if (type(values) is not list or len(values) != 4
                or any(type(x) not in (int, float) or not math.isfinite(x) for x in values)):
            raise Denied("bad original logits")
        label = target["label"]
        pivot = max(values)
        weights = [math.exp(x-pivot) for x in values]
        denominator = sum(weights)
        correct.append(int(max(range(4), key=values.__getitem__) == label))
        nll.append(math.log(denominator) + pivot - values[label])
        brier.append(sum((v/denominator - int(ix == label))**2
                         for ix, v in enumerate(weights)))
    return {
        "count": 32,
        "correct": sum(correct),
        "accuracy": sum(correct)/32,
        "mean_nll": sum(nll)/32,
        "brier": sum(brier)/32,
        "per_class_accuracy": {name: sum(correct[ix] for ix in range(8*label, 8*(label+1)))/8
                               for label, name in enumerate(INTENTS)},
    }


def _agree(computed: dict, archived: dict) -> None:
    expected = {"count", "accuracy", "mean_nll", "brier", "per_class_accuracy"}
    if type(archived) is not dict or set(archived) != expected or archived["count"] != 32:
        raise Denied("archived scoring metric shape changed")
    for field in ("accuracy", "mean_nll", "brier"):
        value = archived[field]
        if type(value) not in (int, float) or not math.isfinite(value):
            raise Denied("bad archived metric")
        if not math.isclose(computed[field], value, rel_tol=0, abs_tol=1e-12):
            raise Denied("independent prediction/label score disagrees with original report")
    if type(archived["per_class_accuracy"]) is not dict or set(archived["per_class_accuracy"]) != set(INTENTS):
        raise Denied("incomplete class metrics")
    for cat in INTENTS:
        v = archived["per_class_accuracy"][cat]
        if type(v) not in (int, float) or not math.isfinite(v):
            raise Denied("bad per-class score")
        if not math.isclose(computed["per_class_accuracy"][cat], v, abs_tol=1e-12, rel_tol=0):
            raise Denied("original per-class outcome mismatch")


def recount(train_raw: bytes, test_raw: bytes, archive: bytes) -> dict:
    """Reconstruct labels independently from SHA-fixed publisher source and score raw logits."""
    audit = audit_bytes(archive, expected_sha256=EXPECTED_ZIP_SHA256)
    cases = reconstruct(train_raw, test_raw)
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        scores = _json(z.read(ROOT + "scores.json"))
        selection = _json(z.read(ROOT + "selection.json"))
        original = {}
        for arm in ARMS:
            original[arm] = _json(z.read(ROOT + f"trial/{arm}/predictions.json"))
    if (selection["raw_sha256"] != SOURCE_SHA256 or
            selection["selected_ids"] != {s: [r["id"] for r in cases[s]] for s in cases}):
        raise Denied("selection census not identical to independently reconstructed source")
    per_arm = {}
    for arm in ARMS:
        values = {}
        for phase in ("before", "after"):
            computed = score_logits(original[arm], cases["heldout"], f"{phase}_logits")
            _agree(computed, scores["scores"][arm][phase])
            values[phase] = computed
        per_arm[arm] = values
    return {
        "schema": "hepta.hdcf.original-public-source-independent-recount.v1",
        "archive_id": 11877613315,
        "archive_sha256": EXPECTED_ZIP_SHA256,
        "original_model_snapshot_sha256": audit["model_snapshot_sha256"],
        "original_source_revision": SOURCE_REVISION,
        "original_source_csv_sha256": dict(SOURCE_SHA256),
        "original_source_selected_case_ids_rebuilt": 96,
        "original_source_independently_parsed_and_hashed": True,
        "original_historical_scores_recomputed_from_original_logits": True,
        "original_training_csv_consumed_for_selection": True,
        "new_pretrained_encoder_forwards": 0,
        "retrospective_same_public_dataset": True,
        "future_source_independence_verified": False,
        "full_end_to_end_cost_verified": False,
        "new_hdcf_head_efficacy_verified": False,
        "production_authorized": False,
        "external_effect_authorized": False,
        "arms": per_arm,
    }


def _read_file(path: str, cap: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        stat_before = os.fstat(stream.fileno())
        if not stat.S_ISREG(stat_before.st_mode) or not 0 < stat_before.st_size <= cap:
            raise Denied("missing or unsafe source file")
        data = stream.read(cap + 1)
        stat_after = os.fstat(stream.fileno())
        if (len(data) > cap or len(data) != stat_before.st_size
                or stat_after.st_ino != stat_before.st_ino
                or stat_after.st_size != stat_before.st_size):
            raise Denied("source changed during read")
    return data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--train", required=True)
    ap.add_argument("--test", required=True)
    ap.add_argument("--archive", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    try:
        result = recount(_read_file(args.train, MAX_CSV_BYTES),
                         _read_file(args.test, MAX_CSV_BYTES),
                         _read_file(args.archive, 15_000_000))
        write_once(args.out, result)
    except (Denied, OSError, UnicodeError) as exc:
        ap.exit(2, f"DENY_ALL: {type(exc).__name__}: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
