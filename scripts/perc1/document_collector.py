"""Executed image/OCR collection with retained native wire and measured receipts.

No evaluator is accepted. OCR confidence is not a calibrated probability;
execution receipts are local observations rather than independent attestation.
"""

import base64
import csv
import io
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from PIL import Image

from .native import wire_bytes
from .producer import produce
from .schema import ActorObservation, Cost, Invalid, PHASES, canonical, require, sha


def _micros(value):
    return max(1, (value + 999) // 1000)


def regions_for(image):
    """Partition the admitted RGB crop into four lossless, nonoverlapping tiles."""
    width, height = image.size
    require(
        width >= 2 and height >= 2 and width * height * 3 <= 8192,
        "2x2 document crop exceeds native bounds",
    )
    xs, ys = (0, width // 2, width), (0, height // 2, height)
    return [
        dict(
            evidence_id=f"tile-{row}-{column}",
            x=xs[column],
            y=ys[row],
            width=xs[column + 1] - xs[column],
            height=ys[row + 1] - ys[row],
        )
        for row in range(2)
        for column in range(2)
    ]


class Collector:
    """Run real OCR and optional frozen neural inference, preserving each call."""

    def __init__(self, dataset, worker, projection, output):
        started = time.perf_counter_ns()
        self.dataset, self.worker, self.projection = dataset, worker, projection
        self.output = Path(output)
        require(
            not self.output.exists() or not any(self.output.iterdir()),
            "collector output contains prior evidence",
        )
        (self.output / "records").mkdir(parents=True, exist_ok=True)
        self.dataset_sha256 = sha(dataset.value)
        self.encoder_sha256 = sha(
            {
                "backbone_sha256": worker.weights_sha256,
                "projection_sha256": sha(projection),
            }
        )
        ocr_init = time.perf_counter_ns()
        self.tesseract = shutil.which("tesseract")
        require(self.tesseract is not None, "tesseract is required")
        version_output = subprocess.run(
            [self.tesseract, "--version"], capture_output=True, timeout=10, check=True
        ).stdout
        languages = subprocess.run(
            [self.tesseract, "--list-langs"],
            capture_output=True,
            timeout=10,
            check=True,
        ).stdout.decode()
        directory = re.search(r'List of available languages in "([^"]+)"', languages)
        require(
            directory is not None and "eng" in languages.splitlines(),
            "English OCR model unavailable",
        )
        self.tessdata = Path(directory[1]).resolve()
        traineddata = self.tessdata / "eng.traineddata"
        config = self.tessdata / "configs" / "tsv"
        require(
            traineddata.stat().st_size <= 64 * 1024 * 1024
            and config.stat().st_size <= 65536,
            "OCR language/config exceeds bound",
        )
        self.engine = {
            "name": "tesseract",
            "version": version_output.decode().splitlines()[0],
            "version_output_sha256": sha(version_output),
            "psm": 7,
            "oem": 1,
            "language": "eng",
            "tessdata_dir": str(self.tessdata),
            "language_data_sha256": sha(traineddata.read_bytes()),
            "tsv_config_sha256": sha(config.read_bytes()),
            "executable_sha256": sha(Path(self.tesseract).resolve().read_bytes()),
            "upscale": 4,
            "interpolation": "Pillow.Resampling.BILINEAR",
            "omp_thread_limit": 1,
            "output": "tsv",
            "confidence": "mean word confidence; not probability",
        }
        self.records = []
        self._entries, self.finalization = {}, None
        self.index = {
            "schema": "perc1.document-receipt-index.v1",
            "dataset_sha256": self.dataset_sha256,
            "encoder_sha256": self.encoder_sha256,
            "records": self.records,
            "ocr_init_ns": time.perf_counter_ns() - ocr_init,
            "startup_ns": time.perf_counter_ns() - started,
            "worker_cold_load_ns": worker.cold_load_ns,
            "provider_billing": None,
            "energy_joules": None,
            "index_write_ns": [],
            "scientific_qualified": False,
        }
        (self.output / "index.json").write_bytes(canonical(self.index) + b"\n")

    def observe(self, source_id, representation, encode=True):
        require(
            self.finalization is None, "collector was finalized; preserve its index"
        )
        require(
            representation in ("global", "dense") and type(encode) is bool,
            "invalid document observation mode",
        )
        source = self.dataset.sources[source_id]
        sequence = len(self.records) + 1
        stem = f"records/{sequence:06d}"
        started = time.perf_counter_ns()
        costs = dict.fromkeys(PHASES, 0)
        stage_ns = {}
        try:
            raw = self.dataset.read(source_id)
            image = Image.open(io.BytesIO(raw)).convert("RGB")
            loc = source["locator"]
            require(
                image.size == (loc["x1"] - loc["x0"], loc["y1"] - loc["y0"]),
                "capture dimensions disagree with registered document rectangle",
            )
            regions = regions_for(image)
            stage_ns["acquisition"] = time.perf_counter_ns() - started
            costs["acquisition"] = _micros(stage_ns["acquisition"])
            ocr_start = time.perf_counter_ns()
            scaled = image.resize(
                (image.width * 4, image.height * 4), Image.Resampling.BILINEAR
            )
            buffer = io.BytesIO()
            scaled.save(buffer, format="PNG")
            ocr_input = buffer.getvalue()
            response = subprocess.run(
                [
                    self.tesseract,
                    "stdin",
                    "stdout",
                    "--tessdata-dir",
                    str(self.tessdata),
                    "-l",
                    "eng",
                    "--oem",
                    "1",
                    "--psm",
                    "7",
                    "tsv",
                ],
                input=ocr_input,
                capture_output=True,
                timeout=30,
                check=True,
                env={**os.environ, "OMP_THREAD_LIMIT": "1"},
            )
            require(len(response.stdout) <= 65536, "OCR output exceeds bound")
            rows = list(
                csv.DictReader(
                    io.StringIO(response.stdout.decode("utf-8")), delimiter="\t"
                )
            )
            words = [
                row
                for row in rows
                if row.get("level") == "5" and row.get("text", "").strip()
            ]
            text = " ".join(row["text"].strip() for row in words)
            confidence = sum(
                max(0.0, min(100.0, float(row["conf"]))) for row in words
            ) / max(1, len(words))
            require(len(text.encode()) <= 8192, "OCR text exceeds native text bound")
            for suffix, payload in (
                (".ocr.png", ocr_input),
                (".ocr.tsv", response.stdout),
                (".ocr.txt", text.encode()),
                (".ocr.stderr", response.stderr),
            ):
                (self.output / (stem + suffix)).write_bytes(payload)
            stage_ns["inference"] = time.perf_counter_ns() - ocr_start
            costs["inference"] = _micros(stage_ns["inference"])
            ocr = {
                "text": text,
                "confidence": confidence,
                "engine": self.engine,
                "capture_sha256": sha(raw),
                "input_sha256": sha(ocr_input),
                "output_sha256": sha(response.stdout),
                "text_sha256": sha(text.encode()),
                "elapsed_ns": stage_ns["inference"],
                "fidelity": "ocr_transcription_unverified",
            }
            produced, request, native_wire = None, None, None
            if encode:
                request = {
                    "schema": "perc1.producer-request.v1",
                    "operation_id": f"document-{sequence:06d}",
                    "capture_path": str(self.dataset.root / source["path"]),
                    "capture_sha256": sha(raw),
                    "source_id": source_id,
                    "observed_at_micros": time.time_ns() // 1000,
                    "regions": regions,
                    "representation": representation,
                    "scope_digest": sha(
                        {
                            "dataset_sha256": self.dataset_sha256,
                            "episode_id": source["episode_id"],
                        }
                    ),
                    "source_frontier": sha(source),
                    "exact_text": {
                        "kind": "ocr",
                        "path": str(self.output / (stem + ".ocr.txt")),
                        "sha256": sha(text.encode()),
                        "capture_sha256": sha(raw),
                        "engine": version_string(self.engine),
                    }
                    if text
                    else None,
                }
                encoder_start = time.perf_counter_ns()
                produced = produce(self.worker, request, self.projection)
                stage_ns["encoding"] = time.perf_counter_ns() - encoder_start
                costs["encoding"] = _micros(stage_ns["encoding"])
            transfer_start = time.perf_counter_ns()
            observed_ns = time.perf_counter_ns()
            evidence = dict(
                source_id=source_id,
                raw_sha256=sha(raw),
                raw_base64=base64.b64encode(raw).decode(),
                locator=loc,
                observed_ns=observed_ns,
            )
            if encode:
                wire = wire_bytes(produced["observation"])
                require(
                    sha(wire) == produced["observation_sha256"],
                    "producer wire digest mismatch",
                )
                (self.output / (stem + ".native.json")).write_bytes(wire)
                native_wire = {
                    "path": stem + ".native.json",
                    "sha256": sha(wire),
                    "byte_length": len(wire),
                }
                tokens = []
                for index, latent in enumerate(produced["observation"]["latents"]):
                    position = dict(loc)
                    if representation == "dense":
                        region = regions[index]
                        position.update(
                            x0=loc["x0"] + region["x"],
                            y0=loc["y0"] + region["y"],
                            x1=loc["x0"] + region["x"] + region["width"],
                            y1=loc["y0"] + region["y"] + region["height"],
                        )
                    tokens.append(
                        {
                            "locator": position,
                            "values": [v / 2**24 for v in latent["values_q24"]],
                        }
                    )
                evidence = ActorObservation(
                    **evidence, encoder_sha256=self.encoder_sha256, tokens=tokens
                ).to_dict()
            else:
                evidence.update(schema="perc1.document-ocr-observation.v1", ocr=ocr)
            transfer_bytes = (
                len(canonical(evidence)) + len(ocr_input) + len(response.stdout)
            )
            if native_wire:
                transfer_bytes += native_wire["byte_length"]
            stage_ns["communication"] = time.perf_counter_ns() - transfer_start
            costs["communication"] = transfer_bytes + _micros(stage_ns["communication"])
            costs["decision"] = _micros(
                max(0, time.perf_counter_ns() - started - sum(stage_ns.values()))
            )
            result = {
                "schema": "perc1.document-observation.v1",
                "status": "observed",
                "source_id": source_id,
                "representation": representation if encode else "ocr",
                "encoded": encode,
                "producer": produced,
                "producer_request": request,
                "native_wire": native_wire,
                "ocr": ocr,
                "observation": evidence,
                "cost": costs,
                "measurements": {
                    "started_ns": started,
                    "finished_ns": observed_ns,
                    "stage_ns": stage_ns,
                    "serialized_transport_bytes": transfer_bytes,
                    "provider_billing": None,
                    "energy_joules": None,
                },
                "scientific_qualified": False,
            }
        except Exception as error:
            costs["failure"] = _micros(
                max(0, time.perf_counter_ns() - started - sum(stage_ns.values()))
            )
            result = {
                "schema": "perc1.document-observation.v1",
                "status": "failed",
                "source_id": source_id,
                "representation": representation if encode else "ocr",
                "encoded": encode,
                "cost": costs,
                "error": {"type": type(error).__name__, "message": str(error)[:512]},
                "scientific_qualified": False,
            }
            result["receipt_sha256"] = sha(result)
            self._save(stem, result)
            raise Invalid(
                f"document observation failed; retained {stem}.json: {error}"
            ) from error
        finished = time.perf_counter_ns()
        result["observation"]["observed_ns"] = finished
        result["measurements"]["finished_ns"] = finished
        result["receipt_sha256"] = sha(result)
        self._save(stem, result)
        return result

    def _save(self, stem, result):
        started = time.perf_counter_ns()
        payload = canonical(result) + b"\n"
        (self.output / (stem + ".json")).write_bytes(payload)
        elapsed = time.perf_counter_ns() - started
        entry = {
            "source_id": result["source_id"],
            "representation": result["representation"],
            "status": result["status"],
            "path": stem + ".json",
            "file_sha256": sha(payload),
            "receipt_sha256": result["receipt_sha256"],
            "byte_length": len(payload),
            "receipt_serialization_and_persist_ns": elapsed,
        }
        self.records.append(entry)
        self._entries[result["receipt_sha256"]] = entry
        journal_start = time.perf_counter_ns()
        (self.output / "index.json").write_bytes(canonical(self.index) + b"\n")
        entry["index_persist_ns"] = time.perf_counter_ns() - journal_start
        self.index["index_write_ns"].append(entry["index_persist_ns"])
        entry["accounted_cost"] = dict(result["cost"])
        entry["accounted_cost"]["communication"] += _micros(
            elapsed + entry["index_persist_ns"]
        )

    def accounted_cost(self, item):
        """Return the settled cost without changing the already hashed receipt."""
        entry = self._entries.get(item["receipt_sha256"])
        require(entry is not None, "receipt was not retained by this collector")
        Cost.parse(entry["accounted_cost"])
        return dict(entry["accounted_cost"])

    def finalize(self):
        """Persist the last completed index-write metric; report terminal overhead."""
        if self.finalization is None:
            started = time.perf_counter_ns()
            payload = canonical(self.index) + b"\n"
            (self.output / "index.json").write_bytes(payload)
            elapsed = time.perf_counter_ns() - started
            costs = dict.fromkeys(PHASES, 0)
            costs["communication"] = _micros(elapsed)
            self.finalization = {
                "schema": "perc1.document-index-finalization.v1",
                "index_sha256": sha(payload),
                "index_finalization_ns": elapsed,
                "cost": costs,
                "scope": "final index serialization/write; finalization receipt write is separate terminal bookkeeping",
            }
            (self.output / "finalization.json").write_bytes(
                canonical(self.finalization) + b"\n"
            )
        return dict(self.finalization)


def version_string(engine):
    return (
        engine["version"]
        + "; -l eng --oem 1 --psm 7 tsv; Pillow bilinear 4x; pin "
        + sha(engine)
    )
