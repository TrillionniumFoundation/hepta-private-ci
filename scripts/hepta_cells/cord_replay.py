"""Freeze verified CORD-002 historical train/dev records for offline replay.

No actor, encoder, OCR or evaluator runs. Capture spacing supplies an explicit
replay schedule; it does not authenticate historical feature availability.
"""

import argparse
from collections import Counter
import gzip
import json
import os
from pathlib import Path
import sqlite3

from .cord_evidence import (
    BANDS,
    PHASES,
    REFERENCE_COMMIT,
    EvidenceImporter,
    ReplayImportError,
    _canonical,
    _integer,
    _require,
    _sha,
)


class _Importer(EvidenceImporter):
    def run(self):
        _require(
            type(self.public) is list
            and len({t["id"] for t in self.public}) == len(self.public),
            "duplicate public source",
        )
        tasks = {t["id"]: t for t in self.public if t["split"] in ("train", "dev")}
        _require(
            Counter(t["split"] for t in tasks.values()) == {"train": 24, "dev": 8},
            "expected complete 24 train and 8 dev documents",
        )
        _require(
            type(self.pairs) is list and len(self.pairs) == 96,
            "expected 96 complete pairs; censoring requires a new protocol",
        )
        rows = {(r["source_group"], r["candidate_id"]): r for r in self.pairs}
        _require(
            len(rows) == 96 and set(rows) == {(t, b) for t in tasks for b in BANDS},
            "missing, duplicate or extra candidate pair",
        )
        records, proxy = [], Counter()
        for identity, task in sorted(tasks.items()):
            _require(
                task["schema"] == "perc1.cord-public-task.v1"
                and task["task_sha256"] == _sha(task["task"].encode())
                and task["target_rectangle_public"] is False,
                "public task identity mismatch",
            )
            binding, observations = self.owner(task)
            initial = observations["initial"]
            prefix = dict(
                schema="perc1.profiled-active-prefix.v1",
                task_sha256=task["task_sha256"],
                owner_binding_sha256=_sha(binding),
                operation_ids=["initial"],
                receipt_sha256s=[initial["receipt_sha256"]],
                feature_profile_sha256=_sha(self.profile),
                feature_extractor_sha256=self.extractor,
                selected_operation_id="initial",
                selected_receipt_sha256=initial["receipt_sha256"],
                selected_wire_sha256=initial["wire_sha256"],
                selected_source_evidence_sha256=initial["source_evidence_sha256"],
                latent_evidence_digests=initial["mapping"],
                latent_summary=initial["latent"],
            )
            for item in observations.values():
                proxy.update(item["cost"])
            for candidate in BANDS:
                row, extra = rows[identity, candidate], observations[candidate]
                features = row["features"]
                _require(
                    row["schema"] == "perc1.acquisition-pair.v1"
                    and row["split"] == task["split"]
                    and features["acquired_latent"] == initial["latent"]
                    and features["acquired_receipt_sha256s"]
                    == [initial["receipt_sha256"]]
                    and features["prefix_sha256"] == _sha(prefix),
                    "pair initial feature/receipt/prefix mismatch",
                )
                for arm, names in (
                    ("without", ("initial",)),
                    ("with", ("initial", candidate)),
                ):
                    value = row[arm]
                    expected_evidence = [
                        dict(
                            source_id=n,
                            receipt_sha256=observations[n]["receipt_sha256"],
                            capture_sha256=observations[n]["capture_sha256"],
                        )
                        for n in names
                    ]
                    expected_cost = {
                        k: sum(observations[n]["cost"][k] for n in names)
                        for k in PHASES
                    }
                    _require(
                        value["evidence"] == expected_evidence
                        and value["cost"] == expected_cost
                        and value["prefix_sha256"] == _sha(prefix)
                        and value["solver_sha256"] == self.pins["cord_task.py"]
                        and value["inference_seed"] == self.plan["seed"]
                        and type(value["score"]) in (int, float)
                        and value["score"] in (0, 1),
                        "pair label/evidence/cost identity mismatch",
                    )
                dt = extra["observed_at_us"] - initial["observed_at_us"]
                _require(dt >= 0, "capture clock reversed; explicit censoring required")
                records.append(
                    dict(
                        source_group=identity,
                        split=task["split"],
                        candidate_id=candidate,
                        task_id=candidate,
                        target=int(row["with"]["score"]),
                        initial_latent=initial["latent"],
                        candidate_latent=extra["latent"],
                        observed_at_us=[
                            initial["observed_at_us"],
                            extra["observed_at_us"],
                        ],
                        replay_exposure_us=[0, dt],
                        receipt_sha256s=[
                            initial["receipt_sha256"],
                            extra["receipt_sha256"],
                        ],
                        document_sha256=task["image_sha256"],
                        feature_profile_sha256=_sha(self.profile),
                    )
                )
        inventory = sorted(self.inventory.values(), key=lambda x: x["path"])
        return dict(
            schema="hepta.cell.cord-retained-replay.v1",
            feature_dim=64,
            records=records,
            counts=dict(
                train_documents=24,
                dev_documents=8,
                pairs=96,
                unique_owner_receipts=len(self.measurements),
            ),
            fresh_confirmation=0,
            source_independence_verified=False,
            scientific_status="HOLD",
            timestamp_semantics="observed_at_us is recorded capture time; replay_exposure_us is a per-pair offline schedule from capture spacing, not authenticated historical feature availability",
            target_semantics="retained post-acquisition correctness; initial-only pre-action prediction must not consume candidate_latent",
            historical_costs=dict(
                scope="128 unique train/dev owner receipts; shared initial charged once per source",
                owner_wall_ns=sum(m["wall_ns"] for m in self.measurements.values()),
                owner_process_cpu_ns=sum(
                    m["process_cpu_ns"] for m in self.measurements.values()
                ),
                view_preparation_wall_ns=sum(
                    _integer(t["preparation_wall_ns"]) for t in tasks.values()
                ),
                receipt_measurements=self.measurements,
                proxy_microseconds_by_phase=dict(proxy),
                proxy_semantics="PERC-1 labels call dispatch-minus-read inference; overlaps owner envelope, not extra solver cost",
                energy_joules=None,
                provider_billing=None,
                excluded="prior failed fits, confirmation-arm captures, owner bookkeeping and label-solver costs; retained PLAN preserves prior attempts",
            ),
            source_inventory=inventory,
            source_inventory_sha256=_sha(inventory),
            dependency_pins=self.pins,
            reference_commit=REFERENCE_COMMIT,
            importer_sha256=_sha(Path(__file__).read_bytes()),
            verifier_sha256=_sha(
                Path(__file__).with_name("cord_evidence.py").read_bytes()
            ),
        )


def _load(pilot_dir):
    try:
        importer = _Importer(pilot_dir)
        return importer.run(), importer
    except ReplayImportError:
        raise
    except (KeyError, TypeError, ValueError, OSError, sqlite3.Error) as error:
        raise ReplayImportError(f"retained replay import failed: {error}") from error


def load_cord_replay(pilot_dir):
    """Return complete verified JSON-safe records, or fail without dropping rows."""
    return _load(pilot_dir)[0]


def freeze_cord_replay(pilot_dir, output_dir):
    """Freeze records and exact root/config/SQLite originals with dependency hashes."""
    dataset, importer = _load(pilot_dir)
    archive = gzip.compress(
        _canonical(
            dict(
                schema="hepta.cell.cord-retained-originals.v1",
                encoding="base64",
                files=importer.originals,
                source_inventory=dataset["source_inventory"],
                external_dependencies="capture artifacts are hash-pinned in source_inventory; retain the original pilot archive",
            )
        ),
        mtime=0,
    )
    dataset["originals_archive"] = dict(
        file="ORIGINALS.json.gz", sha256=_sha(archive), byte_length=len(archive)
    )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in (
        ("ORIGINALS.json.gz", archive),
        ("DATASET.json", _canonical(dataset) + b"\n"),
    ):
        with (output / name).open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    return dataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pilot_dir")
    parser.add_argument("output_dir")
    args = parser.parse_args()
    dataset = freeze_cord_replay(args.pilot_dir, args.output_dir)
    print(
        json.dumps(
            dict(
                output=str(Path(args.output_dir) / "DATASET.json"),
                counts=dataset["counts"],
                source_inventory_sha256=dataset["source_inventory_sha256"],
            )
        )
    )


if __name__ == "__main__":
    main()
