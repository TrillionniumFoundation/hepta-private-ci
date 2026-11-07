"""Human-authored SQuAD reading tasks, with public input and offline gold split.

Integrity and answer-span checks supply development material, not independent
confirmation, prior-capability retention, or a general domain-evaluator pass.
"""

from collections import Counter
import codecs
import hashlib
import json
import re
import time

from .materials import _read, _strict_json, _text, check_file
from .state import exact_fields, sha256_value


SCHEMA = "hepta.squad-text-candidates.v1"
HISTORY_SCHEMA = "hepta.squad-source-history.v1"
SOURCE_URL = "https://rajpurkar.github.io/SQuAD-explorer/dataset/train-v1.1.json"
SELECTOR = {
    "complete_articles": 6,
    "train_articles": 3,
    "questions_per_article": 3,
    "order": "original_file_order_no_outcome_filter",
}


def _verify_http_material(root, receipt, source, prefix, tail):
    if (
        receipt["schema"] != "hepta.bounded-material-increment.v1"
        or receipt["status"] != "completed"
        or receipt["shared_cap_bytes"] != 25 * 1024**2
    ):
        raise ValueError("A completed original cumulative HTTP receipt is required")
    quantities = [
        receipt[name]
        for name in (
            "prior_body_bytes",
            "new_body_bytes",
            "cumulative_body_bytes",
            "reservation_bytes",
        )
    ]
    quantities += [row["bytes_read"] for row in receipt["attempts"]]
    if any(type(value) is not int or value < 0 for value in quantities):
        raise ValueError("Exact nonnegative HTTP body counters required")
    body_sum = sum(row["bytes_read"] for row in receipt["attempts"])
    if (
        receipt["new_body_bytes"] != body_sum
        or receipt["cumulative_body_bytes"] != receipt["prior_body_bytes"] + body_sum
        or not body_sum <= receipt["reservation_bytes"] <= 786560
        or receipt["cumulative_body_bytes"] > receipt["shared_cap_bytes"]
    ):
        raise ValueError("Cumulative source cost ledger does not reconcile")
    chunks, observed_tail = [], None
    for row in receipt["attempts"]:
        if (
            row["status"] != "completed"
            or row["url"] != SOURCE_URL
            or row["final_url"] != SOURCE_URL
        ):
            raise ValueError("Source acquisition contains an unmatched request")
        if row["method"] == "HEAD":
            if row["bytes_read"] != 0:
                raise ValueError("HEAD cannot hide unregistered body exposure")
            continue
        first, last = row["span"]
        if (
            row["http_status"] != 206
            or row["headers"]["etag"] != source["etag"]
            or row["headers"]["content-range"]
            != f"bytes {first}-{last}/{source['content_length']}"
        ):
            raise ValueError("Source response version/range differs")
        body = check_file(root, row["body"], limit=786432)
        if (
            len(body) != last - first + 1
            or len(body) != row["bytes_read"]
            or hashlib.sha256(body).hexdigest() != row["sha256"]
        ):
            raise ValueError("Source HTTP body length differs")
        if first == source["content_length"] - len(tail) and observed_tail is None:
            observed_tail = body
        elif first == sum(len(item) for item in chunks):
            chunks.append(body)
        else:
            raise ValueError("Source prefix ranges overlap, leave gaps or change order")
    if b"".join(chunks) != prefix or observed_tail != tail:
        raise ValueError("Candidate source bytes differ from original HTTP bodies")


def complete_articles(prefix):
    """Return complete original article objects and exact UTF-8 byte ranges."""
    text = codecs.getincrementaldecoder("utf-8")().decode(prefix, final=False)
    match = re.match(r'\s*\{\s*"data"\s*:\s*\[', text)
    if match is None:
        raise ValueError("Expected the pinned SQuAD data-array layout")
    cursor, rows, decoder = match.end(), [], json.JSONDecoder()
    while cursor < len(text):
        while cursor < len(text) and text[cursor] in " \r\n\t":
            cursor += 1
        if cursor >= len(text) or text[cursor] == "]":
            break
        if text[cursor] != "{":
            raise ValueError("Malformed original article-array prefix")
        start = cursor
        try:
            row, cursor = decoder.raw_decode(text, cursor)
        except json.JSONDecodeError:
            break
        if not isinstance(row, dict) or set(row) != {"title", "paragraphs"}:
            raise ValueError("Unexpected original article structure")
        first, end = len(text[:start].encode()), len(text[:cursor].encode())
        raw = prefix[first:end]
        if _strict_json(raw) != row:
            raise ValueError("Original byte-range/record mismatch")
        rows.append(
            {
                "record": row,
                "first_byte": first,
                "last_byte": end - 1,
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
        while cursor < len(text) and text[cursor] in " \r\n\t":
            cursor += 1
        if cursor < len(text) and text[cursor] == ",":
            cursor += 1
        elif cursor < len(text) and text[cursor] != "]":
            raise ValueError("Malformed original article-array separator")
    return rows


def _validate_reference(context, original):
    exact_fields(original, ("answers", "question", "id"), "original human question")
    _text(original["id"], "question identity")
    _text(original["question"], "question text")
    if not isinstance(original["answers"], list) or not original["answers"]:
        raise ValueError("Original nonempty human answers required")
    for answer in original["answers"]:
        exact_fields(answer, ("answer_start", "text"), "original answer span")
        start, text = answer["answer_start"], _text(answer["text"], "answer text")
        if (
            type(start) is not int
            or start < 0
            or context[start : start + len(text)] != text
        ):
            raise ValueError(
                "Human answer is not the exact span in the original context"
            )


def load_text_observation(root, case):
    """Return the original context and question only; no roles, IDs, or answers."""
    public = _strict_json(check_file(root, case["public"], limit=1024**2))
    exact_fields(public, ("context", "question"), "public reading observation")
    return {name: _text(public[name], name) for name in ("context", "question")}


def admit_text_pool(root, *, expected_manifest_sha256, expected_history_sha256):
    started = time.process_time(), time.perf_counter()
    raw, manifest_sha, _ = _read(root, "CANDIDATES.json", 8 * 1024**2)
    history_raw, history_sha, _ = _read(root, "HISTORY.json", 8 * 1024**2)
    if manifest_sha != sha256_value(
        expected_manifest_sha256, "manifest pin"
    ) or history_sha != sha256_value(expected_history_sha256, "history pin"):
        raise ValueError("Text source manifest/history differs from external pins")
    manifest, history = _strict_json(raw), _strict_json(history_raw)
    exact_fields(
        manifest,
        ("schema", "source", "plan", "history_sha256", "acquisition_receipt", "cases"),
        "text manifest",
    )
    exact_fields(
        history,
        (
            "schema",
            "upstream_release",
            "confirmation_use",
            "articles",
            "cases",
            "exposed_ranges",
        ),
        "text history",
    )
    if (
        manifest["schema"] != SCHEMA
        or history["schema"] != HISTORY_SCHEMA
        or manifest["history_sha256"] != history_sha
    ):
        raise ValueError("Unrecognized text source schema or history binding")
    if (
        history["confirmation_use"]
        != "forbidden_for_this_exposed_upstream_train_release"
    ):
        raise ValueError("The exposed source release cannot supply confirmation")
    plan = _strict_json(check_file(root, manifest["plan"], limit=2 * 1024**2))
    receipt = _strict_json(
        check_file(root, manifest["acquisition_receipt"], limit=2 * 1024**2)
    )
    if plan.get("selector") != SELECTOR:
        raise ValueError("The prospective source/role selector differs")
    if (
        plan["prior_receipt_sha256"] != receipt["prior_receipt_sha256"]
        or plan["prior_body_bytes"] != receipt["prior_body_bytes"]
    ):
        raise ValueError("The prospective cumulative budget binding differs")
    source = manifest["source"]
    exact_fields(
        source,
        (
            "url",
            "release",
            "etag",
            "content_length",
            "prefix",
            "release_tail",
            "whole_file_sha256",
            "license_url",
            "attribution",
        ),
        "upstream source",
    )
    if (
        source["url"] != SOURCE_URL
        or source["release"] != "SQuAD v1.1"
        or source["whole_file_sha256"] is not None
        or source["license_url"] != "https://creativecommons.org/licenses/by-sa/4.0/"
    ):
        raise ValueError("Unexpected source release or license contract")
    if (
        history["upstream_release"] != SOURCE_URL
        or not isinstance(source["etag"], str)
        or source["etag"].startswith("W/")
        or not source["etag"].startswith('"')
        or type(source["content_length"]) is not int
    ):
        raise ValueError("Strong source identity and known byte length required")
    prefix = check_file(root, source["prefix"], limit=1024**2)
    tail = check_file(root, source["release_tail"], limit=1024)
    if not re.search(rb'"version"\s*:\s*"1\.1"\s*}\s*$', tail):
        raise ValueError("The pinned source tail must declare version 1.1")
    if history["exposed_ranges"] != [
        [0, len(prefix) - 1],
        [source["content_length"] - len(tail), source["content_length"] - 1],
    ]:
        raise ValueError("Exposure history must bind every consumed source range")
    _verify_http_material(root, receipt, source, prefix, tail)
    parsed = complete_articles(prefix)
    if len(parsed) < SELECTOR["complete_articles"] or len(history["articles"]) != len(
        parsed
    ):
        raise ValueError(
            "Incomplete selected cohort or omitted exposed article history"
        )
    roles, registered, titles, source_digests = {}, {}, {}, {}
    paragraph_roles = {}
    expected_cases = []
    for index, article in enumerate(history["articles"]):
        exact_fields(
            article, ("group_id", "title", "role", "original"), "article history"
        )
        group = _text(article["group_id"], "source group")
        if (
            group
            != "squad1.1:article:"
            + hashlib.sha256(article["title"].encode()).hexdigest()
        ):
            raise ValueError("Stable upstream article identity required")
        if group in roles or article["role"] not in {
            "train",
            "development",
            "excluded_exposed",
        }:
            raise ValueError("Duplicate article or unsupported role")
        roles[group] = article["role"]
        original = _strict_json(
            check_file(root, article["original"], limit=2 * 1024**2)
        )
        expected_role = (
            "train" if index < 3 else "development" if index < 6 else "excluded_exposed"
        )
        if (
            article["original"]["sha256"] != parsed[index]["sha256"]
            or article["role"] != expected_role
        ):
            raise ValueError(
                "Article bytes/order/role differs from prospective source selection"
            )
        if original["title"] != article["title"] or original["title"] in titles:
            raise ValueError("Article identity or duplicated source title differs")
        titles[original["title"]] = group
        source_digests[group] = original
        flat = []
        for p, paragraph in enumerate(original["paragraphs"]):
            context_sha = hashlib.sha256(paragraph["context"].encode()).hexdigest()
            if expected_role != "excluded_exposed":
                if (
                    context_sha in paragraph_roles
                    and paragraph_roles[context_sha] != expected_role
                ):
                    raise ValueError(
                        "Identical context crosses source roles in full history"
                    )
                paragraph_roles[context_sha] = expected_role
            flat.extend((qa["id"], p, q) for q, qa in enumerate(paragraph["qas"]))
        if index < 6:
            if len(flat) < 3:
                raise ValueError("Incomplete article question roster")
            expected_cases.extend(
                ("squad1.1:" + identity, group, p, q, expected_role)
                for identity, p, q in flat[:3]
            )
    for case in history["cases"]:
        exact_fields(
            case,
            (
                "id",
                "source_group_id",
                "episode_group_id",
                "paragraph_index",
                "question_index",
                "project_split",
                "public",
                "reference",
            ),
            "text case",
        )
        if (
            case["id"] in registered
            or roles.get(case["source_group_id"]) != case["project_split"]
            or case["project_split"] not in {"train", "development"}
        ):
            raise ValueError(
                "Repeated identity or source group crosses/reassigns roles"
            )
        registered[case["id"]] = case
    roster = [
        (
            c["id"],
            c["source_group_id"],
            c["paragraph_index"],
            c["question_index"],
            c["project_split"],
        )
        for c in history["cases"]
    ]
    if roster != expected_cases or manifest["cases"] != history["cases"]:
        raise ValueError("Missing, reordered or changed prospective question roster")
    selected = set()
    for case in manifest["cases"]:
        if case["id"] in selected or registered.get(case["id"]) != case:
            raise ValueError("Selection changes a historical source/reference binding")
        selected.add(case["id"])
        source = source_digests[case["source_group_id"]]
        p, q = case["paragraph_index"], case["question_index"]
        if type(p) is not int or type(q) is not int or p < 0 or q < 0:
            raise ValueError("Original nonnegative paragraph/question indices required")
        paragraph = source["paragraphs"][p]
        original = paragraph["qas"][q]
        public = load_text_observation(root, case)
        reference = _strict_json(check_file(root, case["reference"], limit=1024**2))
        if (
            public
            != {"context": paragraph["context"], "question": original["question"]}
            or reference != original
            or case["id"] != "squad1.1:" + original["id"]
        ):
            raise ValueError("Public text or gold differs from original human material")
        if case["episode_group_id"] != case["source_group_id"] + ":paragraph:" + str(p):
            raise ValueError("Episode grouping must retain the original paragraph")
        _validate_reference(public["context"], reference)
    return {
        "schema": "hepta.squad-text-admission.v1",
        "manifest_sha256": manifest_sha,
        "history_sha256": history_sha,
        "case_counts": dict(Counter(c["project_split"] for c in manifest["cases"])),
        "source_article_groups": len({c["source_group_id"] for c in manifest["cases"]}),
        "human_answer_spans_verified": True,
        "candidate_task_family": "text_sufficient",
        "independently_reviewed_task_families": [],
        "pretraining_exposure": "unknown",
        "independent_cluster_count": None,
        "confirmation_cases": 0,
        "retention_cases": 0,
        "online_reference_access": "API projection excludes gold; OS isolation is unverified",
        "scientific_admission": False,
        "research_status": "HOLD",
        "cpu_seconds": time.process_time() - started[0],
        "wall_seconds": time.perf_counter() - started[1],
        "unknown_costs": ["energy", "charges", "outer process and final receipt write"],
    }
