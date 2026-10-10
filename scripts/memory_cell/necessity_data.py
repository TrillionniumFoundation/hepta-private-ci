"""Pinned published human chain reviews, not an independent Hepta certificate.

Keep all original eOBQA votes, join original OpenBookQA options, and accept only
three affirmative votes with no requested extra fact. One-fact, disputed and
unknown chains stay in the acquisition census. Published judgments are fallible;
this profile does not fabricate reviewer identities, dates, or signatures.
"""

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import io
from pathlib import Path
import re
import urllib.request
import zipfile

from composition_evidence import parse_json, sha, write
from evidence_bundle import EvidenceBundle, EvidenceSpan
from native import Document, Question, digest

REVISION = "65e25d0f7b6f547f1694358d1cded40636b676e7"
REPOSITORY = "harsh19/Reasoning-Chains-MultihopQA"
CHAIN_PATH = "data/eobqa/obqa_chains.tsv.processed.tsv"
CHAIN_BLOB = "d17c485e51cc44944070d725ad297067d4817b0e"
CHAIN_BYTES = 311732
OBQA_SHA = "82368cf05df2e3b309c17d162e10b888b4d768fad6e171e0a041954c8553be46"
OBQA_BYTES = 1446098
OBQA_URL = "https://s3-us-west-2.amazonaws.com/ai2-website/data/OpenBookQA-V1-Sep2018.zip"
HEADER = "QID\tChain#\tTag\tQuestion\tAnswer\tFact1\tFact2\tWOL score\tTurk\tTurks\tExtra Facts\tDF"
LIMITS = {"train": 8, "capability": 8, "transfer": 4, "retention": 4}
PROFILE = "hepta.publisher-unanimous-necessity.v1"


def normalized(text):
    return " ".join(text.casefold().split())


def root_of(text):
    return "eobqa-fact:" + sha(normalized(text).encode())


def verified_chains(raw):
    git_blob = hashlib.sha1(
        b"blob " + str(len(raw)).encode() + b"\0" + raw
    ).hexdigest()
    if len(raw) != CHAIN_BYTES or git_blob != CHAIN_BLOB:
        raise ValueError("published chain bytes differ from immutable Git blob")
    return parse_chains(raw)


def parse_chains(raw):
    if len(raw) > 1024 * 1024:
        raise ValueError("chain byte bound")
    lines = raw.decode("utf-8", "strict").splitlines()
    if not lines or lines[0] != HEADER:
        raise ValueError("original chain schema required")
    fields, records, seen = HEADER.split("\t"), [], set()
    for line_number, line in enumerate(lines[1:], 2):
        cells = line.split("\t")
        if len(cells) != len(fields) or any(len(s.encode()) > 16384 for s in cells):
            raise ValueError("malformed original chain row")
        row = dict(zip(fields, cells, strict=True))
        key = (row["QID"], row["Chain#"])
        if not all(key) or key in seen:
            raise ValueError("duplicate original question/chain identity")
        seen.add(key)
        records.append(dict(line=line_number, raw_sha256=sha(line.encode()), row=row))
    if not records or len(records) > 2000:
        raise ValueError("chain census bound")
    return records


def verified_questions(raw):
    if len(raw) != OBQA_BYTES or sha(raw) != OBQA_SHA:
        raise ValueError("original OpenBookQA archive checksum")
    name = "OpenBookQA-V1-Sep2018/Data/Main/test.jsonl"
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        matches = [i for i in archive.infolist() if i.filename == name]
        if len(matches) != 1 or not 1 <= matches[0].file_size <= 2 * 1024 * 1024:
            raise ValueError("unique bounded original question file required")
        content = archive.read(matches[0])
    questions = [parse_json(s) for s in content.decode("utf-8").splitlines()]
    by_id = {r["id"]: r for r in questions}
    if len(questions) != 500 or len(by_id) != 500:
        raise ValueError("complete original 500-question census required")
    for row in questions:
        q = row["question"]
        choices = q["choices"]
        if (
            not isinstance(q["stem"], str)
            or not q["stem"].strip()
            or len(choices) != 4
            or {c["label"] for c in choices} != set("ABCD")
            or row["answerKey"] not in set("ABCD")
            or any(not isinstance(c["text"], str) or not c["text"].strip() for c in choices)
        ):
            raise ValueError("invalid original question/options")
    return by_id, content


def decision(record, questions):
    r = record["row"]
    q = questions.get(r["QID"])
    if q is None or r["Tag"] != "test":
        return "unresolved_original_question"
    if normalized(r["Question"]) != normalized(q["question"]["stem"]):
        return "original_question_mismatch"
    answer = next(c["text"] for c in q["question"]["choices"] if c["label"] == q["answerKey"])
    if normalized(answer) != normalized(r["Answer"]):
        return "original_answer_mismatch"
    if r["Turk"] != "yes" or r["Turks"].split() != ["yes", "yes", "yes"]:
        return "not_unanimous_two_fact_judgement"
    if r["Extra Facts"].strip() != "NIL":
        return "unprovided_extra_requirement"
    if any(not r[k].strip() or "\0" in r[k] or len(r[k].encode()) > 4096 for k in ("Fact1", "Fact2")):
        return "invalid_source_sentence"
    if root_of(r["Fact1"]) == root_of(r["Fact2"]):
        return "identical_facts_not_two_requirements"
    return "eligible_published_unanimous_claim"


def select(records, questions):
    dispositions, eligible = [], []
    for record in records:
        status = decision(record, questions)
        dispositions.append(record | {"status": status})
        if status == "eligible_published_unanimous_claim":
            eligible.append(record)
    # Coalesce shared facts/questions BEFORE splitting; do not count variants as
    # independent families or leak an alternative approved chain across phases.
    parent = {r["row"]["QID"]: r["row"]["QID"] for r in eligible}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owners = {}
    for record in eligible:
        r = record["row"]
        qid = r["QID"]
        keys = ["q:" + normalized(r["Question"]), root_of(r["Fact1"]), root_of(r["Fact2"])]
        for key in keys:
            if key in owners:
                a, b = find(qid), find(owners[key])
                parent[max(a, b)] = min(a, b)
            owners[key] = qid
    groups = {}
    for record in eligible:
        groups.setdefault(find(record["row"]["QID"]), []).append(record)
    representatives = []
    for group in groups.values():
        ids = sorted({r["row"]["QID"] for r in group})
        chosen = min(group, key=lambda r: digest(r["row"]))
        representatives.append(chosen | {"family": "eobqa-group:" + digest(ids)})
    representatives.sort(key=lambda r: digest((PROFILE, r["family"])))
    counts = dict(Counter(r["status"] for r in dispositions))
    census = dict(
        original_chains=len(records), original_questions=len(questions),
        statuses=counts, unanimous_components=len(representatives),
        original_test_repurposed_as_development=True, independent_samples_certified=False,
    )
    if len(representatives) < sum(LIMITS.values()):
        return None, dispositions, census
    result, offset = {}, 0
    for phase, count in LIMITS.items():
        result[phase] = representatives[offset:offset + count]
        offset += count
    census["selected_counts"] = LIMITS
    census["unused_eligible_components"] = len(representatives) - offset
    return result, dispositions, census


def make_case(record, question, noise, acquired_at, phase):
    r = record["row"]
    facts = [r["Fact1"], r["Fact2"], *noise]
    if len(facts) > 8 or len({root_of(s) for s in facts}) != len(facts):
        raise ValueError("distinct bounded evidence view")
    scope = "eobqa:" + r["QID"]
    options = "\n".join(f"({c['label']}) {c['text']}" for c in question["question"]["choices"])
    text = question["question"]["stem"] + "\nOriginal answer options:\n" + options
    text += "\nGive the answer text, not just its option letter."
    q = Question(scope, record["family"], scope, text, acquired_at)
    docs = tuple(Document("eobqa-sentence:" + sha(t.encode()), root_of(t), scope,
                          "publisher-chain", acquired_at, t) for t in facts)
    frontier = digest([asdict(d) for d in docs])
    spans = tuple(EvidenceSpan(d.identity, d.root, d.scope, d.session, d.observed_at,
                              0, len(d.content.encode()), d.content, digest(d.content)) for d in docs)
    selections = {
        "publisher_pair": spans[:2], "pair_reversed": tuple(reversed(spans[:2])),
        "without_fact1": spans[1:2], "without_fact2": spans[:1],
        "noise_before": spans[2:4] + spans[:2], "noise_after": spans[:2] + spans[2:4],
        "empty": (),
    }
    conditions = {}
    for name, selected in selections.items():
        bundle = EvidenceBundle(digest(asdict(q)), frontier, selected, name)
        bundle.validate(q, {d.identity: d for d in docs}, frontier=frontier, revoked=set())
        conditions[name] = dict(
            bundle=asdict(bundle), bundle_digest=bundle.seal(),
            delivered_evidence=bundle.delivered(), token_limit=2048,
            oracle_kind="published_unanimous_chain_claim_not_Hepta_certificate",
            review_row_sha256=record["raw_sha256"], world_answerability_unchanged=True,
            independent_review=False, sufficient_context_certified=False,
        )
    case = dict(question=asdict(q), phase=phase, family=record["family"],
                originals=[asdict(d) for d in docs], frontier=frontier, conditions=conditions,
                source_time_kind="download_observation_not_fact_validity")
    label = dict(answer=r["Answer"], unanswerable=False,
                 support_roots=[root_of(r[k]) for k in ("Fact1", "Fact2")],
                 publication_review=record, reviewed_at=None,
                 necessary_requirements_claimed_by="three_original_affirmative_votes",
                 original_question_sha256=digest(question), production_accepted=False)
    return case, label


def prepare(output, source_commit):
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("exact implementation source required")
    output.mkdir()
    urls = {
        "reviews.tsv": (f"https://raw.githubusercontent.com/{REPOSITORY}/{REVISION}/{CHAIN_PATH}", CHAIN_BYTES),
        "openbookqa.zip": (OBQA_URL, OBQA_BYTES),
    }
    data = {}
    for name, (url, size) in urls.items():
        with urllib.request.urlopen(url, timeout=90) as response:
            data[name] = response.read(size + 1)
        (output / name).write_bytes(data[name])
    records = verified_chains(data["reviews.tsv"])
    questions, original = verified_questions(data["openbookqa.zip"])
    (output / "original-test.jsonl").write_bytes(original)
    selected, dispositions, census = select(records, questions)
    write(output / "acquisition-census.json", census)
    write(output / "all-review-dispositions.json", dispositions)
    print(__import__("json").dumps(census, indent=2))
    if selected is None:
        raise ValueError("insufficient unanimous disjoint chains; fixed horizon not reduced")
    acquired = datetime.now(timezone.utc).isoformat()
    cases, labels = [], {}
    for phase, members in selected.items():
        universe = sorted({r["row"][k] for r in members for k in ("Fact1", "Fact2")}, key=digest)
        for record in members:
            positive = {root_of(record["row"][k]) for k in ("Fact1", "Fact2")}
            noise = [t for t in universe if root_of(t) not in positive][:6]
            case, label = make_case(record, questions[record["row"]["QID"]], noise, acquired, phase)
            cases.append(case)
            labels[case["question"]["identity"]] = label
    plan = dict(schema="hepta.bundle-diagnostic.plan.v1", profile=PROFILE,
                source_commit=source_commit, cases=cases, frozen_counts=LIMITS,
                chain_blob=CHAIN_BLOB, dataset_sha256=sha(data["reviews.tsv"]),
                original_question_archive_sha256=OBQA_SHA, acquisition_time=acquired,
                data_selection_before_model_execution=True, prospective_windows=0,
                publisher_test_repurposed_for_development=True,
                publisher_review_not_independent_Hepta_acceptance=True,
                production_accepted=False)
    write(output / "plan.json", plan)
    write(output / "labels.json", labels)
    write(output / "provenance.json", dict(
        repository=REPOSITORY, revision=REVISION, chain_path=CHAIN_PATH,
        chain_git_blob=CHAIN_BLOB, chain_sha256=sha(data["reviews.tsv"]),
        question_sha256=OBQA_SHA, license="CC-BY-4.0 (eOBQA annotations)",
        attribution="Harsh Jhamtani and Peter Clark, Learning to Explain, EMNLP 2020; OpenBookQA, Mihaylov et al., EMNLP 2018",
        acquisition_time=acquired, reviewer_ids=None, original_review_time=None,
        publication_judgements_are_fallible=True, independent_acceptance=False))
    write(output / "READY.json", dict(plan_sha256=sha((output / "plan.json").read_bytes()),
                                      labels_sha256=sha((output / "labels.json").read_bytes()),
                                      production_accepted=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    prepare(args.output, args.source_commit)
