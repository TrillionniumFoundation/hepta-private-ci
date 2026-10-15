"""Bounded proof-carrying multi-hop relation engine, RESEARCH_ONLY / DENY_ALL.

Consumes only public sentences, question and candidate. No label, source metadata,
model checkpoint, hidden answer, annotations or authority enters this implementation.
An intentionally restricted formal grammar is NOT natural-language reasoning.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
import re

TYPES = ("object", "person", "box", "shelf", "room", "building", "district")
PATTERNS = (
    re.compile(r"The ([a-z]+) belongs to ([A-Z][a-z]+)\.", re.ASCII),
    re.compile(r"([A-Z][a-z]+) stores all their possessions in the ([a-z]+) box\.", re.ASCII),
    re.compile(r"The ([a-z]+) box is on the ([a-z]+) shelf\.", re.ASCII),
    re.compile(r"The ([a-z]+) shelf is in the ([a-z]+) room\.", re.ASCII),
    re.compile(r"The ([a-z]+) room is in the ([a-z]+) building\.", re.ASCII),
    re.compile(r"The ([a-z]+) building is in the ([a-z]+) district\.", re.ASCII),
)
QUESTION = re.compile(r"Where is the ([a-z]+) at the (box|shelf|room|building|district) level\?", re.ASCII)
CANDIDATE = re.compile(r"The ([a-z]+) (box|shelf|room|building|district)\.", re.ASCII)


class RejectGraph(ValueError):
    """Fail closed for unknown, incomplete, ambiguous or over-budget evidence."""


def canonical(data):
    return json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()


def digest(data):
    return sha256(canonical(data)).hexdigest()


@dataclass(frozen=True)
class Proof:
    claim: bool
    object: str
    candidate: str
    final_type: str
    # Hop includes explicit source index and both typed endpoints.
    hops: tuple
    source_sha256: str

    def receipt(self):
        return dict(claim=self.claim, object=self.object, candidate=self.candidate,
                    final_type=self.final_type, hops=[list(h) for h in self.hops],
                    source_sha256=self.source_sha256)


def solve(facts, question, candidate, *, max_hops=6):
    """Traverse up to six typed, uniquely determined relation links."""
    if (type(facts) not in (list, tuple) or not 1 <= len(facts) <= 64
            or not all(type(s) is str and 1 <= len(s) <= 256 for s in facts)
            or type(question) is not str or type(candidate) is not str
            or len(question) > 256 or len(candidate) > 256
            or type(max_hops) is not int or not 2 <= max_hops <= 6):
        raise RejectGraph("bounded public relation input required")
    qm, cm = QUESTION.fullmatch(question), CANDIDATE.fullmatch(candidate)
    if qm is None or cm is None or qm[2] != cm[2]:
        raise RejectGraph("registered question and same-type candidate required")
    depth = TYPES.index(qm[2])
    if depth > max_hops:
        raise RejectGraph("query exceeds admitted reasoning depth")
    graph = {}
    present_candidates = set()
    for line, fact in enumerate(facts, 1):
        recognized = [(i, m) for i, pattern in enumerate(PATTERNS) if (m := pattern.fullmatch(fact))]
        if len(recognized) != 1:
            raise RejectGraph("unrecognized or multiply interpreted evidence")
        i, match = recognized[0]
        left, right = match.groups()
        key = TYPES[i], left
        if key in graph:
            raise RejectGraph("ambiguous or duplicated source edge")
        graph[key] = (TYPES[i + 1], right, line)
        if TYPES[i + 1] == qm[2]:
            present_candidates.add(right)
    if cm[1] not in present_candidates:
        raise RejectGraph("candidate has no declared evidence-domain identity")
    node = ("object", qm[1])
    hops = []
    for _ in range(depth):
        if node not in graph:
            raise RejectGraph("missing required evidence edge")
        nxt, value, line = graph[node]
        expected = TYPES[TYPES.index(node[0]) + 1]
        if nxt != expected:
            raise RejectGraph("invalid typed edge transition")
        hops.append((line, node[0], node[1], nxt, value))
        node = nxt, value
    if node[0] != qm[2]:
        raise RejectGraph("wrong terminal type")
    return Proof(node[1] == cm[1], qm[1], cm[1], qm[2], tuple(hops), digest(list(facts)))


def verify_proof(facts, question, candidate, receipt):
    """Separate witness checker: rebuild each step's sentence from public endpoints.

    Does not invoke solve or trust the claimed source indices/terminal value.
    """
    if type(receipt) is not dict or set(receipt) != {
            "claim", "object", "candidate", "final_type", "hops", "source_sha256"}:
        raise RejectGraph("complete proof receipt required")
    if digest(list(facts)) != receipt["source_sha256"]:
        raise RejectGraph("source content was replaced")
    qm, cm = QUESTION.fullmatch(question), CANDIDATE.fullmatch(candidate)
    if qm is None or cm is None or qm[2] != cm[2] or qm[1] != receipt["object"]:
        raise RejectGraph("proof question mismatch")
    if cm[1] != receipt["candidate"] or cm[2] != receipt["final_type"]:
        raise RejectGraph("proof candidate mismatch")
    steps = receipt["hops"]
    depth = TYPES.index(qm[2])
    if type(steps) is not list or len(steps) != depth:
        raise RejectGraph("complete proof path required")
    current = ("object", qm[1])
    used = set()
    for i, step in enumerate(steps):
        if type(step) is not list or len(step) != 5:
            raise RejectGraph("typed proof step required")
        line, src_type, src_name, dst_type, dst_name = step
        if (type(line) is not int or not 1 <= line <= len(facts) or line in used
                or src_type != TYPES[i] or dst_type != TYPES[i + 1]
                or (src_type, src_name) != current):
            raise RejectGraph("invalid witness transition or repeated source")
        used.add(line)
        match = PATTERNS[i].fullmatch(facts[line - 1])
        if match is None or match.groups() != (src_name, dst_name):
            raise RejectGraph("witness not grounded in cited sentence")
        current = dst_type, dst_name
    if type(receipt["claim"]) is not bool or receipt["claim"] != (current[1] == cm[1]):
        raise RejectGraph("incorrect proof conclusion")
    return True
