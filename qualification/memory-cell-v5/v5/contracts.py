"""Small, explicit request contract and canonical evidence encoding."""

import hashlib
import json
from pathlib import Path
import re
import unicodedata


INTENTS = ("at", "previous", "change", "mean3", "range3", "peak3")
REJECT = "__reject__"
LABELS = (*INTENTS, REJECT)
REQUEST_KEYS = {"utterance", "series_name", "date"}

CONTRACT = {
    "at": "recorded numeric value at t",
    "previous": "recorded numeric value at t-1 calendar month",
    "change": "recorded value at t minus recorded value at t-1",
    "mean3": "arithmetic mean over [t-2,t-1,t] calendar months",
    "range3": "maximum minus minimum over [t-2,t-1,t] calendar months",
    "peak3": "maximum numeric value over [t-2,t-1,t] calendar months",
    REJECT: "all other requested operations, outputs, windows, alignments, or compound tasks",
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path = Path(path)
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")
    return file_identity(path)


def file_identity(path):
    raw = Path(path).read_bytes()
    return {"bytes": len(raw), "sha256": sha256(raw)}


def normalized_request(request):
    """Replace only supplied identity slots; never inspect an intent lexicon."""
    if not isinstance(request, dict) or set(request) != REQUEST_KEYS:
        raise ValueError("serving requests must have exactly utterance, series_name, date")
    if any(not isinstance(request[key], str) or not request[key].strip() for key in REQUEST_KEYS):
        raise ValueError("serving fields must be nonempty strings")
    if len(request["utterance"]) > 4096 or len(request["series_name"]) > 256:
        raise ValueError("request exceeds the declared length limit")
    if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", request["date"]):
        raise ValueError("date must be YYYY-MM")
    text = unicodedata.normalize("NFKC", request["utterance"]).casefold()
    series = unicodedata.normalize("NFKC", request["series_name"]).casefold()
    text = text.replace(series, " [series] ")
    text = text.replace(request["date"], " [date] ")
    return " ".join(text.split())


def unlabeled(row):
    return {key: row[key] for key in sorted(REQUEST_KEYS)}
