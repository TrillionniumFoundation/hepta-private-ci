"""Query-conditioned, byte-exact windows; no answer/annotation input.

This is a bounded projection over already admitted native Documents, not a new
store or entitlement source. Offsets refer to original Document.content UTF-8,
never a whitespace-normalized chunk. Its digests bind inspected bytes, not an
unread suffix. Ranking/quotation cannot establish semantic entailment.
"""

from bisect import bisect_right
from dataclasses import asdict, dataclass
import math
import re

from citation_audit import MARKER
from grounded_protocol import Quote
from native import Document, Question, digest


@dataclass(frozen=True)
class WindowBudget:
    sources: int = 8
    scan_bytes: int = 16384
    per_source_bytes: int = 4096
    window_bytes: int = 384
    stride_bytes: int = 192
    candidates: int = 32

    def validate(self):
        if any(type(v) is not int for v in asdict(self).values()) or not (
            1 <= self.sources <= 8
            and 512 <= self.scan_bytes <= 65536
            and 512 <= self.per_source_bytes <= self.scan_bytes
            and 64 <= self.stride_bytes <= self.window_bytes <= 512
            and 1 <= self.candidates <= 64
        ):
            raise ValueError("window resource profile")


@dataclass(frozen=True)
class Window:
    source_id: str
    root: str
    scope: str
    observed_at: str
    start: int
    end: int
    text: str
    inspected_sha256: str

    def identity(self):
        return digest(asdict(self))

    def quote(self, number: int):
        return Quote(
            f"E{number}", self.source_id, self.root, self.start, self.end, self.text
        )


@dataclass(frozen=True)
class WindowPool:
    query_digest: str
    profile: str
    windows: tuple[Window, ...]
    inspected: tuple[dict, ...]
    scanned_bytes: int
    enumerated_windows: int
    budget: WindowBudget

    def seal(self):
        return digest(asdict(self))

    def revalidate(self, query: Question, revoked: set[str]):
        if digest(asdict(query)) != self.query_digest:
            raise ValueError("query/pool mismatch")
        if any(
            s["root"] in revoked or s["scope"] != query.scope for s in self.inspected
        ):
            raise ValueError("withdrawn or cross-scope window pool")
        if len({w.identity() for w in self.windows}) != len(self.windows):
            raise ValueError("duplicate window identity")
        by_id = {s["id"]: s for s in self.inspected}
        if len(by_id) != len(self.inspected):
            raise ValueError("duplicate inspected source")
        for w in self.windows:
            s = by_id[w.source_id]
            if (
                type(w.start) is not int
                or type(w.end) is not int
                or not 0 <= w.start < w.end <= len(s["excerpt"].encode())
                or (w.root, w.scope, w.observed_at, w.inspected_sha256)
                != (s["root"], s["scope"], s["observed_at"], s["inspected_sha256"])
                or s["excerpt"].encode()[w.start : w.end].decode() != w.text
                or digest(s["excerpt"]) != w.inspected_sha256
            ):
                raise ValueError("detached original source window")

    def delivered(self):
        """One actually scored window per label; original offsets remain explicit."""
        return [
            dict(
                id=w.identity(),
                original_id=w.source_id,
                root=w.root,
                scope=w.scope,
                label=f"E{i}",
                excerpt=w.text,
                source_start=w.start,
                source_end=w.end,
                observed_at=w.observed_at,
                inspected_sha256=w.inspected_sha256,
            )
            for i, w in enumerate(self.windows, 1)
        ]


def _prefix(text: str, byte_limit: int):
    # At most byte_limit codepoints are encoded, not an unbounded source suffix.
    # At most one additional codepoint is inspected at the byte boundary.
    offered = bytearray()
    for c in text:
        encoded = c.encode("utf-8", "strict")
        if len(offered) + len(encoded) > byte_limit:
            break
        offered.extend(encoded)
    return offered.decode("utf-8", "strict")


def _spans(text: str, budget: WindowBudget):
    offsets = [0]
    for char in text:
        offsets.append(offsets[-1] + len(char.encode()))
    start = 0
    while start < len(text):
        end = bisect_right(offsets, offsets[start] + budget.window_bytes) - 1
        if end < len(text):
            # Avoid cutting a word when a nearby delimiter exists. No source edit.
            delimiters = [
                i
                for i in range(max(start + 1, end - 64), end)
                if text[i].isspace() or text[i] in ".!?。！？"
            ]
            if delimiters:
                end = delimiters[-1] + 1
        left, right = start, end
        while left < right and text[left].isspace():
            left += 1
        while right > left and text[right - 1].isspace():
            right -= 1
        body = text[left:right]
        if (
            body
            and not MARKER.search(body.encode())
            and not any(ord(c) < 32 and c not in "\n\t" for c in body)
        ):
            yield offsets[left], offsets[right], body
        if end == len(text):
            break
        next_start = bisect_right(offsets, offsets[start] + budget.stride_bytes) - 1
        start = max(start + 1, min(next_start, end))


def candidate_windows(
    documents: tuple[Document, ...],
    query: Question,
    *,
    revoked: set[str],
    budget: WindowBudget = WindowBudget(),
    profile: str = "query_windows",
) -> WindowPool:
    budget.validate()
    if profile not in ("prefix", "query_windows"):
        raise ValueError("unregistered window profile")
    if (
        len(documents) > budget.sources
        or len({d.identity for d in documents}) != len(documents)
        or any(d.scope != query.scope or d.root in revoked for d in documents)
    ):
        raise ValueError("source count/scope/withdrawal")
    if (
        not isinstance(query.content, str)
        or not query.content.strip()
        or len(query.content.encode()) > 16384
        or not query.observed_at
        or len(query.observed_at.encode()) > 256
    ):
        raise ValueError("bounded query required")
    terms = set(re.findall(r"\w+", query.content.lower()))
    inspected, ranked, mandatory, used = [], [], [], 0
    for number, doc in enumerate(documents):
        if (
            not isinstance(doc.content, str)
            or not doc.identity
            or not doc.root
            or "#chunk:" in doc.identity
        ):
            raise ValueError("original non-normalized Document required")
        remaining = budget.scan_bytes - used
        allowance = min(budget.per_source_bytes, remaining // (len(documents) - number))
        if allowance <= 0:
            break
        if profile == "prefix":
            allowance = min(512, allowance)
        prefix = _prefix(doc.content, allowance)
        if "\0" in prefix:
            raise ValueError("invalid source prefix")
        used += len(prefix.encode())
        source = dict(
            id=doc.identity,
            root=doc.root,
            scope=doc.scope,
            observed_at=doc.observed_at,
            excerpt=prefix,
            inspected_sha256=digest(prefix),
            unscanned_characters=len(doc.content) - len(prefix),
        )
        inspected.append(source)
        spans = list(_spans(prefix, budget))
        if profile == "prefix":
            spans = spans[:1]
        for span_number, (start, end, body) in enumerate(spans):
            w = Window(
                doc.identity,
                doc.root,
                doc.scope,
                doc.observed_at,
                start,
                end,
                body,
                source["inspected_sha256"],
            )
            tokens = re.findall(r"\w+", body.lower())
            # Cheap query-dependent shortlist; learned/frozen scorers share it.
            # This is not semantic relevance and never uses answer annotations.
            overlap = len(terms.intersection(tokens)) / math.sqrt(max(1, len(tokens)))
            ranked.append((overlap, w))
            if span_number == 0:
                mandatory.append(w)
    ranked.sort(key=lambda item: (-item[0], item[1].source_id, item[1].start))
    # Preserve each retrieved source's first admissible window before expansion.
    # Otherwise long early documents could hide every later source under the cap.
    windows = mandatory[: budget.candidates]
    seen = {w.identity() for w in windows}
    for _, w in ranked:
        if w.identity() not in seen and len(windows) < budget.candidates:
            windows.append(w)
            seen.add(w.identity())
    pool = WindowPool(
        digest(asdict(query)),
        profile,
        tuple(windows),
        tuple(inspected),
        used,
        len(ranked),
        budget,
    )
    pool.revalidate(query, revoked)
    return pool
