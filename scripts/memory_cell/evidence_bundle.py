"""Read-only evidence-set projection over native Documents; no new owner authority.

Every selected fragment remains bound to ORIGINAL bytes. Query-time selection
never receives answer labels. Scope/revocation checks apply to every final use.
The bundle is experimental, not a replacement for RecallPacketV1 or its owners.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import re

from native import Document, Question, digest

PROFILE = "hepta.evidence-bundle.v1"
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_INDEX_BYTES = 8 * 1024 * 1024
MAX_WINDOWS = 20000


def observed_time(value):
    """Parse registered dataset formats. Observation time is NOT valid time."""
    for fmt in ("%Y/%m/%d (%a) %H:%M", "%I:%M %p on %d %B, %Y"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pass
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (TypeError, ValueError, AttributeError):
        raise ValueError("unregistered observation time") from None


@dataclass(frozen=True)
class EvidenceSpan:
    source_id: str
    root: str
    scope: str
    session: str
    observed_at: str
    start: int
    end: int
    excerpt: str
    source_digest: str

    def identity(self):
        return digest(asdict(self))

    def validate(self, source, query, revoked):
        if (source.identity, source.root, source.scope, source.session, source.observed_at) != (
            self.source_id, self.root, self.scope, self.session, self.observed_at
        ) or self.root in revoked or self.scope != query.scope:
            raise ValueError("source identity/scope/revocation changed")
        raw = source.content.encode("utf-8", "strict")
        if (type(self.start) is not int or type(self.end) is not int
            or not 0 <= self.start < self.end <= len(raw) <= MAX_SOURCE_BYTES
            or not self.excerpt.strip() or digest(source.content) != self.source_digest
            or raw[self.start:self.end].decode("utf-8", "strict") != self.excerpt):
            raise ValueError("detached original evidence span")
        if observed_time(self.observed_at) > observed_time(query.observed_at):
            raise ValueError("future observation is not available at query time")

    def document(self):
        return Document(self.identity(), self.root, self.scope, self.session,
                        self.observed_at, self.excerpt)


def build_windows(documents, *, window_bytes=512, stride_bytes=384):
    """Index the whole admitted view once; fail on budget, never hide a suffix.

    This is ingestion/indexing cost, not a free query-time full-history scan.
    Per-query retrieval is bounded separately. Nothing consults evaluation labels.
    """
    if (type(window_bytes) is not int or type(stride_bytes) is not int
        or not 64 <= stride_bytes <= window_bytes <= 2048):
        raise ValueError("window size budget")
    if not 1 <= len(documents) <= 10000 or len({d.identity for d in documents}) != len(documents):
        raise ValueError("bounded unique source view required")
    if len({d.scope for d in documents}) != 1:
        raise ValueError("cross-scope index")
    total, spans = 0, []
    for doc in documents:
        raw = doc.content.encode("utf-8", "strict")
        total += len(raw)
        if not 1 <= len(raw) <= MAX_SOURCE_BYTES or total > MAX_INDEX_BYTES:
            raise ValueError("complete index exceeds source byte budget")
        identity = digest(doc.content)
        start = 0
        while start < len(raw):
            end = min(start + window_bytes, len(raw))
            while end < len(raw) and raw[end] & 0xC0 == 0x80:
                end -= 1
            excerpt = raw[start:end].decode("utf-8", "strict")
            if excerpt.strip():
                spans.append(EvidenceSpan(doc.identity, doc.root, doc.scope, doc.session,
                    doc.observed_at, start, end, excerpt, identity))
            if len(spans) > MAX_WINDOWS:
                raise ValueError("complete index exceeds window count budget")
            if end == len(raw):
                break
            next_start = min(start + stride_bytes, end)
            while next_start < len(raw) and raw[next_start] & 0xC0 == 0x80:
                next_start += 1
            start = next_start
    return tuple(spans), dict(source_bytes=total, windows=len(spans),
                             source_manifest=digest([asdict(d) for d in documents]),
                             full_scan_charged_at_index_build=True)


@dataclass(frozen=True)
class EvidenceBundle:
    query_digest: str
    source_frontier: str
    selected: tuple[EvidenceSpan, ...]
    mode: str
    rounds: int = 1

    def seal(self):
        return digest((PROFILE, asdict(self)))

    def validate(self, query, originals, *, frontier, revoked):
        if (self.query_digest != digest(asdict(query)) or self.source_frontier != frontier
            or not frontier or len(self.selected) > 8 or type(self.rounds) is not int
            or not 0 <= self.rounds <= 3):
            raise ValueError("bundle query/frontier/bounds")
        if len({s.identity() for s in self.selected}) != len(self.selected):
            raise ValueError("duplicate bundle fragment")
        for span in self.selected:
            if span.source_id not in originals:
                raise ValueError("missing original source")
            span.validate(originals[span.source_id], query, revoked)

    def delivered(self):
        return [dict(label=f"E{i}", id=s.identity(), original_id=s.source_id,
                     root=s.root, scope=s.scope, excerpt=s.excerpt,
                     source_start=s.start, source_end=s.end, observed_at=s.observed_at,
                     source_digest=s.source_digest)
                for i, s in enumerate(self.selected, 1)]


def terms(text):
    # A transparent coverage heuristic, NOT a semantic-sufficiency certificate.
    stop = {"the", "a", "an", "of", "in", "on", "and", "or", "is", "was", "did",
            "i", "my", "me", "what", "how", "when", "where", "to", "for", "it"}
    return frozenset(re.findall(r"\w+", text.lower())) - stop


def select_set(query, candidates, *, count, mode):
    """Fixed ranked-list control or marginal lexical coverage with redundancy cost.

    Never interprets a newer observation as superseding older valid knowledge.
    Empty uncovered terms cannot certify that an answer is possible.
    """
    if type(count) is not int or count not in (1, 2, 4, 8) or mode not in ("ranked", "coverage"):
        raise ValueError("unregistered bundle selection")
    if len(candidates) > 128 or len({s.identity() for s in candidates}) != len(candidates):
        raise ValueError("bounded unique candidates required")
    eligible = [s for s in candidates if s.scope == query.scope and
                observed_time(s.observed_at) <= observed_time(query.observed_at)]
    if mode == "ranked":
        return tuple(eligible[:count])
    chosen, uncovered = [], set(terms(query.content))
    remaining = list(enumerate(eligible))
    while remaining and len(chosen) < count:
        def merit(pair):
            rank, s = pair
            overlap = max((max(0, min(s.end, old.end)-max(s.start, old.start)) /
                           (s.end-s.start) if s.source_id == old.source_id else 0
                           for old in chosen), default=0)
            gain = len(terms(s.excerpt) & uncovered) / max(1, len(terms(query.content)))
            diversity = float(all(s.source_id != old.source_id for old in chosen))
            return gain + 0.1 * diversity + 0.25 / (rank + 1) - 0.8 * overlap
        best = max(remaining, key=lambda p: (merit(p), -p[0]))
        remaining.remove(best)
        chosen.append(best[1])
        uncovered.difference_update(terms(best[1].excerpt))
    return tuple(chosen)


def retrieve_bundle(query, retrieve, originals, *, frontier, revoked, count=8,
                    mode="coverage", rounds=1):
    """Bounded supplemental retrieval through an injected existing read owner.

    retrieve(query, k) must return (original spans, resource receipt). The only
    expansion cue is uncovered query vocabulary; gold labels are not accepted.
    """
    if type(rounds) is not int or not 1 <= rounds <= 3:
        raise ValueError("retrieval rounds bound")
    pool, seen, receipts, used = [], set(), [], 0
    next_query = query
    for _ in range(rounds):
        found, receipt = retrieve(next_query, 32)
        if len(found) > 32 or not isinstance(receipt, dict):
            raise ValueError("retrieval exceeded requested bound")
        used += 1
        receipts.append(receipt)
        additions = 0
        for span in found:
            span.validate(originals[span.source_id], query, revoked)
            if span.identity() not in seen:
                seen.add(span.identity()); pool.append(span); additions += 1
        selected = select_set(query, pool, count=count, mode=mode)
        missing = terms(query.content) - frozenset().union(*(terms(s.excerpt) for s in selected))
        if not missing or not additions:
            break
        next_query = Question(query.identity, query.family, query.scope,
            query.content + "\nAdditional retrieval cues: " + " ".join(sorted(missing)),
            query.observed_at)
    bundle = EvidenceBundle(digest(asdict(query)), frontier, selected, mode, used)
    bundle.validate(query, originals, frontier=frontier, revoked=revoked)
    return bundle, dict(rounds=used, unique_candidates=len(pool), reads=receipts,
                        semantic_sufficiency=None, target_annotations_used=False)
