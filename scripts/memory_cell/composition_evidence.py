"""Pinned publisher sentence compositions, not self-issued minimality reviews.

QASC's original fact1/fact2 annotations provide SHORT supporting candidates.
The combined fact and answer key never enter a model prompt or retrieval query.
Deleting a publisher fact is an intervention, not a new unanswerable gold label.
Full independently reviewed bundles may still be attached by reviewed_bundle.
"""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile
import urllib.request

from evidence_bundle import EvidenceBundle, EvidenceSpan
from native import Document, Question, digest

ARCHIVE_SHA = "a7b3f2244f768974c609fd621346c931a72715609f171cb5544fc1da2a2ad55c"
ARCHIVE_BYTES = 1616514
URL = "https://data.allenai.org/downloads/qasc/qasc_dataset.tar.gz"
PIN_SOURCE = "huggingface/datasets@1.18.4:datasets/qasc/dataset_infos.json"
EXPECTED_ROWS = {"train": 8134, "dev": 926}
LIMITS = {"train": 64, "capability": 8, "transfer": 8, "retention": 8}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def parse_json(text):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError("duplicate JSON key")
            out[key] = value
        return out

    def invalid(value):
        raise ValueError("nonfinite JSON: " + value)

    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)


def write(path, value):
    import os

    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def fact_root(text):
    # Conservative exact/case/whitespace grouping, not certified independence.
    return "qasc-fact:" + sha(" ".join(text.casefold().split()).encode())


def validate_row(row):
    if not isinstance(row, dict) or not isinstance(row.get("question"), dict):
        raise ValueError("QASC row shape")
    for value in (row.get("id"), row["question"].get("stem"), row.get("fact1"),
                  row.get("fact2"), row.get("combinedfact")):
        if not isinstance(value, str) or not value.strip() or "\0" in value:
            raise ValueError("missing original question/fact")
        if len(value.encode()) > 4096:
            raise ValueError("publisher field byte limit")
    choices = row["question"].get("choices")
    if not isinstance(choices, list) or len(choices) != 8:
        raise ValueError("eight original answer options required")
    if any(not isinstance(c, dict) or not isinstance(c.get("text"), str)
           or not c["text"].strip() or len(c["text"].encode()) > 1024
           or c.get("label") not in "ABCDEFGH" for c in choices):
        raise ValueError("invalid answer option")
    if {c["label"] for c in choices} != set("ABCDEFGH"):
        raise ValueError("duplicate/missing answer label")
    if row.get("answerKey") not in set("ABCDEFGH"):
        raise ValueError("missing publisher answer key")
    if fact_root(row["fact1"]) == fact_root(row["fact2"]):
        raise ValueError("duplicate facts cannot supply two removable requirements")
    return row


def unpack(raw):
    if len(raw) != ARCHIVE_BYTES or sha(raw) != ARCHIVE_SHA:
        raise ValueError("original QASC archive pin mismatch")
    rows, files = {}, {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for split, count in EXPECTED_ROWS.items():
            name = "QASC_Dataset/" + split + ".jsonl"
            members = [m for m in archive.getmembers() if m.name == name]
            if len(members) != 1 or not members[0].isfile():
                raise ValueError("unique regular publisher split required")
            if not 1 <= members[0].size <= 16 * 1024 * 1024:
                raise ValueError("expanded split size limit")
            data = archive.extractfile(members[0]).read(16 * 1024 * 1024 + 1)
            values = [parse_json(line) for line in data.decode("utf-8").splitlines()]
            if len(values) != count or len({r["id"] for r in values}) != count:
                raise ValueError("complete publisher split census mismatch")
            # No filesystem extraction and no test-set labels are manufactured.
            rows[split], files[split] = values, data
    return rows, files


def split_rows(rows):
    """Freeze membership before generation; report unusable rows, never resample scores."""
    selected = {phase: [] for phase in LIMITS}
    used_ids, used_roots, exclusions = set(), set(), []
    for phase, original_split in (("capability", "dev"), ("transfer", "dev"),
                                  ("retention", "dev"), ("train", "train")):
        for row in sorted(rows[original_split], key=lambda r: digest(r["id"])):
            if row["id"] in used_ids:
                continue
            try:
                validate_row(row)
            except (ValueError, KeyError, TypeError) as error:
                exclusions.append(dict(phase=phase, id=row.get("id"),
                                       reason=str(error), before_model_execution=True))
                continue
            roots = {fact_root(row[k]) for k in ("fact1", "fact2")}
            if roots & used_roots:
                exclusions.append(dict(phase=phase, id=row["id"],
                                       reason="shared_fact_root", before_model_execution=True))
                continue
            selected[phase].append(row)
            used_ids.add(row["id"])
            used_roots.update(roots)
            if len(selected[phase]) == LIMITS[phase]:
                break
        if len(selected[phase]) != LIMITS[phase]:
            raise ValueError("insufficient disjoint publisher rows for frozen profile")
    return selected, exclusions


def make_case(row, noise, acquired_at, phase):
    """Answers are a SEPARATE return value. Original fact strings are unmodified."""
    validate_row(row)
    texts = [row["fact1"], row["fact2"], *noise]
    if len(texts) > 8 or len({fact_root(t) for t in texts}) != len(texts):
        raise ValueError("bounded distinct evidence candidates required")
    scope = "qasc:" + row["id"]
    query = Question(scope, scope, scope, row["question"]["stem"], acquired_at)
    documents = tuple(Document("qasc-sentence:" + sha(t.encode()), fact_root(t),
                               scope, "publisher-sentence", acquired_at, t) for t in texts)
    original = {d.identity: d for d in documents}
    frontier = digest([asdict(d) for d in documents])
    spans = tuple(EvidenceSpan(d.identity, d.root, d.scope, d.session, d.observed_at,
                              0, len(d.content.encode()), d.content, digest(d.content))
                  for d in documents)
    conditions = {}
    selections = {
        "publisher_pair": spans[:2],
        "without_fact1": spans[1:2],
        "without_fact2": spans[:1],
        "pair_reversed": tuple(reversed(spans[:2])),
        "noise_before": spans[2:4] + spans[:2],
        "noise_after": spans[:2] + spans[2:4],
        "empty": (),
    }
    for name, chosen in selections.items():
        bundle = EvidenceBundle(digest(asdict(query)), frontier, chosen, name)
        bundle.validate(query, original, frontier=frontier, revoked=set())
        conditions[name] = dict(bundle=asdict(bundle), bundle_digest=bundle.seal(),
            delivered_evidence=bundle.delivered(), token_limit=2048,
            oracle_kind="publisher_composition_candidate_not_minimality_certificate",
            independent_review=False, sufficient_context_certified=False,
            world_answerability_unchanged=True)
    labels = {c["label"]: c["text"] for c in row["question"]["choices"]}
    target = dict(answer=labels[row["answerKey"]], unanswerable=False,
        support_roots=[fact_root(row["fact1"]), fact_root(row["fact2"])],
        original_annotation_digest=digest(row), combinedfact=row["combinedfact"],
        choices=row["question"]["choices"], original_answer_key=row["answerKey"])
    case = dict(question=asdict(query), phase=phase, family=scope,
        originals=[asdict(d) for d in documents], frontier=frontier, conditions=conditions,
        source_time_kind="actual_download_observation_not_fact_valid_time",
        sampling_unit_independence_certified=False)
    return case, target


def prepare(root, *, source_commit):
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("exact implementation commit required")
    root.mkdir()
    error = None
    for url in (URL, URL.replace("https:", "http:")):
        try:
            with urllib.request.urlopen(url, timeout=90) as response:
                raw = response.read(ARCHIVE_BYTES + 1)
            rows, files = unpack(raw)
            break
        except Exception as failure:
            error = failure
    else:
        raise ValueError("publisher download or fixed checksum failed") from error
    acquired = datetime.now(timezone.utc).isoformat()
    (root / "qasc_dataset.tar.gz").write_bytes(raw)
    selected, exclusions = split_rows(rows)
    for split, data in files.items():
        (root / (split + ".jsonl")).write_bytes(data)
    cases, labels = [], {}
    for phase, members in selected.items():
        # Noise only from this phase, and never duplicated within a question.
        universe = sorted({r[k] for r in members for k in ("fact1", "fact2")},
                          key=digest)
        for row in members:
            positive = {fact_root(row[k]) for k in ("fact1", "fact2")}
            noise = [s for s in universe if fact_root(s) not in positive][:6]
            case, target = make_case(row, noise, acquired, phase)
            cases.append(case)
            labels[case["question"]["identity"]] = target
    plan = dict(schema="hepta.bundle-diagnostic.plan.v1", source_commit=source_commit,
        cases=cases, dataset_sha256=ARCHIVE_SHA, acquisition_time=acquired,
        profile="qasc-publisher-sentence-composition-v1", free_answer_not_official_mcq=True,
        publisher_split_counts=EXPECTED_ROWS, frozen_counts=LIMITS,
        reader_training=False, prospective_windows=0, production_accepted=False)
    write(root / "plan.json", plan)
    write(root / "labels.json", labels)
    write(root / "exclusions.json", exclusions)
    write(root / "provenance.json", dict(url=url, bytes=len(raw), sha256=ARCHIVE_SHA,
        checksum_source=PIN_SOURCE, acquired_at=acquired, license="CC-BY-4.0",
        attribution="QASC: Khot, Clark, Guerquin, Jansen and Sabharwal, AAAI 2020",
        independent_semantic_review=False, minimality_certified=False,
        annotation_strings_are_not_observations_of_new_events=True))
    write(root / "READY.json", dict(plan_sha256=sha((root / "plan.json").read_bytes()),
        labels_sha256=sha((root / "labels.json").read_bytes()), production_accepted=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    prepare(args.output, source_commit=args.source_commit)
