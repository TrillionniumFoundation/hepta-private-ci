"""Exercise the actual schema validator, without loading unrelated registries.

HEPTA_READINESS_SOURCE is only for excerpt-based local verification in the
remediation bundle. In repository CI the default is scripts/hepta-readiness.py.
"""
from __future__ import annotations
import ast
import copy
import itertools
import json
import os
from pathlib import Path
import random
import re
from typing import Any
import unittest


def validator_namespace():
    source = Path(os.environ.get("HEPTA_READINESS_SOURCE", str(Path(__file__).with_name("hepta-readiness.py")))).read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {"DuplicateKey", "pairs", "die", "need", "validate_schema_node",
             "BYTE_BOUNDED_SCALAR_TYPES", "FIXED_SCALAR_TYPES", "ARRAY_TYPES",
             "FIXED_POINT_VECTOR_TYPES", "OBJECT_TYPES", "FIELD_TYPES", "FIELD_NAME"}
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in node.targets):
            nodes.append(node)
    namespace = {"json": json, "re": re, "Any": Any}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "actual_readiness_validator", "exec"), namespace)
    return namespace


def shuffled(value, rng):
    if isinstance(value, dict):
        keys = list(value)
        rng.shuffle(keys)
        return {key: shuffled(value[key], rng) for key in keys}
    if isinstance(value, list):
        return [shuffled(item, rng) for item in value]  # Do NOT reorder arrays.
    return value


def scalar():
    return {"name": "flag", "type": "bool", "required": True}


def schemas():
    return [scalar(),
            {"name": "text", "type": "utf8", "required": True, "maxBytes": 20},
            {"name": "kind", "type": "enum", "required": True, "maxBytes": 20, "values": ["A", "B"]},
            {"name": "values", "type": "bounded_array", "required": True, "maxBytes": 80,
             "minItems": 0, "maxItems": 4, "uniqueItems": False, "items": {"type": "u32"}},
            {"name": "vector", "type": "bounded_fixed_point_vector", "required": True, "maxBytes": 80,
             "scale": "Q24", "minItems": 1, "maxItems": 4, "items": {"type": "i64"}},
            {"name": "object", "type": "bounded_object", "required": True, "maxBytes": 80,
             "minProperties": 1, "maxProperties": 1, "additionalProperties": False, "properties": [scalar()]}]


class SchemaOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = validator_namespace()

    def validate(self, node):
        return self.ns["validate_schema_node"](node, 1024, "fixture", named=True)

    def test_all_scalar_key_permutations(self):
        value = scalar()
        for keys in itertools.permutations(value):
            with self.subTest(keys=keys):
                self.validate({key: value[key] for key in keys})

    def test_all_schema_families_and_nested_key_order(self):
        rng = random.Random(20260919)
        for node in schemas():
            for sample in range(32):
                with self.subTest(type=node["type"], sample=sample):
                    self.validate(shuffled(node, rng))

    def test_extra_keys_remain_rejected(self):
        for node in schemas():
            node["unknown"] = False
            with self.subTest(type=node["type"]), self.assertRaises(SystemExit):
                self.validate(node)

    def test_missing_keys_remain_rejected(self):
        for node in schemas():
            del node["required"]
            with self.subTest(type=node["type"]), self.assertRaises(SystemExit):
                self.validate(node)

    def test_duplicate_json_keys_remain_rejected(self):
        with self.assertRaises(self.ns["DuplicateKey"]):
            json.loads('{"type":"bool","type":"u32"}', object_pairs_hook=self.ns["pairs"])

    def test_boolean_cannot_masquerade_as_byte_count(self):
        node = schemas()[1]
        node["maxBytes"] = True
        with self.assertRaises(SystemExit):
            self.validate(node)

    def test_additional_properties_remain_forbidden(self):
        node = schemas()[-1]
        node["additionalProperties"] = True
        with self.assertRaises(SystemExit):
            self.validate(node)

    def test_duplicate_property_names_remain_rejected(self):
        node = schemas()[-1]
        node["properties"].append(copy.deepcopy(node["properties"][0]))
        node["maxProperties"] = node["minProperties"] = 2
        with self.assertRaises(SystemExit):
            self.validate(node)

    def test_required_property_bounds_remain_checked(self):
        node = schemas()[-1]
        node["minProperties"] = 0
        with self.assertRaises(SystemExit):
            self.validate(node)

    def test_duplicate_enum_values_remain_rejected(self):
        node = schemas()[2]
        node["values"] = ["A", "A"]
        with self.assertRaises(SystemExit):
            self.validate(node)

    def test_nesting_bound_remains_checked(self):
        node = scalar()
        for _ in range(6):
            node = {"name": "object", "type": "bounded_object", "required": True, "maxBytes": 80,
                    "minProperties": 1, "maxProperties": 1, "additionalProperties": False, "properties": [node]}
        with self.assertRaises(SystemExit):
            self.validate(node)


if __name__ == "__main__":
    unittest.main()
