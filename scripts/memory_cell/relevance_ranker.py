"""Offline query/passage LoRA selector on an explicitly pinned ranking model.

Shares immutable tensor admission with the existing worker, not production
selection authority. Training source membership is checked before optimization.
"""

from contextlib import nullcontext
import time
import hashlib
import json

import torch
from peft import LoraConfig, get_peft_model, get_peft_model_state_dict
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from native import digest
from pretrained import LoRAReader, file_inventory, frozen_digest
from relevance_protocol import validate_training
from tensor_contract import canonical_config

RANKER_ID = "cross-encoder/ms-marco-MiniLM-L6-v2"
RANKER_REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
RANKER_TENSOR_SHA256 = (
    "821d1aa69520101d6e0737f78a042ae25b19e5cb9160701909d10434f4aeb0ae"
)


class RelevanceRanker(LoRAReader):
    def __init__(self, directory):
        torch.manual_seed(1729)
        self.inventory = file_inventory(directory)
        if (
            self.inventory.get("model.safetensors", {}).get("sha256")
            != RANKER_TENSOR_SHA256
        ):
            raise ValueError("ranking model tensor pin mismatch")
        self.identity = digest(self.inventory)
        self.tokenizer = AutoTokenizer.from_pretrained(
            directory, local_files_only=True, trust_remote_code=False
        )
        base = AutoModelForSequenceClassification.from_pretrained(
            directory,
            local_files_only=True,
            trust_remote_code=False,
            use_safetensors=True,
            torch_dtype=torch.float32,
        )
        if base.config.num_labels != 1:
            raise ValueError("scalar relevance logit required")
        # No task_type: keep the existing frozen classifier head, adapting only
        # attention query/value. No randomly reinitialized classification head.
        self.model = get_peft_model(
            base,
            LoraConfig(
                r=4,
                lora_alpha=8,
                lora_dropout=0.0,
                target_modules=["query", "value"],
                bias="none",
            ),
        )
        self.initial = {
            k: v.detach().clone()
            for k, v in get_peft_model_state_dict(self.model).items()
        }
        self.trainable_parameters = sum(
            p.numel() for p in self.model.parameters() if p.requires_grad
        )
        self.base_digest = frozen_digest(self.model)
        self.adapter_config = canonical_config(
            self.model.peft_config["default"].to_dict()
        )
        self.scope, self.roots, self.quarantined = None, set(), False

    def tokens(self, queries, passages):
        if not 1 <= len(queries) == len(passages) <= 8 or any(
            not isinstance(t, str) or not t.strip() or len(t.encode()) > 16384
            for t in (*queries, *passages)
        ):
            raise ValueError("ranker batch/text limit")
        lengths = [
            len(self.tokenizer.encode(q, p, add_special_tokens=True))
            for q, p in zip(queries, passages, strict=True)
        ]
        if max(lengths) > 512:
            raise ValueError("ranker input exceeds 512 tokens; no hidden truncation")
        return self.tokenizer(
            queries, passages, padding=True, truncation=False, return_tensors="pt"
        )

    @torch.no_grad()
    def score(self, query, passages, *, revoked, disable_adapter=False):
        if (
            self.quarantined
            or self.scope is None
            or self.roots & revoked
            or len(passages) > 64
        ):
            raise ValueError("unavailable, withdrawn or unbounded ranker")
        self.model.eval()
        values, tokens, started = [], 0, time.perf_counter()
        inputs_hash = hashlib.sha256(b"hepta.relevance.paired-input-tensors.v1\0")
        with self.model.disable_adapter() if disable_adapter else nullcontext():
            for start in range(0, len(passages), 8):
                batch = passages[start : start + 8]
                x = self.tokens([query] * len(batch), batch)
                inputs_hash.update(
                    json.dumps(
                        {k: v.tolist() for k, v in sorted(x.items())},
                        separators=(",", ":"),
                    ).encode()
                )
                y = self.model(**x).logits.flatten()
                if not torch.isfinite(y).all():
                    raise ValueError("nonfinite ranking logits")
                values.extend(y.tolist())
                tokens += int(x["attention_mask"].sum())
        return values, dict(
            pair_tokens=tokens,
            pairs=len(passages),
            seconds=time.perf_counter() - started,
            input_ids_sha256=inputs_hash.hexdigest(),
            input_digest_schema="paired-input-tensors-v1",
            scores_are_calibrated_probabilities=False,
        )

    def fit_pairs(
        self,
        pairs,
        *,
        permitted_questions,
        permitted_families,
        forbidden_roots,
        revoked,
        maximum_steps=48,
        token_ceiling=24576,
    ):
        training_digest = validate_training(
            pairs, permitted_questions, permitted_families, forbidden_roots, revoked
        )
        if (
            self.quarantined
            or self.scope is None
            or self.roots & revoked
            or not 1 <= maximum_steps <= 128
        ):
            raise ValueError("unavailable training instance or step budget")
        if not 1024 <= token_ceiling <= 65536:
            raise ValueError("training token ceiling")
        by_family = {}
        for pair in pairs:
            by_family.setdefault(pair.family, []).append(pair)
        family_order = sorted(by_family)
        batches = []
        for step in range(maximum_steps):
            family = family_order[step % len(family_order)]
            group = by_family[family]
            pair = group[(step // len(family_order)) % len(group)]
            texts = [
                f"Observed {d.observed_at}. {d.content[:768]}"
                for d in (pair.positive, pair.negative)
            ]
            batches.append((pair, self.tokens([pair.question] * 2, texts)))
        before = {
            k: v.clone() for k, v in get_peft_model_state_dict(self.model).items()
        }
        parameters = [p for p in self.model.parameters() if p.requires_grad]
        optimizer = torch.optim.AdamW(parameters, lr=5e-5)
        losses, tokens, roots, started = [], 0, set(self.roots), time.perf_counter()
        # Eval mode removes dropout; gradient tracking stays enabled.
        self.model.eval()
        try:
            for pair, x in batches:
                used = int(x["attention_mask"].sum())
                if tokens + used > token_ceiling:
                    break
                optimizer.zero_grad(set_to_none=True)
                scores = self.model(**x).logits.flatten()
                loss = torch.nn.functional.softplus(scores[1] - scores[0])
                if not torch.isfinite(loss):
                    raise ValueError("nonfinite pairwise loss")
                loss.backward()
                torch.nn.utils.clip_grad_norm_(parameters, 1.0, error_if_nonfinite=True)
                optimizer.step()
                tokens += used
                losses.append(float(loss.detach()))
                roots.update((pair.positive.root, pair.negative.root))
            delta = sum(
                float((v - before[k]).square().sum())
                for k, v in get_peft_model_state_dict(self.model).items()
            )
            if (
                not losses
                or not delta > 0
                or frozen_digest(self.model) != self.base_digest
            ):
                raise ValueError("no update or frozen base changed")
            if any(not torch.isfinite(p).all() for p in parameters):
                raise ValueError("nonfinite adapter")
            self.roots = roots
            return dict(
                objective="native-train-family-pairwise-ranking-v1",
                training_digest=training_digest,
                losses=losses,
                steps=len(losses),
                tokens=tokens,
                token_ceiling=token_ceiling,
                maximum_steps=maximum_steps,
                train_seconds=time.perf_counter() - started,
                adapter_delta_squared_norm=delta,
                trainable_parameters=self.trainable_parameters,
                roots=sorted(roots),
                training_families=family_order,
                annotation_scope="train-only native evidence; unlabelled negatives are weak",
                base_unchanged=True,
                production_accepted=False,
            )
        except Exception:
            self.quarantined, self.scope = True, None
            raise
