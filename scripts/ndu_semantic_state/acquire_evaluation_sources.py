"""Serial, bounded additions to the existing material ledger; never a new cap."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import time
import zipfile

from .bounded_source_http import BoundedSourceHTTP
from .materials import _strict_json
from .review_packet import _json_bytes, _write
from .text_sources import (
    HISTORY_SCHEMA,
    SCHEMA,
    SELECTOR,
    SOURCE_URL,
    admit_text_pool,
    complete_articles,
)


VQA_URL = "https://vizwiz.cs.colorado.edu/VizWiz_final/vqa_data/API.zip"
VQA_ETAG = '"b100d2d-5f706f9ea99e6"'
VQA_BYTES = 185601325
VQA_SHA256 = "d26ef7ac2db06351444c3531f8d95fd9c454423fbcb9fd5dd984f12281146694"


class PinnedArchive(io.RawIOBase):
    def __init__(self, budget, url, total, etag):
        self.budget, self.url, self.total, self.etag, self.position = (
            budget,
            url,
            total,
            etag,
            0,
        )

    def seek(self, offset, whence=0):
        position = offset + (
            0 if whence == 0 else self.position if whence == 1 else self.total
        )
        if whence not in (0, 1, 2) or not 0 <= position <= self.total:
            raise ValueError("Invalid archive seek")
        self.position = position
        return position

    def tell(self):
        return self.position

    def read(self, size=-1):
        size = min(self.total - self.position, size if size >= 0 else self.total)
        if not size:
            return b""
        data, _ = self.budget.fetch(
            self.url,
            span=(self.position, self.position + size - 1),
            etag=self.etag,
            total=self.total,
        )
        self.position += len(data)
        return data

    def seekable(self):
        return True


def _prior(path, expected, field):
    raw = Path(path).read_bytes()
    if len(raw) > 2 * 1024**2 or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("Prior cumulative receipt differs from the external pin")
    row = _strict_json(raw)
    if row.get("status") not in {
        "prepared",
        "completed",
        "failed",
        "Failed",
        "succeeded",
    }:
        raise ValueError("An unresolved prior acquisition cannot release its budget")
    for name in field.split("."):
        row = row[name]
    if type(row) is not int:
        raise ValueError("Prior cumulative total must be an integer")
    return row


def acquire_vqa(root, budget):
    plan = {
        "schema": "hepta.official-vqa-evaluator-acquisition.v1",
        "url": VQA_URL,
        "etag": VQA_ETAG,
        "archive_bytes": VQA_BYTES,
        "reservation_bytes": budget.reservation,
        "selector": "unique PythonEvaluationTools/vqaEvaluation/vqaEval.py member only",
        "started_unix": time.time(),
        "expected_member_sha256": VQA_SHA256,
        "scientific_admission": False,
    }
    plan_binding = _write(root, "PLAN.json", _json_bytes(plan))
    _, head = budget.fetch(VQA_URL, head=True)
    if (
        int(head["headers"]["content-length"]) != VQA_BYTES
        or head["headers"]["etag"] != VQA_ETAG
    ):
        raise ValueError("Official evaluator archive identity changed")
    with zipfile.ZipFile(
        PinnedArchive(budget, VQA_URL, VQA_BYTES, VQA_ETAG)
    ) as archive:
        members = [
            m
            for m in archive.infolist()
            if m.filename.endswith("PythonEvaluationTools/vqaEvaluation/vqaEval.py")
            and not m.filename.startswith("__MACOSX/")
        ]
        if len(members) != 1 or members[0].file_size > 65536:
            raise ValueError("A unique bounded upstream evaluator source is required")
        member = members[0]
        raw = archive.read(member)
        binding = _write(root, "vqaEval.py", raw)
        if binding["sha256"] != VQA_SHA256:
            raise ValueError(
                "Official evaluator source differs from the prospective pin"
            )
        license_members = [
            m.filename
            for m in archive.infolist()
            if Path(m.filename).name.lower().startswith(("license", "copying"))
        ]
    result = {
        "schema": "hepta.official-vizwiz-source-lock.v1",
        "plan": plan_binding,
        "archive_url": VQA_URL,
        "archive_etag": VQA_ETAG,
        "archive_bytes": VQA_BYTES,
        "whole_archive_sha256": None,
        "member_name": member.filename,
        "member_crc32": member.CRC,
        "source": binding,
        "license_member_names_only": license_members,
        "upstream_source_published_publicly": False,
        "independent_reference_component_only": True,
        "five_family_evaluator_qualified": False,
    }
    _write(root, "SOURCE_LOCK.json", _json_bytes(result))
    return result


def acquire_squad(root, budget):
    _, head = budget.fetch(SOURCE_URL, head=True)
    total, etag = int(head["headers"]["content-length"]), head["headers"]["etag"]
    if not etag.startswith('"') or etag.startswith("W/") or total <= 786432:
        raise ValueError("Strong source version and bounded prefix profile required")
    plan = {
        "schema": "hepta.squad-text-acquisition-plan.v1",
        "source_url": SOURCE_URL,
        "release": "SQuAD v1.1",
        "etag": etag,
        "content_length": total,
        "selector": SELECTOR,
        "chunk_bytes": 131072,
        "prefix_cap_bytes": 786432,
        "tail_bytes": 128,
        "reservation_bytes": budget.reservation,
        "confirmation_use": "forbidden_for_this_exposed_upstream_train_release",
        "started_unix": time.time(),
        "prior_receipt_sha256": budget.prior_pin,
        "prior_body_bytes": budget.prior,
    }
    plan_binding = _write(root, "PLAN.json", _json_bytes(plan))
    tail, _ = budget.fetch(
        SOURCE_URL, span=(total - 128, total - 1), etag=etag, total=total
    )
    tail_binding = _write(root, "raw/release-tail.bin", tail)
    prefix, parsed = b"", []
    for first in range(0, 786432, 131072):
        part, _ = budget.fetch(
            SOURCE_URL, span=(first, first + 131071), etag=etag, total=total
        )
        prefix += part
        parsed = complete_articles(prefix)
        if len(parsed) >= SELECTOR["complete_articles"]:
            break
    prefix_binding = _write(root, "raw/source-prefix.json.part", prefix)
    if len(parsed) < SELECTOR["complete_articles"]:
        raise ValueError(
            "Bounded source prefix does not complete the predeclared article cohort"
        )
    articles, cases = [], []
    for index, item in enumerate(parsed):
        original = item["record"]
        role = (
            "train" if index < 3 else "development" if index < 6 else "excluded_exposed"
        )
        group = (
            "squad1.1:article:" + hashlib.sha256(original["title"].encode()).hexdigest()
        )
        original_binding = _write(
            root,
            f"private/articles/{index:04d}.json",
            prefix[item["first_byte"] : item["last_byte"] + 1],
        )
        articles.append(
            {
                "group_id": group,
                "title": original["title"],
                "role": role,
                "original": original_binding,
            }
        )
        if index >= 6:
            continue
        selected = [
            (p, q, paragraph, qa)
            for p, paragraph in enumerate(original["paragraphs"])
            for q, qa in enumerate(paragraph["qas"])
        ][:3]
        if len(selected) != 3:
            raise ValueError("Missing predeclared original question records")
        for p, q, paragraph, qa in selected:
            number = len(cases)
            public = _write(
                root,
                f"public/{number:04d}.json",
                _json_bytes(
                    {"context": paragraph["context"], "question": qa["question"]}
                ),
            )
            reference = _write(
                root, f"private/references/{number:04d}.json", _json_bytes(qa)
            )
            cases.append(
                {
                    "id": "squad1.1:" + qa["id"],
                    "source_group_id": group,
                    "episode_group_id": group + ":paragraph:" + str(p),
                    "paragraph_index": p,
                    "question_index": q,
                    "project_split": role,
                    "public": public,
                    "reference": reference,
                }
            )
    history = {
        "schema": HISTORY_SCHEMA,
        "upstream_release": SOURCE_URL,
        "confirmation_use": plan["confirmation_use"],
        "articles": articles,
        "cases": cases,
        "exposed_ranges": [[0, len(prefix) - 1], [total - 128, total - 1]],
    }
    history_binding = _write(root, "HISTORY.json", _json_bytes(history))
    budget.close_receipt("completed")
    receipt = (root / "ACQUISITION_RECEIPT.json").read_bytes()
    receipt_binding = {
        "path": "ACQUISITION_RECEIPT.json",
        "sha256": hashlib.sha256(receipt).hexdigest(),
        "bytes": len(receipt),
    }
    manifest = {
        "schema": SCHEMA,
        "source": {
            "url": SOURCE_URL,
            "release": "SQuAD v1.1",
            "etag": etag,
            "content_length": total,
            "prefix": prefix_binding,
            "release_tail": tail_binding,
            "whole_file_sha256": None,
            "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
            "attribution": "SQuAD v1.1; Rajpurkar, Zhang, Lopyrev and Liang; human questions over Wikipedia passages; dataset CC BY-SA 4.0; original article and QA content preserved.",
        },
        "plan": plan_binding,
        "history_sha256": history_binding["sha256"],
        "acquisition_receipt": receipt_binding,
        "cases": cases,
    }
    manifest_binding = _write(root, "CANDIDATES.json", _json_bytes(manifest))
    result = admit_text_pool(
        root,
        expected_manifest_sha256=manifest_binding["sha256"],
        expected_history_sha256=history_binding["sha256"],
    )
    _write(root, "ADMISSION.json", _json_bytes(result))
    return result


def main():
    started = time.process_time(), time.perf_counter()
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("vizwiz_evaluator", "squad"))
    parser.add_argument("--output", required=True)
    parser.add_argument("--prior-receipt", required=True)
    parser.add_argument("--prior-sha256", required=True)
    parser.add_argument("--prior-total-field", required=True)
    args = parser.parse_args()
    prior = _prior(args.prior_receipt, args.prior_sha256, args.prior_total_field)
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=False)
    budget = BoundedSourceHTTP(
        root,
        prior_body_bytes=prior,
        reservation_bytes=262144 if args.kind == "vizwiz_evaluator" else 786560,
        prior_receipt_sha256=args.prior_sha256,
    )
    try:
        result = (acquire_vqa if args.kind == "vizwiz_evaluator" else acquire_squad)(
            root, budget
        )
    except BaseException:
        budget.close_receipt("failed")
        raise
    # SQuAD admission pins its completed acquisition receipt; never rewrite it.
    if args.kind == "vizwiz_evaluator":
        budget.close_receipt("completed")
    _write(
        root,
        "OPERATION_RESULT.json",
        _json_bytes(
            {
                "status": "completed",
                "result": result,
                "cpu_seconds": time.process_time() - started[0],
                "wall_seconds": time.perf_counter() - started[1],
                "cost_scope": "inclusive operation; HTTP and admission costs nested",
                "unknown_costs": [
                    "process startup",
                    "final serialization",
                    "energy",
                    "charges",
                ],
                "source_sha256": {
                    p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (
                        Path(__file__),
                        Path(__file__).with_name("bounded_source_http.py"),
                        Path(__file__).with_name("text_sources.py"),
                    )
                },
            }
        ),
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
