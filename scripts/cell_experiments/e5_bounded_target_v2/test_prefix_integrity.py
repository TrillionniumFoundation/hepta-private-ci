"""Offline regression controls; synthetic token counts never establish E5 results."""

import ast
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import count_tokens as v2
import run_targets

ROOT = Path(__file__).resolve().parents[3]
MATERIALS = ROOT / "qualification/cell-e5-material-adapter-20261120"
INDEX = MATERIALS / "MATERIAL_INDEX.json"
PREFIX = MATERIALS / "SOURCE_PREFIX_FREEZE.json"


def fixture(refused=(), closed=16):
    sources = v2.original_source_ids(INDEX, PREFIX)
    request = {
        "schema": "hepta.e5.v2.complete-target-tokenizer-request.v1",
        **{k: chr(97 + i) * 64 for i, k in enumerate(v2.TUPLE)},
        "records": [],
        "source_refusals": [],
    }
    counter = {
        "schema": "hepta.e5-codec-tokenizer-readout.v1",
        "serialization": "native_chat_v2; separately encode exact inference prefix and full assistant continuation",
        "truncation": False,
        **{k: 0 for k in v2.ZERO_COUNTERS},
        **{k: request[k] for k in v2.TUPLE},
        "rows": [],
    }
    for ordinal, source in enumerate(sources):
        identity = {"ordinal": ordinal, "source_id": source}
        if ordinal in refused:
            request["source_refusals"].append({**identity, "status": "SOURCE_REFUSAL"})
            continue
        prompt, target = f"synthetic before {ordinal}", "[]"
        request["records"].append(
            {
                **identity,
                "prompt": prompt,
                "prompt_sha256": v2.sha(prompt.encode()),
                "target": target,
                **{k: ordinal < closed for k in v2.GATES},
            }
        )
        counter["rows"].append(
            {
                **identity,
                "prompt_sha256": v2.sha(prompt.encode()),
                "prompt_bytes": len(prompt.encode()),
                "prefix_tokens": 100,
                "prefix_ids_sha256": "d" * 64,
                "target_ids_sha256": "e" * 64,
                "prefix_labels_masked": 100,
                "all_target_labels_retained": 10,
                "target_sha256": v2.sha(target.encode()),
                "target_bytes": len(target.encode()),
                "target_tokens": 10,
                "complete_sft_positions": 110,
                "static_representation_admitted": ordinal < closed,
                "training_execution_admitted": False,
                **{
                    k: True
                    for k in (
                        "fits_original_native_message_bytes_65536",
                        "fits_original_input_4096",
                        "fits_original_sft_3584",
                        "fits_original_generation_384",
                        "fits_original_answer_bytes_32768",
                    )
                },
            }
        )
    counter["prefix_1_4_16_representable"] = {
        str(n): all(r["static_representation_admitted"] for r in counter["rows"][:n])
        for n in (1, 4, 16)
    }
    return sources, request, counter


def serialized(request, counter):
    raw = (json.dumps(request) + "\n").encode()
    return raw, (json.dumps({**counter, "request_sha256": v2.sha(raw)}) + "\n").encode()


class PrefixIntegrityTests(unittest.TestCase):
    def test_target_source_freeze_covers_actual_new_helper(self):
        pins = []
        for module in (run_targets, v2):
            path = Path(module.__file__).resolve()
            raw = path.read_bytes()
            pins.append(
                {
                    "path": str(path.relative_to(ROOT)),
                    "bytes": len(raw),
                    "sha256": v2.sha(raw),
                }
            )
        run_targets.verify_source(ROOT, {"source_pins": pins})
        for incomplete in ([], pins[:1], pins[1:]):
            with (
                self.subTest(pins=incomplete),
                self.assertRaisesRegex(ValueError, "must be source-pinned"),
            ):
                run_targets.verify_source(ROOT, {"source_pins": incomplete})

    def test_refused_original_slot_is_not_compacted(self):
        sources, request, counter = fixture(refused=(13,))
        original = ROOT / "scripts/cell_experiments/e5_source_codec_v1/count_tokens.py"
        expression = next(
            n
            for n in ast.walk(ast.parse(original.read_text()))
            if isinstance(n, ast.DictComp)
            and "static_representation_admitted" in ast.unparse(n)
        )
        old = eval(
            compile(ast.Expression(expression), str(original), "eval"),
            {"rows": counter["rows"]},
        )
        self.assertTrue(old["16"])
        fixed = v2.complete_readout(*serialized(request, counter), sources)
        self.assertEqual(
            fixed["prefix_1_4_16_64_representable"],
            {"1": True, "4": True, "16": False, "64": False},
        )
        self.assertEqual([r["source_id"] for r in fixed["rows"]], sources)
        self.assertEqual(fixed["rows"][13]["status"], "SOURCE_REFUSAL")

    def test_complete_original_prefixes_and_64_absence(self):
        for completed in (0, 1, 4, 16):
            with self.subTest(completed=completed):
                sources, request, counter = fixture(closed=completed)
                fixed = v2.complete_readout(*serialized(request, counter), sources)
                self.assertEqual(
                    fixed["prefix_1_4_16_64_representable"],
                    {str(n): n <= completed for n in (1, 4, 16, 64)},
                )
                self.assertEqual(fixed["missing_sources_for_64"], 48)
                self.assertFalse(
                    any(fixed["training_prefix_1_4_16_64_admitted"].values())
                )

    def test_empty_short_and_missing13_requests_fail(self):
        for kept in ((), tuple(range(4)), tuple(i for i in range(16) if i != 13)):
            sources, request, counter = fixture()
            request["records"] = [r for r in request["records"] if r["ordinal"] in kept]
            counter["rows"] = [r for r in counter["rows"] if r["ordinal"] in kept]
            with self.subTest(kept=kept), self.assertRaises(ValueError):
                v2.complete_readout(*serialized(request, counter), sources)

    def test_invalid_request_positions_fail(self):
        sources, original, counter = fixture()
        for mutation in (
            lambda rows: rows.append(copy.deepcopy(rows[0])),
            lambda rows: rows.reverse(),
            lambda rows: rows[0].update(source_id=rows[0]["source_id"].lower()),
            lambda rows: rows[0].update(source_id=rows[1]["source_id"]),
            *(
                lambda rows, value=v: rows[0].update(ordinal=value)
                for v in (False, 0.0, -1, 16)
            ),
        ):
            request = copy.deepcopy(original)
            mutation(request["records"])
            with self.assertRaises(ValueError):
                v2.complete_readout(*serialized(request, counter), sources)

    def test_refusals_are_an_exact_disjoint_partition(self):
        sources, original, counter = fixture(refused=(1, 13))
        for mutation in (
            lambda r: r["source_refusals"].clear(),
            lambda r: r["source_refusals"].reverse(),
            lambda r: r["source_refusals"].append(r["source_refusals"][0]),
            lambda r: r["source_refusals"][0].update(status="MEASURED"),
            lambda r: r["records"].insert(
                1, {**r["records"][0], "ordinal": 1, "source_id": sources[1]}
            ),
        ):
            request = copy.deepcopy(original)
            mutation(request)
            with self.assertRaises(ValueError):
                v2.complete_readout(*serialized(request, counter), sources)

    def test_counter_rows_cannot_be_dropped_swapped_or_rebound(self):
        sources, request, original = fixture()
        mutations = [
            lambda rows: rows.pop(),
            lambda rows: rows.reverse(),
            lambda rows: rows.append(copy.deepcopy(rows[0])),
        ]
        mutations += [
            lambda rows, key=k, value=v: rows[0].update({key: value})
            for k, v in (
                ("ordinal", False),
                ("source_id", sources[1]),
                ("prompt_sha256", "f" * 64),
                ("target_sha256", "f" * 64),
                ("prefix_tokens", True),
                ("target_tokens", True),
                ("complete_sft_positions", 111),
                ("training_execution_admitted", True),
            )
        ]
        for mutation in mutations:
            counter = copy.deepcopy(original)
            mutation(counter["rows"])
            with self.assertRaises(ValueError):
                v2.complete_readout(*serialized(request, counter), sources)

    def test_exact_request_and_freeze_tuple_required(self):
        sources, request, original = fixture()
        raw_request, raw_counter = serialized(request, original)
        with self.assertRaises(ValueError):
            v2.complete_readout(raw_request + b"\n", raw_counter, sources)
        for key in v2.TUPLE:
            counter = {**original, key: "f" * 64}
            with self.subTest(key=key), self.assertRaises(ValueError):
                v2.complete_readout(*serialized(request, counter), sources)

    def test_wrong_schemas_entrypoint_and_missing_binding_fail(self):
        sources, request, counter = fixture()
        for object_name, key, value in (
            ("request", "schema", "unrelated"),
            ("request", "tokenizer_entrypoint", "old-counter"),
            ("counter", "schema", "unrelated"),
            ("request", v2.TUPLE[0], None),
        ):
            inputs = {
                "request": copy.deepcopy(request),
                "counter": copy.deepcopy(counter),
            }
            inputs[object_name][key] = value
            with (
                self.subTest(object=object_name, key=key),
                self.assertRaises(ValueError),
            ):
                v2.complete_readout(
                    *serialized(inputs["request"], inputs["counter"]), sources
                )

    def test_unrepresented_target_keeps_its_original_position(self):
        sources, request, counter = fixture(refused=(13,), closed=0)
        request["records"][1]["target"] = None
        row = counter["rows"][1]
        for key in (
            "target_sha256",
            "target_bytes",
            "fits_original_answer_bytes_32768",
        ):
            del row[key]
        row.update(
            target_tokens=None,
            complete_sft_positions=None,
            fits_original_sft_3584=False,
            fits_original_generation_384=False,
        )
        fixed = v2.complete_readout(*serialized(request, counter), sources)
        self.assertEqual(fixed["rows"][1]["source_id"], sources[1])
        self.assertIsNone(fixed["rows"][1]["target_tokens"])
        self.assertFalse(any(fixed["prefix_1_4_16_64_representable"].values()))

    def test_false_gates_and_original_bounds_cannot_be_promoted(self):
        sources, request, counter = fixture(refused=(13,), closed=0)
        fixed = v2.complete_readout(*serialized(request, counter), sources)
        self.assertFalse(any(fixed["prefix_1_4_16_64_representable"].values()))
        counter["rows"][0]["static_representation_admitted"] = True
        with self.assertRaises(ValueError):
            v2.complete_readout(*serialized(request, counter), sources)
        for value in (1, "true", None):
            sources, request, counter = fixture()
            request["records"][0]["v1_static_context_closed"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                v2.complete_readout(*serialized(request, counter), sources)
        sources, request, counter = fixture()
        counter["rows"][0].update(
            target_tokens=385,
            all_target_labels_retained=385,
            complete_sft_positions=485,
            fits_original_generation_384=False,
            static_representation_admitted=False,
        )
        self.assertFalse(
            v2.complete_readout(*serialized(request, counter), sources)[
                "prefix_1_4_16_representable"
            ]["1"]
        )

    def test_truncation_and_non_tokenizer_scope_are_not_dropped(self):
        sources, request, original = fixture()
        for key, value in (
            ("truncation", True),
            ("truncation", None),
            *((key, value) for key in v2.ZERO_COUNTERS for value in (1, False, None)),
            ("serialization", "changed-template"),
        ):
            counter = {**original, key: value}
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                v2.complete_readout(*serialized(request, counter), sources)

    def test_complete_labels_and_exact_token_identities_are_required(self):
        sources, request, original = fixture()
        for key, value in (
            ("prefix_labels_masked", 99),
            ("all_target_labels_retained", 9),
            ("all_target_labels_retained", True),
            ("prefix_ids_sha256", None),
            ("target_ids_sha256", "not-a-hash"),
        ):
            counter = copy.deepcopy(original)
            counter["rows"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                v2.complete_readout(*serialized(request, counter), sources)

    def test_pinned_manifest_rejects_self_consistent_reordering(self):
        with tempfile.TemporaryDirectory() as directory:
            index = json.loads(INDEX.read_bytes())
            prefix = json.loads(PREFIX.read_bytes())
            index["materials"].reverse()
            prefix["materials"].reverse()
            prefix_path, index_path = (
                Path(directory) / "prefix.json",
                Path(directory) / "index.json",
            )
            prefix_path.write_text(json.dumps(prefix))
            index["prefix_sha256"] = v2.sha(prefix_path.read_bytes())
            index_path.write_text(json.dumps(index))
            with self.assertRaises(ValueError):
                v2.original_source_ids(index_path, prefix_path)

    def test_cli_preserves_raw_bytes_and_reports_all_positions(self):
        sources, request, counter = fixture(refused=(13,), closed=0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_raw, counter_raw = serialized(request, counter)
            (root / "request.json").write_bytes(request_raw)
            (root / "counter.json").write_bytes(counter_raw)
            child = subprocess.run(
                [
                    sys.executable,
                    str(Path(v2.__file__)),
                    "--request",
                    str(root / "request.json"),
                    "--counter-result",
                    str(root / "counter.json"),
                    "--material-index",
                    str(INDEX),
                    "--source-prefix",
                    str(PREFIX),
                    "--output",
                    str(root / "out"),
                ],
                capture_output=True,
            )
            self.assertEqual(child.returncode, 0, child.stderr.decode())
            result = json.loads((root / "out/RESULT.json").read_bytes())
            self.assertEqual([r["source_id"] for r in result["rows"]], sources)
            self.assertFalse(any(result["prefix_1_4_16_64_representable"].values()))
            self.assertEqual(
                (root / "out/ORIGINAL_COUNTER_RESULT.json").read_bytes(), counter_raw
            )
            self.assertEqual((root / "counter.json").read_bytes(), counter_raw)
            self.assertEqual(
                (root / "out/ORIGINAL_REQUEST.json").read_bytes(), request_raw
            )

    def test_invalid_request_is_refused_before_tokenizer_or_output(self):
        _, request, counter = fixture()
        request["records"] = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "request.json").write_bytes(serialized(request, counter)[0])
            child = subprocess.run(
                [
                    sys.executable,
                    str(Path(v2.__file__)),
                    "--request",
                    str(root / "request.json"),
                    "--tokenizer-freeze",
                    str(root / "absent.json"),
                    "--material-index",
                    str(INDEX),
                    "--source-prefix",
                    str(PREFIX),
                    "--output",
                    str(root / "out"),
                ],
                capture_output=True,
            )
            self.assertNotEqual(child.returncode, 0)
            self.assertIn(b"cover every original source exactly once", child.stderr)
            self.assertFalse((root / "out").exists())


if __name__ == "__main__":
    unittest.main()
