"""Check human Reader verdicts against original question/prompt/answer/source bytes.

This checks deterministic provenance, NOT review independence or semantic truth.
The caller must separately pin the digest of this externally supplied manifest.
No artificial negative labels are generated for absent or failed evidence.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

from reader_review_ledger import CONDITIONS

SCHEMA = "hepta.reader.originals.v1"
QUESTION_KEYS = frozenset(("identity", "family", "scope", "content", "observed_at"))
SOURCE_KEYS = frozenset(("identity", "root", "scope", "session", "observed_at",
                         "content", "start", "end"))
CASE_KEYS = frozenset(("item_id", "condition", "question_record", "input_ids",
                       "raw_answer", "delivered_sources"))
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_CASE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_ANSWER_BYTES = 16 * 1024
MAX_PROMPT_IDS = 8192
MAX_ATTESTATION_FILE_BYTES = 96 * 1024 * 1024
CITE = re.compile(r"\[E([0-9]+)\]", re.I)


def canonical_sha(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False).encode("utf-8")).hexdigest()


def load_strict_json_file(path, *, expected_file_sha256=None,
                          require_pin=False, max_bytes=MAX_ATTESTATION_FILE_BYTES):
    """Read one bounded ORIGINAL JSON file, rejecting duplicate keys and byte drift.

    A hash of parsed JSON is NOT an external file-byte pin: different input
    bytes (including ignored duplicate keys) can parse to the same object.
    Mandatory raw-byte pins must be operator supplied, never embedded in the
    JSON being read. This parser does NOT authenticate owners or reviewers.
    """
    if (type(max_bytes) is not int or
            not 1 <= max_bytes <= MAX_ATTESTATION_FILE_BYTES):
        raise ValueError("invalid original JSON file budget")
    if (require_pin and (type(expected_file_sha256) is not str or
            re.fullmatch(r"[0-9a-f]{64}", expected_file_sha256) is None)):
        raise ValueError("out-of-band-original-file-pin-required")
    if (expected_file_sha256 is not None and
            (type(expected_file_sha256) is not str or
             re.fullmatch(r"[0-9a-f]{64}", expected_file_sha256) is None)):
        raise ValueError("invalid raw-file SHA256 pin")
    file = Path(path)
    if file.is_symlink() or any(parent.is_symlink() for parent in file.parents):
        raise ValueError("symlink in reviewed JSON file path")
    if not file.is_file():
        raise ValueError("reviewed JSON must be a regular file")
    with file.open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    if not raw or len(raw) > max_bytes:
        raise ValueError("reviewed JSON file byte limit")
    if (expected_file_sha256 is not None and
            hashlib.sha256(raw).hexdigest() != expected_file_sha256):
        raise ValueError("original JSON raw-file SHA256 mismatch")

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key in reviewed input")
            result[key] = value
        return result

    def nonfinite(_):
        raise ValueError("nonfinite JSON constant in reviewed input")

    try:
        result = json.loads(raw.decode("utf-8", "strict"),
                            object_pairs_hook=unique_pairs,
                            parse_constant=nonfinite)
    except (UnicodeError, ValueError) as error:
        raise ValueError("malformed or ambiguous reviewed JSON") from error
    if type(result) is not dict:
        raise ValueError("reviewed JSON root must be an object")
    return result


def source_fingerprint(source):
    """Bind ORIGINAL source ID/ACL/time/full content and exact UTF-8 byte window.

    The resulting fingerprint uses the EvidenceSpan field names, matching the
    original Reader's byte-window provenance rather than only the excerpt text.
    """
    if type(source) is not dict or set(source) != SOURCE_KEYS:
        raise ValueError("unregistered source record")
    for key in SOURCE_KEYS - {"start", "end"}:
        if type(source[key]) is not str or not source[key]:
            raise ValueError("missing source original or owner")
    raw = source["content"].encode("utf-8", "strict")
    start, end = source["start"], source["end"]
    if (type(start) is not int or type(end) is not int
            or not 0 <= start < end <= len(raw) <= MAX_SOURCE_BYTES):
        raise ValueError("invalid original UTF-8 byte span")
    excerpt = raw[start:end].decode("utf-8", "strict")
    if not excerpt.strip():
        raise ValueError("empty evidence span")
    return canonical_sha(dict(
        source_id=source["identity"], root=source["root"], scope=source["scope"],
        session=source["session"], observed_at=source["observed_at"],
        start=start, end=end, excerpt=excerpt,
        source_digest=canonical_sha(source["content"]),
    ))


def _datetime(value):
    """Require explicitly offset-aware ISO timestamps for new reviewed evidence."""
    if type(value) is not str or len(value) > 128:
        raise ValueError("invalid source time")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("unbound source time zone")
    return stamp


def audit_originals(cohort, model_binding, reviewed_items, originals):
    """Return a stable failure reason, or None for exact raw-source concordance.

    A valid source manifest MUST also be authenticated by an out-of-band pin;
    this function alone never admits experiments or judges an answer correct.
    """
    if (type(originals) is not dict or set(originals) !=
            {"schema", "cohort", "model_binding", "items"}
            or originals["schema"] != SCHEMA
            or originals["cohort"] != cohort
            or originals["model_binding"] != model_binding):
        return "original-source-manifest-schema-or-binding-mismatch"
    if (type(cohort) is not list or not cohort or any(type(q) is not str or not q for q in cohort)
            or len(set(cohort)) != len(cohort)
            or type(reviewed_items) is not list or type(originals["items"]) is not list
            or len(originals["items"]) != len(cohort) * len(CONDITIONS)
            or len(reviewed_items) != len(originals["items"])):
        return "original-source-manifest-incomplete"
    expected = {(qid, arm) for qid in cohort for arm in CONDITIONS}
    original_by_key = {}
    # Stable source identity cannot silently change owner, version, timestamp
    # or original bytes between the four experimental conditions. Different
    # UTF-8 excerpt windows over the SAME immutable original remain valid.
    source_origins = {}
    try:
        size = 0
        for row in originals["items"]:
            if type(row) is not dict or set(row) != CASE_KEYS:
                return "original-case-schema-invalid"
            qid, condition = row["item_id"], row["condition"]
            key = (qid, condition)
            if (type(qid) is not str or type(condition) is not str or
                    key not in expected or key in original_by_key):
                return "original-case-identity-incomplete-or-duplicate"
            question = row["question_record"]
            if (type(question) is not dict or set(question) != QUESTION_KEYS
                    or question["identity"] != qid or
                    any(type(question[k]) is not str or not question[k] for k in QUESTION_KEYS)):
                return "original-question-byte-identity-invalid"
            timestamp = _datetime(question["observed_at"])
            input_ids = row["input_ids"]
            if (type(input_ids) is not list or not 1 <= len(input_ids) <= MAX_PROMPT_IDS
                    or any(type(t) is not int or not 0 <= t <= 2**31-1 for t in input_ids)):
                return "original-encoded-prompt-invalid"
            answer = row["raw_answer"]
            if (type(answer) is not str or not answer.strip()
                    or len(answer.encode("utf-8")) > MAX_ANSWER_BYTES):
                return "original-raw-answer-invalid"
            sources = row["delivered_sources"]
            if type(sources) is not list or len(sources) > 64:
                return "original-source-count-invalid"
            fingerprints = []
            identities = set()
            local_size = (len(json.dumps(question,ensure_ascii=False).encode("utf-8"))
                          + 4*len(input_ids) + len(answer.encode("utf-8")))
            for source in sources:
                fingerprint = source_fingerprint(source)
                source_key = (source["scope"], source["identity"])
                provenance = tuple(source[field] for field in (
                    "root", "session", "observed_at", "content"
                ))
                if (source_key in source_origins and
                        source_origins[source_key] != provenance):
                    return "original-source-identity-reused-with-different-bytes"
                source_origins[source_key] = provenance
                if (source["identity"] in identities or source["scope"] != question["scope"]
                        or _datetime(source["observed_at"]) > timestamp):
                    return "original-source-scope-time-or-identity-invalid"
                identities.add(source["identity"])
                local_size += len(source["content"].encode("utf-8"))
                fingerprints.append(fingerprint)
            if local_size > MAX_CASE_BYTES:
                return "original-case-size-budget-exceeded"
            size += local_size
            if size > MAX_TOTAL_BYTES:
                return "original-review-archive-size-budget-exceeded"
            citations = []
            for match in CITE.finditer(answer):
                index = int(match[1])
                if not 1 <= index <= len(sources):
                    return "original-answer-cites-nonexistent-evidence"
                label = fingerprints[index-1]
                if label not in citations:
                    citations.append(label)
            original_by_key[key] = dict(
                question_sha256=canonical_sha(question),
                prompt_input_ids_sha256=canonical_sha(input_ids),
                raw_answer_sha256=canonical_sha(answer),
                delivered_source_sha256=fingerprints,
                cited_source_sha256=citations,
            )
        if set(original_by_key) != expected:
            return "original-case-denominator-mismatch"
        seen = set()
        for row in reviewed_items:
            if type(row) is not dict:
                return "original-review-row-invalid"
            key = (row.get("item_id"), row.get("condition"))
            if key not in expected or key in seen:
                return "original-review-case-not-unique"
            seen.add(key)
            canonical = original_by_key[key]
            if any(row.get(field) != value for field, value in canonical.items()):
                return "original-question-prompt-answer-or-citation-drift"
    except (UnicodeError, ValueError, TypeError, OverflowError, KeyError):
        return "original-case-bytes-malformed"
    return None
