"""Hardware scout regressions: no untrusted PR code on personal runners."""

from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from strong_rag_cpu_scout import SCHEMA, STANDARD_IMAGES, census, main

SHA = "a" * 40


def cpuinfo(flags):
    return "processor : 0\nmodel name : Test CPU\nflags : " + " ".join(flags) + "\n"


class StandardRunnerScoutTests(unittest.TestCase):
    def test_ineligible_epyc_is_recorded_not_hidden(self):
        row = census(
            cpuinfo(["avx2", "fma"]),
            machine="x86_64",
            runner_arch="X64",
            image="ubuntu-24.04",
            source_commit=SHA,
        )
        self.assertEqual(row["schema"], SCHEMA)
        self.assertFalse(row["eligible_cpu_for_unchanged_bf16_reader"])
        self.assertFalse(row["same_hardware_on_next_run_guaranteed"])
        self.assertEqual(row["new_model_calls"], 0)
        self.assertFalse(row["production_accepted"])

    def test_accelerated_cpu_is_candidate_not_model_success(self):
        row = census(
            cpuinfo(["avx2", "avx512_bf16"]),
            machine="x86_64",
            runner_arch="X64",
            image="ubuntu-22.04",
            source_commit=SHA,
        )
        self.assertTrue(row["eligible_cpu_for_unchanged_bf16_reader"])
        self.assertFalse(row["eligible_host_reserved"])
        self.assertEqual(row["new_model_calls"], 0)
        self.assertFalse(row["hardware"]["full_inference_latency_qualified"])

    def test_only_documented_standard_hosted_runner_images(self):
        self.assertEqual(len(STANDARD_IMAGES), 3)
        for label in ("self-hosted", "rog", "pocket4", "ubuntu-latest-gpu", "desktop"):
            with self.subTest(label=label), self.assertRaises(ValueError):
                census(
                    cpuinfo(["avx512_bf16"]),
                    machine="x86_64",
                    runner_arch="X64",
                    image=label,
                    source_commit=SHA,
                )

    def test_source_sha_and_mixed_cpu_must_fail_closed(self):
        with self.assertRaises(ValueError):
            census(
                cpuinfo(["avx512_bf16"]),
                machine="x86_64",
                runner_arch="X64",
                image="ubuntu-24.04",
                source_commit="main",
            )
        mixed = (
            cpuinfo(["avx512_bf16"])
            + "processor : 1\nmodel name : Test CPU\nflags : avx2\n"
        )
        row = census(
            mixed,
            machine="x86_64",
            runner_arch="X64",
            image="ubuntu-24.04",
            source_commit=SHA,
        )
        self.assertFalse(row["eligible_cpu_for_unchanged_bf16_reader"])

    def test_cli_writes_once_and_never_overwrites_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            result_path = Path(tmp) / "result.json"
            with (
                patch(
                    "strong_rag_cpu_scout.sys.argv",
                    [
                        "scout",
                        "--runner-image",
                        "ubuntu-24.04",
                        "--source-commit",
                        SHA,
                        "--output",
                        str(result_path),
                    ],
                ),
                patch("strong_rag_cpu_scout.sys.platform", "linux"),
                patch("strong_rag_cpu_scout.platform.machine", return_value="x86_64"),
                patch(
                    "strong_rag_cpu_scout.Path.read_text",
                    return_value=cpuinfo(["avx2"]),
                ),
                patch.dict("strong_rag_cpu_scout.os.environ", {"RUNNER_ARCH": "X64"}),
            ):
                self.assertEqual(main(), 0)
                with result_path.open(encoding="utf-8") as stream:
                    report = json.load(stream)
                self.assertEqual(report["source_commit"], SHA)
                with self.assertRaises(FileExistsError):
                    main()


if __name__ == "__main__":
    unittest.main()
