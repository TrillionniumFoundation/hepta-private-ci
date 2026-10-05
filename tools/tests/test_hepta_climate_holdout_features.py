import importlib.util
from pathlib import Path
import unittest


PROGRAM = Path(__file__).parents[1] / "hepta_prepare_climate_holdout_features.py"
SPEC = importlib.util.spec_from_file_location("climate_features", PROGRAM)
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)


class Preview:
    PUBLIC_EXAMPLE_CLAIM_IDS = frozenset({"0"})

    def __init__(self, expected):
        self.expected = expected

    @staticmethod
    def normalized_hash(text):
        return ADAPTER.sha(" ".join(text.casefold().split()).encode())

    @classmethod
    def article_hash(cls, text):
        return cls.normalized_hash(text.replace("_", " "))

    @staticmethod
    def text(value):
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError("text")
        return value

    @staticmethod
    def unique_keys(items):
        result = {}
        for key, value in items:
            if key in result:
                raise RuntimeError("duplicate")
            result[key] = value
        return result

    def preview(self, raw, earlier):
        return self.expected


def claim(identity, article=None):
    return dict(
        claim_id=str(identity),
        claim="Claim " + str(identity),
        claim_label={"opaque": True},
        evidences=[
            dict(
                evidence_id=str(identity) + "-" + str(index),
                evidence_label={"opaque": True},
                article=article or str(identity) + " article",
                evidence=str(identity) + " sentence " + str(index),
                entropy={},
                votes=[],
            )
            for index in range(5)
        ],
    )


def encoded(rows):
    return b"\n".join(ADAPTER.canonical(row) for row in rows)


class FeatureCutTests(unittest.TestCase):
    def test_full_indirect_component_is_excluded_through_unscored_evidence(self):
        rows = [claim(index) for index in range(5)]
        # Evidence label values are deliberately opaque. A neutral bridge must
        # still exclude the entire connected component before any label use.
        rows[1]["evidences"][4]["article"] = "old_article"
        rows[2]["evidences"][0]["evidence"] = rows[1]["evidences"][0]["evidence"]
        rows[3]["evidences"][0]["article"] = rows[2]["evidences"][0]["article"]
        preview = Preview(
            dict(candidate_disjoint_components=1, candidate_disjoint_claims=1)
        )
        earlier = [("other claim", (), (preview.article_hash("Old Article"),))]
        components, _ = ADAPTER.eligible_components(encoded(rows), earlier, preview)
        self.assertEqual(components, [["4"]])

    def test_changing_every_annotation_keeps_exact_feature_cut(self):
        rows = [claim(index) for index in range(3)]
        rows[2]["evidences"][0]["article"] = rows[1]["evidences"][0]["article"]
        preview = Preview(
            dict(candidate_disjoint_components=1, candidate_disjoint_claims=2)
        )
        before = ADAPTER.eligible_components(encoded(rows), [], preview)
        for row in rows:
            row["claim_label"] = "DISPUTED"
            for evidence in row["evidences"]:
                evidence.update(
                    evidence_label="NOT_ENOUGH_INFO", entropy=999, votes=["not read"]
                )
        self.assertEqual(
            ADAPTER.eligible_components(encoded(rows), [], preview), before
        )

    def test_public_example_excludes_its_whole_connected_component(self):
        rows = [claim(0, "shared"), claim(1, "shared"), claim(2)]
        preview = Preview(
            dict(candidate_disjoint_components=1, candidate_disjoint_claims=1)
        )
        self.assertEqual(
            ADAPTER.eligible_components(encoded(rows), [], preview)[0], [["2"]]
        )

    def test_partial_or_duplicated_source_and_projection_drift_fail_closed(self):
        preview = Preview(
            dict(candidate_disjoint_components=1, candidate_disjoint_claims=1)
        )
        for rows in ([claim(1)], [claim(0), claim(1), claim(1)]):
            with self.assertRaises(RuntimeError):
                ADAPTER.eligible_components(encoded(rows), [], preview)
        preview.expected = dict(
            candidate_disjoint_components=9, candidate_disjoint_claims=9
        )
        with self.assertRaises(RuntimeError):
            ADAPTER.eligible_components(encoded([claim(0), claim(1)]), [], preview)


if __name__ == "__main__":
    unittest.main()
