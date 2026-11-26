"""Matched frozen-generator intervention after evidence selection.

This path generates NEW free-text answers. It never attaches citations to old
answers, hard-codes a selector's abstention as model output, or changes the
prompt/decoder according to the experimental arm. No labels enter this module.
"""

from dataclasses import asdict
import time

import torch

from native import digest

SYSTEM = (
    "Answer the question using only the supplied evidence. Give a short direct "
    "answer and cite the evidence label [E1]. Do not just repeat an unrelated "
    "passage. If the evidence does not support an answer, reply exactly: "
    "I do not have enough evidence."
)
ABSTAIN = "I do not have enough evidence."
GENERATION = dict(max_new_tokens=96, do_sample=False, num_beams=1, use_cache=True)
ARMS = (
    "frozen_forced",
    "trained_forced",
    "frozen_null",
    "trained_null",
    "frozen_calibrated",
    "trained_calibrated",
)


def selected_window(query, pool, feature, choice, revoked):
    pool.revalidate(query, revoked)
    if (
        feature.question_id != query.identity
        or feature.pool_digest != pool.seal()
        or feature.candidate_ids != tuple(w.identity() for w in pool.windows)
        or feature.roots.intersection(revoked)
    ):
        raise ValueError("selector/generator input binding")
    if choice is None:
        return ()
    if type(choice) is not int or not 0 <= choice < len(pool.windows):
        raise ValueError("selected index outside exact candidate pool")
    w = pool.windows[choice]
    return (
        dict(
            label="E1",
            id=w.identity(),
            original_id=w.source_id,
            root=w.root,
            scope=w.scope,
            excerpt=w.text,
            source_start=w.start,
            source_end=w.end,
            observed_at=w.observed_at,
            inspected_sha256=w.inspected_sha256,
        ),
    )


def selection_logits(head, feature, *, trained, revoked):
    if head.roots.intersection(revoked) or feature.roots.intersection(revoked):
        raise ValueError("withdrawn selection inputs")
    # head() still validates the encoder, shape, finite values and quarantine.
    with torch.no_grad():
        values = head(feature).tolist()
    if not trained:
        values = feature.frozen_scores.tolist() + [0.0]
    return values


def choose(values, ids, *, allow_null, offset=0.0):
    import math

    if len(values) != len(ids) + 1 or any(
        not math.isfinite(v) for v in (*values, offset)
    ):
        raise ValueError("invalid selection logits")
    if not ids:
        return None
    best = min(range(len(ids)), key=lambda i: (-values[i], ids[i]))
    return None if allow_null and values[-1] + offset >= values[best] else best


class FrozenAnswerGenerator:
    def __init__(self, directory, *, expected_inventory):
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from pretrained import file_inventory, frozen_digest

        self.inventory = file_inventory(directory)
        if digest(self.inventory) != expected_inventory:
            raise ValueError("frozen answer model inventory pin")
        self.tokenizer = AutoTokenizer.from_pretrained(
            directory, local_files_only=True, trust_remote_code=False
        )
        self.model = AutoModelForCausalLM.from_pretrained(
            directory,
            local_files_only=True,
            trust_remote_code=False,
            use_safetensors=True,
            torch_dtype=torch.float32,
        ).eval()
        self.model.requires_grad_(False)
        self.parameter_digest = frozen_digest(self.model)
        self.identity = digest((self.inventory, self.parameter_digest))
        self.profile = digest((SYSTEM, GENERATION, self.tokenizer.chat_template))
        self.quarantined = False

    @torch.no_grad()
    def answer(self, query, sources, *, revoked):
        import json

        if self.quarantined or len(sources) > 1:
            raise ValueError("unavailable matched generator")
        if any(s["root"] in revoked or s["scope"] != query.scope for s in sources):
            raise ValueError("withdrawn or cross-scope generation source")
        body = dict(
            question=query.content,
            question_time=query.observed_at,
            evidence=[
                dict(label=s["label"], observed_at=s["observed_at"], text=s["excerpt"])
                for s in sources
            ],
        )
        messages = [
            dict(role="system", content=SYSTEM),
            dict(role="user", content=json.dumps(body, ensure_ascii=False)),
        ]
        ids = self.tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True
        )
        if not 1 <= len(ids) <= 1024:
            raise ValueError("generator input budget; no truncation")
        start = time.perf_counter()
        try:
            x = torch.tensor([ids], dtype=torch.long)
            output = self.model.generate(
                input_ids=x,
                attention_mask=torch.ones_like(x),
                **GENERATION,
                eos_token_id=self.tokenizer.eos_token_id,
                pad_token_id=self.tokenizer.eos_token_id,
            )
            emitted = output[0, len(ids) :].tolist()
            raw = self.tokenizer.decode(
                emitted, skip_special_tokens=True, clean_up_tokenization_spaces=False
            )
            if not raw.strip():
                raise ValueError("empty generated answer")
            return raw, dict(
                generator_identity=self.identity,
                generator_profile=self.profile,
                input_ids_digest=digest(ids),
                generated_ids_digest=digest(emitted),
                question_digest=digest(asdict(query)),
                delivered_evidence=list(sources),
                input_tokens=len(ids),
                generated_tokens=len(emitted),
                generation_seconds=time.perf_counter() - start,
                reached_token_ceiling=len(emitted) == GENERATION["max_new_tokens"],
                generator_parameter_updates=0,
                answer_postprocessed=False,
                selector_abstention_was_still_generated=not sources,
                semantic_citation_precision=None,
                production_accepted=False,
            )
        except Exception:
            self.quarantined = True
            raise

    def verify_frozen(self):
        from pretrained import frozen_digest

        if frozen_digest(self.model) != self.parameter_digest or any(
            p.requires_grad for p in self.model.parameters()
        ):
            self.quarantined = True
            raise ValueError("matched answer generator changed")


def paired_generate(query, family, pool, feature, head, generator, offsets, *, revoked):
    """All six selections use one exact pool, head state and generator object."""
    frozen = selection_logits(head, feature, trained=False, revoked=revoked)
    trained = selection_logits(head, feature, trained=True, revoked=revoked)
    records = []
    for arm in ARMS:
        learned = arm.startswith("trained")
        logits = trained if learned else frozen
        offset = (
            offsets["trained" if learned else "frozen"]
            if arm.endswith("calibrated")
            else 0.0
        )
        selected = choose(
            logits,
            feature.candidate_ids,
            allow_null=not arm.endswith("forced"),
            offset=offset,
        )
        item = dict(
            arm=arm,
            question_id=query.identity,
            family=family,
            pool_digest=pool.seal(),
            feature_digest=feature.seal(),
            candidate_ids=feature.candidate_ids,
            selected=selected,
            selector_logits=logits,
            null_offset=offset,
        )
        try:
            sources = selected_window(query, pool, feature, selected, revoked)
            answer, receipt = generator.answer(query, sources, revoked=revoked)
            item.update(status="succeeded", answer=answer, receipt=receipt)
        except Exception as e:
            item.update(
                status="failed", error_type=type(e).__name__, error=str(e)[:1024]
            )
        records.append(item)
    return records
