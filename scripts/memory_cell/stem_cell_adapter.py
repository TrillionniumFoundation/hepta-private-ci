"""Actual encoder-internal LoRA controls, not relabelled post-encoder MLPs.

A lineage shares one adapted encoder; independent controls instantiate separate
encoders. Adapters learn only at the first registered curriculum checkpoint,
then freeze so continuing heads retain one stable representation identity.
"""

import json
import time

import torch
from peft import (
    LoraConfig,
    get_peft_model,
    get_peft_model_state_dict,
    set_peft_model_state_dict,
)
from safetensors.torch import load as load_tensors
from safetensors.torch import save as save_tensors

from native import digest
from pretrained import frozen_digest
from selector_encoder import FrozenPairEncoder
from stem_cell import sha256


class DifferentiatedEncoder(FrozenPairEncoder):
    def __init__(self, directory):
        super().__init__(directory)
        self.parent_identity = self.identity
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(1729)
            self.model = get_peft_model(
                self.model,
                LoraConfig(
                    r=4,
                    lora_alpha=8,
                    lora_dropout=0.0,
                    target_modules=["query", "value"],
                    bias="none",
                ),
            )
        self.base_digest = frozen_digest(self.model)
        self.roots = set()
        self.frozen = False
        self.adapter_digest = None
        self.receipt = None
        self.quarantined = False

    def fit(self, rows, queries, pools, cut, *, revoked, steps=24, token_ceiling=16384):
        if (
            self.frozen
            or self.quarantined
            or not 1 <= len(rows) <= 256
            or type(steps) is not int
            or not 1 <= steps <= 48
            or not cut.admission_digest
            or self.roots.intersection(revoked | cut.forbidden_roots)
        ):
            raise ValueError("unavailable encoder differentiation session")
        if type(token_ceiling) is not int or not 1024 <= token_ceiling <= 65536:
            raise ValueError("encoder differentiation token ceiling")
        prepared, omissions, seen = [], [], set()
        for row in rows:
            f = row.features
            f.validate(self.dimension)
            if (
                f.encoder_identity != self.parent_identity
                or f.question_id in seen
                or f.question_id not in cut.question_ids
                or f.family not in cut.families
                or not f.roots.issubset(cut.allowed_roots)
                or f.roots.intersection(cut.forbidden_roots | revoked)
                or len(set(row.positive_indices)) != len(row.positive_indices)
                or any(
                    type(i) is not int or not 0 <= i < len(f.candidate_ids)
                    for i in row.positive_indices
                )
            ):
                raise ValueError("unadmitted encoder training row")
            seen.add(f.question_id)
            query, pool = queries[f.question_id], pools[f.question_id]
            pool.revalidate(query, revoked)
            if (
                query.identity != f.question_id
                or pool.seal() != f.pool_digest
                or f.candidate_ids != tuple(w.identity() for w in pool.windows)
            ):
                raise ValueError("encoder training source binding")
            negatives = [
                i for i in range(len(f.candidate_ids)) if i not in row.positive_indices
            ]
            if not row.positive_indices or not negatives:
                omissions.append(f.question_id)
                continue
            pos = min(row.positive_indices, key=lambda i: f.candidate_ids[i])
            neg = min(negatives, key=lambda i: f.candidate_ids[i])
            question = f"As of {query.observed_at}: {query.content}"
            texts = [
                f"Observed {pool.windows[i].observed_at}. Passage: {pool.windows[i].text}"
                for i in (pos, neg)
            ]
            if any(
                len(self.tokenizer.encode(question, text, add_special_tokens=True))
                > 512
                for text in texts
            ):
                raise ValueError("encoder training token overflow; no truncation")
            x = self.tokenizer(
                [question] * 2,
                texts,
                padding=True,
                truncation=False,
                return_tensors="pt",
            )
            prepared.append((f, x))
        if not prepared:
            raise ValueError("no admitted positive-negative encoder training pair")
        parameters = [p for p in self.model.parameters() if p.requires_grad]
        optimizer = torch.optim.AdamW(parameters, lr=5e-5)
        before = {
            k: v.clone() for k, v in get_peft_model_state_dict(self.model).items()
        }
        tokens, losses, started, used = 0, [], time.perf_counter(), []
        self.receipt = dict(
            status="running",
            steps=0,
            tokens=0,
            token_ceiling=token_ceiling,
            prepared_questions=[f.question_id for f, _ in prepared],
            consumed_questions=[],
            ineligible_pair_questions=omissions,
            weak_unannotated_negatives=True,
            admission_digest=cut.admission_digest,
            trainable_parameters=sum(p.numel() for p in parameters),
            production_accepted=False,
        )
        self.model.eval()
        try:
            for step in range(steps):
                f, x = prepared[step % len(prepared)]
                cost = int(x["attention_mask"].sum())
                if tokens + cost > token_ceiling:
                    break
                # Charge the attempted forward/backward even if the update fails.
                tokens += cost
                used.append(f.question_id)
                self.receipt.update(tokens=tokens, consumed_questions=list(used))
                optimizer.zero_grad(set_to_none=True)
                logits = self.model(**x).logits.flatten()
                loss = torch.nn.functional.softplus(logits[1] - logits[0])
                if not torch.isfinite(loss):
                    raise ValueError("nonfinite encoder differentiation loss")
                loss.backward()
                torch.nn.utils.clip_grad_norm_(parameters, 1.0, error_if_nonfinite=True)
                optimizer.step()
                losses.append(float(loss.detach()))
                self.receipt["steps"] = len(losses)
                self.roots.update(f.roots)
            state = get_peft_model_state_dict(self.model)
            delta = sum(float((v - before[k]).square().sum()) for k, v in state.items())
            if (
                not losses
                or not delta > 0
                or frozen_digest(self.model) != self.base_digest
            ):
                raise ValueError("no encoder adapter update or base drift")
            if any(not torch.isfinite(t).all() for t in state.values()):
                raise ValueError("nonfinite encoder adapter weights")
            self.receipt.update(
                status="succeeded",
                seconds=time.perf_counter() - started,
                adapter_delta_squared_norm=delta,
                base_unchanged=True,
                optimizer_tensor_bytes=sum(
                    v.numel() * v.element_size()
                    for state in optimizer.state.values()
                    for v in state.values()
                    if isinstance(v, torch.Tensor)
                ),
            )
            self.freeze()
            return self.receipt
        except Exception:
            self.receipt.update(status="failed", seconds=time.perf_counter() - started)
            self.quarantined = True
            raise

    def freeze(self):
        self.model.requires_grad_(False)
        for p in self.model.parameters():
            p.grad = None
        self.model.eval()
        self.adapter_digest = sha256(self.tensor_bytes())
        self.identity = digest(
            ("stem-encoder-lora-v1", self.parent_identity, self.adapter_digest)
        )
        self.frozen = True

    def tensor_bytes(self):
        state = {
            k: v.detach().cpu().contiguous()
            for k, v in get_peft_model_state_dict(self.model).items()
        }
        return save_tensors(state)

    def export(self, directory):
        self.verify_frozen()
        directory.mkdir()
        payload = self.tensor_bytes()
        (directory / "adapter.safetensors").write_bytes(payload)
        metadata = dict(
            parent_identity=self.parent_identity,
            identity=self.identity,
            tensor_sha256=sha256(payload),
            roots=sorted(self.roots),
            receipt=self.receipt,
            production_accepted=False,
        )
        (directory / "adapter.json").write_text(
            json.dumps(metadata, indent=2, allow_nan=False)
        )
        return metadata

    def restore_into(self, directory, *, expected_metadata, allowed_roots, revoked):
        if self.frozen or self.quarantined:
            raise ValueError("restore requires a fresh differentiated encoder")
        paths = (directory / "adapter.json", directory / "adapter.safetensors")
        if directory.is_symlink() or any(
            p.is_symlink()
            or not p.is_file()
            or not 0 < p.stat().st_size <= 4 * 1024 * 1024
            for p in paths
        ):
            raise ValueError("bounded regular adapter artifact files required")
        metadata = json.loads(paths[0].read_text())
        payload = paths[1].read_bytes()
        if (
            metadata != expected_metadata
            or metadata["production_accepted"] is not False
            or metadata["parent_identity"] != self.parent_identity
            or sha256(payload) != metadata["tensor_sha256"]
            or not set(metadata["roots"]).issubset(allowed_roots)
            or set(metadata["roots"]) & revoked
        ):
            raise ValueError("adapter restore identity or lineage")
        state, expected = load_tensors(payload), get_peft_model_state_dict(self.model)
        if set(state) != set(expected) or any(
            state[k].shape != v.shape
            or state[k].dtype != v.dtype
            or not torch.isfinite(state[k]).all()
            for k, v in expected.items()
        ):
            raise ValueError("adapter restore tensor contract")
        set_peft_model_state_dict(self.model, state)
        self.roots, self.receipt = set(metadata["roots"]), metadata["receipt"]
        self.freeze()
        if self.identity != metadata["identity"]:
            self.quarantined = True
            raise ValueError("adapter restored representation differs")

    def encode(self, query, family, pool, *, revoked):
        if not self.frozen or self.quarantined or self.roots.intersection(revoked):
            raise ValueError("unfrozen or withdrawn encoder")
        return super().encode(query, family, pool, revoked=revoked)

    def verify_frozen(self):
        if (
            not self.frozen
            or self.quarantined
            or frozen_digest(self.model) != self.base_digest
            or sha256(self.tensor_bytes()) != self.adapter_digest
            or any(p.requires_grad for p in self.model.parameters())
        ):
            raise ValueError("differentiated encoder changed after freeze")
