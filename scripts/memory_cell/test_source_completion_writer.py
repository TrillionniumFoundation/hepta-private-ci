"""Exercise the real writer loop with explicit dependency fixtures, not PEFT.

The separate pinned-library test must still pass before adopting the new backend.
"""

import ast
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace
import time
import unittest
from unittest.mock import patch

import torch
import torch._dynamo  # Eagerly load before patching sys.modules in the fixtures.

from test_source_completion_loss import CausalFixture


def mock_source_schedule(*args, **kwargs):
    ids = [1, 2, 3, 4, 5]
    labels = [-100, -100, -100, 4, 5]
    plan = dict(
        schema="hepta.source-write.schedule.v1",
        entries=[0] * 7,
        scopes=["s"],
        planned_steps=7,
        planned_input_tokens=35,
        planned_supervised_tokens=14,
        maximum_steps=8,
        token_ceiling=39,
    )
    return [(ids, labels)], plan


def writer_loop():
    tree = ast.parse(Path(__file__).with_name("experience_memory.py").read_text())
    method = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "fit_sources"
    )
    ns = dict(
        source_examples=lambda *a, **kw: (
            [dict(query=dict(scope="s"), target="fixture")],
            [],
        ),
        Question=lambda **kw: SimpleNamespace(**kw),
        render=lambda *a: [1, 2, 3],
        STEPS=8,
        TOKEN_CEILING=39,
        PROFILE="fixture-source-knowledge",
        digest=lambda value: hashlib.sha256(
            json.dumps(value, sort_keys=True).encode()
        ).hexdigest(),
        math=math,
        time=time,
        json=json,
    )
    exec(
        compile(ast.Module(body=[method], type_ignores=[]), "real-fit-sources", "exec"),
        ns,
    )
    return ns["fit_sources"]


def adapter_state(model):
    return {
        n: p.detach()
        for n, p in model.named_parameters()
        if n.startswith(("down.", "up."))
    }


def frozen_state(model):
    return hashlib.sha256(
        b"".join(
            p.detach().numpy().tobytes()
            for n, p in model.named_parameters()
            if n.startswith(("embedding.", "head."))
        )
    ).hexdigest()


class SourceWriterLoopTests(unittest.TestCase):
    def test_same_schedule_full_token_budget_roots_and_frozen_state(self):
        results = []
        for backend in ("full", "supervised_positions"):
            model = CausalFixture()
            writer = SimpleNamespace(
                model=model,
                tokenizer=None,
                quarantined=False,
                roots=set(),
                scope="s",
                base_digest=frozen_state(model),
                trainable_parameters=sum(
                    p.numel() for p in model.parameters() if p.requires_grad
                ),
            )
            with patch.dict(
                "sys.modules",
                {
                    "peft": SimpleNamespace(get_peft_model_state_dict=adapter_state),
                    "source_write_schedule": SimpleNamespace(
                        prepare=mock_source_schedule
                    ),
                    "pretrained": SimpleNamespace(frozen_digest=frozen_state),
                },
            ):
                receipt = writer_loop()(
                    writer,
                    [SimpleNamespace(scope="s")],
                    revision=2,
                    allowed_roots={"r"},
                    revoked=set(),
                    loss_backend=backend,
                )
            self.assertEqual(receipt["steps"], 7)
            self.assertEqual(receipt["input_tokens"], 35)
            self.assertEqual(receipt["supervised_tokens"], 14)
            self.assertEqual(model.calls, 7)
            self.assertEqual(writer.roots, {"r"})
            self.assertEqual(frozen_state(model), writer.base_digest)
            self.assertFalse(writer.quarantined)
            self.assertTrue(
                all(p.grad is None and not p.requires_grad for p in model.parameters())
            )
            results.append(
                (receipt, {n: p.clone() for n, p in adapter_state(model).items()})
            )
        self.assertEqual(
            results[0][0]["training_digest"], results[1][0]["training_digest"]
        )
        self.assertEqual(results[0][0]["actual_projection_positions"], 35)
        self.assertEqual(results[1][0]["actual_projection_positions"], 14)
        for name in results[0][1]:
            torch.testing.assert_close(
                results[0][1][name], results[1][1][name], rtol=0, atol=2e-6
            )

    def test_failed_optimized_forward_quarantines_and_clears_flags(self):
        model = CausalFixture()
        model.config.model_type = "unsupported"
        writer = SimpleNamespace(
            model=model,
            tokenizer=None,
            quarantined=False,
            roots=set(),
            scope="s",
            base_digest=frozen_state(model),
            trainable_parameters=1,
        )
        with patch.dict(
            "sys.modules",
            {
                "peft": SimpleNamespace(get_peft_model_state_dict=adapter_state),
                "source_write_schedule": SimpleNamespace(prepare=mock_source_schedule),
                "pretrained": SimpleNamespace(frozen_digest=frozen_state),
            },
        ):
            with self.assertRaises(ValueError):
                writer_loop()(
                    writer,
                    [SimpleNamespace(scope="s")],
                    revision=2,
                    allowed_roots={"r"},
                    revoked=set(),
                    loss_backend="supervised_positions",
                )
        self.assertEqual(model.calls, 0)
        self.assertTrue(writer.quarantined)
        self.assertIsNone(writer.scope)
        self.assertEqual(writer.roots, set())
        self.assertTrue(
            all(p.grad is None and not p.requires_grad for p in model.parameters())
        )


if __name__ == "__main__":
    unittest.main()
