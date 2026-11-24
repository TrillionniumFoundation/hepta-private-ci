"""Verify retained CORD-002 train/dev receipts and freeze an offline replay.

No encoder, acquisition callback, OCR or label evaluator is invoked. Capture
timestamps describe recorded capture spacing, NOT authenticated feature
availability. Historical labels and source reuse remain HOLD. The original
owner/schema/native conventions are pinned to PERC-1 commit
57d8fe8b8a2be4580323a8b2598f992fc8fba045; hashes establish byte integrity only.
"""

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat

REFERENCE_COMMIT = "57d8fe8b8a2be4580323a8b2598f992fc8fba045"
BANDS = ("upper", "middle", "lower")
OPS = ("initial",) + BANDS
PHASES = "acquisition encoding communication decision planning inference wait training evaluation failure cancellation".split()
PROFILE_CODE = "source_feature_profile capture_entry source_capture native schema acquisition mlp_head".split()
BACKEND_CODE = (
    "source_entry.py",
    "source_capture.py",
    "browser_capture.py",
    "capture_entry.py",
)
LIMITS = dict(
    image=4 << 20,
    document=16 << 20,
    operator_config=65536,
    ocr_tsv=512 << 10,
    ocr_text=65536,
    ocr_stderr=16384,
)


class ReplayImportError(ValueError):
    """A missing or inconsistent original prevents the entire import."""


def _require(condition, message):
    if not condition:
        raise ReplayImportError(message)


def _canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _sha(value):
    return hashlib.sha256(
        value if isinstance(value, bytes) else _canonical(value)
    ).hexdigest()


def _json(raw, canonical=False):
    def pairs(items):
        value = {}
        for key, item in items:
            _require(key not in value, "duplicate JSON key")
            value[key] = item
        return value

    def constant(value):
        raise ReplayImportError("nonfinite JSON constant: " + value)

    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    if canonical:
        _require(_canonical(value).decode() == raw, "noncanonical owner journal JSON")
    return value


def _signed(value, field):
    pin = _sha({k: v for k, v in value.items() if k != field})
    _require(value[field] == pin, field + " mismatch")
    return pin


def _integer(value):
    _require(type(value) is int and 0 <= value < 2**63, "invalid nonnegative integer")
    return value


def _wire_digest(value):
    _require(
        type(value) is list
        and len(value) == 32
        and all(type(x) is int and 0 <= x <= 255 for x in value),
        "invalid wire digest",
    )
    return bytes(value).hex()


class EvidenceImporter:
    def __init__(self, root):
        self.root = Path(root).absolute()
        _require(self.root == self.root.resolve(), "pilot path contains symlink")
        self.inventory, self.originals, self.measurements = {}, {}, {}
        self.pairs, self.profile, self.plan, self.public = [
            _json(self.read(name, archive=True))
            for name in ("PAIRS.json", "PROFILE.json", "PLAN.json", "PUBLIC_TASKS.json")
        ]
        p = self.profile
        _require(
            p["schema"] == "perc1.source-feature-profile.v1"
            and (
                p["observation"],
                p["aggregation"],
                p["representation"],
                p["token_count"],
                p["token_dimension"],
                p["task_goal_width"],
            )
            == ("first", "flatten", "dense", 4, 16, 5),
            "unsupported CORD feature profile",
        )
        _require(
            self.plan["scientific_status"] == "HOLD"
            and self.plan["source_independence_verified"] is False,
            "historical assurance changed",
        )
        self.pins = self.plan["source_pins"]
        self.extractor = _sha(
            {
                "profile": p,
                "code": {name: self.pins[name + ".py"] for name in PROFILE_CODE},
            }
        )

    def read(self, relative, *, archive=False, limit=32 << 20):
        path = self.root / relative
        _require(
            not Path(relative).is_absolute()
            and path.resolve().is_relative_to(self.root)
            and path.absolute() == path.resolve(),
            "source path escapes root or contains symlink",
        )
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            _require(
                stat.S_ISREG(before.st_mode) and before.st_size <= limit,
                "artifact size/type bound",
            )
            raw = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
        _require(
            len(raw) <= limit
            and all(getattr(before, k) == getattr(after, k) for k in fields),
            "artifact changed during read",
        )
        item = dict(path=str(relative), byte_length=len(raw), sha256=_sha(raw))
        _require(
            str(relative) not in self.inventory
            or self.inventory[str(relative)] == item,
            "source changed during import",
        )
        self.inventory[str(relative)] = item
        if archive:
            self.originals[str(relative)] = base64.b64encode(raw).decode("ascii")
        return raw

    def owner(self, task):
        identity = task["id"]
        _require(re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identity), "unsafe source group")
        directory = identity + "-train"
        config = _json(self.read(identity + "-config.json", archive=True))
        backend = _sha({name: self.pins[name] for name in BACKEND_CODE})
        grant = dict(
            schema="perc1.capture-grant.v1",
            owner_id=identity + ":" + directory,
            generation=1,
            scope_digest=task["task_sha256"],
            source_ids=sorted(task["sources"]),
            source_frontier=_sha(
                {"sources": task["sources"], "capture_backend_sha256": backend}
            ),
        )
        _require(
            config["grant"] == grant
            and config["sources"] == task["sources"]
            and config["model"] == task["model"]
            and config["capture_backend_sha256"] == backend,
            "operator/public source or grant mismatch",
        )
        binding = {k: grant[k] for k in ("owner_id", "generation", "source_frontier")}
        binding.update(
            grant_sha256=_sha(grant), encoder_sha256=self.profile["latent_model_digest"]
        )
        db_relative = directory + "/owner.sqlite3"
        self.read(db_relative, archive=True)
        db_path = self.root / db_relative
        for suffix in ("-wal", "-journal"):
            _require(
                not Path(str(db_path) + suffix).exists(),
                "live SQLite journal cannot be frozen",
            )
        with sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("PRAGMA trusted_schema=OFF")
            metadata_rows = db.execute("SELECT value FROM metadata").fetchall()
            db.row_factory = sqlite3.Row
            rows = [
                dict(row) for row in db.execute("SELECT * FROM operations ORDER BY id")
            ]
        self.read(db_relative)
        _require(len(metadata_rows) == 1, "ambiguous owner metadata")
        metadata = _json(metadata_rows[0][0], canonical=True)
        _require(
            metadata["schema"] == "perc1.owner.v1"
            and metadata["binding"] == binding
            and metadata["budget_units"] == config["budget_units"]
            and metadata["code_sha256"]
            == {name: self.pins[name + ".py"] for name in ("owner", "schema")},
            "owner metadata mismatch",
        )
        _require(
            len(rows) == 4 and {r["id"] for r in rows} == set(OPS),
            "incomplete or extra owner observations",
        )
        result = {}
        for row in rows:
            operation = row["id"]
            _require(
                row["state"] in ("retained", "settled") and row["units"] == 1,
                "incomplete owner operation",
            )
            payload = _json(row["payload"], canonical=True)
            _require(
                payload
                == {
                    "request": {
                        "capture": task["requests"][operation],
                        "adapter_sha256": self.pins["capture_entry.py"],
                    },
                    "units": 1,
                }
                and _sha(payload) == row["request_sha"],
                "owner request mismatch",
            )
            receipt = _json(row["receipt"], canonical=True)
            pin = _signed(receipt, "receipt_sha256")
            _require(
                pin == row["receipt_sha"]
                and receipt["schema"] == "perc1.owner-receipt.v1"
                and receipt["operation_id"] == operation
                and receipt["request_sha256"] == row["request_sha"]
                and receipt["owner_binding_sha256"] == _sha(binding)
                and receipt["reserved_units"] == 1
                and receipt["status"] == "executed"
                and receipt["error"] is None
                and receipt["scientific_status"] == "HOLD",
                "receipt owner/status mismatch",
            )
            measurement = receipt["measurements"]
            for key in ("wall_ns", "process_cpu_ns"):
                _integer(measurement[key])
            _require(
                measurement["energy_joules"] is None
                and measurement["provider_billing"] is None,
                "unexpected measured energy/billing requires a new cost schema",
            )
            _require(
                pin not in self.measurements, "duplicate owner receipt across sources"
            )
            self.measurements[pin] = measurement
            result[operation] = self.observation(task, directory, binding, receipt)
        return binding, result

    def observation(self, task, directory, binding, receipt):
        operation, result = receipt["operation_id"], receipt["result"]
        _require(
            result["schema"] == "perc1.owned-encoding.v2", "source evidence required"
        )
        producer, native, source = (
            result["producer"],
            result["native_wire"],
            result["source_evidence"],
        )
        _signed(producer, "receipt_sha256")
        _signed(source, "evidence_sha256")
        raw = base64.b64decode(native["bytes_base64"], validate=True)
        _require(
            native["encoding"] == "base64"
            and 0 < len(raw) <= 1 << 20
            and len(raw) == native["byte_length"]
            and _sha(raw) == native["sha256"] == producer["observation_sha256"],
            "native wire hash/length mismatch",
        )
        wire = _json(raw)
        _require(
            wire == producer["observation"]
            and wire["schema"] == "hepta.perception.observation.v1"
            and producer["schema"] == "perc1.producer-receipt.v1"
            and producer["status"] == "executed"
            and producer["scientific_status"] == "HOLD",
            "producer/native observation mismatch",
        )
        model, encoder, p = producer["model"], producer["encoder"], self.profile
        _require(
            _sha(model) == p["latent_model_digest"] == binding["encoder_sha256"]
            and _sha(encoder) == p["encoder_digest"]
            and encoder["model"] == model
            and model["projection_sha256"] == p["projection_sha256"]
            and model["backbone_sha256"] == task["model"]["weights_sha256"]
            and encoder["dimension"] == 16
            and wire["representation"] == encoder["representation"] == "dense"
            and _wire_digest(wire["scope_digest"]) == task["task_sha256"]
            and _wire_digest(wire["source_frontier"]) == binding["source_frontier"]
            and _wire_digest(wire["encoder_digest"]) == p["encoder_digest"]
            and _wire_digest(wire["latent_model_digest"]) == p["latent_model_digest"],
            "encoder/model/source profile mismatch",
        )
        public_source = task["sources"][operation]
        _require(
            source["schema"] == "perc1.source-evidence.v1"
            and source["source_id"] == operation
            and source["source_group"] == task["id"]
            and source["kind"] == "document_page"
            and source["source_uri"] == public_source["source_uri"]
            and source["adapter_sha256"] == self.pins["source_capture.py"]
            and source["capture_sha256"]
            == public_source["image"]["sha256"]
            == producer["transform"]["capture_sha256"],
            "source/document identity mismatch",
        )
        _require(
            all(
                source[key] is False
                for key in (
                    "origin_authenticated",
                    "rendered_from_document_verified",
                    "ocr_verified",
                )
            ),
            "unsupported source assurance",
        )
        artifacts, restored = source["artifacts"], {}
        _require(
            set(artifacts) == set(LIMITS),
            "incomplete or unexpected CORD source artifacts",
        )
        for role, item in artifacts.items():
            _require(
                re.fullmatch(r"captures/[0-9a-f]{64}\." + role, item["relative_path"]),
                "unsafe source artifact path",
            )
            content = self.read(
                directory + "/" + item["relative_path"], limit=LIMITS[role]
            )
            _require(
                len(content) == item["byte_length"] and _sha(content) == item["sha256"],
                "source artifact hash/length mismatch",
            )
            restored[role] = content
        _require(
            _json(restored["operator_config"]) == public_source
            and artifacts["operator_config"]["sha256"] == source["config_sha256"]
            and artifacts["image"]["sha256"] == source["capture_sha256"]
            and artifacts["document"]["sha256"]
            == task["image_sha256"]
            == public_source["document"]["sha256"]
            and source["page_index"] == public_source["document"]["page_index"],
            "source artifact/config/document mismatch",
        )
        if source["native_text"]["status"] == "included":
            text = producer["exact_text"]
            text_name = _sha(operation.encode()) + ".txt"
            _require(
                Path(text["path"]).parts[-3:] == (directory, "captures", text_name),
                "native text path is outside retained owner",
            )
            text_file = self.read(directory + "/captures/" + text_name, limit=8192)
            _require(
                base64.b64decode(text["raw_base64"], validate=True)
                == restored["ocr_text"]
                == text_file
                and text["sha256"] == artifacts["ocr_text"]["sha256"]
                and text["kind"] == "ocr",
                "native text/source mismatch",
            )
        else:
            _require(producer["exact_text"] is None, "unexpected native text")
        evidence, tokens = wire["evidence"], wire["latents"]
        _require(len(evidence) == len(tokens) == 4, "native token layout mismatch")
        times, latent, mapping = set(), [], []
        for item, token, region in zip(
            evidence, tokens, task["requests"][operation]["regions"]
        ):
            evidence_raw = json.dumps(
                item, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode()
            reference = list(
                hashlib.sha256(
                    b"hepta.perception.evidence.v1\0" + evidence_raw
                ).digest()
            )
            values, origin = token["values_q24"], item["source"]
            _require(
                token["evidence_digests"] == [reference]
                and len(values) == 16
                and all(
                    type(v) is int and -(8 << 24) <= v <= (8 << 24) for v in values
                ),
                "native token/evidence mapping mismatch",
            )
            _require(
                origin["source_id"] == operation
                and _wire_digest(origin["origin_digest"]) == source["capture_sha256"]
                and _wire_digest(origin["content_digest"])
                == producer["transform"]["raster_rgb_sha256"]
                and item["evidence_id"] == region["evidence_id"]
                and item["coordinates"]
                == {
                    "kind": "image_region",
                    **{k: region[k] for k in ("x", "y", "width", "height")},
                },
                "native source/region mismatch",
            )
            times.add(_integer(origin["observed_at_micros"]))
            latent.extend(v / 2**24 for v in values)
            mapping.append([bytes(reference).hex()])
        _require(len(times) == 1 and min(times) > 0, "ambiguous capture time")
        read_ns = _integer(source["measurements"]["read_wall_ns"])
        total_us = max(1, (receipt["measurements"]["wall_ns"] + 999) // 1000)
        read_us = max(1, (read_ns + 999) // 1000)
        _require(total_us >= read_us, "source read cost exceeds owner envelope")
        cost = dict.fromkeys(PHASES, 0)
        cost.update(acquisition=read_us, inference=total_us - read_us)
        return dict(
            latent=latent,
            observed_at_us=min(times),
            receipt_sha256=receipt["receipt_sha256"],
            capture_sha256=source["capture_sha256"],
            wire_sha256=_sha(raw),
            source_evidence_sha256=_sha(source),
            mapping=mapping,
            cost=cost,
        )
