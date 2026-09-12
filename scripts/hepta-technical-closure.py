#!/usr/bin/env python3
"""Validate detailed design coverage and analytic qualification oracles, never runtime claims.

`self-test` is dependency-free. `verify` requires an actual complete Git checkout.
No write, deploy, model, network, merge or capability operation is performed.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import subprocess
import sys
import unittest
from fractions import Fraction
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REL = Path("qualification/module-execution-dossiers")
PHASES = (
    "prepared",
    "admission_stopped",
    "drained",
    "old_writer_fenced",
    "snapshotted",
    "migrated",
    "validated",
    "new_writer_fenced",
    "route_published",
    "retired",
)
HEADINGS = (
    "## 1. Source and work envelope",
    "## 2. Public operations and contract details",
    "## 3. State records and transaction design",
    "## 4. Deterministic algorithm and scheduling",
    "## 5. Capacity and performance profile",
    "## 6. Concrete verification cases",
    "## 7. Integration, rollback and capability ceiling",
)


class Invalid(ValueError):
    """Invalid bounded input or failed evidence/compatibility condition."""


def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in values:
        if key in result:
            raise Invalid("duplicate JSON key: " + key)
        result[key] = value
    return result


def load(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=pairs,
        parse_constant=lambda s: (_ for _ in ()).throw(Invalid(s)),
    )


def rescale(value: int, source: int, target: int, rounding: str, bits: int = 64) -> int:
    """Exact reference; production uses checked bounded wide intermediates."""
    if any(type(x) is not int for x in (value, source, target, bits)):
        raise Invalid("integer arguments required")
    if (
        not 0 < source < (1 << 127)
        or not 0 < target < (1 << 127)
        or not 2 <= bits <= 128
    ):
        raise Invalid("scale/bits")
    if not -(1 << (bits - 1)) <= value < (1 << (bits - 1)):
        raise Invalid("input overflow")
    product = value * target
    if not -(1 << 127) <= product < (1 << 127):
        raise Invalid("wide intermediate overflow")
    q, r = divmod(abs(product), source)
    if rounding == "ties_even":
        q += int(2 * r > source or (2 * r == source and q % 2 == 1))
    elif rounding != "toward_zero":
        raise Invalid("unknown rounding")
    result = q if product >= 0 else -q
    if not -(1 << (bits - 1)) <= result < (1 << (bits - 1)):
        raise Invalid("output overflow")
    return result


def covariance_z(cov: list[list[Fraction]], moment: list[Fraction]) -> list[Fraction]:
    """Solve C z^T = B^T exactly for symmetric positive-definite fixture covariance.

    This oracle does not estimate conditional moments, certify a runtime condition
    number or solve the full FBSDE. Singular/indefinite fixtures are rejected.
    """
    n = len(moment)
    if not 1 <= n <= 32 or len(cov) != n or any(len(r) != n for r in cov):
        raise Invalid("covariance dimensions")
    c = [[Fraction(v) for v in row] for row in cov]
    if any(c[i][j] != c[j][i] for i in range(n) for j in range(n)):
        raise Invalid("nonsymmetric covariance")
    # Exact LDL^T decomposition checks positive definiteness without sqrt.
    low = [[Fraction(int(i == j)) for j in range(n)] for i in range(n)]
    diagonal: list[Fraction] = []
    for i in range(n):
        d = c[i][i] - sum(low[i][k] ** 2 * diagonal[k] for k in range(i))
        if d <= 0:
            raise Invalid("singular/indefinite covariance")
        diagonal.append(d)
        for j in range(i + 1, n):
            low[j][i] = (
                c[j][i] - sum(low[j][k] * low[i][k] * diagonal[k] for k in range(i))
            ) / d
    y: list[Fraction] = []
    for i in range(n):
        y.append(Fraction(moment[i]) - sum(low[i][j] * y[j] for j in range(i)))
    w = [y[i] / diagonal[i] for i in range(n)]
    z = [Fraction(0)] * n
    for i in reversed(range(n)):
        z[i] = w[i] - sum(low[j][i] * z[j] for j in range(i + 1, n))
    return z


def sequential_dr(
    rows: list[dict[str, Fraction]], terminal: Fraction = Fraction(0)
) -> Fraction:
    if not 1 <= len(rows) <= 128:
        raise Invalid("horizon")
    value = Fraction(terminal)
    for row in reversed(rows):
        if set(row) != {"v", "q", "reward", "behavior", "evaluation", "discount"}:
            raise Invalid("trajectory fields")
        b, e, g = (Fraction(row[k]) for k in ("behavior", "evaluation", "discount"))
        if not 0 < b <= 1 or not 0 <= e <= 1 or not 0 <= g <= 1:
            raise Invalid("support/probability/discount")
        ratio = e / b
        value = Fraction(row["v"]) + ratio * (
            Fraction(row["reward"]) + g * value - Fraction(row["q"])
        )
    return value


def interval_feasible(atoms: list[tuple[str, str, int, int]]) -> bool:
    bounds: dict[str, tuple[int, int]] = {}
    seen: set[str] = set()
    for ident, axis, lo, hi in atoms:
        if (
            not isinstance(ident, str)
            or not ident
            or not isinstance(axis, str)
            or not axis
            or ident in seen
            or type(lo) is not int
            or type(hi) is not int
        ):
            raise Invalid("duplicate or untyped constraint")
        seen.add(ident)
        old_lo, old_hi = bounds.get(axis, (lo, hi))
        bounds[axis] = (max(lo, old_lo), min(hi, old_hi))
    return all(lo <= hi for lo, hi in bounds.values())


def action_closure(
    nodes: list[str],
    edges: list[tuple[str, str]],
    required: set[str],
    forbidden: set[str],
) -> set[str]:
    """Bounded positive-implication oracle, not an authority decision."""
    node_set = set(nodes)
    if (
        len(nodes) > 128
        or len(node_set) != len(nodes)
        or len(edges) > 16384
        or not required <= node_set
        or not forbidden <= node_set
    ):
        raise Invalid("action graph bounds or identity")
    outgoing: dict[str, list[str]] = {node: [] for node in nodes}
    for source, target in edges:
        if source not in node_set or target not in node_set:
            raise Invalid("unknown implication node")
        outgoing[source].append(target)
    reached = set(required)
    queue = list(sorted(required))
    for source in queue:
        for target in sorted(outgoing[source]):
            if target not in reached:
                reached.add(target)
                queue.append(target)
    if reached & forbidden:
        raise Invalid("infeasible action closure")
    return reached


def centered_regression(samples: list[tuple[Fraction, Fraction]]) -> Fraction:
    """Exact scalar centered sample-moment fixture; not a conditional estimator."""
    if not 2 <= len(samples) <= 4096:
        raise Invalid("sample bound")
    n = len(samples)
    mean_m = sum(Fraction(m) for m, _ in samples) / n
    mean_u = sum(Fraction(u) for _, u in samples) / n
    c = sum((Fraction(m) - mean_m) ** 2 for m, _ in samples) / n
    b = sum((Fraction(m) - mean_m) * (Fraction(u) - mean_u) for m, u in samples) / n
    return covariance_z([[c]], [b])[0]


def interval_core(
    atoms: list[tuple[str, str, int, int]], budget: int = 257
) -> list[tuple[str, str, int, int]]:
    """Inclusion-minimal deterministic core for the interval-only oracle fixture."""
    if len(atoms) > 256 or budget < 1 or len({r[0] for r in atoms}) != len(atoms):
        raise Invalid("constraint bounds/IDs")
    current = sorted(atoms)
    calls = 1
    if interval_feasible(current):
        return []
    for atom in list(current):
        if calls >= budget:
            raise Invalid("budget_exhausted")
        trial = [item for item in current if item[0] != atom[0]]
        calls += 1
        if not interval_feasible(trial):
            current = trial
    return current


def effective_ess_minimum(n: int, floors: list[int]) -> int:
    if (
        type(n) is not int
        or n < 0
        or not floors
        or any(type(x) is not int or x < 0 for x in floors)
    ):
        raise Invalid("ESS inputs")
    return max(400, (n + 9) // 10, *floors)


def validate_schema(value: Any, schema: dict[str, Any], label: str = "record") -> None:
    """Validate the explicitly used bounded subset of Draft 2020-12 keywords.

    Not a general JSON Schema implementation. Unknown validation keywords fail,
    rather than silently widening acceptance. Schema is also usable with a full
    standards-compliant validator independently of this oracle.
    """
    known = {
        "$schema",
        "$id",
        "title",
        "description",
        "type",
        "const",
        "enum",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "uniqueItems",
        "minItems",
        "maxItems",
        "minLength",
        "maxLength",
        "pattern",
        "minimum",
        "maximum",
    }
    if set(schema) - known:
        raise Invalid(label + ": unsupported schema keyword")
    types = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "boolean": bool,
    }
    kind = schema.get("type")
    if kind not in types or type(value) is not types[kind]:
        raise Invalid(label + ": type")
    if "const" in schema and (
        type(value) is not type(schema["const"]) or value != schema["const"]
    ):
        raise Invalid(label + ": const")
    if "enum" in schema and value not in schema["enum"]:
        raise Invalid(label + ": enum")
    if kind == "object":
        properties = schema.get("properties", {})
        if set(schema.get("required", [])) - set(value):
            raise Invalid(label + ": missing required field")
        if schema.get("additionalProperties") is False and set(value) - set(properties):
            raise Invalid(label + ": unknown field")
        for key, item in value.items():
            if key in properties:
                validate_schema(item, properties[key], label + "." + key)
    elif kind == "array":
        if (
            not schema.get("minItems", 0)
            <= len(value)
            <= schema.get("maxItems", sys.maxsize)
        ):
            raise Invalid(label + ": count")
        if schema.get("uniqueItems") and len(
            {json.dumps(x, sort_keys=True) for x in value}
        ) != len(value):
            raise Invalid(label + ": duplicates")
        for i, item in enumerate(value):
            validate_schema(item, schema["items"], f"{label}[{i}]")
    elif kind == "string":
        if (
            not schema.get("minLength", 0)
            <= len(value)
            <= schema.get("maxLength", sys.maxsize)
        ):
            raise Invalid(label + ": length")
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            raise Invalid(label + ": pattern")
    elif kind == "integer":
        if (
            not schema.get("minimum", -math.inf)
            <= value
            <= schema.get("maximum", math.inf)
        ):
            raise Invalid(label + ": numeric bounds")


def validate_handoff(record: dict[str, Any], schema: dict[str, Any]) -> None:
    validate_schema(record, schema)
    if (
        record["oldFence"] >= record["newFence"]
        or record["oldGeneration"] >= record["newGeneration"]
        or record["oldBodyGeneration"] >= record["newBodyGeneration"]
    ):
        raise Invalid("fence/generation not advanced")
    if record["sourceModule"] != record["targetModule"]:
        raise Invalid("pilot cannot transfer canonical module ownership")
    if len(record["witnessPrincipals"]) != len(record["witnessReceiptDigests"]):
        raise Invalid("witness evidence cardinality")
    if record["generatorPrincipal"] in record["witnessPrincipals"]:
        raise Invalid("witness/generator collision")
    if record["oldWriterValid"] and record["newWriterValid"]:
        raise Invalid("two live writers")
    phase = record["phase"]
    if phase == "quarantined":
        if any(
            record[k]
            for k in (
                "oldWriterValid",
                "newWriterValid",
                "oldWriterAdmissionOpen",
                "newWriterAdmissionOpen",
            )
        ):
            raise Invalid("quarantined writer still live or admitting")
        return
    index = PHASES.index(phase)
    if record["oldWriterAdmissionOpen"] != (index == 0):
        raise Invalid("old product admission posture")
    if record["newWriterAdmissionOpen"] != (index >= 8):
        raise Invalid("new product admission before route publication")
    if index >= 2 and "outboxWatermark" not in record:
        raise Invalid("missing outbox watermark")
    if index >= 4 and "sourceRange" not in record:
        raise Invalid("missing source export range")
    if "sourceRange" in record:
        span = record["sourceRange"]
        if span["lastExclusiveSequence"] - span["firstSequence"] != span["recordCount"]:
            raise Invalid("invalid canonical export range/count")
    if (
        index >= 5
        and record.get("targetRecordCount") != record["sourceRange"]["recordCount"]
    ):
        raise Invalid("pilot migration count mismatch")
    if index < 3 and (not record["oldWriterValid"] or record["newWriterValid"]):
        raise Invalid("pre-fence writer posture")
    if 3 <= index < 7 and (record["oldWriterValid"] or record["newWriterValid"]):
        raise Invalid("migration target must not be live")
    if index >= 7 and (record["oldWriterValid"] or not record["newWriterValid"]):
        raise Invalid("post-fence writer posture")
    if index >= 3 and record["unknownEffectCount"]:
        raise Invalid("unresolved effect at mutation cutover")
    required = {"migrationPlan", "rollback", "revocationFrontier", "schema"}
    if index >= 2:
        required.add("outboxInventory")
    if index >= 4:
        required.add("sourceSnapshot")
    if index >= 5:
        required.add("targetSnapshot")
    if index >= 6:
        required.add("consumerCompatibility")
    if index >= 8:
        required.add("route")
    if required - set(record["evidenceDigests"]):
        raise Invalid("phase evidence incomplete")


def validate_transition(
    before: dict[str, Any], after: dict[str, Any], schema: dict[str, Any]
) -> None:
    validate_handoff(before, schema)
    validate_handoff(after, schema)
    fixed = (
        "operationId",
        "domainId",
        "sourceModule",
        "targetModule",
        "sourceOrgan",
        "targetOrgan",
        "sourceCommit",
        "sourceTree",
        "oldGeneration",
        "newGeneration",
        "oldFence",
        "newFence",
        "generatorPrincipal",
        "witnessPrincipals",
        "witnessReceiptDigests",
        "authorityEpoch",
        "oldBodyGeneration",
        "newBodyGeneration",
        "sourceManifestDigest",
        "targetManifestDigest",
        "sourceHostDigest",
        "targetHostDigest",
        "rollbackPredecessorDigest",
    )
    if any(before[k] != after[k] for k in fixed):
        raise Invalid("handoff identity drift")
    if after == before:  # Identical observation retry only; performs no effect.
        return
    if before["phase"] == "quarantined":
        raise Invalid("recovery needs a separately authorized new transition")
    if (
        after["phase"] != "quarantined"
        and PHASES.index(after["phase"]) != PHASES.index(before["phase"]) + 1
    ):
        raise Invalid("phase skip or rollback replay")
    expected = hashlib.sha256(
        json.dumps(before, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if after["previousReceiptDigest"] != expected:
        raise Invalid("receipt predecessor mismatch")
    # Earlier evidence is immutable. A new plan/frontier starts a new handoff.
    for key in ("outboxWatermark", "sourceRange", "targetRecordCount"):
        if key in before and after.get(key) != before[key]:
            raise Invalid("handoff progress drift")
    if any(
        after["evidenceDigests"].get(k) != v
        for k, v in before["evidenceDigests"].items()
    ):
        raise Invalid("handoff evidence drift")


def fixture_handoff(phase: str = "prepared") -> dict[str, Any]:
    i = PHASES.index(phase)
    evidence = {
        k: "a" * 64
        for k in ("migrationPlan", "rollback", "revocationFrontier", "schema")
    }
    for threshold, key in (
        (2, "outboxInventory"),
        (4, "sourceSnapshot"),
        (5, "targetSnapshot"),
        (6, "consumerCompatibility"),
        (8, "route"),
    ):
        if i >= threshold:
            evidence[key] = "b" * 64
    record = {
        "schemaVersion": 1,
        "recordKind": "state_handoff_receipt",
        "operationId": "fixture.handoff",
        "domainId": "fixture.domain",
        "sourceModule": "kernel.operations",
        "targetModule": "kernel.operations",
        "sourceOrgan": "fixture.old",
        "targetOrgan": "fixture.new",
        "sourceCommit": "1" * 40,
        "sourceTree": "2" * 40,
        "oldGeneration": 1,
        "newGeneration": 2,
        "oldFence": 10,
        "newFence": 11,
        "oldWriterValid": i < 3,
        "newWriterValid": i >= 7,
        "phase": phase,
        "unknownEffectCount": 0,
        "generatorPrincipal": "fixture.generator",
        "witnessPrincipals": ["fixture.witness"],
        "evidenceDigests": evidence,
        "previousReceiptDigest": "0" * 64,
        "authorityGranted": False,
        "externalIdentityVerificationRequired": True,
        "authorityEpoch": 1,
        "oldBodyGeneration": 1,
        "newBodyGeneration": 2,
        "sourceManifestDigest": "c" * 64,
        "targetManifestDigest": "d" * 64,
        "sourceHostDigest": "e" * 64,
        "targetHostDigest": "f" * 64,
        "rollbackPredecessorDigest": "1" * 64,
        "witnessReceiptDigests": ["2" * 64],
        "oldWriterAdmissionOpen": i == 0,
        "newWriterAdmissionOpen": i >= 8,
    }
    if i >= 2:
        record["outboxWatermark"] = 100
    if i >= 4:
        record["sourceRange"] = dict(
            firstSequence=0,
            lastExclusiveSequence=10,
            recordCount=10,
            rangeManifestDigest="3" * 64,
        )
    if i >= 5:
        record["targetRecordCount"] = 10
    return record


class OracleTests(unittest.TestCase):
    schema: dict[str, Any] = {}

    def test_nonzero_mean_centering(self):
        self.assertEqual(centered_regression([(1, 8), (3, 14)]), 3)

    def test_action_cycle_closure(self):
        self.assertEqual(
            action_closure(["a", "b"], [("a", "b"), ("b", "a")], {"a"}, set()),
            {"a", "b"},
        )

    def test_action_forbidden_conflict(self):
        with self.assertRaises(Invalid):
            action_closure(["a", "b"], [("a", "b")], {"a"}, {"b"})

    def test_action_unknown_node(self):
        with self.assertRaises(Invalid):
            action_closure(["a"], [("a", "b")], {"a"}, set())

    def test_invalid_atom_after_conflict(self):
        with self.assertRaises(Invalid):
            interval_feasible([("a", "x", 2, 1), ("b", "x", True, 2)])

    def test_handoff_missing_epoch(self):
        value = fixture_handoff()
        del value["authorityEpoch"]
        with self.assertRaises(Invalid):
            validate_handoff(value, self.schema)

    def test_handoff_no_early_new_admission(self):
        value = fixture_handoff("new_writer_fenced")
        value["newWriterAdmissionOpen"] = True
        with self.assertRaises(Invalid):
            validate_handoff(value, self.schema)

    def test_handoff_no_late_old_admission(self):
        value = fixture_handoff("admission_stopped")
        value["oldWriterAdmissionOpen"] = True
        with self.assertRaises(Invalid):
            validate_handoff(value, self.schema)

    def test_handoff_owner_transfer_requires_new_profile(self):
        value = fixture_handoff()
        value["targetModule"] = "cognitive.store"
        with self.assertRaises(Invalid):
            validate_handoff(value, self.schema)

    def test_handoff_export_range_count(self):
        value = fixture_handoff("snapshotted")
        value["sourceRange"]["recordCount"] = 11
        with self.assertRaises(Invalid):
            validate_handoff(value, self.schema)

    def test_handoff_migration_count(self):
        value = fixture_handoff("migrated")
        value["targetRecordCount"] = 11
        with self.assertRaises(Invalid):
            validate_handoff(value, self.schema)

    def test_handoff_missing_drain_watermark(self):
        value = fixture_handoff("drained")
        del value["outboxWatermark"]
        with self.assertRaises(Invalid):
            validate_handoff(value, self.schema)

    def test_handoff_progress_immutable(self):
        before = fixture_handoff("drained")
        after = fixture_handoff("old_writer_fenced")
        after["outboxWatermark"] += 1
        after["previousReceiptDigest"] = hashlib.sha256(
            json.dumps(before, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        with self.assertRaisesRegex(Invalid, "progress drift"):
            validate_transition(before, after, self.schema)

    def test_handoff_quarantine_closes_admission(self):
        before = fixture_handoff("route_published")
        after = copy.deepcopy(before)
        after.update(
            phase="quarantined",
            oldWriterValid=False,
            newWriterValid=False,
            oldWriterAdmissionOpen=False,
            newWriterAdmissionOpen=False,
        )
        after["previousReceiptDigest"] = hashlib.sha256(
            json.dumps(before, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        validate_transition(before, after, self.schema)
        after["newWriterAdmissionOpen"] = True
        with self.assertRaises(Invalid):
            validate_handoff(after, self.schema)

    def test_handoff_body_generation_advance(self):
        value = fixture_handoff()
        value["newBodyGeneration"] = 1
        with self.assertRaises(Invalid):
            validate_handoff(value, self.schema)

    def test_scaled_covariance(self):
        self.assertEqual(covariance_z([[Fraction(2)]], [Fraction(6)]), [3])

    def test_correlated_covariance(self):
        self.assertEqual(covariance_z([[2, 1], [1, 2]], [5, 1]), [3, -1])

    def test_identity_covariance(self):
        self.assertEqual(covariance_z([[1, 0], [0, 1]], [2, -4]), [2, -4])

    def test_singular_covariance(self):
        with self.assertRaises(Invalid):
            covariance_z([[1, 1], [1, 1]], [2, 2])

    def test_indefinite_covariance(self):
        with self.assertRaises(Invalid):
            covariance_z([[1, 2], [2, 1]], [1, 2])

    def test_nonsymmetric_covariance(self):
        with self.assertRaises(Invalid):
            covariance_z([[1, 0], [1, 1]], [1, 2])

    def test_numeric_ties(self):
        for n, want in ((25, 2), (35, 4), (-25, -2), (-35, -4), (0, 0)):
            with self.subTest(n=n):
                self.assertEqual(rescale(n, 10, 1, "ties_even"), want)

    def test_numeric_toward_zero(self):
        self.assertEqual(rescale(-35, 10, 1, "toward_zero"), -3)

    def test_numeric_roundtrip(self):
        for n in (-1000000, -123457, -1, 0, 1, 123457, 1000000):
            q = rescale(n, 1000000, 1 << 24, "ties_even")
            self.assertEqual(rescale(q, 1 << 24, 1000000, "ties_even"), n)

    def test_numeric_overflow(self):
        with self.assertRaises(Invalid):
            rescale(127, 1, 2, "ties_even", bits=8)

    def test_unknown_numeric_profile(self):
        with self.assertRaises(Invalid):
            rescale(1, 1, 1, "guess")

    def test_boolean_not_integer(self):
        with self.assertRaises(Invalid):
            rescale(True, 1, 1, "ties_even")

    def test_ess_stricter_floor(self):
        self.assertEqual(effective_ess_minimum(1000, [200, 400]), 400)
        self.assertEqual(effective_ess_minimum(9000, [200]), 900)
        self.assertEqual(effective_ess_minimum(1000, [700]), 700)

    def test_interval_conflict_core(self):
        atoms = [("a", "x", 0, 1), ("b", "x", 2, 3), ("c", "y", -9, 9)]
        self.assertEqual(interval_core(atoms), atoms[:2])
        self.assertEqual(interval_core(list(reversed(atoms))), atoms[:2])

    def test_interval_feasible(self):
        self.assertEqual(interval_core([("a", "x", 0, 2), ("b", "x", 1, 3)]), [])

    def test_interval_budget(self):
        with self.assertRaisesRegex(Invalid, "budget_exhausted"):
            interval_core([("a", "x", 0, 1), ("b", "x", 2, 3)], budget=1)

    def test_interval_duplicate(self):
        with self.assertRaises(Invalid):
            interval_core([("a", "x", 0, 1), ("a", "x", 2, 3)])

    def test_sequential_dr_gold(self):
        f = Fraction
        rows = [
            dict(
                v=f(1, 4),
                q=f(1, 4),
                reward=f(1, 5),
                behavior=f(1, 2),
                evaluation=f(1, 4),
                discount=f(9, 10),
            ),
            dict(
                v=f(1, 2),
                q=f(1, 2),
                reward=f(1),
                behavior=f(1, 4),
                evaluation=f(1, 2),
                discount=f(1),
            ),
        ]
        self.assertEqual(sequential_dr(rows), f(9, 10))

    def test_sequential_zero_support(self):
        with self.assertRaises(Invalid):
            sequential_dr(
                [dict(v=0, q=0, reward=1, behavior=0, evaluation=1, discount=1)]
            )

    def test_sequential_missing_history_fields(self):
        with self.assertRaises(Invalid):
            sequential_dr([{"reward": Fraction(1)}])

    def test_handoff_every_phase_reopen(self):
        for phase in PHASES:
            value = fixture_handoff(phase)
            validate_handoff(json.loads(json.dumps(value)), self.schema)

    def test_handoff_full_transition_chain(self):
        before = fixture_handoff()
        for phase in PHASES[1:]:
            after = fixture_handoff(phase)
            after["previousReceiptDigest"] = hashlib.sha256(
                json.dumps(before, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            validate_transition(before, after, self.schema)
            before = after

    def test_handoff_two_writers(self):
        value = fixture_handoff("new_writer_fenced")
        value["oldWriterValid"] = True
        with self.assertRaises(Invalid):
            validate_handoff(value, self.schema)

    def test_handoff_stale_fence(self):
        value = fixture_handoff()
        value["newFence"] = value["oldFence"]
        with self.assertRaises(Invalid):
            validate_handoff(value, self.schema)

    def test_handoff_unknown_effect(self):
        value = fixture_handoff("old_writer_fenced")
        value["unknownEffectCount"] = 1
        with self.assertRaises(Invalid):
            validate_handoff(value, self.schema)

    def test_handoff_missing_evidence(self):
        value = fixture_handoff("route_published")
        del value["evidenceDigests"]["route"]
        with self.assertRaises(Invalid):
            validate_handoff(value, self.schema)

    def test_handoff_role_collision(self):
        value = fixture_handoff()
        value["witnessPrincipals"] = [value["generatorPrincipal"]]
        with self.assertRaises(Invalid):
            validate_handoff(value, self.schema)

    def test_handoff_no_authority(self):
        value = fixture_handoff()
        value["authorityGranted"] = True
        with self.assertRaises(Invalid):
            validate_handoff(value, self.schema)

    def test_handoff_unknown_secret_field(self):
        value = fixture_handoff()
        value["secret"] = "forbidden"
        with self.assertRaises(Invalid):
            validate_handoff(value, self.schema)

    def test_handoff_phase_skip(self):
        with self.assertRaises(Invalid):
            validate_transition(
                fixture_handoff(), fixture_handoff("drained"), self.schema
            )

    def test_handoff_identity_drift(self):
        after = fixture_handoff("admission_stopped")
        after["operationId"] = "other"
        with self.assertRaises(Invalid):
            validate_transition(fixture_handoff(), after, self.schema)

    def test_handoff_idempotent_observation(self):
        before = fixture_handoff()
        validate_transition(before, copy.deepcopy(before), self.schema)

    def test_unknown_schema_keyword(self):
        with self.assertRaises(Invalid):
            validate_schema("x", {"type": "string", "unimplementedRule": True})

    def test_duplicate_json_key(self):
        with self.assertRaises(Invalid):
            json.loads('{"a":1,"a":2}', object_pairs_hook=pairs)


def self_test(base: Path) -> int:
    OracleTests.schema = load(base / "STATE_HANDOFF.schema.json")
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(OracleTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(
        json.dumps(
            {
                "kind": "analytic_qualification_fixture",
                "testsRun": result.testsRun,
                "passed": result.wasSuccessful(),
                "runtimeProof": False,
                "independentAcceptance": False,
                "authorityGranted": False,
            },
            sort_keys=True,
        )
    )
    return 0 if result.wasSuccessful() else 1


def git_bytes(root: Path, rel: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), "show", "HEAD:" + rel],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise Invalid("committed source path missing: " + rel)
    return result.stdout


def verify_details(base: Path, run_tests: bool = True) -> int:
    """Companion-only verification, deliberately not canonical repository CI."""
    index = load(base / "DETAILS.json")
    gaps = load(base / "DETAIL_GAPS.json")
    if (
        index["schema"] != "hepta.module-detailed-design-index.v1"
        or index["schemaVersion"] != 1
        or index["planVersion"] != "8.0.0"
        or index["moduleCount"] != 40
        or len(index["rows"]) != 40
    ):
        raise Invalid("detailed index identity or count")
    rows = index["rows"]
    modules = {row["module"] for row in rows}
    if len(modules) != 40 or any(
        value is not False for value in index["claimBoundary"].values()
    ):
        raise Invalid("duplicate module or positive claim")
    expected_files = set()
    named_test_count = 0
    for row in rows:
        mid = row["module"]
        if re.fullmatch(r"[a-z]+[.][a-z]+", mid) is None:
            raise Invalid("module ID grammar")
        expected = str(REL / "detail" / (mid + ".md"))
        if (
            row["path"] != expected
            or row["guide"] != f"docs/modules/{mid}/TECHNICAL.md"
        ):
            raise Invalid(mid + ": canonical path shape")
        if (
            row["state"] != "specified"
            or row["productTestsExecuted"] is not False
            or row["runtimeComposed"] is not False
            or not row["workPackages"]
            or not row["declaredRoots"]
        ):
            raise Invalid(mid + ": design status or binding")
        path = base / "detail" / (mid + ".md")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise Invalid(mid + ": design digest drift")
        text = data.decode("utf-8")
        if not text.startswith(f"# {mid}: implementation design\n") or not all(
            re.search(r"^## " + str(number) + r"\. \S", text, re.M)
            for number in range(1, len(HEADINGS) + 1)
        ):
            raise Invalid(mid + ": design sections")
        test_ids = re.findall(r"^- `?([A-Z0-9-]+-[0-9]{2})`?:", text, re.M)
        if not test_ids or len(set(test_ids)) != len(test_ids):
            raise Invalid(mid + ": missing or duplicate named product-test designs")
        named_test_count += len(test_ids)
        expected_files.add(path.name)
    if {path.name for path in (base / "detail").glob("*.md")} != expected_files:
        raise Invalid("unindexed detail file")
    external_ids = [f"RDY-EXT-{i:03d}" for i in range(1, 10)]
    if index["externalGateIds"] != external_ids:
        raise Invalid("external gate projection")
    if (
        gaps["allGapsClosed"] is not False
        or gaps["semanticReviewPassed"] is not False
        or len(gaps["moduleDesignRequirements"]) != 40
        or {row["module"] for row in gaps["moduleDesignRequirements"]} != modules
        or [row["id"] for row in gaps["auditRequirements"]]
        != [f"AUD-{i:02d}" for i in range(1, 10)]
    ):
        raise Invalid("requirement coverage or false closure")
    external = gaps["externalCapabilityGates"]
    if [row["id"] for row in external] != external_ids or any(
        row["repositoryDocumentationMaySelfCertify"] is not False for row in external
    ):
        raise Invalid("external gate self-certification")
    for row in gaps["auditRequirements"]:
        if (
            row["state"] not in {"specified", "blocked_external"}
            or not row["remainingGate"]
        ):
            raise Invalid("audit disposition")
        for evidence in row["evidence"]:
            name = evidence.split("#", 1)[0]
            if (
                name.startswith(str(REL) + "/")
                and not (base / name[len(str(REL)) + 1 :]).is_file()
            ):
                raise Invalid(row["id"] + ": companion evidence absent")
    if run_tests and self_test(base):
        return 1
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_COMPANION_CONFORMANCE",
                "modules": 40,
                "namedProductTestDesigns": named_test_count,
                "repositoryBindingsChecked": False,
                "productTestsExecuted": False,
                "allGapsClosed": False,
                "independentReview": False,
                "authorityGranted": False,
            },
            sort_keys=True,
        )
    )
    return 0


def verify(root: Path) -> int:
    """Add canonical repository bindings to companion-only checks."""
    base = root / REL
    verify_details(base, run_tests=False)
    index = load(base / "DETAILS.json")
    canonical = load(root / "docs/modules/MODULES.json")["modules"]
    source_rows = load(root / "docs/modules/SOURCE_BINDINGS.json")["bindings"]
    readiness = load(root / "docs/readiness/READINESS.json")
    packages = {
        row["id"] for row in load(root / "docs/delivery/WORK_PACKAGES.json")["packages"]
    }
    expected = {row["id"] for row in canonical}
    bindings = {row["module"]: row for row in source_rows}
    lanes = {}
    for lane in readiness["implementationLanes"]:
        for mid in lane["modules"]:
            if mid in lanes:
                raise Invalid("duplicate canonical lane binding")
            lanes[mid] = lane["id"]
    if (
        len(canonical) != 40
        or len(expected) != 40
        or len(source_rows) != 40
        or set(bindings) != expected
        or set(lanes) != expected
        or {row["module"] for row in index["rows"]} != expected
    ):
        raise Invalid("canonical closed-world module bindings")
    for row in index["rows"]:
        mid = row["module"]
        if (
            row["lane"] != lanes[mid]
            or row["declaredRoots"] != bindings[mid]["declaredRoots"]
        ):
            raise Invalid(mid + ": lane/source-root drift")
        if not set(row["workPackages"]) <= packages:
            raise Invalid(mid + ": unknown package")
        guide = git_bytes(root, row["guide"]).decode("utf-8")
        if not all(package in guide for package in row["workPackages"]):
            raise Invalid(mid + ": work package absent from committed guide")
        if any(
            not (root / source_root).exists() for source_root in row["declaredRoots"]
        ):
            raise Invalid(mid + ": absent declared source root")
    external = load(root / "docs/readiness/GAPS.json")["externalCapabilityGates"]
    if [row["id"] for row in external] != index["externalGateIds"] or any(
        row["repositoryDocumentationMaySelfCertify"] is not False for row in external
    ):
        raise Invalid("canonical external gates")
    for row in load(base / "DETAIL_GAPS.json")["auditRequirements"]:
        for evidence in row["evidence"]:
            if not (root / evidence.split("#", 1)[0]).is_file():
                raise Invalid(row["id"] + ": evidence path absent")
    result = self_test(base)
    if result:
        return result
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_DETAILED_DESIGN_CONFORMANCE",
                "modules": 40,
                "repositoryBindingsChecked": True,
                "allGapsClosed": False,
                "meaning": "coverage_hashes_paths_and_analytic_oracles_only",
                "independentReview": False,
                "productTestsExecuted": False,
                "authorityGranted": False,
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["self-test", "verify-details", "verify"])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--fixture-dir", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "self-test":
            return self_test(args.fixture_dir or args.root / REL)
        if args.command == "verify-details":
            return verify_details(args.fixture_dir or args.root / REL)
        return verify(args.root)
    except (Invalid, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print("FAIL_HEPTA_DETAILED_DESIGN: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
