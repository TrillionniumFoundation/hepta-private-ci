"""Model-free runner eligibility and unmodified-reader safeguards."""

import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from strong_rag_host_gate import SCHEMA, assess, main


def cpu_info(flag_sets, model="Synthetic pinned CPU"):
    return "\n\n".join(
        f"processor : {i}\nmodel name : {model}\nflags : {' '.join(flags)}"
        for i, flags in enumerate(flag_sets)
    )


class Bf16RunnerGateTests(unittest.TestCase):
    def test_actual_amd_epyc_7763_without_bf16_fails_closed(self):
        info = cpu_info([["sse2", "avx2", "fma", "f16c"]] * 4, "AMD EPYC 7763")
        receipt = assess(info, machine="x86_64", runner_arch="X64")
        self.assertFalse(receipt["host_eligible"])
        self.assertEqual(receipt["new_model_calls"], 0)
        self.assertFalse(receipt["production_accepted"])

    def test_accelerated_bf16_cpu_is_eligible_not_benchmark_qualified(self):
        for hardware_flag in ("avx512_bf16", "amx_bf16"):
            with self.subTest(hardware_flag=hardware_flag):
                receipt = assess(
                    cpu_info([["avx2", hardware_flag]] * 2),
                    machine="x86_64",
                    runner_arch="X64",
                )
                self.assertTrue(receipt["host_eligible"])
                self.assertEqual(
                    receipt["shared_acceleration_features"], [hardware_flag]
                )
                self.assertEqual(receipt["schema"], SCHEMA)
                self.assertFalse(receipt["full_inference_latency_qualified"])

    def test_mixed_cpu_capabilities_never_qualify(self):
        data = cpu_info([["avx512_bf16"], ["avx2"]])
        result = assess(data, machine="x86_64", runner_arch="X64")
        self.assertFalse(result["host_eligible"])
        self.assertEqual(result["shared_acceleration_features"], [])

    def test_individually_accelerated_cpus_require_a_shared_bf16_isa(self):
        data = cpu_info([["avx512_bf16"], ["amx_bf16"]])
        receipt = assess(data, machine="x86_64", runner_arch="X64")
        self.assertFalse(receipt["host_eligible"])
        self.assertEqual(receipt["shared_acceleration_features"], [])

    def test_every_cpu_record_requires_its_own_complete_fields(self):
        first, second = cpu_info([["avx512_bf16"]] * 2).split("\n\n")
        for field in ("processor", "model name", "flags"):
            for change in ("missing", "empty", "duplicate"):
                with self.subTest(field=field, change=change):
                    lines = second.splitlines()
                    target = next(line for line in lines if line.startswith(field))
                    if change == "missing":
                        lines.remove(target)
                    elif change == "empty":
                        lines[lines.index(target)] = f"{field} : "
                    else:
                        lines.append(target)
                    receipt = assess(
                        first + "\n\n" + "\n".join(lines), machine="x86_64"
                    )
                    self.assertFalse(receipt["host_eligible"])
                    self.assertFalse(receipt["production_accepted"])
                    self.assertEqual(receipt["new_model_calls"], 0)

    def test_processor_identities_must_be_decimal_and_distinct(self):
        original = cpu_info([["avx512_bf16"]] * 2)
        for identity in ("0", "00", "-1", "one", "1 2"):
            with self.subTest(identity=identity):
                info = original.replace("processor : 1", f"processor : {identity}")
                self.assertFalse(assess(info, machine="x86_64")["host_eligible"])

    def test_offline_cpu_identity_gaps_preserve_shared_capability(self):
        info = cpu_info([["avx2", "avx512_bf16"]] * 2).replace(
            "processor : 1", "processor : 7"
        )
        receipt = assess(info, machine="x86_64", runner_arch="X64")
        self.assertTrue(receipt["host_eligible"])
        self.assertEqual(receipt["logical_cpu_records"], 2)
        self.assertEqual(receipt["shared_acceleration_features"], ["avx512_bf16"])
        self.assertFalse(receipt["full_inference_latency_qualified"])

    def test_truncated_lines_and_whitespace_only_input_fail_closed(self):
        complete = cpu_info([["avx512_bf16"]])
        for truncated in ("\nprocessor", "\n\nprocessor : 1", "\nflags"):
            with self.subTest(truncated=truncated):
                self.assertFalse(
                    assess(complete + truncated, machine="x86_64")["host_eligible"]
                )
        with self.assertRaises(ValueError):
            assess(" \t\n\n", machine="x86_64")

    def test_architecture_and_runner_label_are_bound(self):
        cpu = cpu_info([["avx512_bf16"]])
        self.assertFalse(
            assess(cpu, machine="aarch64", runner_arch="ARM64")["host_eligible"]
        )
        self.assertFalse(
            assess(cpu, machine="x86_64", runner_arch="ARM64")["host_eligible"]
        )

    def test_missing_flags_model_or_truncated_cpuinfo_fail_closed(self):
        self.assertFalse(assess("processor : 0", machine="x86_64")["host_eligible"])
        self.assertFalse(
            assess("processor: 0\nflags: avx512_bf16", machine="x86_64")[
                "host_eligible"
            ]
        )
        for invalid in ("", "x" * (256 * 1024 + 1)):
            with self.assertRaises(ValueError):
                assess(invalid, machine="x86_64")

    def test_cli_records_rejection_before_exiting_without_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "host.json"
            with (
                patch("sys.argv", ["gate", "--output", str(output)]),
                patch("strong_rag_host_gate.sys.platform", "linux"),
                patch("strong_rag_host_gate.platform.machine", return_value="x86_64"),
                patch(
                    "strong_rag_host_gate.Path.read_text",
                    return_value=cpu_info([["avx2"]]),
                ),
                patch.dict("strong_rag_host_gate.os.environ", {"RUNNER_ARCH": "X64"}),
            ):
                with self.assertRaises(SystemExit) as err:
                    main()
            self.assertEqual(err.exception.code, 3)
            receipt = json.loads(output.read_text())
            self.assertFalse(receipt["host_eligible"])
            self.assertEqual(receipt["new_model_calls"], 0)

    def test_cli_preserves_receipt_for_a_truncated_second_cpu(self):
        info = cpu_info([["avx512_bf16"]]) + "\n\nprocessor : 1\nmodel name : CPU"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "host.json"
            with (
                patch("sys.argv", ["gate", "--output", str(output)]),
                patch("strong_rag_host_gate.sys.platform", "linux"),
                patch("strong_rag_host_gate.platform.machine", return_value="x86_64"),
                patch("strong_rag_host_gate.Path.read_text", return_value=info),
                patch.dict("strong_rag_host_gate.os.environ", {"RUNNER_ARCH": "X64"}),
            ):
                with self.assertRaises(SystemExit) as err:
                    main()
            self.assertEqual(err.exception.code, 3)
            receipt = json.loads(output.read_text())
            self.assertFalse(receipt["host_eligible"])
            self.assertEqual(receipt["logical_cpu_records"], 2)
            self.assertEqual(receipt["new_model_calls"], 0)
            self.assertFalse(receipt["production_accepted"])


if __name__ == "__main__":
    unittest.main()
