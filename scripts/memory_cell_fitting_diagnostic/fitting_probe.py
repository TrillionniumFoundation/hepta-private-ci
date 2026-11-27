"""Frozen-state teacher-forced and prompt-prefill observations, never generate()."""

import hashlib
import time

from fitting_common import digest, require


def observe(cell, examples, ledger, stage, teacher_first=None):
    import torch
    from experience_inference import frozen_adapter_mode
    from parametric_model import adapter_digest

    prefill = stage == "reload_prefill"
    state = adapter_digest(cell.reader.model)
    ledger.begin(stage)
    rows, first_vectors = [], []
    for index, example in enumerate(examples):
        require(
            cell.prompt_ids(example["question"]) == example["prompt_ids"],
            "loaded reader prompt differs",
        )
        ids = example["prompt_ids"] if prefill else example["input_ids"]
        x = torch.tensor([ids], dtype=torch.long)
        arguments = dict(
            input_ids=x,
            attention_mask=torch.ones_like(x),
            use_cache=prefill,
            return_dict=True,
        )
        if prefill:
            arguments["logits_to_keep"] = 1
        else:
            arguments["labels"] = torch.tensor([example["labels"]], dtype=torch.long)
        started = time.perf_counter()
        with frozen_adapter_mode(cell.reader.model, enabled=True):
            output = cell.reader.model(**arguments)
            seconds = time.perf_counter() - started
            require(
                torch.isfinite(output.logits).all().item(),
                "nonfinite diagnostic logits",
            )
            start = len(example["prompt_ids"]) - 1
            logits = (
                (
                    output.logits[0]
                    if prefill
                    else output.logits[0, start : start + len(example["target_ids"])]
                )
                .float()
                .contiguous()
            )
            require(
                logits.shape
                == (
                    1 if prefill else len(example["target_ids"]),
                    cell.reader.model.config.vocab_size,
                ),
                "diagnostic projection shape changed",
            )
            first = logits[0]
            values = first.log_softmax(dim=-1)
            argmax = int(first.argmax())
            top = first.topk(2).values
            row = dict(
                example_index=index,
                question=example["question"],
                target_ids=example["target_ids"],
                prompt_sha256=digest(example["prompt_ids"]),
                adapter_state_sha256=state,
                input_tokens=len(ids),
                projected_positions=int(output.logits.shape[1]),
                supervised_logits_sha256=hashlib.sha256(
                    logits.cpu().numpy().tobytes()
                ).hexdigest(),
                first=dict(
                    argmax_id=argmax,
                    gold_id=example["target_ids"][0],
                    gold_log_probability=float(values[example["target_ids"][0]]),
                    gold_logit=float(first[example["target_ids"][0]]),
                    argmax_logit=float(first[argmax]),
                    top_two_logit_margin=float(top[0] - top[1]),
                ),
                call_seconds_with_frozen_context=seconds,
                teacher_targets_in_input=not prefill,
                full_answer_quality_measured=False,
                autoregressive_generation_called=False,
            )
            if prefill:
                require(
                    teacher_first is not None and len(teacher_first) == 40,
                    "paired teacher logits required",
                )
                row["teacher_prefill_max_abs_difference"] = float(
                    (first - teacher_first[index]).abs().max()
                )
            else:
                require(
                    output.loss is not None and torch.isfinite(output.loss).item(),
                    "finite teacher loss required",
                )
                row["completion_ce"] = float(output.loss)
                row["teacher_argmax_ids"] = logits.argmax(dim=-1).tolist()
                row["target_log_probabilities"] = (
                    logits.log_softmax(dim=-1)
                    .gather(1, torch.tensor(example["target_ids"]).unsqueeze(1))
                    .squeeze(1)
                    .tolist()
                )
            first_vectors.append(first.clone())
        rows.append(row)
    require(
        adapter_digest(cell.reader.model) == state, "diagnostic changed adapter state"
    )
    return rows, first_vectors
