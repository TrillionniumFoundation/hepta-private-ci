"""Source-only decoder memory; raw generation never receives source values.

Research receipts bind actual optimizer exposure and verified weight ancestry.
They establish neither compression nor independent task generalization.
"""

import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
from string import Formatter
import time

import torch
from peft import get_peft_model_state_dict
from torch.optim import optimizer as optimizer_module

from experience_inference import frozen_adapter_mode
from grounded_protocol import completion_ids
from native import digest
from pretrained import LoRAReader, frozen_digest
from source_binding_margin import binding_margin_loss
from source_completion_loss import completion_loss

SYSTEM = (
    "Answer using stored memory in the specified scope. Return only the value. "
    "If unknown, say 'unknown'. Do not cite sources."
)
GENERATION = dict(max_new_tokens=16, do_sample=False, num_beams=1, use_cache=True)
FACT_FIELDS = {"scope", "entity", "relation", "value", "source_digest"}


def adapter_digest(model):
    h = hashlib.sha256()
    for name, value in sorted(get_peft_model_state_dict(model).items()):
        tensor = value.detach().cpu().contiguous()
        h.update(digest((name, list(tensor.shape), str(tensor.dtype))).encode())
        h.update(tensor.view(torch.uint8).numpy().tobytes())
    return h.hexdigest()


def reject_global_optimizer_hooks():
    if (
        optimizer_module._global_optimizer_pre_hooks
        or optimizer_module._global_optimizer_post_hooks
    ):
        raise ValueError("global optimizer hooks can mutate another memory cell")


class SourceMemoryCell:
    """A scoped LoRA over a real pretrained autoregressive decoder."""

    def __init__(self, base_dir, rank=8, seed=2718):
        if type(rank) is not int or type(seed) is not int or not 0 <= seed < 2**31:
            raise ValueError("integer registered rank and bounded seed required")
        self.reader = LoRAReader(Path(base_dir), rank=rank, seed=seed)
        self.seed = seed
        self._receipt = None
        self._parent = None
        self._initialization = "frozen_base"
        self._expected_adapter = adapter_digest(self.reader.model)
        self.last_save_receipt = None
        self._freeze()

    def _freeze(self):
        self.reader.model.eval()
        self.reader.model.requires_grad_(False)
        for parameter in self.reader.model.parameters():
            parameter.grad = None

    def _available(self):
        if self.reader.quarantined or not self.reader.scope:
            raise ValueError("unavailable or unscoped memory cell")
        if adapter_digest(self.reader.model) != self._expected_adapter:
            self.reader.quarantined, self.reader.scope = True, None
            raise ValueError("adapter changed outside a verified load or source write")

    def reset(self, scope):
        self.reader.reset(scope)
        self._receipt, self._parent = None, None
        self._initialization = "frozen_base"
        self._expected_adapter = adapter_digest(self.reader.model)
        self._freeze()

    def prompt_ids(self, question):
        self._available()
        if (
            type(question) is not str
            or not question.strip()
            or len(question.encode()) > 4096
        ):
            raise ValueError("bounded nonempty question string required")
        ids = self.reader.tokenizer.apply_chat_template(
            [
                dict(role="system", content=SYSTEM),
                dict(role="user", content=f"Scope: {self.reader.scope}\n{question}"),
            ],
            tokenize=True,
            add_generation_prompt=True,
        )
        if not 1 <= len(ids) <= 192:
            raise ValueError("complete prompt exceeds 192 tokens; no truncation")
        return ids

    def fit_sources(
        self, facts, steps, learning_rate, templates, objective="completion_ce"
    ):
        """Train only source-derived completions, including inherited adapters."""
        started = time.perf_counter()
        try:
            self._available()
            reject_global_optimizer_hooks()
            if (
                type(steps) is not int
                or not 1 <= steps <= 4096
                or type(learning_rate) not in (int, float)
                or not math.isfinite(learning_rate)
                or not 0 < learning_rate <= 0.1
                or objective not in ("completion_ce", "source_margin")
                or type(facts) is not list
                or not 1 <= len(facts) <= 128
                or type(templates) is not list
                or not 1 <= len(templates) <= 8
            ):
                raise ValueError("bounded source training configuration required")
            for template in templates:
                if type(template) is not str or not 1 <= len(template.encode()) <= 1024:
                    raise ValueError("bounded source-only question template required")
                fields = list(Formatter().parse(template))
                if {f for _, f, _, _ in fields if f is not None} != {
                    "entity",
                    "relation",
                } or any(spec or conversion for _, _, spec, conversion in fields):
                    raise ValueError(
                        "templates must use only entity and relation fields"
                    )
            if len(set(templates)) != len(templates):
                raise ValueError("duplicate source templates")
            keys, value_tokens = set(), []
            for fact in facts:
                if (
                    type(fact) is not dict
                    or set(fact) != FACT_FIELDS
                    or any(
                        type(v) is not str or not v.strip() or len(v.encode()) > 1024
                        for v in fact.values()
                    )
                ):
                    raise ValueError("exact bounded fact fields required")
                key = fact["entity"], fact["relation"]
                if (
                    fact["scope"] != self.reader.scope
                    or key in keys
                    or re.fullmatch(r"[0-9a-f]{64}", fact["source_digest"]) is None
                ):
                    raise ValueError("fact scope, identity or source digest mismatch")
                keys.add(key)
                tokens = self.reader.tokenizer.encode(
                    fact["value"], add_special_tokens=False
                )
                if (
                    not 1 <= len(tokens) < GENERATION["max_new_tokens"]
                    or self.reader.tokenizer.eos_token_id in tokens
                ):
                    raise ValueError("value plus EOS must fit the generation budget")
                value_tokens.append(tokens)
            prepared, negatives = [], []
            maximum = min(256, self.reader.model.config.max_position_embeddings)
            for i, fact in enumerate(facts):
                candidates = [
                    j
                    for j, other in enumerate(facts)
                    if other["value"] != fact["value"]
                    and len(value_tokens[j]) == len(value_tokens[i])
                ]
                if objective == "source_margin" and not candidates:
                    raise ValueError(
                        "source margin requires equal-length distinct source values"
                    )
                negative = (
                    min(
                        candidates,
                        key=lambda j: (facts[j]["relation"] != fact["relation"], j),
                    )
                    if candidates
                    else None
                )
                for template in templates:
                    prompt = self.prompt_ids(
                        template.format(
                            entity=fact["entity"], relation=fact["relation"]
                        )
                    )
                    ids, labels = completion_ids(
                        self.reader.tokenizer, prompt, fact["value"], maximum=maximum
                    )
                    prepared.append((i, prompt, ids, labels))
                    negatives.append(negative)
            if frozen_digest(self.reader.model) != self.reader.base_digest:
                raise ValueError("frozen base changed before source write")
            inherited = sorted(self.reader.roots)
            initialization = (
                "in_memory_adapter"
                if self._receipt is not None
                else self._initialization
            )
            previous = digest(self._receipt) if self._receipt is not None else None
            before = {
                k: v.detach().clone()
                for k, v in get_peft_model_state_dict(self.reader.model).items()
            }
            starting_adapter = adapter_digest(self.reader.model)
            self.reader.model.requires_grad_(False)
            for name, parameter in self.reader.model.named_parameters():
                if "lora_" in name:
                    parameter.requires_grad_(True)
            params = [p for p in self.reader.model.parameters() if p.requires_grad]
            if sum(p.numel() for p in params) != self.reader.trainable_parameters:
                raise ValueError("trainable adapter inventory changed")
            optimizer = torch.optim.AdamW(params, lr=learning_rate)
            visits, fact_visits = [0] * len(prepared), [0] * len(facts)
            negative_visits = [0] * len(facts)
            schedule = []
            for epoch in range((steps + len(prepared) - 1) // len(prepared)):
                order = list(range(len(prepared)))
                random.Random(self.seed + epoch).shuffle(order)
                schedule.extend(order[: steps - len(schedule)])
            losses, input_tokens, supervised_tokens, forwards = [], 0, 0, 0
            accessed = set()
            self.reader.model.train()
            for index in schedule:
                i, prompt, ids, labels = prepared[index]
                optimizer.zero_grad(set_to_none=True)
                if objective == "source_margin":
                    negative = negatives[index]
                    loss, charge = binding_margin_loss(
                        self.reader.model,
                        self.reader.tokenizer,
                        prompt,
                        facts[i]["value"],
                        facts[negative]["value"],
                        backend="full",
                    )
                    used_tokens, supervised = (
                        charge["actual_input_tokens"],
                        charge["actual_supervised_tokens"],
                    )
                    used_forwards = charge["actual_model_forwards"]
                else:
                    loss, charge = completion_loss(
                        self.reader.model, ids, labels, backend="full"
                    )
                    used_tokens, supervised, used_forwards = (
                        charge["input_tokens"],
                        charge["supervised_tokens"],
                        1,
                    )
                if not torch.isfinite(loss):
                    raise ValueError("nonfinite source loss")
                loss.backward()
                torch.nn.utils.clip_grad_norm_(params, 1.0, error_if_nonfinite=True)
                reject_global_optimizer_hooks()
                optimizer.step()
                if any(not torch.isfinite(p).all() for p in params):
                    raise ValueError("nonfinite source parameter update")
                visits[index] += 1
                fact_visits[i] += 1
                accessed.add(facts[i]["source_digest"])
                if objective == "source_margin":
                    accessed.add(facts[negatives[index]]["source_digest"])
                    negative_visits[negatives[index]] += 1
                input_tokens += used_tokens
                supervised_tokens += supervised
                forwards += used_forwards
                losses.append(float(loss.detach()))
            delta = sum(
                float((v - before[k]).square().sum())
                for k, v in get_peft_model_state_dict(self.reader.model).items()
            )
            if (
                not math.isfinite(delta)
                or delta <= 0
                or frozen_digest(self.reader.model) != self.reader.base_digest
            ):
                raise ValueError("missing finite adapter write or frozen base changed")
            self.reader.roots.update(accessed)
            receipt = dict(
                schema="hepta.source-memory.decoder-write.v1",
                objective=objective,
                scope=self.reader.scope,
                initialization=initialization,
                learned_parent_manifest_sha256=self._parent,
                starting_adapter_sha256=starting_adapter,
                adapter_state_sha256=adapter_digest(self.reader.model),
                previous_write_receipt_sha256=previous,
                inherited_roots=inherited,
                accessed_roots=sorted(accessed),
                roots=sorted(self.reader.roots),
                source_facts_sha256=digest(facts),
                templates_sha256=digest(templates),
                source_digests=[f["source_digest"] for f in facts],
                steps=steps,
                learning_rate=learning_rate,
                losses=losses,
                writer_seed=self.seed,
                schedule="seeded_epoch_permutation_v1",
                schedule_indices=schedule,
                schedule_sha256=digest(schedule),
                example_visits=visits,
                fact_visits=fact_visits,
                negative_fact_visits=negative_visits,
                negative_fact_indices=negatives if objective == "source_margin" else [],
                input_tokens=input_tokens,
                supervised_tokens=supervised_tokens,
                actual_model_forwards=forwards,
                adapter_delta_squared_norm=delta,
                trainable_parameters=sum(p.numel() for p in params),
                parameter_bytes=sum(p.numel() * p.element_size() for p in params),
                gradient_bytes=sum(
                    p.grad.numel() * p.grad.element_size()
                    for p in params
                    if p.grad is not None
                ),
                optimizer_tensor_bytes=sum(
                    v.numel() * v.element_size()
                    for state in optimizer.state.values()
                    for v in state.values()
                    if isinstance(v, torch.Tensor)
                ),
                base_identity=self.reader.identity,
                base_unchanged=True,
                seconds=time.perf_counter() - started,
                evaluation_targets_used=False,
                production_accepted=False,
            )
            self._receipt = json.loads(json.dumps(receipt, allow_nan=False))
            self._expected_adapter = receipt["adapter_state_sha256"]
            return receipt
        except Exception:
            self.reader.quarantined, self.reader.scope = True, None
            raise
        finally:
            self._freeze()

    def generate(self, questions, enabled=True):
        self._available()
        if (
            type(enabled) is not bool
            or type(questions) is not list
            or not 1 <= len(questions) <= 256
        ):
            raise ValueError(
                "bounded string questions and explicit adapter mode required"
            )
        prompts = [self.prompt_ids(question) for question in questions]
        if any(
            len(ids) + GENERATION["max_new_tokens"]
            > self.reader.model.config.max_position_embeddings
            for ids in prompts
        ):
            raise ValueError("decoder position limit exceeded")
        records = []
        try:
            for question, ids in zip(questions, prompts):
                x = torch.tensor([ids], dtype=torch.long)
                started = time.perf_counter()
                with frozen_adapter_mode(self.reader.model, enabled=enabled):
                    output = self.reader.model.generate(
                        input_ids=x,
                        attention_mask=torch.ones_like(x),
                        **GENERATION,
                        eos_token_id=self.reader.tokenizer.eos_token_id,
                        pad_token_id=self.reader.tokenizer.eos_token_id,
                    )
                tokens = output[0, len(ids) :].tolist()
                if (
                    not 1 <= len(tokens) <= GENERATION["max_new_tokens"]
                    or output[0, : len(ids)].tolist() != ids
                ):
                    raise ValueError("invalid raw autoregressive generation")
                records.append(
                    dict(
                        question=question,
                        text=self.reader.tokenizer.decode(
                            tokens,
                            skip_special_tokens=True,
                            clean_up_tokenization_spaces=False,
                        ),
                        token_ids=tokens,
                        prompt_sha256=digest(ids),
                        prompt_token_ids=ids,
                        input_tokens=len(ids),
                        generated_tokens=len(tokens),
                        evidence=[],
                        adapter_enabled=enabled,
                        base_identity=self.reader.identity,
                        seconds=time.perf_counter() - started,
                        answer_postprocessed=False,
                    )
                )
            if frozen_digest(self.reader.model) != self.reader.base_digest:
                raise ValueError("generation changed frozen base")
            return records
        except Exception:
            self.reader.quarantined, self.reader.scope = True, None
            raise

    def save(self, destination, receipt=None):
        self._available()
        if self._receipt is None or (receipt is not None and receipt != self._receipt):
            raise ValueError("save requires the unchanged measured write receipt")
        self._freeze()
        if (
            adapter_digest(self.reader.model) != self._receipt["adapter_state_sha256"]
            or frozen_digest(self.reader.model) != self.reader.base_digest
        ):
            self.reader.quarantined, self.reader.scope = True, None
            raise ValueError("weights changed after measured source write")
        destination = Path(destination)
        self.last_save_receipt = None
        try:
            manifest = self.reader.save(destination, self._receipt)
            names = ["adapter_model.safetensors", "adapter_config.json", "lineage.json"]
            for name in names:
                with (destination / name).open("r+b") as stream:
                    os.fsync(stream.fileno())
            # Windows has no directory-fsync interface through Python os.open.
            if os.name != "nt":
                for directory in (destination, destination.parent):
                    fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
            self.last_save_receipt = dict(
                manifest_sha256=manifest,
                flushed_files=names,
                directory_fsync=os.name != "nt",
                parent_directory_fsync=os.name != "nt",
                directory_policy="unsupported_on_windows"
                if os.name == "nt"
                else "posix_fsync",
                power_loss_recovery_verified=False,
            )
            return manifest
        except Exception:
            self.reader.quarantined, self.reader.scope = True, None
            raise

    def load(
        self, directory, *, expected_manifest_sha256, scope, allowed_roots, revoked
    ):
        try:
            receipt = self.reader.load_candidate(
                Path(directory),
                expected_manifest_sha256=expected_manifest_sha256,
                scope=scope,
                allowed_roots=allowed_roots,
                revoked=revoked,
            )
            self._receipt = None
            self._parent = expected_manifest_sha256
            self._initialization = "verified_adapter"
            self._expected_adapter = adapter_digest(self.reader.model)
            return receipt
        except Exception:
            self.reader.quarantined, self.reader.scope = True, None
            raise
        finally:
            self._freeze()
