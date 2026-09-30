"""Exercise growing catalogs without weakening their named obligations."""

import contextlib
import importlib.util
import io
import json
import tempfile
from pathlib import Path
import unittest
from unittest import mock

from hepta_metadata import has_registry_ids, has_repository_references

ROOT = Path(__file__).resolve().parents[1]


def verifier(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_metadata(module, mutate):
    loader = "load" if hasattr(module, "load") else "load_json"
    load = getattr(module, loader)

    def changed(path):
        value = load(path)
        mutate(path, value)
        return value

    # Isolate catalog validation from the separately tested generated view.
    view = (
        mock.patch.object(
            module, "status_text", return_value=(ROOT / module.STATUS_PATH).read_text()
        )
        if hasattr(module, "status_text")
        else contextlib.nullcontext()
    )
    output = io.StringIO()
    with mock.patch.object(module, loader, side_effect=changed):
        with view:
            with contextlib.redirect_stdout(output):
                if module.verify() != 0:
                    raise AssertionError("metadata verification failed")
    return json.loads(output.getvalue().strip().splitlines()[-1])


class RegistryEvolutionTests(unittest.TestCase):
    def test_named_identity_coverage_accepts_growth_not_substitution(self):
        original = [{"id": "owner.a"}, {"id": "owner.b"}]
        required = {"owner.a", "owner.b"}
        grown = [*reversed(original), {"id": "owner.c"}]
        self.assertTrue(has_registry_ids(grown, required=required))
        self.assertTrue(has_registry_ids(grown[:-1], required=required))
        for invalid in (
            [],
            None,
            ["owner.a"],
            [{"id": []}],
            [{"id": " "}],
            original + [original[0]],
            [original[0], {"id": "other"}],
        ):
            with self.subTest(invalid=invalid):
                self.assertFalse(has_registry_ids(invalid, required=required))

    def test_cns_accepts_extension_and_retirement_through_the_same_verifier(self):
        module = verifier("hepta-cns")
        baseline = check_metadata(module, lambda path, value: None)

        def extend(path, value):
            if path == module.ARCH_PATH:
                optional = dict(value["organs"][0])
                optional.update(
                    id="extension.readonly",
                    essential=False,
                    dependencies=["constitutional.kernel"],
                )
                value["organs"] = [optional, *reversed(value["organs"])]
                value["requiredOrganRoles"].reverse()
            elif path == module.PROTOCOL_PATH:
                value["protocols"] = [
                    dict(reversed(list(row.items())))
                    for row in reversed(value["protocols"])
                ]
                value["protocols"].append(
                    {
                        "id": "OptionalReadV1",
                        "owner": "extension.readonly",
                        "requiredFields": ["generation"],
                    }
                )
            elif path == module.GAPS_PATH:
                value["gaps"].append(
                    {
                        "id": "OPTIONAL-GAP",
                        "gap": "optional_read",
                        "state": "closed_reference",
                        "evidence": [module.ARCH_PATH],
                    }
                )
                value["externalCapabilityGates"].append(
                    {
                        "id": "OPTIONAL-EXT",
                        "gate": "optional_external",
                        "state": "requires_external_evidence",
                        "repositoryMaySelfCertify": False,
                    }
                )

        extended = check_metadata(module, extend)
        for key in ("organs", "protocols", "repositoryGaps", "externalCapabilityGates"):
            self.assertEqual(extended[key], baseline[key] + 1)
        self.assertEqual(check_metadata(module, lambda path, value: None), baseline)

    def test_cns_rejects_equal_size_obligation_substitution_and_duplicate_ids(self):
        module = verifier("hepta-cns")
        for key, field in [
            ("gaps", "id"),
            ("externalCapabilityGates", "gate"),
            ("externalCapabilityGates", "id"),
        ]:

            def substitute(path, value):
                if path == module.GAPS_PATH:
                    value[key][0][field] = (
                        value[key][1][field]
                        if field == "id"
                        else "substituted_obligation"
                    )

            with self.subTest(key=key, field=field), self.assertRaises(SystemExit):
                check_metadata(module, substitute)

    def test_cns_boundary_flags_cannot_use_truthy_or_numeric_aliases(self):
        module = verifier("hepta-cns")
        for field in ("essential", "localHotPath", "effectBoundary"):
            for invalid in (0, 1, None, "false", [], {}):

                def substitute(path, value):
                    if path == module.ARCH_PATH:
                        value["organs"][0][field] = invalid

                with self.subTest(field=field, invalid=invalid):
                    with self.assertRaisesRegex(SystemExit, "boolean boundary"):
                        check_metadata(module, substitute)

    def test_hnmf_accepts_new_gap_but_rejects_missing_evidence(self):
        module = verifier("hepta-hnmf")
        gap_path = "docs/hnmf/GAPS.json"
        baseline = check_metadata(module, lambda path, value: None)

        def extend(path, value):
            if path == gap_path:
                row = dict(value["gaps"][0])
                row.update(id="HNM-OPTIONAL", gap="optional_memory_projection")
                value["gaps"].append(row)

        extended = check_metadata(module, extend)
        self.assertEqual(extended["gaps"], baseline["gaps"] + 1)

        def substitute(path, value):
            if path == gap_path:
                value["gaps"][0]["evidence"] = ["docs/hnmf/missing-evidence.md"]

        with self.assertRaisesRegex(SystemExit, "references"):
            check_metadata(module, substitute)

    def test_gap_description_rewording_does_not_create_keyword_gates(self):
        for name, gap_path in [
            ("hepta-cns", "docs/cns/GAPS.json"),
            ("hepta-hnmf", "docs/hnmf/GAPS.json"),
        ]:
            module = verifier(name)

            def rewrite(path, value):
                if path == gap_path:
                    for row in value["gaps"]:
                        row["gap"] = "A clearer human-readable explanation."

            with self.subTest(verifier=name):
                check_metadata(module, rewrite)

    def test_required_protocol_cannot_be_substituted_at_equal_count(self):
        module = verifier("hepta-cns")

        def substitute(path, value):
            if path == module.PROTOCOL_PATH:
                value["protocols"][0]["id"] = "NotTheRequiredProtocolV1"

        with self.assertRaisesRegex(SystemExit, "protocol identities"):
            check_metadata(module, substitute)

    def test_evidence_references_reject_missing_duplicate_and_escaping_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "evidence.txt"
            target.write_text("reference input")
            self.assertTrue(has_repository_references(["evidence.txt#locator"], root))
            for invalid in (
                None,
                [],
                "evidence.txt",
                [None],
                [1],
                ["evidence.txt", "evidence.txt"],
                ["absent.txt"],
                ["../outside.txt"],
                [str(target)],
                ["evidence.txt#"],
            ):
                with self.subTest(invalid=invalid):
                    self.assertFalse(has_repository_references(invalid, root))
            with tempfile.TemporaryDirectory() as outside:
                foreign = Path(outside) / "foreign.txt"
                foreign.write_text("not repository evidence")
                (root / "link.txt").symlink_to(foreign)
                self.assertFalse(has_repository_references(["link.txt"], root))
        for name, gap_path in [
            ("hepta-cns", "docs/cns/GAPS.json"),
            ("hepta-hnmf", "docs/hnmf/GAPS.json"),
        ]:
            module = verifier(name)

            def missing(path, value):
                if path == gap_path:
                    value["gaps"][0]["evidence"] = ["docs/missing-evidence-file.md"]

            with (
                self.subTest(verifier=name),
                self.assertRaisesRegex(SystemExit, "references"),
            ):
                check_metadata(module, missing)

    def test_global_verifier_defers_collection_sizes_to_the_owning_verifier(self):
        module = verifier("hepta-docs")
        original = module.subordinate_state
        data = {key: module.load(path) for key, path in module.FILES.items()}
        status = module.status_text(data)

        def extended():
            value = original()
            for registry, collection in [
                ("readiness", "documents"),
                ("readiness_protocols", "protocols"),
                ("readiness_gaps", "gaps"),
                ("cns", "organs"),
                ("cns_gaps", "gaps"),
                ("hnmf_gaps", "gaps"),
            ]:
                value[registry][collection].append({"id": "projection-only-fixture"})
            return value

        # Only the aggregate projection is changed. Actual owner validators and
        # their input files still run; the aggregate must not reimpose old sizes.
        with mock.patch.object(module, "subordinate_state", side_effect=extended):
            with mock.patch.object(module, "status_text", return_value=status):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(module.verify(), 0)


if __name__ == "__main__":
    unittest.main()
