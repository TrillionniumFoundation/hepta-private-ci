"""Synthetic integrity fixtures only: these are never experimental task evidence."""

import base64
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from hepta_cells import cord_evidence as evidence
from hepta_cells import cord_replay as replay


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(evidence._canonical(value) + b"\n")


def fixture(root):
    pins = {
        name: evidence._sha(name.encode())
        for name in {
            *(x + ".py" for x in evidence.PROFILE_CODE),
            *evidence.BACKEND_CODE,
            "owner.py",
            "cord_task.py",
        }
    }
    model = dict(
        architecture="fixture",
        backbone_sha256=evidence._sha(b"weights"),
        projection_sha256=evidence._sha(b"projection"),
        producer_code_sha256=evidence._sha(b"producer"),
    )
    encoder = dict(
        model=model,
        preprocess={},
        representation="dense",
        dimension=16,
        global_pool="mean",
    )
    profile = dict(
        schema="perc1.source-feature-profile.v1",
        observation="first",
        aggregation="flatten",
        representation="dense",
        token_count=4,
        token_dimension=16,
        task_goal_width=5,
        encoder_digest=evidence._sha(encoder),
        latent_model_digest=evidence._sha(model),
        projection_sha256=model["projection_sha256"],
    )
    plan = dict(
        scientific_status="HOLD",
        source_independence_verified=False,
        source_pins=pins,
        seed=7,
    )
    backend = evidence._sha({name: pins[name] for name in evidence.BACKEND_CODE})
    extractor = evidence._sha(
        {
            "profile": profile,
            "code": {name: pins[name + ".py"] for name in evidence.PROFILE_CODE},
        }
    )
    public, pairs = [], []
    for number in range(32):
        identity = "fixture-" + str(number)
        directory = identity + "-train"
        task = dict(
            schema="perc1.cord-public-task.v1",
            id=identity,
            split="train" if number < 24 else "dev",
            preparation_wall_ns=3000,
            task="read amount",
            task_sha256=evidence._sha(b"read amount"),
            target_rectangle_public=False,
            image_sha256=evidence._sha(identity.encode()),
            sources={},
            requests={},
            model={"weights_sha256": model["backbone_sha256"]},
        )
        for operation in evidence.OPS:
            task["sources"][operation] = dict(
                source_uri=identity + "#" + operation,
                kind="document_page",
                source_group=identity,
                image={"sha256": evidence._sha((identity + operation).encode())},
                document={"sha256": task["image_sha256"], "page_index": 0},
            )
            task["requests"][operation] = dict(
                source_id=operation,
                representation="dense",
                regions=[
                    dict(evidence_id="patch-" + str(i), x=i, y=0, width=1, height=1)
                    for i in range(4)
                ],
            )
        grant = dict(
            schema="perc1.capture-grant.v1",
            owner_id=identity + ":" + directory,
            generation=1,
            scope_digest=task["task_sha256"],
            source_ids=sorted(task["sources"]),
            source_frontier=evidence._sha(
                {"sources": task["sources"], "capture_backend_sha256": backend}
            ),
        )
        config = dict(
            grant=grant,
            sources=task["sources"],
            model=task["model"],
            capture_backend_sha256=backend,
            budget_units=8,
        )
        write(root / (identity + "-config.json"), config)
        binding = {k: grant[k] for k in ("owner_id", "generation", "source_frontier")}
        binding.update(
            grant_sha256=evidence._sha(grant),
            encoder_sha256=profile["latent_model_digest"],
        )
        owner = root / directory
        owner.mkdir()
        observations = {}
        with sqlite3.connect(owner / "owner.sqlite3") as db:
            db.execute("CREATE TABLE metadata (value TEXT NOT NULL)")
            db.execute(
                "CREATE TABLE operations (id TEXT PRIMARY KEY,payload TEXT,request_sha TEXT,units INTEGER,state TEXT,receipt TEXT,receipt_sha TEXT)"
            )
            metadata = dict(
                schema="perc1.owner.v1",
                binding=binding,
                budget_units=8,
                code_sha256={name: pins[name + ".py"] for name in ("owner", "schema")},
            )
            db.execute(
                "INSERT INTO metadata VALUES (?)",
                (evidence._canonical(metadata).decode(),),
            )
            for position, operation in enumerate(evidence.OPS):
                capture = (identity + operation).encode()
                artifacts = dict(
                    image=capture,
                    document=identity.encode(),
                    operator_config=evidence._canonical(task["sources"][operation]),
                    ocr_tsv=b"fixture TSV",
                    ocr_text=b"",
                    ocr_stderr=b"",
                )
                source = dict(
                    schema="perc1.source-evidence.v1",
                    source_id=operation,
                    source_group=identity,
                    kind="document_page",
                    source_uri=task["sources"][operation]["source_uri"],
                    page_index=0,
                    adapter_sha256=pins["source_capture.py"],
                    capture_sha256=evidence._sha(capture),
                    config_sha256=evidence._sha(artifacts["operator_config"]),
                    origin_authenticated=False,
                    rendered_from_document_verified=False,
                    ocr_verified=False,
                    artifacts={},
                    native_text={"status": "absent_or_empty", "role": "ocr_text"},
                    measurements={"read_wall_ns": 500},
                )
                for role, raw in artifacts.items():
                    relative = (
                        "captures/" + evidence._sha(operation.encode()) + "." + role
                    )
                    path = owner / relative
                    path.parent.mkdir(exist_ok=True)
                    path.write_bytes(raw)
                    source["artifacts"][role] = dict(
                        relative_path=relative,
                        sha256=evidence._sha(raw),
                        byte_length=len(raw),
                    )
                source["evidence_sha256"] = evidence._sha(source)
                patches, tokens, mapping = [], [], []
                timestamp = 1_000_000 + number * 10000 + position * 100
                for region in task["requests"][operation]["regions"]:
                    item = dict(
                        evidence_id=region["evidence_id"],
                        source=dict(
                            source_id=operation,
                            origin_digest=list(bytes.fromhex(source["capture_sha256"])),
                            content_digest=list(bytes.fromhex(evidence._sha(b"rgb"))),
                            observed_at_micros=timestamp,
                        ),
                        coordinates={
                            "kind": "image_region",
                            **{k: region[k] for k in ("x", "y", "width", "height")},
                        },
                    )
                    raw_item = json.dumps(
                        item, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                    ).encode()
                    reference = list(
                        hashlib.sha256(
                            b"hepta.perception.evidence.v1\0" + raw_item
                        ).digest()
                    )
                    patches.append(item)
                    tokens.append(
                        dict(
                            evidence_digests=[reference],
                            values_q24=[number + position] * 16,
                        )
                    )
                    mapping.append([bytes(reference).hex()])
                wire = dict(
                    schema="hepta.perception.observation.v1",
                    representation="dense",
                    scope_digest=list(bytes.fromhex(task["task_sha256"])),
                    source_frontier=list(bytes.fromhex(binding["source_frontier"])),
                    encoder_digest=list(bytes.fromhex(profile["encoder_digest"])),
                    latent_model_digest=list(
                        bytes.fromhex(profile["latent_model_digest"])
                    ),
                    evidence=patches,
                    latents=tokens,
                )
                raw = json.dumps(
                    wire, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                ).encode()
                producer = dict(
                    schema="perc1.producer-receipt.v1",
                    observation=wire,
                    observation_sha256=evidence._sha(raw),
                    status="executed",
                    scientific_status="HOLD",
                    model=model,
                    encoder=encoder,
                    exact_text=None,
                    transform=dict(
                        capture_sha256=source["capture_sha256"],
                        raster_rgb_sha256=evidence._sha(b"rgb"),
                    ),
                )
                producer["receipt_sha256"] = evidence._sha(producer)
                result = dict(
                    schema="perc1.owned-encoding.v2",
                    producer=producer,
                    source_evidence=source,
                    native_wire=dict(
                        encoding="base64",
                        bytes_base64=base64.b64encode(raw).decode(),
                        sha256=evidence._sha(raw),
                        byte_length=len(raw),
                    ),
                )
                payload = {
                    "request": {
                        "capture": task["requests"][operation],
                        "adapter_sha256": pins["capture_entry.py"],
                    },
                    "units": 1,
                }
                receipt = dict(
                    schema="perc1.owner-receipt.v1",
                    operation_id=operation,
                    request_sha256=evidence._sha(payload),
                    owner_binding_sha256=evidence._sha(binding),
                    reserved_units=1,
                    status="executed",
                    error=None,
                    result=result,
                    scientific_status="HOLD",
                    measurements={
                        "wall_ns": 2000,
                        "process_cpu_ns": 1000,
                        "energy_joules": None,
                        "provider_billing": None,
                    },
                )
                receipt["receipt_sha256"] = evidence._sha(receipt)
                db.execute(
                    "INSERT INTO operations VALUES (?,?,?,?,?,?,?)",
                    (
                        operation,
                        evidence._canonical(payload).decode(),
                        evidence._sha(payload),
                        1,
                        "settled",
                        evidence._canonical(receipt).decode(),
                        receipt["receipt_sha256"],
                    ),
                )
                observations[operation] = dict(
                    receipt=receipt,
                    latent=[(number + position) / 2**24] * 64,
                    mapping=mapping,
                    wire_sha=evidence._sha(raw),
                )
        initial = observations["initial"]
        initial_receipt = initial["receipt"]
        prefix = dict(
            schema="perc1.profiled-active-prefix.v1",
            task_sha256=task["task_sha256"],
            owner_binding_sha256=evidence._sha(binding),
            operation_ids=["initial"],
            receipt_sha256s=[initial_receipt["receipt_sha256"]],
            feature_profile_sha256=evidence._sha(profile),
            feature_extractor_sha256=extractor,
            selected_operation_id="initial",
            selected_receipt_sha256=initial_receipt["receipt_sha256"],
            selected_wire_sha256=initial["wire_sha"],
            selected_source_evidence_sha256=evidence._sha(
                initial_receipt["result"]["source_evidence"]
            ),
            latent_evidence_digests=initial["mapping"],
            latent_summary=initial["latent"],
        )
        for operation in evidence.BANDS:
            row = dict(
                schema="perc1.acquisition-pair.v1",
                source_group=identity,
                candidate_id=operation,
                split=task["split"],
                features=dict(
                    acquired_latent=initial["latent"],
                    acquired_receipt_sha256s=[initial_receipt["receipt_sha256"]],
                    prefix_sha256=evidence._sha(prefix),
                ),
            )
            for arm, names in (
                ("without", ("initial",)),
                ("with", ("initial", operation)),
            ):
                cost = dict.fromkeys(evidence.PHASES, 0)
                cost.update(acquisition=len(names), inference=len(names))
                row[arm] = dict(
                    score=float((number + len(names)) % 2),
                    cost=cost,
                    prefix_sha256=evidence._sha(prefix),
                    inference_seed=7,
                    solver_sha256=pins["cord_task.py"],
                    evidence=[
                        dict(
                            source_id=n,
                            receipt_sha256=observations[n]["receipt"]["receipt_sha256"],
                            capture_sha256=observations[n]["receipt"]["result"][
                                "source_evidence"
                            ]["capture_sha256"],
                        )
                        for n in names
                    ],
                )
            pairs.append(row)
        public.append(task)
    for name, value in (
        ("PAIRS.json", pairs),
        ("PROFILE.json", profile),
        ("PLAN.json", plan),
        ("PUBLIC_TASKS.json", public),
    ):
        write(root / name, value)


class CordReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "pilot"
        self.root.mkdir()
        fixture(self.root)

    def test_full_coverage_actual_two_vectors_and_unique_cost(self):
        value = replay.load_cord_replay(self.root)
        self.assertEqual(
            value["counts"],
            dict(
                train_documents=24, dev_documents=8, pairs=96, unique_owner_receipts=128
            ),
        )
        first = value["records"][0]
        self.assertEqual(first["initial_latent"], [0.0] * 64)
        self.assertEqual(first["candidate_latent"], [1 / 2**24] * 64)
        self.assertEqual(first["replay_exposure_us"], [0, 100])
        self.assertEqual(value["historical_costs"]["owner_wall_ns"], 128 * 2000)
        self.assertEqual(
            value["historical_costs"]["proxy_microseconds_by_phase"]["inference"], 128
        )
        self.assertEqual(
            (value["fresh_confirmation"], value["source_independence_verified"]),
            (0, False),
        )
        json.dumps(value, allow_nan=False)

    def test_freeze_contains_exact_sqlite_originals_and_refuses_overwrite(self):
        output = Path(self.tmp.name) / "frozen"
        data = replay.freeze_cord_replay(self.root, output)
        raw = (output / "ORIGINALS.json.gz").read_bytes()
        self.assertEqual(evidence._sha(raw), data["originals_archive"]["sha256"])
        originals = json.loads(gzip.decompress(raw))
        relative = "fixture-0-train/owner.sqlite3"
        self.assertEqual(
            base64.b64decode(originals["files"][relative]),
            (self.root / relative).read_bytes(),
        )
        self.assertEqual(data, json.loads((output / "DATASET.json").read_bytes()))
        with self.assertRaises(FileExistsError):
            replay.freeze_cord_replay(self.root, output)

    def test_missing_duplicate_and_wrong_initial_are_never_silently_dropped(self):
        original = json.loads((self.root / "PAIRS.json").read_bytes())
        for mode in ("missing", "duplicate", "feature", "score", "cost"):
            rows = json.loads(json.dumps(original))
            if mode == "missing":
                rows.pop()
            elif mode == "duplicate":
                rows[-1] = rows[0]
            elif mode == "feature":
                rows[0]["features"]["acquired_latent"][0] += 1
            elif mode == "score":
                rows[0]["with"]["score"] = 2
            else:
                rows[0]["with"]["cost"]["inference"] += 1
            write(self.root / "PAIRS.json", rows)
            with self.subTest(mode=mode), self.assertRaises(replay.ReplayImportError):
                replay.load_cord_replay(self.root)

    def test_receipt_and_native_hashes_are_checked_independently(self):
        db_path = self.root / "fixture-0-train/owner.sqlite3"
        with sqlite3.connect(db_path) as db:
            old, _ = db.execute(
                "SELECT receipt,receipt_sha FROM operations WHERE id='upper'"
            ).fetchone()
            receipt = json.loads(old)
            receipt["measurements"]["wall_ns"] += 1
            db.execute(
                "UPDATE operations SET receipt=? WHERE id='upper'",
                (evidence._canonical(receipt).decode(),),
            )
        with self.assertRaisesRegex(
            replay.ReplayImportError, "receipt_sha256 mismatch"
        ):
            replay.load_cord_replay(self.root)
        receipt = json.loads(old)
        receipt["result"]["native_wire"]["bytes_base64"] = base64.b64encode(
            b"{}"
        ).decode()
        receipt["receipt_sha256"] = evidence._sha(
            {k: v for k, v in receipt.items() if k != "receipt_sha256"}
        )
        with sqlite3.connect(db_path) as db:
            db.execute(
                "UPDATE operations SET receipt=?,receipt_sha=? WHERE id='upper'",
                (evidence._canonical(receipt).decode(), receipt["receipt_sha256"]),
            )
        with self.assertRaisesRegex(
            replay.ReplayImportError, "native wire hash/length"
        ):
            replay.load_cord_replay(self.root)

    def test_artifact_corruption_and_symlink_fail(self):
        path = (
            self.root
            / "fixture-0-train/captures"
            / (evidence._sha(b"initial") + ".document")
        )
        original = path.read_bytes()
        path.write_bytes(b"damaged")
        with self.assertRaisesRegex(replay.ReplayImportError, "artifact hash/length"):
            replay.load_cord_replay(self.root)
        path.unlink()
        target = Path(self.tmp.name) / "outside"
        target.write_bytes(original)
        path.symlink_to(target)
        with self.assertRaisesRegex(
            replay.ReplayImportError, "escapes root or contains symlink"
        ):
            replay.load_cord_replay(self.root)


if __name__ == "__main__":
    unittest.main()
