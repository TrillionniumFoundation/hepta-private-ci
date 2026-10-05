"""Supply tests cover actual causal joins, prior feedback and annotation leakage."""

import copy
import unittest

from hepta_prepare_public_healthver_supply import (
    canonical,
    digest,
    normalized,
    prepare_supply,
)


def fixture(rows_per_component=3):
    graph, approved, membership, cut, measurements = [], [], [], [], []
    for group in range(4):
        entries = []
        claim = f"public claim {group}"
        # An official dev row joins the final train row to the others. Removing
        # this unmeasured bridge would falsely split one causal component.
        for index in range(rows_per_component + 1):
            split = "dev" if index == rows_per_component else "train"
            feature = {
                "domain": "hepta.healthver.public-feature-record.v1",
                "source": "HealthVer",
                "source_split": split,
                "source_row_1based": group * (rows_per_component + 2) + index + 2,
                "upstream_id": str(group * 1000 + index),
                "topic": str(group),
                "question": "public question",
                "claim_text": claim
                if index < rows_per_component - 1
                else claim + " bridge",
                "evidence_text": f"public evidence {group}:{index if split == 'train' else 0}",
            }
            entries.append(feature)
        keys = sorted(
            {
                (kind, normalized(feature[name]))
                for feature in entries
                for kind, name in (
                    ("claim", "claim_text"),
                    ("evidence", "evidence_text"),
                )
            }
        )
        component = digest(
            b"hepta.healthver.claim-evidence-component.v1\0" + canonical(keys)
        )
        for index, feature in enumerate(entries):
            pin = digest(canonical(feature))
            graph.append(
                {
                    "feature": feature,
                    "feature_digest": pin,
                    "component_digest": component,
                    "claim_feature_digest": normalized(feature["claim_text"]),
                    "evidence_feature_digest": normalized(feature["evidence_text"]),
                }
            )
            if feature["source_split"] == "dev":
                continue
            approved.append(
                feature
                | {
                    "component_sha256": component,
                    "gold": "SUPPORT",
                    "entropy": 0,
                    "original_row_sha256": "annotation-dependent-original",
                }
            )
            if group < 2 and index < 2:
                pair_id = f"healthver:train:{feature['source_row_1based']}"
                row = {
                    "pair_id": pair_id,
                    "feature_digest": pin,
                    "component_digest": component,
                    "partition": "previous-public-development",
                }
                membership.append(row)
                cut.append(
                    row | {"partition": "train" if group == 0 else "development"}
                )
                measurements.append(
                    {
                        "pair_id": pair_id,
                        "source_row_sha256": pin,
                        "features_q24": [1] * 512,
                    }
                )
    observations = {
        "schema": "hepta.eval.public-development.measurement-source.v1",
        "purpose": "PublicDevelopmentMeasurementOnlyV1",
        "holdout_consumed": False,
        "learning_evidence_signed": False,
        "production_activation": False,
        "qualification": False,
        "plan_frozen": False,
        "measurements": measurements,
    }
    return approved, graph, membership, cut, observations


class PublicSupplyTests(unittest.TestCase):
    def test_all_annotation_changes_leave_full_masks_cut_and_batches_unchanged(self):
        args = fixture()
        original = prepare_supply(*args)
        changed = copy.deepcopy(args)
        for row in changed[0]:
            row.update(
                gold="CONTRADICT",
                entropy=100,
                original_row_sha256="changed",
                votes={"fake": 900},
                evaluation_result=False,
            )
        for rows in changed[:4]:
            rows.reverse()
        changed[4]["measurements"].reverse()
        self.assertEqual(canonical(original), canonical(prepare_supply(*changed)))

    def test_seen_development_component_and_new_rows_never_return_to_train(self):
        approved, graph, membership, cut, observations = fixture()
        result = prepare_supply(approved, graph, membership, cut, observations)
        old_parts = {row["component_digest"]: row["partition"] for row in cut}
        for row in result["membership"]:
            if row["component_digest"] in old_parts:
                self.assertEqual(row["partition"], old_parts[row["component_digest"]])
        partitions = {}
        for row in result["membership"]:
            partitions.setdefault(row["component_digest"], set()).add(row["partition"])
        self.assertTrue(all(len(values) == 1 for values in partitions.values()))
        self.assertEqual(
            sum(values == {"development"} for values in partitions.values()), 2
        )
        closure = result["component_closure"]
        self.assertTrue(all(row["complete_graph_rows"] == 4 for row in closure))
        self.assertEqual(sum(row["previous_development_seen"] for row in closure), 1)

    def test_neutral_dev_bridge_or_forged_component_cannot_split_causal_cut(self):
        args = fixture()
        without_bridge = copy.deepcopy(args)
        without_bridge[1][:] = [
            row for row in without_bridge[1] if row["feature"]["source_split"] != "dev"
        ]
        with self.assertRaisesRegex(
            ValueError, "whole claim/evidence component changed"
        ):
            prepare_supply(*without_bridge)
        forged = copy.deepcopy(args)
        forged[1][0]["component_digest"] = "a" * 64
        with self.assertRaisesRegex(
            ValueError, "whole claim/evidence component changed"
        ):
            prepare_supply(*forged)

    def test_pending_batches_cover_each_new_feature_once_with_native_pair_codec(self):
        args = fixture(150)
        result = prepare_supply(*args)
        old = {row["pair_id"] for row in args[2]}
        pending = [row for chunk in result["pending_chunks"] for row in chunk]
        self.assertTrue(
            all(1 <= len(chunk) <= 147 for chunk in result["pending_chunks"])
        )
        self.assertEqual(len(pending), len({row["pair_id"] for row in pending}))
        self.assertEqual(
            {row["pair_id"] for row in pending},
            {row["pair_id"] for row in result["masked_pairs"]} - old,
        )
        masked = {
            row["pair_id"]: row["source_row_sha256"] for row in result["masked_pairs"]
        }
        self.assertEqual(
            {row["pair_id"]: row["source_row_sha256"] for row in pending},
            {key: value for key, value in masked.items() if key not in old},
        )
        self.assertTrue(
            all(set(row) == {"pair_id", "source_row_sha256"} for row in pending)
        )

    def test_missing_or_relabelled_physical_rows_and_partial_prior_cut_refused(self):
        for mutation in ("measurement", "source", "cut", "partition"):
            args = copy.deepcopy(fixture())
            if mutation == "measurement":
                args[4]["measurements"].pop()
            elif mutation == "source":
                args[4]["measurements"][0]["source_row_sha256"] = "b" * 64
            elif mutation == "cut":
                args[3].pop()
            else:
                args[3][1]["partition"] = "development"
            with self.assertRaises(ValueError):
                prepare_supply(*args)


if __name__ == "__main__":
    unittest.main()
