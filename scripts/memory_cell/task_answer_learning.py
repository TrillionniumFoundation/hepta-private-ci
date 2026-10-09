"""Supervise actual answers/citations on admitted external TRAIN questions only.

This is an opt-in experimental reader. Its baseline disables exactly the learned
adapter on the same base, tokenizer, template and decoder. No citation is added
or repaired after inference. Empty-evidence decisions still invoke the model.
"""

from contextlib import nullcontext
from dataclasses import dataclass
import json
import time

import torch
from peft import get_peft_model_state_dict

from grounded_protocol import completion_ids
from native import digest
from pretrained import LoRAReader, frozen_digest
from selector_answering import ABSTAIN, GENERATION, SYSTEM


@dataclass(frozen=True)
class AnswerExample:
    question: object
    family: str
    root: str
    sources: tuple[dict, ...]
    completion: str
    annotation_digest: str


def wire_source(window):
    return dict(
        label="E1",
        id=window.identity(),
        original_id=window.source_id,
        root=window.root,
        scope=window.scope,
        excerpt=window.text,
        source_start=window.start,
        source_end=window.end,
        observed_at=window.observed_at,
        inspected_sha256=window.inspected_sha256,
    )


def prompt_ids(tokenizer, question, sources, *, revoked):
    if len(sources) > 1 or not question.content.strip():
        raise ValueError("answer evidence/question bound")
    for source in sources:
        if (
            source["scope"] != question.scope
            or source["root"] in revoked
            or source["label"] != "E1"
            or not source["excerpt"]
            or len(source["excerpt"].encode()) > 4096
        ):
            raise ValueError("answer source scope/label/value")
    body = dict(
        question=question.content,
        question_time=question.observed_at,
        evidence=[
            dict(label=s["label"], observed_at=s["observed_at"], text=s["excerpt"])
            for s in sources
        ],
    )
    ids = tokenizer.apply_chat_template(
        [dict(role="system", content=SYSTEM),
         dict(role="user", content=json.dumps(body, ensure_ascii=False))],
        tokenize=True,
        add_generation_prompt=True,
    )
    if not 1 <= len(ids) <= 1024:
        raise ValueError("answer prompt exceeds budget; no truncation")
    return ids


def answer_examples(queries, corpus, pools, cut, *, revoked):
    examples, dispositions = [], []
    for number, q in enumerate(queries):
        pool = pools[q.identity]
        pool.revalidate(q, revoked)
        if (
            q.identity not in cut.question_ids
            or q.family not in cut.families
            or any(w.root not in cut.allowed_roots or w.root in cut.forbidden_roots for w in pool.windows)
        ):
            raise ValueError("outside admitted answer training cut")
        target, doc = corpus.targets[q.identity], corpus.documents[q.scope]
        if target.source_id != doc.identity or target.source_digest != digest(doc.content):
            raise ValueError("answer supervision source drift")
        positive = target.indices(q, pool)
        if target.unanswerable:
            sources = (wire_source(pool.windows[0]),) if pool.windows else ()
            completion = ABSTAIN
        elif positive:
            window = pool.windows[min(positive, key=lambda i: pool.windows[i].identity())]
            values = [text for start, end, text in target.spans if window.start <= start < end <= window.end]
            # Training labels choose targets, never evaluation-window boundaries.
            completion = values[0] + " [E1]"
            sources = (wire_source(window),)
        else:
            dispositions.append(dict(question_id=q.identity, status="coverage_miss_not_null"))
            continue
        examples.append(AnswerExample(q, q.family, doc.root, sources, completion, target.annotation_digest))
        dispositions.append(dict(question_id=q.identity, status="external_answer_target", sources=len(sources)))
        if number % 4 == 0 and sources:
            # With zero delivered evidence, this *protocol* target is abstention;
            # it does not assert that the real-world question has no answer.
            examples.append(AnswerExample(q, q.family, doc.root, (), ABSTAIN, target.annotation_digest))
    return tuple(examples), dispositions


class TaskAnswerReader(LoRAReader):
    def fit_answers(self, examples, cut, *, revoked, steps=192, token_ceiling=65536):
        if self.quarantined or not self.scope or not examples or len(examples) > 512:
            raise ValueError("unavailable answer trainer")
        if self.roots.intersection(revoked | cut.forbidden_roots):
            raise ValueError("withdrawn answer ancestors")
        prepared, groups = [], {}
        for ex in examples:
            if (
                ex.question.identity not in cut.question_ids
                or ex.family not in cut.families
                or ex.root not in cut.allowed_roots
                or ex.root in cut.forbidden_roots | revoked
                or not ex.annotation_digest
            ):
                raise ValueError("non-admitted answer example")
            prompt = prompt_ids(self.tokenizer, ex.question, ex.sources, revoked=revoked)
            target = self.tokenizer.encode(ex.completion, add_special_tokens=False)
            if len(target) + 1 > GENERATION["max_new_tokens"]:
                raise ValueError("supervised answer exceeds generation budget")
            ids, labels = completion_ids(self.tokenizer, prompt, ex.completion, maximum=1120)
            prepared.append((ex, ids, labels))
            groups.setdefault(ex.family, {}).setdefault(ex.question.identity, []).append(len(prepared) - 1)
        if not 1 <= steps <= 512 or not 1120 <= token_ceiling <= 262144:
            raise ValueError("answer training compute bounds")
        before = {k: v.clone() for k, v in get_peft_model_state_dict(self.model).items()}
        params = [p for p in self.model.parameters() if p.requires_grad]
        optimizer = torch.optim.AdamW(params, lr=0.0002)
        families, tokens, supervised, losses = sorted(groups), 0, 0, []
        started = time.perf_counter()
        self.model.train()
        try:
            for step in range(steps):
                questions = groups[families[step % len(families)]]
                keys, visit = sorted(questions), step // len(families)
                members = questions[keys[visit % len(keys)]]
                ex, ids, labels = prepared[members[(visit // len(keys)) % len(members)]]
                if tokens + len(ids) > token_ceiling:
                    break
                x = torch.tensor([ids], dtype=torch.long)
                optimizer.zero_grad(set_to_none=True)
                loss = self.model(input_ids=x, attention_mask=torch.ones_like(x),
                    labels=torch.tensor([labels], dtype=torch.long), use_cache=False).loss
                if not torch.isfinite(loss):
                    raise ValueError("nonfinite answer loss")
                loss.backward()
                torch.nn.utils.clip_grad_norm_(params, 1.0, error_if_nonfinite=True)
                optimizer.step()
                if any(not torch.isfinite(p).all() for p in params):
                    raise ValueError("nonfinite answer adapter")
                losses.append(float(loss.detach()))
                tokens += len(ids)
                supervised += sum(i != -100 for i in labels)
                self.roots.add(ex.root)
            delta = sum(float((v - before[k]).square().sum())
                for k, v in get_peft_model_state_dict(self.model).items())
            if not losses or not delta > 0 or frozen_digest(self.model) != self.base_digest:
                raise ValueError("no answer update or frozen base changed")
            return dict(
                objective="external-answer-citation-plus-empty-context-v1",
                steps=len(losses), maximum_steps=steps, tokens=tokens,
                supervised_tokens=supervised, token_ceiling=token_ceiling,
                losses=losses, adapter_delta_squared_norm=delta,
                trainable_parameters=self.trainable_parameters,
                roots=sorted(self.roots), families=families,
                training_digest=digest([(e.question.identity, e.annotation_digest, x, y) for e, x, y in prepared]),
                train_seconds=time.perf_counter() - started, base_unchanged=True,
                evaluation_targets_used=False, production_accepted=False,
            )
        except Exception:
            self.quarantined, self.scope = True, None
            raise
        finally:
            self.model.eval()

    @torch.no_grad()
    def answer_task(self, query, sources, *, revoked, enabled):
        if self.quarantined or not self.scope or self.roots.intersection(revoked):
            raise ValueError("unavailable/withdrawn task reader")
        ids = prompt_ids(self.tokenizer, query, sources, revoked=revoked)
        x = torch.tensor([ids], dtype=torch.long)
        started = time.perf_counter()
        self.model.eval()
        try:
            with nullcontext() if enabled else self.model.disable_adapter():
                output = self.model.generate(
                    input_ids=x, attention_mask=torch.ones_like(x), **GENERATION,
                    eos_token_id=self.tokenizer.eos_token_id,
                    pad_token_id=self.tokenizer.eos_token_id,
                )
            emitted = output[0, len(ids):].tolist()
            answer = self.tokenizer.decode(emitted, skip_special_tokens=True,
                clean_up_tokenization_spaces=False)
            if not answer.strip():
                raise ValueError("empty task answer")
            return answer, dict(
                base_identity=self.identity, adapter_enabled=enabled,
                prompt_profile=digest((SYSTEM, GENERATION, self.tokenizer.chat_template)),
                input_ids_digest=digest(ids), generated_ids_digest=digest(emitted),
                input_tokens=len(ids), generated_tokens=len(emitted),
                delivered_evidence=list(sources), seconds=time.perf_counter() - started,
                answer_postprocessed=False, semantic_citation_precision=None,
                production_accepted=False,
            )
        except Exception:
            self.quarantined = True
            raise
