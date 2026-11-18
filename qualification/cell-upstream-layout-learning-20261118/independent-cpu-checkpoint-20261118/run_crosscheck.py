"""Independent CPU-only operator crosscheck; not a model or business qualification.

Compares the byte-pinned checkpointed eager attention with the installed
Transformers Qwen2 eager function, without touching a GPU or research weights.
"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import torch
from transformers.models.qwen2.modeling_qwen2 import eager_attention_forward

SOURCE = (
    Path(__file__).resolve().parent.parent
    / "eager-inner-checkpoint-short-A"
    / "checkpoint_softmax.py"
)
EXPECTED_SOURCE_SHA256 = (
    "81ad33310f7bb427d01d25fd4ff696d281e6c53f3bba24cbc80667df63316aaa"
)


class GQAModule(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.num_key_value_groups = 2


def main():
    observed = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    if observed != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("the frozen operator source changed")
    spec = importlib.util.spec_from_file_location(
        "independent_checkpoint_softmax", SOURCE
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    torch.set_num_threads(2)
    owner = GQAModule()
    cases = []
    for dtype in (torch.float32, torch.bfloat16):
        for n in (7, 129, 257):
            torch.manual_seed(431 + n)
            query = torch.randn((1, 4, n, 16), dtype=dtype)
            key = torch.randn((1, 2, n, 16), dtype=dtype)
            value = torch.randn((1, 2, n, 16), dtype=dtype)
            mask = torch.triu(
                torch.ones((1, 1, n, n), dtype=dtype) * (-10000),
                diagonal=1,
            )
            results = []
            for fn in (
                eager_attention_forward,
                module.eager_checkpointed_softmax,
            ):
                q = query.detach().clone().requires_grad_(True)
                k = key.detach().clone().requires_grad_(True)
                v = value.detach().clone().requires_grad_(True)
                output, weights = fn(
                    owner, q, k, v, mask, 16 ** (-0.5), dropout=0.0
                )
                output.float().square().mean().backward()
                results.append(
                    (
                        output.detach(),
                        weights.detach(),
                        q.grad.detach(),
                        k.grad.detach(),
                        v.grad.detach(),
                    )
                )
            differences = [
                float((a.float() - b.float()).abs().max())
                for a, b in zip(*results)
            ]
            cases.append(
                {
                    "dtype": str(dtype),
                    "length": n,
                    "max_abs_output_weights_qkv_gradient": differences,
                    "all_identical": max(differences) == 0,
                }
            )
    report = {
        "schema": "independent-cpu-eager-checkpoint-synthetic-readonly.v1",
        "module_sha256": EXPECTED_SOURCE_SHA256,
        "torch": torch.__version__,
        "cases": cases,
        "model_calls": 0,
        "business_qualification": False,
    }
    print(json.dumps(report, sort_keys=True))
    if not all(case["all_identical"] for case in cases):
        raise SystemExit("CPU_OPERATOR_DIFFERENCE")


if __name__ == "__main__":
    main()
