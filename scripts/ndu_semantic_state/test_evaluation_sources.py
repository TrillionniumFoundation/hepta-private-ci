"""Synthetic HTTP/annotation fixtures exercise admission, never research results."""

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .acquire_evaluation_sources import _prior, acquire_squad
from .bounded_source_http import BoundedSourceHTTP, CAP
from .text_sources import (
    SOURCE_URL,
    admit_text_pool,
    complete_articles,
    load_text_observation,
)


class Response(io.BytesIO):
    def __init__(self, body, headers, status=206):
        super().__init__(body)
        self.headers, self.status, self.url = headers, status, SOURCE_URL


class SourceAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.articles = []
        for i in range(6):
            context = f"SYNTHETIC café article {i}: token{i}."
            answers = [
                {"text": f"token{i}", "answer_start": context.index(f"token{i}")}
            ]
            self.articles.append(
                {
                    "title": f"SYNTHETIC_{i}",
                    "paragraphs": [
                        {
                            "context": context,
                            "qas": [
                                {
                                    "id": f"{i * 3 + q:024x}",
                                    "question": f"Fixture question {q}?",
                                    "answers": deepcopy(answers),
                                }
                                for q in range(3)
                            ],
                        }
                    ],
                }
            )
        start = json.dumps({"data": self.articles}, ensure_ascii=False).encode()[:-1]
        self.payload = start + b" " * 800000 + b', "version": "1.1"}'
        self.etag = '"synthetic-fixture-only"'
        self.budget = BoundedSourceHTTP(
            self.root,
            prior_body_bytes=17669796,
            reservation_bytes=786560,
            prior_receipt_sha256="1" * 64,
        )

    def http(self, request, timeout):
        headers = {"ETag": self.etag, "Content-Length": str(len(self.payload))}
        if request.method == "HEAD":
            return Response(b"", headers, 200)
        first, last = map(int, request.headers["Range"][6:].split("-"))
        body = self.payload[first : last + 1]
        headers.update(
            {
                "Content-Range": f"bytes {first}-{last}/{len(self.payload)}",
                "Content-Length": str(len(body)),
            }
        )
        return Response(body, headers)

    def acquire(self):
        with patch("urllib.request.urlopen", self.http):
            return acquire_squad(self.root, self.budget)

    def binding(self, path):
        raw = (self.root / path).read_bytes()
        return {
            "path": path,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }

    def admit(self):
        return admit_text_pool(
            self.root,
            expected_manifest_sha256=self.binding("CANDIDATES.json")["sha256"],
            expected_history_sha256=self.binding("HISTORY.json")["sha256"],
        )

    def test_actual_extraction_and_public_projection_do_not_require_gold(self):
        result = self.acquire()
        self.assertEqual(result["case_counts"], {"train": 9, "development": 9})
        self.assertEqual(result["source_article_groups"], 6)
        self.assertFalse(result["scientific_admission"])
        manifest = json.loads((self.root / "CANDIDATES.json").read_bytes())
        case = manifest["cases"][0]
        (self.root / case["reference"]["path"]).unlink()
        public = load_text_observation(self.root, case)
        self.assertEqual(
            public,
            {
                "context": self.articles[0]["paragraphs"][0]["context"],
                "question": "Fixture question 0?",
            },
        )
        with self.assertRaises(FileNotFoundError):
            self.admit()

    def test_original_annotation_cannot_be_replaced_by_another_valid_span(self):
        self.acquire()
        manifest = json.loads((self.root / "CANDIDATES.json").read_bytes())
        history = json.loads((self.root / "HISTORY.json").read_bytes())
        case = history["cases"][0]
        path = case["reference"]["path"]
        reference = json.loads((self.root / path).read_bytes())
        reference["answers"] = [{"text": "SYNTHETIC", "answer_start": 0}]
        (self.root / path).write_text(json.dumps(reference))
        case["reference"] = self.binding(path)
        manifest["cases"] = history["cases"]
        (self.root / "HISTORY.json").write_text(json.dumps(history))
        manifest["history_sha256"] = self.binding("HISTORY.json")["sha256"]
        (self.root / "CANDIDATES.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "differs from original human material"):
            self.admit()

    def test_cumulative_budget_cannot_be_reset_in_the_bound_receipt(self):
        self.acquire()
        path = self.root / "ACQUISITION_RECEIPT.json"
        receipt = json.loads(path.read_bytes())
        receipt["prior_body_bytes"] = 0
        path.write_text(json.dumps(receipt))
        manifest = json.loads((self.root / "CANDIDATES.json").read_bytes())
        manifest["acquisition_receipt"] = self.binding(path.name)
        (self.root / "CANDIDATES.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "cumulative budget binding"):
            self.admit()

    def test_complete_article_offsets_survive_unicode_and_partial_tail(self):
        prefix = (
            '{"data": ['
            + json.dumps(self.articles[0], ensure_ascii=False)
            + ', {"title": "café'
        ).encode()[:-1]
        rows = complete_articles(prefix)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(
            json.loads(prefix[row["first_byte"] : row["last_byte"] + 1]),
            self.articles[0],
        )
        with self.assertRaisesRegex(ValueError, "Malformed"):
            complete_articles(b'{"data": [,{}]')

    def test_ignored_range_reads_no_body_and_retains_failed_attempt(self):
        response = Response(
            b"unregistered full payload",
            {"Content-Length": "25", "ETag": self.etag},
            200,
        )
        with (
            patch("urllib.request.urlopen", return_value=response),
            self.assertRaisesRegex(ValueError, "admission failed"),
        ):
            self.budget.fetch(SOURCE_URL, span=(0, 9), etag=self.etag, total=100)
        self.assertEqual(self.budget.bytes_read, 17669796)
        self.assertEqual(self.budget.receipts[-1]["status"], "failed")

    def test_reservation_and_truncated_bytes_remain_accounted(self):
        with self.assertRaisesRegex(ValueError, "preserved cumulative cap"):
            BoundedSourceHTTP(
                self.root,
                prior_body_bytes=CAP - 1,
                reservation_bytes=2,
                prior_receipt_sha256="1" * 64,
            )
        response = Response(
            b"abc",
            {
                "Content-Length": "10",
                "Content-Range": "bytes 0-9/100",
                "ETag": self.etag,
            },
        )
        with (
            patch("urllib.request.urlopen", return_value=response),
            self.assertRaisesRegex(ValueError, "Truncated"),
        ):
            self.budget.fetch(SOURCE_URL, span=(0, 9), etag=self.etag, total=100)
        self.assertEqual(self.budget.bytes_read, 17669799)
        self.assertEqual(self.budget.receipts[-1]["body"]["bytes"], 3)

    def test_nonterminal_prior_cannot_release_a_new_reservation(self):
        path = self.root / "prior.json"
        raw = b'{"status":"in_progress","cumulative_body_bytes":17669796}'
        path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "unresolved prior acquisition"):
            _prior(path, hashlib.sha256(raw).hexdigest(), "cumulative_body_bytes")


if __name__ == "__main__":
    unittest.main()
