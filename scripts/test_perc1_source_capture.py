"""Source/owner integration controls; fake producer results are not neural evidence."""

import base64
import copy
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw, ImageFont

from perc1 import capture_entry
from perc1.capture_entry import OwnedProducer, decode_native_wire, model_sha256
from perc1.native import wire_bytes
from perc1.owner import Owner
from perc1.schema import Invalid, canonical, sha
from perc1.source_capture import (
    TSV_FIELDS,
    _run_ocr,
    configured_capture,
    parse_tsv,
    retain_source_evidence,
    validate_source_config,
    verify_source_evidence,
)


def tsv(tokens=("0042.50", "2026-11-12", "kg", "原文")):
    rows = ["\t".join(TSV_FIELDS)]
    for index, text in enumerate(tokens):
        rows.append(
            "\t".join(
                map(
                    str,
                    [
                        5,
                        1,
                        1,
                        1,
                        1,
                        index + 1,
                        index * 30,
                        5,
                        25,
                        15,
                        "91.25",
                        text,
                    ],
                )
            )
        )
    return ("\n".join(rows) + "\n").encode()


@unittest.skipUnless(os.name == "posix", "local POSIX source/owner adapter")
class SourceCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = self.root / "source.png"
        Image.new("RGB", (400, 100), "white").save(self.image)
        self.dom = self.root / "source.html"
        self.dom.write_bytes("<p>0042.50 USD; 2026-11-12; 3 kg; 原文</p>".encode())
        self.source = {
            "schema": "perc1.source-capture.v1",
            "kind": "screenshot",
            "image": {"path": str(self.image), "sha256": sha(self.image.read_bytes())},
            "source_uri": "https://example.invalid/controlled",
            "source_group": "controlled-engineering-only",
            "document": None,
            "text": {
                "kind": "dom",
                "path": str(self.dom),
                "sha256": sha(self.dom.read_bytes()),
            },
            "ocr": None,
        }
        self.request = {
            "source_id": "source-1",
            "representation": "dense",
            "regions": [
                {"evidence_id": "roi", "x": 0, "y": 0, "width": 16, "height": 16}
            ],
        }

    def acquired(self, *, ocr=False):
        if not ocr:
            return configured_capture(self.source, self.request)
        self.source["ocr"] = {
            "executable": str(Path(sys.executable).resolve()),
            "sha256": sha(Path(sys.executable).resolve().read_bytes()),
            "language": "eng",
            "psm": 6,
        }
        with mock.patch(
            "perc1.source_capture._run_ocr",
            return_value={
                "ocr_tsv": tsv(),
                "ocr_stderr": b"",
            },
        ):
            return configured_capture(self.source, self.request)

    def retain(self, acquired):
        owned = self.root / "owned"
        owned.mkdir(exist_ok=True)
        metadata = retain_source_evidence(
            owned,
            sha(b"op"),
            acquired["source_evidence"],
            sha(acquired["image_bytes"]),
            self.request["source_id"],
        )
        return owned, metadata

    def test_utf8_spans_keep_amount_date_units_and_original_tokens(self):
        raw, words = parse_tsv(tsv(), 400, 100)
        self.assertEqual(raw, "0042.50 2026-11-12 kg 原文".encode())
        self.assertEqual(
            [raw[w["start"] : w["end"]].decode() for w in words],
            ["0042.50", "2026-11-12", "kg", "原文"],
        )
        self.assertEqual(words[-1]["end"] - words[-1]["start"], 6)
        self.assertEqual(words[0]["confidence"], "91.25")

    def test_original_dom_and_raw_tsv_survive_deleted_inputs(self):
        acquired = self.acquired(ocr=True)
        expected = acquired["source_evidence"]["artifacts"]
        owned, metadata = self.retain(acquired)
        self.image.unlink()
        self.dom.unlink()
        restored = verify_source_evidence(json.loads(canonical(metadata)), owned)
        self.assertEqual(restored, expected)
        self.assertFalse(metadata["ocr_verified"])
        self.assertFalse(metadata["origin_authenticated"])
        self.assertEqual(
            metadata["ocr"]["confidence_semantics"], "engine_score_not_probability"
        )

    def test_large_dom_is_retained_without_silent_native_truncation(self):
        raw = ("金额0042.50\n" * 1000).encode()
        self.dom.write_bytes(raw)
        self.source["text"]["sha256"] = sha(raw)
        acquired = self.acquired()
        self.assertIsNone(acquired["exact_text"])
        owned, metadata = self.retain(acquired)
        self.assertEqual(
            metadata["native_text"],
            {"role": "dom", "status": "omitted_over_native_limit"},
        )
        self.assertEqual(verify_source_evidence(metadata, owned)["dom"], raw)

    def test_changed_artifact_missing_sidecar_and_forged_spans_fail(self):
        owned, metadata = self.retain(self.acquired(ocr=True))
        changed = copy.deepcopy(metadata)
        changed["ocr"]["words"][0]["end"] += 1
        changed["evidence_sha256"] = sha(
            {k: v for k, v in changed.items() if k != "evidence_sha256"}
        )
        with self.assertRaises(Invalid):
            verify_source_evidence(changed, owned)
        path = owned / metadata["artifacts"]["ocr_tsv"]["relative_path"]
        path.write_bytes(path.read_bytes().replace(b"0042.50", b"0043.50"))
        with self.assertRaises(Invalid):
            verify_source_evidence(metadata, owned)
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            verify_source_evidence(metadata, owned)

    def test_wrong_pin_symlink_and_escaping_retained_path_fail(self):
        wrong = copy.deepcopy(self.source)
        wrong["image"]["sha256"] = sha(b"other image")
        with self.assertRaises(Invalid):
            configured_capture(wrong, self.request)
        alias = self.root / "alias.png"
        alias.symlink_to(self.image)
        wrong["image"] = {"path": str(alias), "sha256": self.source["image"]["sha256"]}
        with self.assertRaises(OSError):
            configured_capture(wrong, self.request)
        owned, metadata = self.retain(self.acquired())
        metadata["artifacts"]["image"]["relative_path"] = "../source.png"
        metadata["evidence_sha256"] = sha(
            {k: v for k, v in metadata.items() if k != "evidence_sha256"}
        )
        with self.assertRaises(Invalid):
            verify_source_evidence(metadata, owned)

    def test_invalid_tsv_and_actor_configuration_are_rejected(self):
        for raw in (
            b"bad header\n",
            tsv().replace(b"\t25\t15\t", b"\t999\t15\t"),
            tsv().replace(b"91.25", b"nan"),
        ):
            with self.subTest(raw=raw[:40]), self.assertRaises(Invalid):
                parse_tsv(raw, 400, 100)
        invalid = copy.deepcopy(self.source)
        invalid["ocr"] = {
            "executable": "/bin/false",
            "sha256": sha(b"x"),
            "language": "--help",
            "psm": 6,
        }
        with self.assertRaises(Invalid):
            validate_source_config(invalid)

    def test_ocr_process_failure_and_output_bound_are_enforced(self):
        script = self.root / "fake-ocr"
        script.write_text("#!" + sys.executable + "\nimport sys\nsys.exit(7)\n")
        script.chmod(0o700)
        ocr = {"executable": str(script), "language": "eng", "psm": 6}
        with self.assertRaisesRegex(Invalid, "OCR process failed"):
            _run_ocr(ocr, b"controlled")
        script.write_text(
            "#!" + sys.executable + "\nimport os\nos.write(1, b'x' * 600000)\n"
        )
        with self.assertRaisesRegex(Invalid, "output bound"):
            _run_ocr(ocr, b"controlled")

    def test_owner_admits_before_capture_and_v2_cold_read_reuses_exact_wire(self):
        projection, weights = {"controlled": "projection"}, sha(b"controlled weights")
        grant = {
            "schema": "perc1.capture-grant.v1",
            "owner_id": "source-owner",
            "generation": 1,
            "source_frontier": sha(self.source),
            "source_ids": ["source-1"],
            "scope_digest": sha(b"controlled scope"),
        }
        binding = {
            "owner_id": grant["owner_id"],
            "generation": 1,
            "source_frontier": grant["source_frontier"],
            "encoder_sha256": model_sha256(weights, projection),
            "grant_sha256": sha(grant),
        }
        calls, module = [], types.ModuleType("perc1.producer")

        class Worker:
            def __init__(self, *args):
                self.calls = 0

        def produce(worker, request, projection):
            worker.calls += 1
            observation = {
                "evidence": [
                    {
                        "source": {
                            "source_id": request["source_id"],
                            "origin_digest": list(
                                bytes.fromhex(request["capture_sha256"])
                            ),
                        }
                    }
                ]
            }
            code = {
                name: sha(
                    Path(capture_entry.__file__).with_name(name + ".py").read_bytes()
                )
                for name in ("producer", "projection", "raster", "native", "schema")
            }
            result = {
                "schema": "perc1.producer-receipt.v1",
                "status": "executed",
                "model": {
                    "architecture": "torchvision.mobilenet_v3_small.features",
                    "backbone_sha256": weights,
                    "projection_sha256": sha(projection),
                    "producer_code_sha256": sha(code),
                },
                "transform": {"capture_sha256": request["capture_sha256"]},
                "observation": observation,
                "observation_sha256": sha(wire_bytes(observation)),
                "exact_text": {
                    "kind": request["exact_text"]["kind"],
                    "sha256": request["exact_text"]["sha256"],
                    "raw_base64": base64.b64encode(
                        Path(request["exact_text"]["path"]).read_bytes()
                    ).decode(),
                },
            }
            result["receipt_sha256"] = sha(result)
            return result

        module.FrozenMobileNet, module.produce = Worker, produce
        owned = self.root / "owner"

        def capture(request):
            with sqlite3.connect(owned / "owner.sqlite3") as db:
                self.assertEqual(
                    db.execute("SELECT state FROM operations WHERE id='op'").fetchone()[
                        0
                    ],
                    "dispatched",
                )
            calls.append("capture")
            return configured_capture(self.source, request)

        with mock.patch.dict(sys.modules, {"perc1.producer": module}):
            with Owner(owned, binding, 2) as owner:
                producer = OwnedProducer(owner, grant, "unused", weights, projection)
                first = producer.observe("op", self.request, capture)
                self.assertEqual(first["status"], "executed", first.get("error"))
                self.assertEqual(first["result"]["schema"], "perc1.owned-encoding.v2")
                original = decode_native_wire(first["result"], source_root=owned)
                tampered = copy.deepcopy(first["result"])
                tampered["producer"]["exact_text"]["sha256"] = sha(
                    b"substituted amount"
                )
                tampered["producer"]["receipt_sha256"] = sha(
                    {
                        k: v
                        for k, v in tampered["producer"].items()
                        if k != "receipt_sha256"
                    }
                )
                with self.assertRaises(Invalid):
                    decode_native_wire(tampered, source_root=owned)
                self.image.unlink()
                self.dom.unlink()
                self.assertEqual(producer.observe("op", self.request, capture), first)
            with Owner(owned, binding, 2) as cold:
                self.assertEqual(cold.receipt("op"), first)
                self.assertEqual(
                    decode_native_wire(cold.receipt("op")["result"], source_root=owned),
                    original,
                )
        self.assertEqual(calls, ["capture"])
        legacy = {k: v for k, v in first["result"].items() if k != "source_evidence"}
        legacy["schema"] = "perc1.owned-encoding.v1"
        self.assertEqual(decode_native_wire(legacy), original)

    @unittest.skipUnless(shutil.which("tesseract"), "actual Tesseract not installed")
    def test_actual_tesseract_retains_executed_output_without_correctness_claim(self):
        font = ImageFont.load_default()
        image = Image.new("RGB", (300, 40), "white")
        ImageDraw.Draw(image).text((5, 5), "Total 0042.50 USD", fill="black", font=font)
        image.resize((1200, 160)).save(self.image)
        executable = Path(shutil.which("tesseract")).resolve()
        self.source["image"]["sha256"] = sha(self.image.read_bytes())
        self.source["text"] = None
        self.source["ocr"] = {
            "executable": str(executable),
            "sha256": sha(executable.read_bytes()),
            "language": "eng",
            "psm": 6,
        }
        acquired = configured_capture(self.source, self.request)
        owned, metadata = self.retain(acquired)
        restored = verify_source_evidence(metadata, owned)
        self.assertGreater(len(restored["ocr_tsv"]), 0)
        self.assertGreater(len(metadata["ocr"]["words"]), 0)
        self.assertFalse(metadata["ocr_verified"])


if __name__ == "__main__":
    unittest.main()
