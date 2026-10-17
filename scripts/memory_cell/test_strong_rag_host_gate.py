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


if __name__ == "__main__":
    unittest.main()
