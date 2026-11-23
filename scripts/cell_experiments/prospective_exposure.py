"""Frozen exposure catalogs for previously trained candidates evaluated on new tasks."""

import hashlib
import re
from pathlib import Path
from urllib.parse import urlsplit

from . import adoption, data

# Only explicitly registered candidates acquire this intake contract.
CATALOGS = {
    "6a094252772cd5bf440ecf9b8ef0009adf6b17ec8b3f7ac44fed11d3c67ab7ba": (
        "public-historical-a-qwen2-052-20261123",
        "4f81473f1c0bac1d1ddd19ad9698d83c20fe188037ac1da27621e14f64891ae6",
    )
}


def catalog_for(candidate):
    pin = CATALOGS.get(data.digest(candidate))
    if pin is None:
        return None
    root = Path(__file__).resolve().parents[2] / "qualification" / pin[0]
    try:
        catalog = adoption.read_json(root / "prospective-exposures.json")
    except FileNotFoundError as error:
        raise ValueError("registered candidate exposure catalog is missing") from error
    adoption.require(
        data.digest(catalog) == pin[1], "registered exposure catalog differs"
    )
    return catalog


def _namespace(value, public_repository):
    """Canonicalize the pinned HF repository while preserving opaque issuer IDs."""
    text = value.strip().rstrip("/")
    name = text
    parsed = urlsplit(text)
    if parsed.scheme in ("https", "http") and parsed.hostname == "huggingface.co":
        name = parsed.path.removeprefix("/datasets/").rstrip("/")
    elif parsed.scheme == "hf" and parsed.netloc == "datasets":
        name = parsed.path.strip("/")
    return (
        public_repository if name.casefold() == public_repository.casefold() else text
    )


def _register(seen, key, message):
    adoption.require(key not in seen, message)
    seen.add(key)


def _original_id(source, field):
    if field not in source:
        return None
    value = source[field]
    adoption.require(
        isinstance(value, str)
        and 0 < len(value) <= 512
        and value.strip() == value
        and not any(ord(c) < 32 for c in value),
        "invalid optional original source identifier",
    )
    return value


def check_request(request, catalog):
    if catalog is None:
        return
    frozen = {
        key: request[key]
        for key in ("parent", "candidate", "retention", "timeout_seconds")
    }
    frozen["schema"] = "hepta.paired-cold.freeze.v1"
    adoption.require(
        data.digest(frozen) == catalog["freeze_sha256"],
        "registered pre-arrival freeze differs",
    )
    known_prompts = {row["prompt_sha256"] for row in catalog["known_inputs"]}
    known_sources = set(catalog["known_artifact_sources"])
    archived = catalog["public_origin"]
    public_repo = archived["repository"]
    seen_ids = {"original_task_id": set(), "operation_id": set()}
    seen_receipts = set()
    record_ids = {old["record_id"] for old in catalog["known_record_ids"]}
    for old in request["retention"]:
        namespace = _namespace(old["source"]["repository"], public_repo)
        seen_ids["original_task_id"].add((namespace, old["task_id"]))
    for record in request["future"]:
        auth = record["authorization"]
        adoption.require(
            auth["evaluation_allowed"] is True
            and auth["training_allowed"] is False
            and record["origin_kind"] == "authorized_agent_run"
            and record["exposure"] == "unexposed",
            "an authorized, evaluation-only, unexposed incoming agent record is required",
        )
        prompt_digest = hashlib.sha256(record["task"]["input"].encode()).hexdigest()
        adoption.require(
            prompt_digest not in known_prompts,
            "future repeats a known historical input",
        )
        _register(record_ids, record["record_id"], "repeated experiment record ID")
        source = record["source"]
        namespace = _namespace(source["repository"], public_repo)
        row = source.get("row_zero_based")
        if "row_zero_based" in source:
            adoption.require(
                type(row) is int and row >= 0, "invalid original source row"
            )
        is_archived_release = source["sha256"] == archived["parquet_sha256"] or (
            namespace == public_repo and source.get("revision") == archived["revision"]
        )
        if is_archived_release:
            adoption.require(row is not None, "original public release row required")
            adoption.require(
                row != archived["row_zero_based"], "already seen public source record"
            )
            raise ValueError("original public release predates this freeze")
        adoption.require(
            source["sha256"] not in known_sources, "already seen source material"
        )
        # v1 permits the content-bound source to identify the intake delivery itself.
        # A retained per-delivery receipt can disambiguate records referencing a common file.
        if "intake_receipt_sha256" in source:
            receipt = source["intake_receipt_sha256"]
            adoption.require(
                isinstance(receipt, str)
                and re.fullmatch(r"[a-f0-9]{64}", receipt)
                and receipt != "0" * 64,
                "invalid original intake receipt digest",
            )
            _register(
                seen_receipts, (receipt, None), "repeated original intake material"
            )
        else:
            _register(
                seen_receipts,
                (source["sha256"], row),
                "repeated original intake material",
            )
        for field, seen in seen_ids.items():
            value = _original_id(source, field)
            if value is not None:
                _register(
                    seen, (namespace, value), "repeated namespaced original identifier"
                )
