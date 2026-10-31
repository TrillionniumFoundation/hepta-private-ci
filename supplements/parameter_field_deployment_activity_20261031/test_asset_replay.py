"""Synthetic current/original producer receipts stay distinct through replay."""

from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from . import asset_replay, portable_common as c


def fixture(root):
    old = dict(
        repository="TrillionniumFoundation/hepta-private-ci",
        run_id="1",
        run_attempt="1",
        head_sha="a" * 40,
        job="original",
    )
    new = {**old, "run_id": "2", "head_sha": "b" * 40, "job": "diagnostic"}
    source, assets, preparation, run = (
        root / name for name in ("source", "assets", "preparation", "run")
    )
    manifest = c.write(
        preparation / "ORIGINAL_INPUT_MANIFEST.json", {"synthetic_fixture": True}
    )
    current = {
        "source_commit": old["head_sha"],
        "preparation_producer": new,
        "current_files": [],
        "public_manifest": manifest,
    }
    for index in range(9):
        current["current_files"].append(
            c.write(assets / f"file{index}.json", {"index": index})
        )
    current_item = c.write(assets / "RESTORATION.json", current)
    historical = {**current, "preparation_producer": old}
    historical_copy = c.write(
        run / "ops/registrations/initial/RESTORATION.json", historical
    )
    historical_item = {**historical_copy, "path": current_item["path"]}
    assets_item = c.write(
        run / "ops/registrations/initial/ASSETS.json",
        {
            "current_asset_assembly": historical_item,
            "current_asset_assembly_copy": historical_copy,
        },
    )
    prepared = c.write(
        preparation / "INPUTS_PREPARED.json",
        {
            "schema": "hepta.execution07.public-input-preparation.1",
            "source_commit": old["head_sha"],
            "files": current["current_files"],
            "manifest": manifest,
            "current_asset_assembly": current_item,
            "scientific_values_decoded": False,
            "self_cpu_seconds": 0.125,
            "wall_seconds": 0.25,
        },
    )
    c.write(
        source / "operational/parameter_field_recovery07/INPUT_CONTRACT.json",
        {"synthetic_fixture": True},
    )
    config = {
        "source_commit": old["head_sha"],
        "actions_identity": old,
        "descriptors": {"assets_receipt": assets_item},
    }
    config_item = c.write(
        run / "ops/registrations/initial/PIPELINE_CONFIG.json", config
    )
    seen = []

    def validate(unused_contract, commit, producer):
        item = c.descriptor(assets / "RESTORATION.json")
        value = c.read(item)
        c.need(
            value["source_commit"] == commit
            and value["preparation_producer"] == producer,
            "Synthetic producer mismatch",
        )
        for row in value["current_files"]:
            c.checked(row)
        c.checked(value["public_manifest"])
        seen.append(deepcopy(producer))
        return item, value

    provenance = SimpleNamespace(
        __file__=str(
            source / "operational/parameter_field_recovery07/asset_provenance.py"
        ),
        validate_current=validate,
    )
    env = dict(
        zip(
            (
                "GITHUB_REPOSITORY",
                "GITHUB_RUN_ID",
                "GITHUB_RUN_ATTEMPT",
                "GITHUB_SHA",
                "GITHUB_JOB",
            ),
            new.values(),
            strict=True,
        )
    )
    return locals()


class AssetReplayTests(unittest.TestCase):
    def test_fresh_literal_is_preserved_and_old_literal_is_only_historical(self):
        with tempfile.TemporaryDirectory() as name:
            f = fixture(Path(name))
            with (
                patch.multiple(
                    c,
                    SOURCE=f["source"],
                    ASSETS=f["assets"],
                    PREPARATION=f["preparation"],
                    RUN=f["run"],
                ),
                patch.dict(asset_replay.os.environ, f["env"]),
            ):
                result = asset_replay.restore(
                    SimpleNamespace(asset_provenance=f["provenance"]),
                    f["config"],
                    f["config_item"],
                    f["new"],
                    Path(name) / "output",
                )
            value = c.read(result)
            self.assertEqual(c.read(value["preserved_fresh_assembly"]), f["current"])
            self.assertEqual(
                c.read(value["reconstructed_original_assembly"]), f["historical"]
            )
            self.assertEqual(c.read(f["prepared"])["self_cpu_seconds"], 0.125)
            self.assertEqual(f["seen"], [f["new"], f["old"]])
            self.assertFalse(
                value["current_and_original_producer_or_cost_receipts_equated"]
            )
            self.assertEqual(
                c.checked(f["historical_copy"]), Path(f["historical_copy"]["path"])
            )

    def test_wrong_new_producer_or_changed_original_copy_refused_before_replacement(
        self,
    ):
        for reason in ("producer", "changed_copy"):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as name:
                f = fixture(Path(name))
                producer = (
                    {**f["new"], "run_id": "3"} if reason == "producer" else f["new"]
                )
                if reason == "changed_copy":
                    Path(f["historical_copy"]["path"]).write_text("{}")
                with (
                    patch.multiple(
                        c,
                        SOURCE=f["source"],
                        ASSETS=f["assets"],
                        PREPARATION=f["preparation"],
                        RUN=f["run"],
                    ),
                    patch.dict(asset_replay.os.environ, f["env"]),
                ):
                    with self.assertRaises(ValueError):
                        asset_replay.restore(
                            SimpleNamespace(asset_provenance=f["provenance"]),
                            f["config"],
                            f["config_item"],
                            producer,
                            Path(name) / "output",
                        )
                self.assertEqual(c.read(f["current_item"]), f["current"])
                self.assertFalse((Path(name) / "output").exists())


if __name__ == "__main__":
    unittest.main()
