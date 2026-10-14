"""Bounded local CPU-FP32 autoregressive proposer for existing System2 callbacks.

Weights are shared, but every proposal reconstructs its whole prefix without KV
state. This deliberately simple reference trades speed for explicit state scope.
It is not a tokenizer/architecture converter, sandbox, verifier or model trainer.
"""
from __future__ import annotations

import copy
import json
import threading
import time
from dataclasses import asdict

import torch

from matrix_bank import state_digest
from next_round_matrix import _digest
from paired_execution import _integer, _sha
from system2_execution import PublicTask, _text

SCHEMA = "hepta.local-causal-proposer.v1"
PROMPT_PROFILE = "public_task_json_then_answer.v1"
ANSWER_MARKER = "\n[ANSWER]\n"


def render_prompt(task: PublicTask, previous, feedback) -> str:
    """Length-bounded public data, not final labels or a hidden answer function."""
    if type(task) is not PublicTask:
        raise ValueError("exact public task type required")
    task.validate()
    if (previous is None) != (feedback is None):
        raise ValueError("previous answer and verification feedback must be paired")
    if previous is not None:
        _text(previous); _text(feedback)
    body = dict(task=asdict(task), previous=previous, feedback=feedback)
    text = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + ANSWER_MARKER
    if len(text.encode("utf-8")) > 65_536:
        raise ValueError("combined public prompt exceeds its byte cap")
    return text


def tokenizer_digest(tokenizer) -> str:
    """Bind the fast tokenizer graph, vocabulary and special-token declarations.

    Tokenizer implementation code still needs owner/source review. A digest is
    content linkage, not proof that an arbitrary supplied Python object is pure.
    """
    graph = tokenizer.backend_tokenizer.to_str()
    if not isinstance(graph, str) or not 1 <= len(graph.encode()) <= 16 * 1024 * 1024:
        raise ValueError("bounded serialized tokenizer graph required")
    vocab = tokenizer.get_vocab()
    if (not isinstance(vocab, dict) or not 1 <= len(vocab) <= 262144
            or any(not isinstance(k, str) or type(v) is not int or v < 0 for k, v in vocab.items())):
        raise ValueError("bounded exact tokenizer vocabulary required")
    return _digest([graph, vocab, tokenizer.special_tokens_map, tokenizer.eos_token_id])


def freeze_generation(*, model_sha256, tokenizer_sha256, vocab_size, eos_token_id,
                      context_tokens=1024, max_new_tokens=64, max_output_bytes=16384):
    for value in (model_sha256, tokenizer_sha256):
        _sha(value, "generation material identity")
    for name, value, limit in (("vocabulary", vocab_size, 262144), ("context", context_tokens, 8192),
                               ("new tokens", max_new_tokens, 256), ("output bytes", max_output_bytes, 65536)):
        _integer(value, name, 1)
        if value > limit:
            raise ValueError("generation bound exceeded: " + name)
    if context_tokens * vocab_size * 4 > 256 * 1024 * 1024:
        raise ValueError("full-prefix logit payload exceeds 256 MiB; activation memory is separate")
    _integer(eos_token_id, "EOS token")
    if eos_token_id >= vocab_size or max_new_tokens >= context_tokens:
        raise ValueError("invalid EOS or token envelope")
    body = dict(schema=SCHEMA, model_sha256=model_sha256, tokenizer_sha256=tokenizer_sha256,
                vocab_size=vocab_size, eos_token_id=eos_token_id, context_tokens=context_tokens,
                max_new_tokens=max_new_tokens, max_output_bytes=max_output_bytes,
                prompt_profile=PROMPT_PROFILE, precision="cpu_fp32", decoding="greedy_first_index",
                persistent_kv_cache=False, require_eos=True)
    return {**body, "profile_id": _digest(body)}


class GenerationIncomplete(RuntimeError):
    """No complete answer was produced; a partial prefix is never returned as success."""


class LocalCausalProposer:
    """Immutable-weight reference adapter; safe sharing is serial, not global state.

    The owner supplies a causal torch model with the stock CausalLM forward shape
    and a fast tokenizer. Unknown operators remain governed by the caller's meter.
    Models with hidden mutable state or side effects are outside this contract.
    """
    def __init__(self, model, tokenizer, policy):
        names = ("model_sha256", "tokenizer_sha256", "vocab_size", "eos_token_id",
                 "context_tokens", "max_new_tokens", "max_output_bytes")
        try:
            expected = freeze_generation(**{k: policy[k] for k in names})
        except (KeyError, TypeError) as exc:
            raise ValueError("complete generation policy required") from exc
        if _digest(policy) != _digest(expected) or not isinstance(model, torch.nn.Module):
            raise ValueError("unbound generation policy or model")
        self._model, self._tokenizer, self._policy = model, tokenizer, copy.deepcopy(expected)
        self._lock, self._last = threading.Lock(), None
        self.verify_integrity()

    def verify_integrity(self):
        model, p = self._model, self._policy
        state = model.state_dict()
        if (not state or any(m.training for m in model.modules())
                or any(t.device.type != "cpu" or (t.is_floating_point() and t.dtype != torch.float32)
                       or t.is_complex() for t in state.values())
                or any(v.requires_grad for v in model.parameters())):
            raise ValueError("frozen eval CPU FP32 model required")
        if state_digest(model) != p["model_sha256"] or tokenizer_digest(self._tokenizer) != p["tokenizer_sha256"]:
            raise ValueError("model/tokenizer differs from frozen generation material")
        vocab = self._tokenizer.get_vocab()
        if (max(vocab.values()) >= p["vocab_size"]
                or type(self._tokenizer.eos_token_id) is not int
                or self._tokenizer.eos_token_id != p["eos_token_id"]):
            raise ValueError("tokenizer IDs disagree with bound output geometry")

    def receipt(self):
        return copy.deepcopy(dict(policy=self._policy, last_generation=self._last,
                                  pretrained_provenance_verified=False, production_authorized=False))

    def __call__(self, task, previous, feedback):
        if not self._lock.acquire(blocking=False):
            raise ValueError("concurrent/reentrant use requires a separate admitted adapter")
        start = time.perf_counter_ns()
        record = dict(schema="hepta.local-causal-generation.v1", profile_id=self._policy["profile_id"],
                      status="failed", forward_attempts=0, token_steps=[], generated_tokens=0,
                      eos_observed=False, prompt_sha256=None, prompt_tokens=None, output_sha256=None)
        generated = []
        try:
            self.verify_integrity()
            text = render_prompt(task, previous, feedback)
            record["prompt_sha256"] = _digest(text)
            ids = self._tokenizer.encode(text, add_special_tokens=False, truncation=False)
            p = self._policy
            if (not isinstance(ids, list) or not ids
                    or any(type(x) is not int or not 0 <= x < p["vocab_size"] for x in ids)):
                raise ValueError("invalid tokenizer IDs")
            record["prompt_tokens"] = len(ids)
            if len(ids) + p["max_new_tokens"] > p["context_tokens"]:
                raise GenerationIncomplete("context envelope exceeded; no silent truncation")
            tokens = torch.tensor([ids], dtype=torch.long)
            with torch.inference_mode():
                for _ in range(p["max_new_tokens"]):
                    record["forward_attempts"] += 1
                    result = self._model(input_ids=tokens, attention_mask=torch.ones_like(tokens),
                                         past_key_values=None, use_cache=False, return_dict=True)
                    logits = result.logits
                    if (logits.shape != (1, tokens.shape[1], p["vocab_size"])
                            or logits.device.type != "cpu" or logits.dtype != torch.float32
                            or not torch.isfinite(logits).all().item()
                            or getattr(result, "past_key_values", None) is not None):
                        raise ValueError("invalid full-prefix causal output or leaked KV state")
                    token = int(logits[0, -1].argmax().item())
                    record["token_steps"].append(dict(prefix_tokens=tokens.shape[1], selected_token=token))
                    if token == p["eos_token_id"]:
                        record["eos_observed"] = True
                        break
                    generated.append(token)
                    tokens = torch.cat((tokens, torch.tensor([[token]], dtype=torch.long)), dim=1)
            if not record["eos_observed"]:
                raise GenerationIncomplete("token budget ended without EOS")
            output = self._tokenizer.decode(generated, skip_special_tokens=False, clean_up_tokenization_spaces=False)
            if output == "":
                raise GenerationIncomplete("EOS produced no decoded answer")
            _text(output)
            if len(output.encode("utf-8")) > p["max_output_bytes"]:
                raise GenerationIncomplete("decoded answer exceeds byte budget")
            self.verify_integrity()
            record.update(status="completed", output_sha256=_digest(output))
            return output
        except Exception as exc:
            record["error_type"] = type(exc).__name__
            raise
        finally:
            record.update(generated_tokens=len(generated), generated_ids_sha256=_digest(generated),
                          elapsed_ns=time.perf_counter_ns() - start,
                          state_scope="public_prefix_no_persistent_kv", full_cost_qualification=False)
            self._last = copy.deepcopy(record)
            self._lock.release()
