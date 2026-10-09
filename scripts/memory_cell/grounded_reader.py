"""Opt-in answer-only LoRA and constrained quotation on the pinned reader.

Does not change LoRAReader, native benchmark history, installed tensor profiles,
serving defaults, signing roles or acceptance. All supervision comes from the
admitted source excerpts, never a benchmark Question/Target or held-out answer.
"""

import hashlib
import json
import time

import torch
from peft import get_peft_model_state_dict

from grounded_protocol import (
    ABSTAIN,
    MAX_NEW_TOKENS,
    SYSTEM,
    QuoteTrie,
    completion_ids,
    quote_options,
    verify_output,
)
from native import Document, Question, digest
from pretrained import LoRAReader, frozen_digest


class GroundedReader(LoRAReader):
    def _prepare(self, query: Question, evidence: list[Document], revoked: set[str]):
        if (
            self.quarantined
            or query.scope != self.scope
            or self.roots.intersection(revoked)
            or len(evidence) > 8
            or any(d.scope != self.scope or d.root in revoked for d in evidence)
            or len({d.identity for d in evidence}) != len(evidence)
        ):
            raise ValueError("revoked, duplicated or cross-scope grounding input")
        if (
            not query.content.strip()
            or len(query.content.encode()) > 16384
            or not query.observed_at
            or len(query.observed_at.encode()) > 256
        ):
            raise ValueError("grounded question bound")
        sources, omitted = [], 0

        def prompt(current):
            return self.tokenizer.apply_chat_template(
                [
                    {"role": "system", "content": SYSTEM},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "question_time": query.observed_at,
                                "question": query.content,
                                "memory": [
                                    {"label": s["label"], "text": s["excerpt"]}
                                    for s in current
                                ],
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                tokenize=True,
                add_generation_prompt=True,
            )

        ids = prompt([])
        if len(ids) > 512:
            raise ValueError("grounded question overhead exceeds budget")
        for i, doc in enumerate(evidence):
            if not isinstance(doc.content, str) or "\0" in doc.content:
                raise ValueError("invalid source text")
            excerpt = doc.content[:512]
            candidate = {
                "id": doc.identity,
                "root": doc.root,
                "label": f"E{i + 1}",
                "excerpt": excerpt,
                "partial": excerpt != doc.content,
            }
            offered = prompt(sources + [candidate])
            if len(offered) > 1024:
                omitted += len(doc.content.encode())
                continue
            omitted += len(doc.content.encode()) - len(excerpt.encode())
            sources.append(candidate)
            ids = offered
        options = quote_options(sources)
        return ids, sources, options, omitted

    @torch.no_grad()
    def answer_grounded(
        self,
        query: Question,
        evidence: list[Document],
        *,
        revoked: set[str],
        decoder: str,
    ) -> tuple[str, dict]:
        if decoder not in ("free", "span"):
            raise ValueError("unregistered decoder")
        ids, sources, options, omitted = self._prepare(query, evidence, revoked)
        trie = QuoteTrie(self.tokenizer, ids, options)
        inputs = torch.tensor([ids], dtype=torch.long)
        start = time.perf_counter()
        # Fixed budget across both decoder arms. No post-hoc labels or repairs.
        result = self.model.generate(
            input_ids=inputs,
            attention_mask=torch.ones_like(inputs),
            max_new_tokens=MAX_NEW_TOKENS,
            min_new_tokens=0,
            do_sample=False,
            num_beams=1,
            use_cache=True,
            eos_token_id=self.tokenizer.eos_token_id,
            pad_token_id=self.tokenizer.eos_token_id,
            prefix_allowed_tokens_fn=trie.allowed if decoder == "span" else None,
        )
        generated = result[0, len(ids) :].tolist()
        raw = self.tokenizer.decode(
            generated, skip_special_tokens=True, clean_up_tokenization_spaces=False
        ).strip()
        if decoder == "span" and trie.completed(generated) != raw:
            raise ValueError("completed tokens and decoded answer disagree")
        if not raw:
            raise ValueError("empty model answer")
        try:
            structure = verify_output(raw, options)
        except ValueError:
            if decoder == "span":
                raise
            structure = {
                "abstained": False,
                "copy_verified": False,
                "semantic_precision": None,
                "relevance_verified": False,
            }
        receipt = {
            "protocol": "source-quotation-development-v1",
            "decoder": decoder,
            "input_tokens": len(ids),
            "generated_tokens": len(generated),
            "query_seconds": time.perf_counter() - start,
            "evidence_bytes_omitted": omitted,
            "candidate_quotes": len(options),
            "tokenization_or_length_excluded": trie.excluded,
            "offered_completions_digest": digest(sorted(trie.outputs.values())),
            "input_ids_sha256": hashlib.sha256(
                b"hepta.memory-prompt.token-ids.v1\0"
                + b"".join(int(i).to_bytes(8, "big") for i in ids)
            ).hexdigest(),
            "generated_ids_sha256": digest(generated),
            "delivered_evidence": sources,
            "structure": structure,
            "citation_entailment_precision": None,
            "production_accepted": False,
        }
        return raw, receipt

    def adapt_grounded(
        self,
        history: tuple[Document, ...],
        *,
        steps: int,
        revoked: set[str],
        token_ceiling: int = 6144,
    ) -> dict:
        if (
            not 1 <= steps <= 64
            or not 1120 <= token_ceiling <= 65536
            or not history
            or len(history) > 8
            or any(d.scope != self.scope or d.root in revoked for d in history)
        ):
            raise ValueError("source-only adaptation bounds or scope")
        # Materialize supervision before updates. There is no Question or Target
        # parameter: cues and exact quotations are derived only from source text.
        examples = []
        documents = sorted(history, key=lambda d: digest(d.identity))
        for step in range(steps):
            rotated = (
                documents[step % len(documents) :] + documents[: step % len(documents)]
            )
            rotated = rotated[:3]
            probe = Question(
                "source-only",
                "source-only",
                self.scope,
                "Quote a relevant passage.",
                "source-bound",
            )
            probe_ids, _, options, _ = self._prepare(probe, rotated, revoked)
            representable = QuoteTrie(
                self.tokenizer, probe_ids, options
            ).outputs.values()
            options = tuple(q for q in options if q.render() in representable)
            if not options:
                raise ValueError("no complete source quotation within budget")
            target = options[step % len(options)]
            cue = target.text[:120]
            if not cue:
                raise ValueError("empty source cue")
            if step % 4 == 3:
                cue = "unobserved-" + digest((step, [d.identity for d in rotated]))[:24]
                if any(cue in d.content for d in rotated):
                    raise ValueError("negative cue actually observed")
                completion = ABSTAIN
            else:
                completion = target.render()
            query = Question(
                "source-only",
                "source-only",
                self.scope,
                f"Quote the passage containing the exact phrase {json.dumps(cue)}.",
                "source-bound",
            )
            prompt, delivered, available, _ = self._prepare(query, rotated, revoked)
            if completion != ABSTAIN:
                verify_output(completion, available)
            inputs, labels = completion_ids(
                self.tokenizer, prompt, completion, maximum=1120
            )
            examples.append((inputs, labels, delivered, completion))
        started = time.perf_counter()
        before = {
            k: v.clone() for k, v in get_peft_model_state_dict(self.model).items()
        }
        optimizer = torch.optim.AdamW(
            (p for p in self.model.parameters() if p.requires_grad),
            lr=2e-4,
        )
        losses, tokens, supervised, roots, seen = [], 0, 0, set(self.roots), set()
        self.model.train()
        try:
            completed = 0
            for inputs, labels, sources, _ in examples:
                if tokens + len(inputs) > token_ceiling:
                    break
                x = torch.tensor([inputs], dtype=torch.long)
                y = torch.tensor([labels], dtype=torch.long)
                optimizer.zero_grad(set_to_none=True)
                loss = self.model(
                    input_ids=x,
                    attention_mask=torch.ones_like(x),
                    labels=y,
                    use_cache=False,
                ).loss
                if not torch.isfinite(loss):
                    raise ValueError("nonfinite grounded loss")
                loss.backward()
                torch.nn.utils.clip_grad_norm_(
                    (p for p in self.model.parameters() if p.requires_grad),
                    1.0,
                    error_if_nonfinite=True,
                )
                optimizer.step()
                losses.append(float(loss.detach()))
                completed += 1
                tokens += len(inputs)
                supervised += sum(v != -100 for v in labels)
                roots.update(s["root"] for s in sources)
                seen.update(s["id"] for s in sources)
            if frozen_digest(self.model) != self.base_digest:
                raise ValueError("grounded adaptation changed frozen base")
            delta = sum(
                float((v - before[k]).square().sum())
                for k, v in get_peft_model_state_dict(self.model).items()
            )
            if not delta > 0:
                raise ValueError("grounded adaptation did not update tensors")
            self.roots = roots
            return {
                "steps": completed,
                "maximum_steps": steps,
                "token_ceiling": token_ceiling,
                "tokens": tokens,
                "supervised_tokens": supervised,
                "train_seconds": time.perf_counter() - started,
                "losses": losses,
                "adapter_delta_squared_norm": delta,
                "base_unchanged": True,
                "documents": sorted(seen),
                "roots": sorted(roots),
                "trainable_parameters": self.trainable_parameters,
                "objective": "source-derived-completion-only-with-abstention-v1",
                "supervision_digest": digest([(x, y) for x, y, _, _ in examples]),
                "benchmark_targets_used": False,
                "training_prompts_from_sources_only": True,
                "optimizer_tensor_bytes": sum(
                    v.numel() * v.element_size()
                    for state in optimizer.state.values()
                    for v in state.values()
                    if isinstance(v, torch.Tensor)
                ),
            }
        except Exception:
            self.quarantined = True
            self.scope = None
            raise
        finally:
            self.model.eval()
