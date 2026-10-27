"""Synthetic contracts for the independent source audit and named-role loader."""

import copy
import hashlib
import importlib
import unittest
from unittest.mock import patch

import source_role_audit as audit


def fixture():
    image = lambda i: bytes([i]) * 784
    digest = lambda i: hashlib.sha256(image(i)).hexdigest()
    # train 0/1 duplicate; image 1 is cross-origin; image 2 conflicts;
    # image 3 is prior allocated. Five train and three test pixels remain;
    # deduplication retains one copy of image 0 rather than discarding both.
    arrays = {"train": ([0, 0, 1, 2, 3, 4, 5, 6, 7], [0, 0, 1, 2, 3, 4, 5, 6, 7]),
              "test": ([1, 2, 8, 9], [1, 3, 8, 9])}
    parts = {origin: {"hashes": [digest(i) for i in ids], "labels": bytes(labels),
                      "pixels": b"".join(image(i) for i in ids)}
             for origin, (ids, labels) in arrays.items()}
    counts = {"fit_gradient": 2, "fit_guard": 2, "primary": 2}
    excluded = {digest(3)}
    roles, available, assigned, conflicts = audit.reconstruct_roles(parts, excluded, counts)
    summaries = {}
    for name, role in roles.items():
        ids = role["identities"]
        hashes = [identity.rsplit(":", 1)[-1] for identity in ids]
        summaries[name] = {"images": len(ids), "pairs": len(ids) // 2,
                           "official_partition": role["official_partition"],
                           "identity_sha256": audit.sha("\n".join(ids).encode()),
                           "pixel_set_sha256": audit.sha("\n".join(sorted(hashes)).encode())}
    return parts, counts, excluded, roles, {"roles": summaries}, (available, assigned, conflicts)


class IndependentAllocationTests(unittest.TestCase):
    def test_exclusion_deduplication_and_cross_origin_boundary(self):
        parts, _, excluded, roles, manifest, accounting = fixture()
        self.assertEqual(accounting, ({"train": 5, "test": 3}, {"train": 4, "test": 2}, 1))
        self.assertEqual(audit.verify_role_records({"roles": roles}, manifest, roles, parts, excluded),
                         manifest["roles"])

    def test_label_relabeling_does_not_change_allocation(self):
        parts, counts, excluded, roles, _, _ = fixture()
        for part in parts.values():
            part["labels"] = bytes((value + 1) % 10 for value in part["labels"])
        self.assertEqual(audit.reconstruct_roles(parts, excluded, counts)[0], roles)

    def test_reordered_identities_are_rejected(self):
        parts, _, excluded, roles, manifest, _ = fixture()
        altered = copy.deepcopy(roles)
        altered["fit_gradient"]["identities"].reverse()
        with self.assertRaisesRegex(ValueError, "independent hash-only"):
            audit.verify_role_records({"roles": altered}, manifest, roles, parts, excluded)

    def test_role_reassignment_is_rejected(self):
        parts, _, excluded, roles, manifest, _ = fixture()
        altered = copy.deepcopy(roles)
        altered["fit_gradient"], altered["fit_guard"] = altered["fit_guard"], altered["fit_gradient"]
        with self.assertRaisesRegex(ValueError, "independent hash-only"):
            audit.verify_role_records({"roles": altered}, manifest, roles, parts, excluded)

    def test_source_summary_cannot_claim_false_pair_count(self):
        parts, _, excluded, roles, manifest, _ = fixture()
        manifest["roles"]["primary"]["pairs"] += 1
        with self.assertRaisesRegex(ValueError, "summary differs"):
            audit.verify_role_records({"roles": roles}, manifest, roles, parts, excluded)

    def test_actual_pixel_hash_and_index_bounds_are_checked(self):
        parts, _, _, roles, _, _ = fixture()
        identity = roles["primary"]["identities"][0]
        fields = identity.split(":")
        for bad_index in ("-1", "999", "01"):
            with self.assertRaisesRegex(ValueError, "source index"):
                audit.checked_identity(":".join(fields[:2] + [bad_index, fields[3]]), parts)
        with self.assertRaisesRegex(ValueError, "original pixels"):
            audit.checked_identity(":".join(fields[:3] + ["0" * 64]), parts)

    def test_prior_registry_must_be_complete(self):
        parts, _, _, roles, _, _ = fixture()
        ids = roles["fit_gradient"]["identities"]
        prior = {"source_splits": {"train": {"identities": ids,
                                             "pixel_sha256": [i.rsplit(":", 1)[1] for i in ids]}}}
        self.assertEqual(len(audit.verify_prior(prior, parts, {"train": 2})), 2)
        with self.assertRaisesRegex(ValueError, "Incomplete prior"):
            audit.verify_prior(prior, parts, {"train": 3})

    def test_insufficient_capacity_fails_without_partial_allocation(self):
        parts, _, excluded, _, _, _ = fixture()
        with self.assertRaisesRegex(ValueError, "Insufficient"):
            audit.reconstruct_roles(parts, excluded, {"fit_gradient": 6})


class SourceApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = importlib.import_module("experiments.multimodal_output_portfolio.field_bridge_v3_20261027.source_roles")

    def test_only_named_roles_materialize_from_synthetic_bytes(self):
        parts, _, _, roles, manifest, _ = fixture()
        with patch.object(self.source, "verify_registry", return_value=({"roles": roles}, manifest)), \
                patch.object(self.source, "read_assets", return_value=(parts, [])):
            corpus = self.source.load_corpus_roles("unused-synthetic", ["fit_guard"])
        self.assertEqual(set(corpus.splits), {"fit_guard"})
        self.assertEqual(corpus.manifest["loaded_roles"], ["fit_guard"])
        self.assertEqual(corpus.splits["fit_guard"].ids, tuple(roles["fit_guard"]["identities"]))
        self.assertEqual(tuple(corpus.splits["fit_guard"].images.shape), (2, 1, 28, 28))
        for identity, image in zip(corpus.splits["fit_guard"].ids, corpus.splits["fit_guard"].images):
            self.assertEqual(audit.sha(bytes(image.flatten().tolist())), identity.rsplit(":", 1)[-1])

    def test_empty_duplicate_unknown_roles_fail_before_asset_read(self):
        _, _, _, roles, manifest, _ = fixture()
        for names in ([], ["fit_guard", "fit_guard"], ["all"], ["test"]):
            with patch.object(self.source, "verify_registry", return_value=({"roles": roles}, manifest)), \
                    patch.object(self.source, "read_assets", side_effect=AssertionError("Unexpected asset access")):
                with self.assertRaises(ValueError):
                    self.source.load_corpus_roles("unused-synthetic", names)

    def test_wrong_origin_and_actual_pixel_identity_rejected(self):
        parts, _, _, roles, manifest, _ = fixture()
        altered = copy.deepcopy(roles)
        altered["fit_guard"]["identities"][0] = altered["primary"]["identities"][0]
        with patch.object(self.source, "verify_registry", return_value=({"roles": altered}, manifest)), \
                patch.object(self.source, "read_assets", return_value=(parts, [])):
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                self.source.load_corpus_roles("unused-synthetic", ["fit_guard"])


if __name__ == "__main__":
    unittest.main()
