"""Execute the *textual* model-cache TTL HIA CFG against independent arithmetic.

This is a narrow Python interpretation of its current SSA-style IR, not the HIA
compiler, a native ABI run, or the original Rust/Chrono oracle. Every supported
operation is checked; unknown instructions fail closed rather than being skipped.
"""

import json
from pathlib import Path
import random
import re
import struct
import unittest


HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "model_cache_ttl.hepta"
FIXTURES = HERE / "model_cache_ttl_oracle_inputs.json"
MASK = (1 << 64) - 1
HEADER = re.compile(r"block ([a-z_][a-z_0-9]*)\((.*)\)$")
ASSIGN = re.compile(r"([a-z_][a-z_0-9]*)(?::[a-z0-9]+)? = ([a-z0-9_.]+)\(([^()]*)\)(?: (\{.*\}))?$")
CALL = re.compile(r"([a-z_][a-z_0-9]*)\(([^()]*)\)$")


def args_list(value):
    return [] if not value.strip() else [item.strip() for item in value.split(",")]


class TextualHiaTtl:
    def __init__(self, text):
        lines = text.splitlines()
        assert lines[0] == "hia-asm.v1 hepta.hia.program.v8 codex_model_cache_ttl"
        assert lines[1].startswith("fn f0(source:readbuf,output:mutbuf,workspace:mutbuf)")
        assert lines[-1] == "end"
        self.blocks = {}
        name = None
        for line in lines[2:-1]:
            if line.startswith("block "):
                found = HEADER.fullmatch(line)
                if not found:
                    raise AssertionError(f"bad block: {line}")
                name = found.group(1)
                if name in self.blocks:
                    raise AssertionError(f"duplicate block: {name}")
                parameters = [part.split(":", 1)[0] for part in args_list(found.group(2))]
                self.blocks[name] = (parameters, [])
            elif line.startswith("  ") and name is not None:
                self.blocks[name][1].append(line.strip())
            else:
                raise AssertionError(f"invalid source line: {line}")
        assert "entry" in self.blocks

    def run(self, source, output_length):
        output = bytearray([0xA5] * output_length)
        buffers = {"source": source, "output": output, "workspace": bytearray()}
        name, inputs = "entry", ["source", "output", "workspace"]
        for _ in range(64):
            parameters, statements = self.blocks[name]
            assert len(inputs) == len(parameters), (name, inputs, parameters)
            variables = dict(zip(parameters, inputs))
            transfer = None
            for statement in statements:
                if statement.startswith("ret("):
                    result = variables[statement[4:-1]]
                    return result, bytes(output)
                if statement.startswith("branch "):
                    match = re.fullmatch(r"branch (\w+) (\w+\([^()]*\)) (\w+\([^()]*\))", statement)
                    assert match, statement
                    target = match.group(2 if variables[match.group(1)] else 3)
                    assert target is not None
                    transfer = self._transfer(target, variables)
                    break
                if statement.startswith("jump "):
                    transfer = self._transfer(statement[5:], variables)
                    break
                assignment = ASSIGN.fullmatch(statement)
                assert assignment, statement
                variable, operation, operands, literal = assignment.groups()
                values = [variables[operand] for operand in args_list(operands)]
                if operation == "const":
                    assert not values and literal is not None
                    result = json.loads(literal)["value"]
                elif operation == "buffer.len":
                    assert len(values) == 1
                    result = len(buffers[values[0]])
                elif operation == "buffer.load.u64.le":
                    assert len(values) == 2
                    result = struct.unpack_from("<Q", buffers[values[0]], values[1])[0]
                elif operation == "buffer.store.u64.le":
                    assert len(values) == 3 and values[0] == "output"
                    struct.pack_into("<Q", buffers[values[0]], values[1], values[2])
                    result = None
                elif operation in ("compare.eq", "compare.le", "compare.ge", "compare.lt"):
                    assert len(values) == 2
                    result = {
                        "compare.eq": lambda a, b: a == b,
                        "compare.le": lambda a, b: a <= b,
                        "compare.ge": lambda a, b: a >= b,
                        "compare.lt": lambda a, b: a < b,
                    }[operation](*values)
                elif operation in ("bool.and", "bool.or"):
                    assert len(values) == 2 and all(isinstance(v, bool) for v in values)
                    result = all(values) if operation == "bool.and" else any(values)
                else:
                    raise AssertionError(f"unsupported HIA operation: {operation}")
                variables[variable] = result
            assert transfer is not None, f"missing terminator in {name}"
            name, inputs = transfer
        raise AssertionError("textual HIA execution exceeded bounded block steps")

    def _transfer(self, call, variables):
        match = CALL.fullmatch(call)
        assert match, call
        target, inputs = match.groups()
        assert target in self.blocks, target
        return target, [variables[value] for value in args_list(inputs)]


def packet(age_seconds=0, age_nanos=0, ttl_seconds=0, ttl_nanos=0, version=1):
    return struct.pack("<QqqQQ", version, age_seconds, age_nanos, ttl_seconds, ttl_nanos)


class ModelCacheTtlTextualIrTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = TextualHiaTtl(SOURCE.read_text(encoding="utf-8"))
        cls.fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))

    def assert_result(self, raw, output_length, status, expected=None):
        got_status, written = self.model.run(raw, output_length)
        self.assertEqual(got_status, status)
        if status == 8:
            self.assertIn(expected, (0, 1))
            self.assertEqual(written[:8], struct.pack("<Q", expected))
            self.assertEqual(written[8:], b"\xa5" * max(0, output_length - 8))
        else:
            self.assertEqual(written, b"\xa5" * output_length)

    def test_literal_decisions_and_error_precedence(self):
        for case in self.fixtures["cases"]:
            with self.subTest(case=case["label"]):
                raw = packet(case["age_seconds"], case["age_nanos"], case["ttl_seconds"], case["ttl_nanos"])
                self.assert_result(raw, 16, 8, int(case["expected_fresh"]))
        for case in self.fixtures["error_cases"]:
            with self.subTest(case=case["label"]):
                age_seconds = case.get("age_seconds", 0)
                raw = packet(age_seconds, case["age_nanos"], 0, case["ttl_nanos"], case["version"])
                raw = raw[:case["source_bytes"]].ljust(case["source_bytes"], b"\x00")
                self.assert_result(raw, case["output_bytes"], case["expected_status"])
        self.assert_result(b"", 0, 0xFFFFFFFE)
        self.assert_result(b"", 8, 0xFFFFFFFF)

    def test_independent_signed_fractional_and_ttl_fuzz(self):
        rng = random.Random(20261122)
        age_seconds_pool = [-9223372036, -86400, -3, -1, 0, 1, 3, 86400, 9223372036]
        ttl_seconds_pool = [0, 1, 2, 86400, 315360000, 9223372036]
        fractions = [0, 1, 2, 999999998, 999999999]
        for i in range(3000):
            age_seconds = rng.choice(age_seconds_pool)
            age_nanos = rng.choice(fractions)
            if age_seconds < 0 or (age_seconds == 0 and rng.choice((True, False))):
                age_nanos = -age_nanos
            ttl_seconds = rng.choice(ttl_seconds_pool)
            ttl_nanos = rng.choice(fractions)
            age_ns = age_seconds * 1000000000 + age_nanos
            ttl_ns = ttl_seconds * 1000000000 + ttl_nanos
            expected = int(ttl_ns > 0 and age_ns <= ttl_ns)
            with self.subTest(case=i):
                self.assert_result(packet(age_seconds, age_nanos, ttl_seconds, ttl_nanos), 8, 8, expected)

    def test_malformed_inputs_never_write(self):
        good = packet(1, 1, 1, 1)
        for n in (0, 1, 7, 8, 9, 16, 39, 41, 48):
            raw = good[:n].ljust(n, b"\x00")
            self.assert_result(raw, 8, 8 if n == 40 else 0xFFFFFFFF)
        for nanos in (1000000000, -1000000000, -9223372036854775808):
            self.assert_result(packet(0, nanos, 1, 0), 8, 0xFFFFFFFF)
        for raw in (packet(1, -1, 1, 0), packet(-1, 1, 1, 0), packet(0, 0, 1, 0, 2)):
            self.assert_result(raw, 8, 0xFFFFFFFF)
        self.assert_result(good, 7, 0xFFFFFFFE)


if __name__ == "__main__":
    unittest.main()
