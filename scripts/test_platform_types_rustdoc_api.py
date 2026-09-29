"""Unit tests for stable, structural rustdoc public-API normalization."""

from __future__ import annotations

import copy
import unittest

from platform_types_rustdoc_api import _Normalizer, diff


def document(offset: int = 0, *, add_function: bool = False) -> dict:
    root = offset
    foo = offset + 1
    function = offset + 2
    field = offset + 3
    bar = offset + 4
    extra = offset + 5
    root_items = [foo, function, bar]
    index = {
        str(root): {
            "id": root,
            "crate_id": 0,
            "name": "codex_hepta_types",
            "docs": "root prose is intentionally ignored",
            "inner": {"module": {"is_crate": True, "items": root_items}},
        },
        str(foo): {
            "id": foo,
            "crate_id": 0,
            "name": "Foo",
            "visibility": "public",
            "inner": {
                "struct": {
                    "kind": {
                        "plain": {
                            "fields": [field],
                            "has_stripped_fields": False,
                            "alignment": 4,
                        }
                    },
                    "generics": {"params": [], "where_predicates": []},
                    "impls": [],
                }
            },
        },
        str(function): {
            "id": function,
            "crate_id": 0,
            "name": "consume",
            "visibility": "public",
            "inner": {
                "function": {
                    "sig": {
                        "inputs": [
                            [
                                "value",
                                {
                                    "resolved_path": {
                                        "name": "Foo",
                                        "id": foo,
                                        "args": {"angle_bracketed": {"args": [], "constraints": []}},
                                    }
                                },
                            ]
                        ],
                        "output": None,
                        "is_c_variadic": False,
                    },
                    "generics": {"params": [], "where_predicates": []},
                    "header": {"is_const": False, "is_unsafe": False},
                    "has_body": True,
                }
            },
        },
        str(field): {
            "id": field,
            "crate_id": 0,
            "name": "value",
            "visibility": "public",
            "inner": {
                "struct_field": {
                    "resolved_path": {
                        "name": "Bar",
                        "id": bar,
                        "args": {"angle_bracketed": {"args": [], "constraints": []}},
                    }
                }
            },
        },
        str(bar): {
            "id": bar,
            "crate_id": 0,
            "name": "Bar",
            "visibility": "public",
            "inner": {
                "struct": {
                    "kind": {"unit": None},
                    "generics": {"params": [], "where_predicates": []},
                    "impls": [],
                }
            },
        },
    }
    paths = {
        str(root): {"crate_id": 0, "path": ["codex_hepta_types"], "kind": "module"},
        str(foo): {"crate_id": 0, "path": ["codex_hepta_types", "Foo"], "kind": "struct"},
        str(function): {
            "crate_id": 0,
            "path": ["codex_hepta_types", "consume"],
            "kind": "function",
        },
        str(bar): {"crate_id": 0, "path": ["codex_hepta_types", "Bar"], "kind": "struct"},
    }
    if add_function:
        root_items.append(extra)
        index[str(extra)] = {
            "id": extra,
            "crate_id": 0,
            "name": "new_function",
            "visibility": "public",
            "inner": {
                "function": {
                    "sig": {"inputs": [], "output": None, "is_c_variadic": False},
                    "generics": {"params": [], "where_predicates": []},
                    "header": {"is_const": False, "is_unsafe": False},
                    "has_body": True,
                }
            },
        }
        paths[str(extra)] = {
            "crate_id": 0,
            "path": ["codex_hepta_types", "new_function"],
            "kind": "function",
        }
    return {
        "root": root,
        "crate_version": "1.0.0",
        "format_version": 42,
        "index": index,
        "paths": paths,
    }


class RustdocApiTests(unittest.TestCase):
    def test_numeric_item_ids_normalize_to_identical_structural_snapshots(self):
        first = _Normalizer(document(0)).snapshot()
        shifted = _Normalizer(document(100)).snapshot()
        self.assertEqual(first["items"], shifted["items"])
        self.assertEqual(first["snapshotSha256"], shifted["snapshotSha256"])

    def test_restricted_visibility_parent_ids_normalize_structurally(self):
        first_document = document(0)
        shifted_document = document(100)
        first_document["index"]["3"]["visibility"] = {
            "restricted": {"parent": 1, "path": "crate::Foo"}
        }
        shifted_document["index"]["103"]["visibility"] = {
            "restricted": {"parent": 101, "path": "crate::Foo"}
        }
        first = _Normalizer(first_document).snapshot()
        shifted = _Normalizer(shifted_document).snapshot()
        self.assertEqual(first["items"], shifted["items"])
        self.assertEqual(first["snapshotSha256"], shifted["snapshotSha256"])

    def test_restricted_visibility_parent_change_is_breaking(self):
        base_document = document()
        candidate_document = copy.deepcopy(base_document)
        base_document["index"]["3"]["visibility"] = {
            "restricted": {"parent": 1, "path": "crate::Foo"}
        }
        candidate_document["index"]["3"]["visibility"] = {
            "restricted": {"parent": 4, "path": "crate::Bar"}
        }
        result = diff(
            _Normalizer(base_document).snapshot(),
            _Normalizer(candidate_document).snapshot(),
        )
        self.assertTrue(result["breaking"])
        changed = {row["path"] for row in result["changed"]}
        self.assertIn("codex_hepta_types::Foo", changed)

    def test_additive_public_path_does_not_mutate_existing_items(self):
        base = _Normalizer(document()).snapshot()
        candidate = _Normalizer(document(add_function=True)).snapshot()
        result = diff(base, candidate)
        self.assertFalse(result["breaking"])
        self.assertEqual(result["removed"], [])
        self.assertEqual(result["changed"], [])
        self.assertEqual(result["added"], ["codex_hepta_types::new_function"])

    def test_additive_impl_does_not_cascade_into_type_or_callers(self):
        base_document = document()
        candidate_document = copy.deepcopy(base_document)
        impl_id = 20
        method_id = 21
        candidate_document["index"]["1"]["inner"]["struct"]["impls"] = [impl_id]
        candidate_document["index"][str(impl_id)] = {
            "id": impl_id,
            "crate_id": 0,
            "name": None,
            "visibility": "default",
            "inner": {
                "impl": {
                    "is_unsafe": False,
                    "generics": {"params": [], "where_predicates": []},
                    "provided_trait_methods": [],
                    "trait": None,
                    "for": {"resolved_path": {"name": "Foo", "id": 1, "args": None}},
                    "items": [method_id],
                    "is_negative": False,
                    "is_synthetic": False,
                    "blanket_impl": None,
                }
            },
        }
        candidate_document["index"][str(method_id)] = {
            "id": method_id,
            "crate_id": 0,
            "name": "new_method",
            "visibility": "public",
            "inner": {
                "function": {
                    "sig": {"inputs": [], "output": None, "is_c_variadic": False},
                    "generics": {"params": [], "where_predicates": []},
                    "header": {"is_const": False, "is_unsafe": False},
                    "has_body": True,
                }
            },
        }
        candidate_document["paths"][str(method_id)] = {
            "crate_id": 0,
            "path": ["codex_hepta_types", "Foo", "new_method"],
            "kind": "function",
        }
        result = diff(
            _Normalizer(base_document).snapshot(),
            _Normalizer(candidate_document).snapshot(),
        )
        self.assertFalse(result["breaking"])
        self.assertEqual(result["changed"], [])
        self.assertEqual(result["added"], ["codex_hepta_types::Foo::new_method"])

    def test_nested_resolved_path_change_is_breaking(self):
        base_document = document()
        candidate_document = copy.deepcopy(base_document)
        baz_id = 6
        candidate_document["index"][str(baz_id)] = {
            "id": baz_id,
            "crate_id": 0,
            "name": "Baz",
            "visibility": "public",
            "inner": {
                "struct": {
                    "kind": {"unit": None},
                    "generics": {"params": [], "where_predicates": []},
                    "impls": [],
                }
            },
        }
        candidate_document["paths"][str(baz_id)] = {
            "crate_id": 0,
            "path": ["codex_hepta_types", "Baz"],
            "kind": "struct",
        }
        candidate_document["index"]["3"]["inner"]["struct_field"]["resolved_path"] = {
            "name": "Baz",
            "id": baz_id,
            "args": {"angle_bracketed": {"args": [], "constraints": []}},
        }
        result = diff(
            _Normalizer(base_document).snapshot(),
            _Normalizer(candidate_document).snapshot(),
        )
        self.assertTrue(result["breaking"])
        changed = {row["path"] for row in result["changed"]}
        self.assertIn("codex_hepta_types::Foo", changed)

    def test_function_parameter_type_change_is_breaking_without_recursive_fingerprints(self):
        base_document = document()
        candidate_document = copy.deepcopy(base_document)
        candidate_document["index"]["2"]["inner"]["function"]["sig"]["inputs"][0][1][
            "resolved_path"
        ] = {
            "name": "Bar",
            "id": 4,
            "args": {"angle_bracketed": {"args": [], "constraints": []}},
        }
        result = diff(
            _Normalizer(base_document).snapshot(),
            _Normalizer(candidate_document).snapshot(),
        )
        self.assertTrue(result["breaking"])
        changed = {row["path"] for row in result["changed"]}
        self.assertIn("codex_hepta_types::consume", changed)

    def test_docs_and_raw_item_numbers_do_not_change_fingerprint(self):
        base_document = document()
        candidate_document = copy.deepcopy(base_document)
        candidate_document["index"]["1"]["docs"] = "rewritten documentation"
        candidate_document["index"]["1"]["inner"]["struct"]["kind"]["plain"][
            "alignment"
        ] = 4
        result = diff(
            _Normalizer(base_document).snapshot(),
            _Normalizer(candidate_document).snapshot(),
        )
        self.assertFalse(result["breaking"])


if __name__ == "__main__":
    unittest.main()
