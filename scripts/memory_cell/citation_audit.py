"""Exact prompt/answer citation audit interchange, not an automatic truth judge.

Auditors receive delivered excerpts, not merely retrieval IDs or benchmark gold.
The binary payloads match learning.eval's citation_audit Rust module. Sign them
through the existing learning evidence owner: this module has no signing key,
trust issuer, production acceptance path, or default 'entailed' decision.
"""
from __future__ import annotations

import hashlib
import re
import struct

MAX_PAYLOAD = 1_048_576
KINDS = {"factual": 0, "nonfactual": 1, "abstention": 2, "unreviewed": 3}
VERDICTS = {"entailed": 0, "contradicted": 1, "unsupported": 2, "unreviewed": 3}
MARKER = re.compile(rb"\[E[0-9]+\]")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) or value == "0" * 64:
        raise ValueError("invalid digest")
    return bytes.fromhex(value)


def _text(value, bound):
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError("missing or invalid text")
    raw = value.encode("utf-8", "strict")
    if len(raw) > bound:
        raise ValueError("text bound")
    return struct.pack(">Q", len(raw)) + raw


def _uint(value, bits):
    if type(value) is not int or not 0 <= value < 2**bits:
        raise ValueError("invalid unsigned integer")
    return struct.pack(">I" if bits == 32 else ">Q", value)


def request_payload(request: dict) -> bytes:
    expected = {"query_id", "scope", "experiment_digest", "family_digest", "prompt_digest",
                "question", "question_time", "answer", "sources"}
    if not isinstance(request, dict) or set(request) != expected:
        raise ValueError("unknown citation request")
    data = bytearray(b"hepta.memory-citation.request.v1\0")
    data += _text(request["query_id"], 1024) + _text(request["scope"], 1024)
    for name in ("experiment_digest", "family_digest", "prompt_digest"):
        data += _digest(request[name])
    for name, bound in (("question", 16384), ("question_time", 256), ("answer", 65536)):
        data += _text(request[name], bound)
    sources = request["sources"]
    if not isinstance(sources, list) or len(sources) > 256:
        raise ValueError("source bound")
    data += _uint(len(sources), 64)
    labels, identities = set(), set()
    for source in sources:
        if not isinstance(source, dict) or set(source) != {"label", "id", "root", "excerpt"}:
            raise ValueError("unknown delivered source")
        label = source["label"]
        if not isinstance(label, str) or not re.fullmatch(r"E[1-9][0-9]{0,5}", label):
            raise ValueError("citation label")
        if label in labels or source["id"] in identities:
            raise ValueError("duplicate delivered source")
        labels.add(label)
        identities.add(source["id"])
        data += _text(label, 7) + _text(source["id"], 1024)
        data += _digest(source["root"]) + _text(source["excerpt"], 32768)
        if len(data) > MAX_PAYLOAD:
            raise ValueError("payload bound")
    return bytes(data)


def judgement_payload(request: dict, judgement: dict) -> bytes:
    raw = request_payload(request)
    if not isinstance(judgement, dict) or set(judgement) != {"claims", "citations"}:
        raise ValueError("unknown citation judgement")
    claims, citations = judgement["claims"], judgement["citations"]
    if not isinstance(claims, list) or not 1 <= len(claims) <= 512 or not isinstance(citations, list) or len(citations) > 512:
        raise ValueError("judgement bound")
    data = bytearray(b"hepta.memory-citation.judgement.v1\0" + hashlib.sha256(raw).digest())
    data += _uint(len(claims), 64)
    for claim in claims:
        if not isinstance(claim, dict) or set(claim) != {"start", "end", "kind"} or claim["kind"] not in KINDS:
            raise ValueError("unknown claim")
        data += _uint(claim["start"], 32) + _uint(claim["end"], 32) + bytes([KINDS[claim["kind"]]])
    data += _uint(len(citations), 64)
    for citation in citations:
        if not isinstance(citation, dict) or set(citation) != {"start", "verdict"} or citation["verdict"] not in VERDICTS:
            raise ValueError("unknown citation verdict")
        data += _uint(citation["start"], 32) + bytes([VERDICTS[citation["verdict"]]])
    return bytes(data)


def validate_judgement(request: dict, judgement: dict, *, revoked_roots: set[str]) -> dict:
    """Structural diagnostic only. Production ingress also verifies BOTH actors.

    Spans are UTF-8 byte offsets. Every non-whitespace character must be reviewed,
    and every emitted [E<number>] occurrence remains in the precision denominator.
    A valid reference is not a positive entailment verdict.
    """
    judgement_payload(request, judgement)
    if not isinstance(revoked_roots, set):
        raise ValueError("a current revocation set is mandatory")
    if any(source["root"] in revoked_roots for source in request["sources"]):
        raise ValueError("revoked delivered source")
    answer = request["answer"].encode("utf-8")
    claims = judgement["claims"]
    position = 0
    for claim in claims:
        start, end = claim["start"], claim["end"]
        if not position <= start < end <= len(answer):
            raise ValueError("overlapping or invalid claim span")
        try:
            gap, text = answer[position:start].decode("utf-8"), answer[start:end].decode("utf-8")
        except UnicodeError as error:
            raise ValueError("claim splits a UTF-8 character") from error
        if gap.strip(" \t\r\n") or not text.strip(" \t\r\n"):
            raise ValueError("unreviewed answer text or empty claim")
        position = end
    if answer[position:].decode("utf-8").strip(" \t\r\n"):
        raise ValueError("unreviewed answer suffix")
    markers = list(MARKER.finditer(answer))
    if len(markers) != len(judgement["citations"]):
        raise ValueError("every citation occurrence must be judged")
    labels = {source["label"] for source in request["sources"]}
    supported, entailed, contradicted, unreviewed = set(), 0, 0, 0
    for marker, citation in zip(markers, judgement["citations"], strict=True):
        if citation["start"] != marker.start():
            raise ValueError("citation occurrence ordering mismatch")
        owners = [i for i, claim in enumerate(claims) if claim["start"] <= marker.start() and marker.end() <= claim["end"]]
        if len(owners) != 1 or claims[owners[0]]["kind"] != "factual":
            raise ValueError("citation outside a factual claim")
        verdict = citation["verdict"]
        label = marker.group()[1:-1].decode("ascii")
        if verdict == "entailed":
            if label not in labels:
                raise ValueError("entailed verdict cites undelivered evidence")
            entailed += 1
            supported.add(owners[0])
        contradicted += verdict == "contradicted"
        unreviewed += verdict == "unreviewed"
    return {"citations": len(markers), "entailed": entailed, "contradicted": contradicted,
            "unreviewed_citations": unreviewed, "factual_claims": sum(c["kind"] == "factual" for c in claims),
            "supported_factual_claims": len(supported), "unreviewed_claims": sum(c["kind"] == "unreviewed" for c in claims),
            "diagnostic_precision_ppm": entailed * 1_000_000 // len(markers) if markers else None,
            "signed_evaluator_verified": False, "production_accepted": False}


def capture(query, answer: str, receipt: dict, *, experiment_digest: str, family_digest: str) -> dict:
    """Called directly on the model's output receipt, before any gold scoring."""
    request = {"query_id": query.identity, "scope": query.scope, "experiment_digest": experiment_digest,
               "family_digest": family_digest, "prompt_digest": receipt.get("input_ids_sha256"),
               "question": query.content, "question_time": query.observed_at, "answer": answer,
               "sources": [{key: source[key] for key in ("label", "id", "root", "excerpt")}
                           for source in receipt.get("delivered_evidence", [])]}
    encoded = request_payload(request)
    return {"schema": "hepta.memory-citation.queue.v1", "request": request,
            "request_sha256": sha(encoded), "judgement": None,
            "generator_signature": None, "evaluator_signature": None,
            "semantic_precision": None, "production_accepted": False}
