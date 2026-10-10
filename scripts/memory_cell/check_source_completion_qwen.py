"""Isolated actual Qwen2/PEFT conformance; random weights are NOT task evidence.

Run in a fresh process, outside tests that install dependency fixtures. Missing
pinned dependencies fail. Tolerances are fixed before execution, never inferred
from observed results. No model is downloaded or production candidate emitted.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import peft
import torch
import transformers
from peft import LoraConfig, get_peft_model
from transformers import Qwen2Config, Qwen2ForCausalLM

from source_completion_loss import completion_loss


def run(output):
    if transformers.__version__ != "4.57.1" or peft.__version__ != "0.17.1":
        raise ValueError("exact pinned Transformers and PEFT required")
    output.mkdir()
    plan = dict(
        schema="hepta.completion-qwen-conformance.v1",
        pretrained_weights=False,
        seed=2718,
        sequence_lengths=[9, 31, 63],
        supervised_lengths=[1, 6, 9],
        attention_backends=["eager", "sdpa"],
        dtypes=["float32", "bfloat16"],
        fp32_tolerance=2e-6,
        bf16_tolerance=2e-3,
        optimizer="AdamW lr=0.0002; clip_norm=1",
        production_accepted=False,
    )
    (output / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    records = []
    for dtype, tolerance in ((torch.float32, 2e-6), (torch.bfloat16, 2e-3)):
        for attention in plan["attention_backends"]:
            with torch.random.fork_rng():
                torch.manual_seed(plan["seed"])
                config = Qwen2Config(
                    vocab_size=97,
                    hidden_size=32,
                    intermediate_size=64,
                    num_hidden_layers=2,
                    num_attention_heads=4,
                    num_key_value_heads=2,
                    max_position_embeddings=128,
                    attention_dropout=0.0,
                )
                config._attn_implementation = attention
                full = get_peft_model(
                    Qwen2ForCausalLM(config).to(dtype=dtype),
                    LoraConfig(
                        r=4,
                        lora_alpha=8,
                        lora_dropout=0.0,
                        target_modules=["q_proj", "v_proj"],
                        bias="none",
                        task_type="CAUSAL_LM",
                    ),
                )
                sliced = deepcopy(full)
                models = (full, sliced)
                initial = {n: p.detach().clone() for n, p in full.named_parameters()}
                optimizers = [
                    torch.optim.AdamW(
                        [p for p in model.parameters() if p.requires_grad], lr=0.0002
                    )
                    for model in models
                ]
                captured = {}

                def capture(module, args, value):
                    value.retain_grad()
                    captured[module] = value

                modules = [m.get_base_model().model.layers[0].self_attn.v_proj for m in models]
                hooks = [m.register_forward_hook(capture) for m in modules]
                try:
                    for step, (length, targets) in enumerate(zip(
                        plan["sequence_lengths"], plan["supervised_lengths"], strict=True
                    )):
                        ids = [(i * 7 + step) % 97 for i in range(length)]
                        prefix = length - targets
                        labels = [-100] * prefix + ids[prefix:]
                        losses, receipts, prompt_grads = [], [], []
                        for backend, model, optimizer, module in zip(
                            ("full", "supervised_positions"), models, optimizers, modules, strict=True
                        ):
                            optimizer.zero_grad(set_to_none=True)
                            loss, receipt = completion_loss(model, ids, labels, backend=backend)
                            loss.backward()
                            losses.append(loss.detach())
                            receipts.append(receipt)
                            prompt_grad = float(captured[module].grad[:, :prefix].float().abs().sum())
                            if not prompt_grad > 0:
                                raise ValueError("prompt attention path lost its gradient")
                            prompt_grads.append(prompt_grad)
                        torch.testing.assert_close(losses[0], losses[1], rtol=0, atol=tolerance)
                        grad_max = 0.0
                        for (name, a), (other_name, b) in zip(
                            full.named_parameters(), sliced.named_parameters(), strict=True
                        ):
                            if name != other_name:
                                raise ValueError("parameter identity drift")
                            if a.requires_grad:
                                torch.testing.assert_close(a.grad, b.grad, rtol=tolerance, atol=tolerance)
                                grad_max = max(grad_max, float((a.grad.float() - b.grad.float()).abs().max()))
                            elif a.grad is not None or b.grad is not None:
                                raise ValueError("frozen parameter acquired a gradient")
                        for model, optimizer in zip(models, optimizers, strict=True):
                            torch.nn.utils.clip_grad_norm_(
                                [p for p in model.parameters() if p.requires_grad], 1.0,
                                error_if_nonfinite=True,
                            )
                            optimizer.step()
                        update_max = delta = 0.0
                        for (name, a), (_, b) in zip(
                            full.named_parameters(), sliced.named_parameters(), strict=True
                        ):
                            if a.requires_grad:
                                torch.testing.assert_close(a, b, rtol=0, atol=tolerance)
                                update_max = max(update_max, float((a.detach().float() - b.detach().float()).abs().max()))
                                delta += float((a.detach().float() - initial[name].float()).square().sum())
                            elif not torch.equal(a, initial[name]) or not torch.equal(b, initial[name]):
                                raise ValueError("frozen base changed")
                        if delta <= 0:
                            raise ValueError("optimizer performed no finite parameter update")
                        row = dict(
                            dtype=str(dtype), attention=attention, step=step,
                            loss_max_abs=float((losses[0] - losses[1]).abs()),
                            gradient_max_abs=grad_max, parameter_max_abs=update_max,
                            update_squared_norm=delta, prompt_gradient_l1=prompt_grads,
                            receipts=receipts,
                        )
                        records.append(row)
                        with (output / "raw.jsonl").open("a") as stream:
                            stream.write(json.dumps(row, allow_nan=False) + "\n")
                finally:
                    for hook in hooks:
                        hook.remove()
    result = dict(
        plan=plan, actual_paired_updates=len(records), records=records,
        torch=torch.__version__, transformers=transformers.__version__, peft=peft.__version__,
        helper_sha256=hashlib.sha256(Path(__file__).with_name("source_completion_loss.py").read_bytes()).hexdigest(),
        task_quality_evaluated=False, pretrained_equivalence=False, production_accepted=False,
    )
    (output / "report.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result, allow_nan=False))
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: check_source_completion_qwen.py OUTPUT_DIRECTORY")
    run(Path(sys.argv[1]))
