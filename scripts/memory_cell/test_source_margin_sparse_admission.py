"""A sparse source-margin job must reach parity admission, not a stale gate.

These tests do not run Qwen or authorize model adoption. Actual Qwen2+PEFT
two-forward gradient equivalence is separately tested in test_source_binding_hf.
"""

import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch

from experience_write_trial import write_memory


class SourceMarginSparseAdmissionTests(unittest.TestCase):
    def test_sparse_margin_reaches_exact_source_pretrained_parity_guard(self):
        fake_pretrained = ModuleType("pretrained")
        fake_pretrained.LoRAReader = object
        fake_losses = ModuleType("source_completion_loss")
        fake_losses.BACKENDS = frozenset(("full", "supervised_positions"))
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "snapshot"
            with (
                patch.dict(
                    sys.modules,
                    {
                        "pretrained": fake_pretrained,
                        "source_completion_loss": fake_losses,
                    },
                ),
                patch.dict(os.environ, {"HEPTA_MEMORY_TESTED_COMMIT": "a" * 40}),
                patch(
                    "experience_write_trial.original_documents",
                    return_value=(),
                ),
                patch(
                    "experience_write_trial.model_inputs",
                    return_value=(
                        {"repository": "pinned", "revision": "fixed"},
                        {"inventory_digest": "b" * 64},
                    ),
                ),
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "optimized source write requires an exact parity receipt",
                ):
                    write_memory(
                        Path(folder) / "sources",
                        Path(folder) / "model",
                        output,
                        source_sha="c" * 64,
                        stage_sha="d" * 64,
                        loss_backend="supervised_positions",
                        binding_objective="source_margin",
                    )
            self.assertFalse(output.exists())

    def test_source_margin_other_curriculum_still_rejects_before_model(self):
        fake_pretrained = ModuleType("pretrained")
        fake_pretrained.LoRAReader = object
        fake_losses = ModuleType("source_completion_loss")
        fake_losses.BACKENDS = frozenset(("full", "supervised_positions"))
        with (
            patch.dict(
                sys.modules,
                {
                    "pretrained": fake_pretrained,
                    "source_completion_loss": fake_losses,
                },
            ),
            self.assertRaisesRegex(ValueError, "single-hop curriculum"),
        ):
            write_memory(
                Path("unused-source"),
                Path("unused-model"),
                Path("unused-output"),
                source_sha="c" * 64,
                stage_sha="d" * 64,
                loss_backend="supervised_positions",
                curriculum="source_two_hop",
                binding_objective="source_margin",
            )


if __name__ == "__main__":
    unittest.main()
