"""One pinned frozen joint query/evidence encoder shared by every head arm."""

from dataclasses import asdict
import time

import torch

from native import digest
from selector_head import Features


class FrozenPairEncoder:
    def __init__(self, directory):
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        from pretrained import file_inventory, frozen_digest
        from relevance_ranker import RANKER_TENSOR_SHA256

        self.inventory = file_inventory(directory)
        if (
            self.inventory.get("model.safetensors", {}).get("sha256")
            != RANKER_TENSOR_SHA256
        ):
            raise ValueError("pretrained pair encoder pin")
        self.identity = digest(("paired-last-cls-plus-native-logit-v1", self.inventory))
        self.tokenizer = AutoTokenizer.from_pretrained(
            directory, local_files_only=True, trust_remote_code=False
        )
        self.model = AutoModelForSequenceClassification.from_pretrained(
            directory,
            local_files_only=True,
            trust_remote_code=False,
            use_safetensors=True,
            torch_dtype=torch.float32,
        ).eval()
        self.model.requires_grad_(False)
        if self.model.config.num_labels != 1:
            raise ValueError("one frozen relevance logit required")
        self.dimension = self.model.config.hidden_size
        self.initial_digest = frozen_digest(self.model)

    @torch.no_grad()
    def encode(self, query, family, pool, *, revoked):
        pool.revalidate(query, revoked)
        texts = [f"Observed {w.observed_at}. Passage: {w.text}" for w in pool.windows]
        question = f"As of {query.observed_at}: {query.content}"
        if len(self.tokenizer.encode(question, add_special_tokens=False)) > 192:
            raise ValueError("question exceeds explicit encoder budget")
        features, scores, inputs, tokens = [], [], [], 0
        started = time.perf_counter()
        for i in range(0, len(texts), 8):
            batch = texts[i : i + 8]
            # Never discard the candidate end through implicit truncation.
            if any(
                len(self.tokenizer.encode(question, p, add_special_tokens=True)) > 512
                for p in batch
            ):
                raise ValueError("paired encoder token budget")
            x = self.tokenizer(
                [question] * len(batch),
                batch,
                padding=True,
                truncation=False,
                return_tensors="pt",
            )
            y = self.model(**x, output_hidden_states=True)
            features.append(y.hidden_states[-1][:, 0, :].detach().cpu())
            scores.append(y.logits.flatten().detach().cpu())
            tokens += int(x["attention_mask"].sum())
            inputs.append({k: v.tolist() for k, v in sorted(x.items())})
        batch = Features(
            query.identity,
            family,
            self.identity,
            pool.seal(),
            tuple(w.identity() for w in pool.windows),
            frozenset(s["root"] for s in pool.inspected),
            torch.cat(features) if features else torch.empty(0, self.dimension),
            torch.cat(scores) if scores else torch.empty(0),
        )
        batch.validate(self.dimension)
        return batch, dict(
            encoder_identity=self.identity,
            input_digest=digest(inputs),
            pool_digest=pool.seal(),
            query_digest=digest(asdict(query)),
            pairs=len(texts),
            pair_tokens=tokens,
            seconds=time.perf_counter() - started,
            encoder_trainable_parameters=0,
            feature_bytes=batch.paired.numel() * 4,
            hidden_truncation=False,
        )

    def verify_frozen(self):
        from pretrained import frozen_digest

        if frozen_digest(self.model) != self.initial_digest or any(
            p.requires_grad for p in self.model.parameters()
        ):
            raise ValueError("shared pair encoder changed")
