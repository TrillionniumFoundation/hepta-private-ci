"""Reference-anchored evidence preference, never a production approval issuer.

The supported question is paired with the SAME question without evidence. Both
answer and refusal likelihoods are measured in both contexts. A globally changed
refusal prior cannot improve both relative preference terms. Unknown windows and
held-out references are not converted into preference labels.
"""

from dataclasses import replace
import math
import time

import torch

from balanced_answer_learning import admitted_groups, update_examples
from native import digest
from selector_answering import ABSTAIN, GENERATION

PROFILE = "reference-anchored-evidence-preference-v1"
MAX_UPDATES = 64
TOKEN_CEILING = 131072
BETA = 2.0
PREFERENCE_WEIGHT = 0.5
CONTEXT_WEIGHT = 0.25
CONTEXT_MARGIN = 1.0
SFT_WEIGHTS = (0.8, 0.1, 0.1)


def preference_loss(losses, reference):
    """Mean completion NLLs: supported A/R, empty A/R, annotated-null R.

    This is a declared length-normalized likelihood experiment, not an exact
    sequence-probability DPO implementation or a semantic correctness oracle.
    The detached reference is the same pretrained reader with adapters disabled.
    """
    if (
        losses.shape != (5,)
        or reference.shape != (4,)
        or reference.requires_grad
        or not torch.isfinite(losses).all()
        or not torch.isfinite(reference).all()
    ):
        raise ValueError("finite detached paired reference required")
    support = losses[1] - losses[0]
    empty = losses[3] - losses[2]
    old_support = reference[1] - reference[0]
    old_empty = reference[3] - reference[2]
    relative = torch.nn.functional.softplus(-BETA * (support - old_support))
    relative = relative + torch.nn.functional.softplus(BETA * (empty - old_empty))
    gap = torch.nn.functional.softplus(CONTEXT_MARGIN - support + empty)
    return PREFERENCE_WEIGHT * relative + CONTEXT_WEIGHT * gap


def fit_preference(
    reader,
    examples,
    cut,
    *,
    revoked,
    updates=MAX_UPDATES,
    token_ceiling=TOKEN_CEILING,
):
    from grounded_protocol import completion_ids
    from peft import get_peft_model_state_dict
    from pretrained import frozen_digest
    from task_answer_learning import prompt_ids

    if (
        reader.quarantined
        or not reader.scope
        or reader.roots.intersection(revoked | cut.forbidden_roots)
        or type(updates) is not int
        or not 1 <= updates <= MAX_UPDATES
        or type(token_ceiling) is not int
        or not 1120 <= token_ceiling <= TOKEN_CEILING
    ):
        raise ValueError("preference reader state or budget")
    groups = admitted_groups(examples, cut, revoked=revoked)
    schedule = []
    for step in range(updates):
        support, null, empty = update_examples(groups, step)
        batch = []
        variants = (
            support,
            replace(support, completion=ABSTAIN),
            replace(support, sources=()),
            empty,
            null,
        )
        for ex in variants:
            prompt = prompt_ids(
                reader.tokenizer, ex.question, ex.sources, revoked=revoked
            )
            target = reader.tokenizer.encode(ex.completion, add_special_tokens=False)
            if len(target) + 1 > GENERATION["max_new_tokens"]:
                raise ValueError("preference completion exceeds generation ceiling")
            ids, labels = completion_ids(
                reader.tokenizer, prompt, ex.completion, maximum=1120
            )
            batch.append((ex, ids, labels, digest((ids, labels))))
        schedule.append(tuple(batch))
    # Determine the COMPLETE executable prefix before any model forward/update.
    # Reference cache work is counted once; all five actor passes count every time.
    executable, cached, planned_tokens = [], set(), 0
    for batch in schedule:
        fresh = {}
        for item in batch[:4]:
            if item[3] not in cached:
                fresh[item[3]] = item
        cost = sum(len(i[1]) for i in batch) + sum(len(i[1]) for i in fresh.values())
        if planned_tokens + cost > token_ceiling:
            break
        executable.append((batch, tuple(fresh.values()), cost))
        cached.update(fresh)
        planned_tokens += cost
    if not executable:
        raise ValueError("budget cannot execute one complete preference update")
    if frozen_digest(reader.model) != reader.base_digest:
        raise ValueError("reference base changed before preference training")
    before = {k: v.clone() for k, v in get_peft_model_state_dict(reader.model).items()}
    params = [p for p in reader.model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(params, lr=0.0002)
    reference_cache, records = {}, []
    actor_tokens, reference_tokens, supervised = 0, 0, 0
    started = time.perf_counter()

    def nll(item):
        _, ids, labels, _ = item
        x = torch.tensor([ids], dtype=torch.long)
        result = reader.model(
            input_ids=x,
            attention_mask=torch.ones_like(x),
            labels=torch.tensor([labels], dtype=torch.long),
            use_cache=False,
        ).loss
        if result.ndim != 0 or not torch.isfinite(result):
            raise ValueError("nonfinite preference forward")
        return result

    try:
        for batch, fresh, cost in executable:
            reader.model.eval()
            with torch.no_grad(), reader.model.disable_adapter():
                for item in fresh:
                    reference_cache[item[3]] = float(nll(item))
                    reference_tokens += len(item[1])
            reference = torch.tensor([reference_cache[i[3]] for i in batch[:4]])
            reader.model.train()
            optimizer.zero_grad(set_to_none=True)
            losses = torch.stack([nll(item) for item in batch])
            preference = preference_loss(losses, reference)
            objective = preference + sum(
                weight * losses[i] for weight, i in zip(SFT_WEIGHTS, (0, 3, 4))
            )
            if not torch.isfinite(objective):
                raise ValueError("nonfinite preference objective")
            objective.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0, error_if_nonfinite=True)
            optimizer.step()
            if any(not torch.isfinite(p).all() for p in params):
                raise ValueError("nonfinite preference adapter")
            actor_tokens += sum(len(i[1]) for i in batch)
            supervised += sum(v != -100 for _, _, ys, _ in batch for v in ys)
            reader.roots.update(i[0].root for i in batch)
            records.append(
                dict(
                    question_id=batch[0][0].question.identity,
                    empty_question_id=batch[2][0].question.identity,
                    unanswerable_question_id=batch[4][0].question.identity,
                    losses=losses.detach().tolist(),
                    reference=reference.tolist(),
                    objective=float(objective.detach()),
                    input_tokens=cost,
                    input_bindings=[i[3] for i in batch],
                )
            )
        delta = sum(
            float((v - before[k]).square().sum())
            for k, v in get_peft_model_state_dict(reader.model).items()
        )
        if not math.isfinite(delta) or delta <= 0:
            raise ValueError("preference training made no finite update")
        if frozen_digest(reader.model) != reader.base_digest:
            raise ValueError("preference training modified the reference base")
        if actor_tokens + reference_tokens != planned_tokens:
            raise ValueError("incomplete or unaccounted preference work")
        return dict(
            objective=PROFILE,
            steps=len(records),
            maximum_steps=updates,
            tokens=actor_tokens + reference_tokens,
            actor_tokens=actor_tokens,
            reference_tokens=reference_tokens,
            reference_forwards=len(reference_cache),
            actor_forwards=5 * len(records),
            supervised_tokens=supervised,
            token_ceiling=token_ceiling,
            sft_weights=SFT_WEIGHTS,
            beta=BETA,
            preference_weight=PREFERENCE_WEIGHT,
            context_weight=CONTEXT_WEIGHT,
            context_margin=CONTEXT_MARGIN,
            paired_steps=records,
            adapter_delta_squared_norm=delta,
            trainable_parameters=reader.trainable_parameters,
            roots=sorted(reader.roots),
            admission_digest=cut.admission_digest,
            training_digest=digest(
                [
                    [
                        (ex.question.identity, ex.annotation_digest, ids, ys)
                        for ex, ids, ys, _ in batch
                    ]
                    for batch, _, _ in executable
                ]
            ),
            train_seconds=time.perf_counter() - started,
            base_unchanged=True,
            evaluation_targets_used=False,
            production_accepted=False,
        )
    except Exception:
        reader.quarantined, reader.scope = True, None
        raise
    finally:
        reader.model.eval()
