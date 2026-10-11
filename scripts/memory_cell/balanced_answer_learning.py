"""Counterfactual reader learning; no change to serving or qualification authority.

Each optimizer update includes a supported answer, an independently annotated
unanswerable example, and the *same supported question* with evidence removed.
The macro weights are fixed before execution, not proportional to duplicate rows
or refusal length. A support-vs-refusal completion margin is TRAIN-only.
"""

from dataclasses import replace
import math
import time

import torch

from native import digest
from selector_answering import ABSTAIN, GENERATION

PROFILE = "balanced-counterfactual-answer-v1"
WEIGHTS = (0.6, 0.2, 0.2)
MARGIN = 1.0
CONTRAST_WEIGHT = 0.1
MAX_UPDATES = 64
TOKEN_CEILING = 65536


def admitted_groups(examples, cut, *, revoked):
    """Validate all inputs before scheduling, including unused empty examples."""
    if not 1 <= len(examples) <= 512 or not cut.admission_digest:
        raise ValueError("bounded admitted answer examples required")
    groups = {"supported": {}, "unanswerable": {}}
    seen = set()
    for ex in examples:
        q = ex.question
        if (
            q.identity not in cut.question_ids
            or q.family != ex.family
            or ex.family not in cut.families
            or ex.root not in cut.allowed_roots
            or ex.root in cut.forbidden_roots | revoked
            or not ex.annotation_digest
            or not isinstance(ex.completion, str)
            or not ex.completion.strip()
            or len(ex.sources) > 1
        ):
            raise ValueError("non-admitted or withdrawn balanced example")
        for source in ex.sources:
            start, end = source["source_start"], source["source_end"]
            if (
                source["root"] != ex.root
                or source["scope"] != q.scope
                or source["label"] != "E1"
                or type(start) is not int
                or type(end) is not int
                or not 0 <= start < end
                or end - start != len(source["excerpt"].encode())
                or end - start > 4096
            ):
                raise ValueError("balanced source binding")
        key = (q.identity, bool(ex.sources))
        if key in seen:
            raise ValueError("duplicate training question/context")
        seen.add(key)
        if not ex.sources:
            if ex.completion != ABSTAIN:
                raise ValueError("empty evidence is not an answer target")
            continue  # Rebuilt only as a paired counterfactual below.
        kind = "unanswerable" if ex.completion == ABSTAIN else "supported"
        if kind == "supported" and (
            not ex.completion.endswith(" [E1]")
            or not ex.completion[:-5].strip()
            or ex.completion[:-5] not in ex.sources[0]["excerpt"]
        ):
            raise ValueError("supported target detached from delivered source")
        groups[kind].setdefault(ex.family, []).append(ex)
    if not all(groups.values()):
        raise ValueError("both external support and unanswerability required")
    for families in groups.values():
        for group in families.values():
            group.sort(key=lambda ex: ex.question.identity)
    return groups


def update_examples(groups, step):
    """Family-balanced, order-independent; the empty pair shares its question."""
    selected = []
    for kind in ("supported", "unanswerable"):
        families = sorted(groups[kind])
        group = groups[kind][families[step % len(families)]]
        selected.append(group[(step // len(families)) % len(group)])
    support, null = selected
    return support, null, replace(support, sources=(), completion=ABSTAIN)


def paired_loss(answer_loss, refusal_loss):
    """Length-normalized completion likelihood comparison, not test reward."""
    return WEIGHTS[0] * answer_loss + CONTRAST_WEIGHT * torch.nn.functional.softplus(
        MARGIN + answer_loss - refusal_loss
    )


def fit_balanced(
    reader, examples, cut, *, revoked, updates=MAX_UPDATES, token_ceiling=TOKEN_CEILING
):
    from peft import get_peft_model_state_dict
    from grounded_protocol import completion_ids
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
        raise ValueError("balanced reader state/budget")
    groups = admitted_groups(examples, cut, revoked=revoked)
    schedule = []
    for step in range(updates):
        support, null, empty = update_examples(groups, step)
        prepared = []
        # Fourth completion contrasts answer vs refusal for IDENTICAL support.
        for ex in (support, null, empty, replace(support, completion=ABSTAIN)):
            prompt = prompt_ids(
                reader.tokenizer, ex.question, ex.sources, revoked=revoked
            )
            target = reader.tokenizer.encode(ex.completion, add_special_tokens=False)
            if len(target) + 1 > GENERATION["max_new_tokens"]:
                raise ValueError("balanced completion budget")
            ids, labels = completion_ids(
                reader.tokenizer, prompt, ex.completion, maximum=1120
            )
            prepared.append((ex, ids, labels))
        schedule.append(prepared)
    # Admit the full fixed schedule before any optimizer state or gradient exists.
    before = {k: v.clone() for k, v in get_peft_model_state_dict(reader.model).items()}
    params = [p for p in reader.model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(params, lr=0.0002)
    records, tokens, supervised = [], 0, 0
    started = time.perf_counter()

    def loss_for(prepared):
        _, ids, labels = prepared
        x = torch.tensor([ids], dtype=torch.long)
        value = reader.model(
            input_ids=x,
            attention_mask=torch.ones_like(x),
            labels=torch.tensor([labels]),
            use_cache=False,
        ).loss
        if not torch.isfinite(value):
            raise ValueError("nonfinite counterfactual loss")
        return value

    reader.model.train()
    try:
        for batch in schedule:
            cost = sum(len(ids) for _, ids, _ in batch)
            if tokens + cost > token_ceiling:
                break  # No partial macro step; all four forward passes are charged.
            optimizer.zero_grad(set_to_none=True)
            support_loss, refusal_loss = loss_for(batch[0]), loss_for(batch[3])
            objective = paired_loss(support_loss, refusal_loss)
            objective.backward()
            scalar = float(objective.detach())
            for index in (1, 2):
                value = WEIGHTS[index] * loss_for(batch[index])
                value.backward()
                scalar += float(value.detach())
            torch.nn.utils.clip_grad_norm_(params, 1.0, error_if_nonfinite=True)
            optimizer.step()
            if any(not torch.isfinite(p).all() for p in params):
                raise ValueError("nonfinite balanced adapter")
            tokens += cost
            supervised += sum(v != -100 for _, _, labels in batch for v in labels)
            reader.roots.update(ex.root for ex, _, _ in batch)
            records.append(
                dict(
                    support=batch[0][0].question.identity,
                    unanswerable=batch[1][0].question.identity,
                    empty=batch[2][0].question.identity,
                    objective=scalar,
                    input_tokens=cost,
                    support_nll=float(support_loss.detach()),
                    support_refusal_nll=float(refusal_loss.detach()),
                )
            )
        delta = sum(
            float((v - before[k]).square().sum())
            for k, v in get_peft_model_state_dict(reader.model).items()
        )
        if not records or not math.isfinite(delta) or delta <= 0:
            raise ValueError("balanced training made no finite update")
        if frozen_digest(reader.model) != reader.base_digest:
            raise ValueError("balanced training modified frozen base")
        return dict(
            objective=PROFILE,
            steps=len(records),
            maximum_steps=updates,
            tokens=tokens,
            supervised_tokens=supervised,
            token_ceiling=token_ceiling,
            macro_weights=WEIGHTS,
            contrast_weight=CONTRAST_WEIGHT,
            margin=MARGIN,
            forward_passes=4 * len(records),
            paired_steps=records,
            adapter_delta_squared_norm=delta,
            trainable_parameters=reader.trainable_parameters,
            roots=sorted(reader.roots),
            admission_digest=cut.admission_digest,
            training_digest=digest(
                [
                    [
                        (ex.question.identity, ex.annotation_digest, ids, labels)
                        for ex, ids, labels in batch
                    ]
                    for batch in schedule
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
