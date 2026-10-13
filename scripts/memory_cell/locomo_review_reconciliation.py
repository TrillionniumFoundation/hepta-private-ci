"""Model-free LoCoMo external-review reconciliation; NEVER authenticates reviewers.

The input is the immutable two-stage, answer-blind sufficiency and unedited
Reader citation worklist. Claims returned by external parties remain untrusted:
this code cannot certify viewing order, credentials, entailment or production.
"""
import argparse
from datetime import datetime
from pathlib import Path
import re

from locomo_sufficiency_worklist import ARMS, CITE, SCHEMA as PACKET, digest_bytes, read_json, write_once

SCHEMA = "hepta.locomo.external-review-preflight.v1"
ACTOR = re.compile(r"[a-zA-Z0-9_.:@-]{8,128}\Z")


def load(path):
    p = Path(path)
    if p.is_symlink() or any(parent.is_symlink() for parent in p.parents):
        raise ValueError("review file symlink")
    with p.open("rb") as f:
        data = f.read(4 * 1024 * 1024 + 1)
    if not data or len(data) > 4 * 1024 * 1024:
        raise ValueError("missing or unbounded review input")
    return data


def originals(folder):
    folder = Path(folder)
    files = {n: load(folder / n) for n in
             ("manifest.json", "sufficiency-only.json", "answer-and-citation.json")}
    sha = {n: digest_bytes(v) for n, v in files.items()}
    manifest, suff, ans = (read_json(files[n]) for n in files)
    lines = load(folder / "SHA256SUMS").decode().splitlines()
    if (len(lines) != 3 or set(lines) !=
        {f"{v}  ./{n}" for n, v in sha.items()}):
        raise ValueError("original SHA256SUMS does not bind the review packet")
    if (
        any(x.get("schema") != PACKET for x in (manifest, suff, ans))
        or manifest.get("sufficiency_worklist_sha256") != sha["sufficiency-only.json"]
        or manifest.get("answer_citation_worklist_sha256") != sha["answer-and-citation.json"]
        or manifest.get("original_public_question_count") != 16
        or manifest.get("original_model_answers") != 32
        or manifest.get("original_published_source_family_proxies") != 2
        or manifest.get("source_sufficiency_decisions") != 0
        or manifest.get("answer_citation_review_decisions") != 0
        or manifest.get("independent_human_semantic_judgement") is not False
        or manifest.get("production_accepted") is not False
        or suff.get("model_answers_in_this_worklist") is not False
        or suff.get("reviewer_verdicts_recorded") != 0
        or ans.get("reviewer_verdicts_recorded") != 0
        or ans.get("original_reader_answers_unchanged") is not True
    ):
        raise ValueError("worklist was not the original unreviewed source-first version")
    a, b = suff.get("review_cases"), ans.get("review_cases")
    if not isinstance(a, list) or not isinstance(b, list) or len(a) != 32 or len(b) != 32:
        raise ValueError("exact 32-case review denominator required")
    ids, families = set(), set()
    for i, (src, answer) in enumerate(zip(a, b, strict=True)):
        key = src.get("review_id")
        if (not isinstance(key, str) or not key or key in ids
            or answer.get("review_id") != key
            or src.get("sufficient_to_answer") is not None
            or answer.get("answer_supported_by_delivered_sources") is not None
            or answer.get("cited_claims_entailed") is not None
            or answer.get("citation_chain_complete") is not None
            or src.get("reviewer_identity") is not None
            or answer.get("reviewer_identity") is not None
            or src.get("reviewed_at") is not None
            or answer.get("reviewed_at") is not None
            or src.get("supporting_utf8_byte_spans") != []
            or "unedited_reader_answer" in src
            or not isinstance(answer.get("unedited_reader_answer"), str)
            or src.get("evidence") != answer.get("evidence")
            or src.get("selected_ids") != answer.get("selected_ids")
            or src.get("question") != answer.get("question")):
            raise ValueError("original review IDs, provenance or blindness drifted")
        ids.add(key)
        families.add(src["source_family_proxy"])
        if len(src["selected_ids"]) != (4 if i % 2 == 0 else 8):
            raise ValueError("original k4/k8 arm source count changed")
        if i % 2:
            before = a[i-1]
            if (src["selected_ids"][:4] != before["selected_ids"]
                or src["question"] != before["question"]
                or src["source_family_proxy"] != before["source_family_proxy"]):
                raise ValueError("original paired Reader source/question drift")
        if len(src["evidence"]) != len(src["selected_ids"]):
            raise ValueError("missing original delivered evidence")
        for sid, ev in zip(src["selected_ids"], src["evidence"], strict=True):
            if (ev.get("source_id") != sid
                or not isinstance(ev.get("original_text"), str)
                or digest_bytes(ev["original_text"].encode()) != ev.get("utf8_sha256")):
                raise ValueError("original UTF-8 evidence source drift")
        labels = {v["label"] for v in src["evidence"]}
        marked = sorted({"E" + m for m in CITE.findall(answer["unedited_reader_answer"])})
        if (answer.get("cited_labels") != marked
            or answer.get("undelivered_cited_labels") != sorted(set(marked) - labels)):
            raise ValueError("original emitted citation labels changed")
    if len(ids) != 32 or len(families) != 2:
        raise ValueError("original two-source-family proxy census drift")
    return a, b, sha


def occurrences(text):
    result = []
    for i, item in enumerate(CITE.finditer(text)):
        result.append(dict(
            index=i, label="E" + item.group(1),
            marker_start=len(text[:item.start()].encode()),
            marker_end=len(text[:item.end()].encode()),
            entailed=None, claim_start=None, claim_end=None,
        ))
    return result


def templates(packet, output):
    a, b, sha = originals(packet)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    source = dict(
        schema=SCHEMA, phase="source-first", authority_authenticated=False,
        worklist_sha256=sha["sufficiency-only.json"],
        rows=[dict(review_id=r["review_id"], sufficient=None,
                   answer_from_sources=None, spans=[], reviewer_id=None,
                   reviewed_at=None) for r in a],
    )
    receipt = write_once(output / "source-return.json", source)
    answers = dict(
        schema=SCHEMA, phase="answer-after-source", authority_authenticated=False,
        worklist_sha256=sha["answer-and-citation.json"],
        source_return_sha256=receipt,
        rows=[dict(review_id=r["review_id"], supported=None, chain_complete=None,
                   citations=occurrences(r["unedited_reader_answer"]),
                   reviewer_id=None, reviewed_at=None) for r in b],
    )
    write_once(output / "answer-return.json", answers)
    return dict(original_questions=16, return_slots=32,
                citation_occurrences=sum(len(v["citations"]) for v in answers["rows"]),
                original_verdicts=0, reviewer_authenticated=False,
                production_accepted=False)


def identity(row, judged):
    name, when = row["reviewer_id"], row["reviewed_at"]
    if judged:
        if not isinstance(name, str) or not ACTOR.fullmatch(name) or not isinstance(when, str):
            raise ValueError("claimed reviewer identity or timestamp missing")
        stamp = datetime.fromisoformat(when)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("review time lacks a timezone")
    elif name is not None or when is not None:
        raise ValueError("unreviewed case cannot contain a reviewer claim")


def bound_support(src, span):
    if not isinstance(span, dict) or set(span) != {"label", "start", "end", "text"}:
        raise ValueError("source support requires a byte-offset quotation")
    matching = [x for x in src["evidence"] if x["label"] == span["label"]]
    if len(matching) != 1:
        raise ValueError("support is not actually delivered")
    raw = matching[0]["original_text"].encode()
    start, end = span["start"], span["end"]
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(raw):
        raise ValueError("source support offset invalid")
    try:
        text = raw[start:end].decode()
    except UnicodeDecodeError as e:
        raise ValueError("support cuts a UTF-8 character") from e
    if not text.strip() or text != span["text"]:
        raise ValueError("support quote is not from original bytes")


def bound_claim(text, verdict, original):
    start, end = verdict["claim_start"], verdict["claim_end"]
    if (type(start) is not int or type(end) is not int
        or not 0 <= start < end <= original["marker_start"]
        or original["marker_start"] - end > 64):
        raise ValueError("cited claim must precede its marker")
    try:
        claim = text.encode()[start:end].decode()
    except UnicodeDecodeError as e:
        raise ValueError("cited claim cuts a UTF-8 character") from e
    if not claim.strip() or CITE.search(claim):
        raise ValueError("claimed assertion empty or includes citation marker")


def reconcile(packet, source_return, answer_return):
    a, b, sha = originals(packet)
    s_raw = load(source_return)
    s, t = read_json(s_raw), read_json(load(answer_return))
    if (s.get("schema") != SCHEMA or t.get("schema") != SCHEMA
        or s.get("phase") != "source-first"
        or t.get("phase") != "answer-after-source"
        or s.get("authority_authenticated") is not False
        or t.get("authority_authenticated") is not False
        or s.get("worklist_sha256") != sha["sufficiency-only.json"]
        or t.get("worklist_sha256") != sha["answer-and-citation.json"]
        or t.get("source_return_sha256") != digest_bytes(s_raw)
        or not isinstance(s.get("rows"), list) or not isinstance(t.get("rows"), list)
        or len(s["rows"]) != 32 or len(t["rows"]) != 32):
        raise ValueError("unbound, incomplete or falsely authenticated review returns")
    stats = {arm: dict(planned=16, sufficiency_reviewed=0, sufficient=0,
                       answer_reviewed=0, claimed_answer_supported=0,
                       citations_emitted=0, citations_reviewed=0,
                       citations_claimed_entailed=0, undelivered=0,
                       claimed_complete_chains=0) for arm in ARMS}
    for i, (src, original, sx, ax) in enumerate(zip(a, b, s["rows"], t["rows"], strict=True)):
        if (not isinstance(sx, dict) or not isinstance(ax, dict)
            or set(sx) != {"review_id", "sufficient", "answer_from_sources",
                           "spans", "reviewer_id", "reviewed_at"}
            or set(ax) != {"review_id", "supported", "chain_complete",
                           "citations", "reviewer_id", "reviewed_at"}
            or sx["review_id"] != src["review_id"]
            or ax["review_id"] != original["review_id"]):
            raise ValueError("review row identity, count or schema drift")
        stat = stats[ARMS[i % 2]]
        sufficient = sx["sufficient"]
        if type(sufficient) not in (bool, type(None)):
            raise ValueError("source sufficiency verdict must be three-state")
        identity(sx, sufficient is not None)
        spans = sx["spans"]
        if not isinstance(spans, list) or len(spans) > 16:
            raise ValueError("source support spans not bounded")
        if sufficient is True:
            if (not isinstance(sx["answer_from_sources"], str)
                or not sx["answer_from_sources"].strip() or not spans):
                raise ValueError("positive sufficiency requires source-only answer and spans")
            for span in spans:
                bound_support(src, span)
        elif sx["answer_from_sources"] is not None or spans:
            raise ValueError("insufficient or unknown support cannot be fabricated")
        stat["sufficiency_reviewed"] += sufficient is not None
        stat["sufficient"] += sufficient is True
        if (type(ax["supported"]) not in (bool, type(None))
            or type(ax["chain_complete"]) not in (bool, type(None))):
            raise ValueError("answer and chain opinions must be three-state")
        originals_cites = occurrences(original["unedited_reader_answer"])
        returns = ax["citations"]
        if not isinstance(returns, list) or len(returns) != len(originals_cites):
            raise ValueError("missing or duplicated cited occurrences")
        touched = ax["supported"] is not None or ax["chain_complete"] is not None
        delivered = {e["label"] for e in original["evidence"]}
        for emitted, claimed in zip(originals_cites, returns, strict=True):
            if (not isinstance(claimed, dict) or set(claimed) != set(emitted)
                or any(claimed[k] != emitted[k]
                       for k in ("index", "label", "marker_start", "marker_end"))
                or type(claimed["entailed"]) not in (bool, type(None))):
                raise ValueError("citation marker or claimed verdict changed shape")
            opinion = claimed["entailed"]
            if opinion is None:
                if claimed["claim_start"] is not None or claimed["claim_end"] is not None:
                    raise ValueError("unreviewed citation cannot contain claim offsets")
            else:
                bound_claim(original["unedited_reader_answer"], claimed, emitted)
                if opinion is True and emitted["label"] not in delivered:
                    raise ValueError("undelivered citation cannot entail any source claim")
            touched |= opinion is not None
            stat["citations_emitted"] += 1
            stat["citations_reviewed"] += opinion is not None
            stat["citations_claimed_entailed"] += opinion is True
            stat["undelivered"] += emitted["label"] not in delivered
        if ax["chain_complete"] is True and (
            not originals_cites or any(x["entailed"] is not True for x in returns)
        ):
            raise ValueError("claimed complete chain includes missing or false citations")
        identity(ax, touched)
        stat["answer_reviewed"] += ax["supported"] is not None
        stat["claimed_answer_supported"] += ax["supported"] is True
        stat["claimed_complete_chains"] += ax["chain_complete"] is True
    for arm in stats.values():
        arm["citations_unreviewed"] = arm["citations_emitted"] - arm["citations_reviewed"]
        arm["unverified_citation_fraction"] = (
            arm["citations_claimed_entailed"] / arm["citations_emitted"]
            if arm["citations_emitted"] and arm["citations_unreviewed"] == 0 else None
        )
    return dict(schema=SCHEMA, original_sha256=sha, questions=16,
                public_source_family_proxies=2, arms=stats,
                reviewer_identity_authenticated=False,
                source_first_view_order_authenticated=False,
                independently_verified_semantic_precision=None,
                effective_independent_sample_size=None,
                production_accepted=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    blank = commands.add_parser("template")
    blank.add_argument("packet", type=Path)
    blank.add_argument("output", type=Path)
    check = commands.add_parser("audit")
    check.add_argument("packet", type=Path)
    check.add_argument("source_return", type=Path)
    check.add_argument("answer_return", type=Path)
    check.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.mode == "template":
        print(templates(args.packet, args.output))
    else:
        output = reconcile(args.packet, args.source_return, args.answer_return)
        write_once(args.output, output)
        print(output)


if __name__ == "__main__":
    main()
