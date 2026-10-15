"""Exact, chunked frozen token features for the V4 evidence experiment.

Chunks preserve the tokenizer's complete original ID sequence. The Encoder sees
bounded chunks independently; cross-chunk context is the Reader's responsibility.
Targets and evidence annotations are excluded from public inference features.
"""
import json
from pathlib import Path
import time

import torch

from execution_meter import TRANSFORMER_POLICY_SCHEMA, WorkLedger
from group_encoder import FrozenTokenEncoder, digest_json, file_digest
from hf_encoder_kernel import verify_loaded_safetensors
from paired_execution import PHASES
from reader_features import tensor_digest
from transformer_work import PROFILE


PUBLIC_FIELDS = frozenset(("facts", "question", "candidate", "fact_mask", "question_mask",
                           "candidate_mask", "sentence_indices", "feature_sha256", "source_sha256"))


class TokenBank:
    """Deduplicate raw public strings while retaining every non-padding token."""

    def __init__(self, encoder, *, batch_size=16, chunk_tokens=64, max_fact_chunks=256,
                 max_role_tokens=1024, scope="reader-v4", generation=0, encoder_load=None):
        specials = encoder.tokenizer.num_special_tokens_to_add(pair=False)
        if (type(batch_size) is not int or not 1 <= batch_size <= 64
                or type(chunk_tokens) is not int or not specials < chunk_tokens <= encoder.max_tokens
                or type(max_fact_chunks) is not int or not 1 <= max_fact_chunks <= 256
                or type(max_role_tokens) is not int or not 1 <= max_role_tokens <= 1024):
            raise ValueError("bounded token chunks and complete feature limits required")
        probe = encoder.tokenizer("hepta", add_special_tokens=False, truncation=False)["input_ids"]
        wrapped = encoder.tokenizer("hepta", add_special_tokens=True, truncation=False)["input_ids"]
        self.prefix_id, self.suffix_id = encoder.tokenizer.cls_token_id, encoder.tokenizer.sep_token_id
        if specials != 2 or wrapped != [self.prefix_id, *probe, self.suffix_id]:
            raise ValueError("registered Granite prefix/content/suffix template required")
        self.encoder, self.batch_size, self.chunk_tokens = encoder, batch_size, chunk_tokens
        self.payload_tokens = chunk_tokens - specials
        self.max_fact_chunks, self.max_role_tokens = max_fact_chunks, max_role_tokens
        self.scope, self.generation, self.encoder_load = scope, generation, encoder_load
        self.feature_generation_load, self.cache_restore = encoder_load, None
        self.tokens, self.values, self.bindings = {}, {}, {}
        self.forward_batches = self.encoded_sequences = self.logical_text_uses = 0
        self.cpu_ns = self.wall_ns = 0
        self.observations = []
        self.preprocess_sha256 = digest_json(dict(schema="hepta.reader.exact-token.v1",
            base=encoder.preprocess_digest, chunk_tokens=chunk_tokens, added_specials=specials,
            prefix_id=self.prefix_id, suffix_id=self.suffix_id,
            output="content-token-last-hidden-state", chunk_context="independent",
            truncation=False, max_fact_chunks=max_fact_chunks, max_role_tokens=max_role_tokens,
            scope=scope, generation=generation))

    @classmethod
    def from_snapshot(cls, snapshot, **kwargs):
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        encoder = FrozenTokenEncoder(snapshot, max_tokens=kwargs.get("chunk_tokens", 64))
        load = dict(cpu_ns=time.process_time_ns() - cpu, wall_ns=time.perf_counter_ns() - wall,
                    material_sha256=digest_json(encoder.material))
        return cls(encoder, encoder_load=load, **kwargs)

    def _binding(self, case):
        return dict(source_sha256=case.source_hash, public_sha256=case.feature_source_hash,
                    fact_texts=list(case.facts), question=case.question, candidate=case.candidate,
                    preprocess_sha256=self.preprocess_sha256)

    def _ids(self, text):
        ids = tuple(self.encoder.tokenizer(text, add_special_tokens=False, truncation=False)["input_ids"])
        if (any(type(i) is not int or i < 0 for i in ids)
                or len(ids) > max(self.max_role_tokens, self.max_fact_chunks * self.payload_tokens)):
            raise ValueError("complete public text exceeds registered token bound")
        return ids

    def register(self, cases):
        """Encode missing strings only; callers determine train/final chronology."""
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        policy = dict(schema=TRANSFORMER_POLICY_SCHEMA, arithmetic_profile=PROFILE, mode="observe",
                      wall_time_ns=3_600_000_000_000, max_process_rss_bytes=None,
                      rapl_zone=None, rapl_max_power_watts=None)
        meter = WorkLedger(policy, dict.fromkeys(PHASES, 10**18))
        new_tokens = {}
        try:
            if self.encoder.model.training or any(p.requires_grad for p in self.encoder.model.parameters()):
                raise ValueError("feature Encoder must remain frozen")
            new_tokens, new_bindings, uses = {}, {}, 0
            for case in cases:
                binding = self._binding(case)
                if (case.case_id in self.bindings and self.bindings[case.case_id] != binding
                        or case.case_id in new_bindings and new_bindings[case.case_id] != binding):
                    raise ValueError("case identity changed public input")
                texts = (*case.facts, case.question, case.candidate)
                for text in texts:
                    if text not in self.tokens and text not in new_tokens:
                        new_tokens[text] = self._ids(text)
                get = lambda text: self.tokens[text] if text in self.tokens else new_tokens[text]
                if (any(not get(fact) for fact in case.facts)
                        or sum((len(get(f)) + self.payload_tokens - 1) // self.payload_tokens
                               for f in case.facts) > self.max_fact_chunks
                        or not get(case.question)
                        or any(len(get(t)) > self.max_role_tokens for t in (case.question, case.candidate))):
                    raise ValueError("complete paragraph/question/candidate exceeds token geometry")
                new_bindings[case.case_id] = binding
                uses += len(texts)
            self.tokens.update(new_tokens)
            pending = []
            parts = {}
            for text in sorted(new_tokens):
                ids = new_tokens[text]
                parts[text] = []
                for offset in range(0, len(ids), self.payload_tokens):
                    payload = list(ids[offset:offset + self.payload_tokens])
                    row = dict(input_ids=[self.prefix_id, *payload, self.suffix_id],
                               attention_mask=[1] * (len(payload) + 2))
                    keep = list(range(1, len(payload) + 1))
                    pending.append((text, offset, row, keep))
            pending.sort(key=lambda record: len(record[2]["input_ids"]))
            for offset in range(0, len(pending), self.batch_size):
                records = pending[offset:offset + self.batch_size]
                tokens = self.encoder.tokenizer.pad([row for _, _, row, _ in records], padding=True,
                                                     return_tensors="pt")
                with meter.scope("inference", "encoder"), torch.no_grad():
                    features = self.encoder.model(**tokens).last_hidden_state
                if (features.shape != (*tokens["input_ids"].shape, 384)
                        or not torch.isfinite(features).all()):
                    raise ValueError("invalid frozen token geometry")
                for index, (text, start, _, keep) in enumerate(records):
                    parts[text].append((start, features[index, keep].detach().clone()))
                self.forward_batches += 1
                self.encoded_sequences += len(records)
            for text, entries in parts.items():
                ordered = [value for _, value in sorted(entries, key=lambda entry: entry[0])]
                self.values[text] = torch.cat(ordered) if ordered else torch.zeros((0, 384))
            self.bindings.update(new_bindings)
            self.logical_text_uses += uses
        except Exception:
            for text in new_tokens:
                self.tokens.pop(text, None)
                self.values.pop(text, None)
            raise
        finally:
            self.observations.append(meter.report())
            self.cpu_ns += time.process_time_ns() - cpu
            self.wall_ns += time.perf_counter_ns() - wall

    def public(self, case, *, deleted=False, permuted=False):
        """Return only public features; reread raw binding to prevent cache substitution."""
        binding = self._binding(case)
        if self.bindings.get(case.case_id) != binding:
            raise ValueError("unregistered or changed public source binding")
        chunks = [(self.values[text][start:start + self.payload_tokens], sentence)
                  for sentence, text in enumerate(case.facts)
                  for start in range(0, len(self.tokens[text]), self.payload_tokens)]
        if permuted:
            chunks.reverse()
        width = max(len(value) for value, _ in chunks)
        facts = torch.zeros((1, len(chunks), width, 384))
        mask = torch.zeros((1, len(chunks), width), dtype=torch.bool)
        for index, (value, _) in enumerate(chunks):
            if not deleted:
                facts[0, index, :len(value)], mask[0, index, :len(value)] = value, True
        question, candidate = (self.values[text].unsqueeze(0).clone() for text in (case.question, case.candidate))
        if candidate.shape[1] == 0:
            candidate = torch.zeros((1, 1, 384))
        result = dict(facts=facts, question=question, candidate=candidate, fact_mask=mask,
            question_mask=torch.ones(question.shape[:2], dtype=torch.bool),
            candidate_mask=torch.full(candidate.shape[:2], bool(self.tokens[case.candidate])),
            sentence_indices=torch.tensor([[sentence for _, sentence in chunks]]),
            source_sha256=case.source_hash)
        result["feature_sha256"] = digest_json(dict(binding=binding, deleted=deleted, permuted=permuted,
            tensors={name: tensor_digest(value) for name, value in result.items() if isinstance(value, torch.Tensor)}))
        return result

    def batch(self, cases):
        from token_reader_training import TokenBatch
        cases = tuple(cases)
        if not cases:
            raise ValueError("nonempty selected cases required")
        rows = [self.public(case) for case in cases]
        tensors = {}
        for name in ("facts", "question", "candidate", "fact_mask", "question_mask", "candidate_mask"):
            shape = tuple(max(row[name].shape[axis] for row in rows) for axis in range(1, rows[0][name].ndim))
            value = torch.zeros((len(rows), *shape), dtype=rows[0][name].dtype)
            for index, row in enumerate(rows):
                slices = (index, *(slice(0, n) for n in row[name].shape[1:]))
                value[slices] = row[name][0]
            tensors[name] = value
        targets = torch.zeros(tensors["facts"].shape[:2])
        supervised = torch.zeros(len(rows), dtype=torch.bool)
        for index, (case, row) in enumerate(zip(cases, rows)):
            if (case.evidence_sentence_indices and case.sentence_ids
                    and set(case.evidence_sentence_indices) <= set(case.sentence_ids)):
                selected = {i for i, sentence_id in enumerate(case.sentence_ids)
                            if sentence_id in case.evidence_sentence_indices}
                values = torch.tensor([int(i in selected) for i in row["sentence_indices"][0].tolist()], dtype=torch.float32)
                targets[index, :len(values)] = values / values.sum()
                supervised[index] = True
        return TokenBatch(**tensors, targets=torch.tensor([case.label for case in cases]),
            source_groups=tuple(case.source_hash for case in cases), evidence_targets=targets,
            evidence_supervision=supervised)

    def dataset(self, cases):
        return TokenDataset(self, tuple(cases))

    def save_local(self, folder):
        root = Path(folder)
        root.mkdir(parents=True, exist_ok=False)
        torch.save(self.values, root / "tokens.pt")
        state = dict(preprocess_sha256=self.preprocess_sha256, tokens=self.tokens, bindings=self.bindings,
            tensor_sha256={text: tensor_digest(value) for text, value in self.values.items()},
            file_sha256=file_digest(root / "tokens.pt"), observations=self.observations,
            encoder_load=self.encoder_load, feature_generation_load=self.feature_generation_load, **{name: getattr(self, name) for name in (
                "forward_batches", "encoded_sequences", "logical_text_uses", "cpu_ns", "wall_ns")})
        (root / "metadata.json").write_text(json.dumps(state, sort_keys=True))

    def restore_local(self, folder):
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        if self.values or self.bindings or self.tokens:
            raise ValueError("restore requires a fresh token bank")
        root = Path(folder)
        state = json.loads((root / "metadata.json").read_text())
        if (state["preprocess_sha256"] != self.preprocess_sha256
                or (root / "tokens.pt").stat().st_size > 2_000_000_000
                or file_digest(root / "tokens.pt") != state["file_sha256"]):
            raise ValueError("token cache file or preprocessing mismatch")
        values = torch.load(root / "tokens.pt", map_location="cpu", weights_only=True)
        if not isinstance(values, dict) or set(values) != set(state["tokens"]):
            raise ValueError("token cache keys mismatch")
        for text, value in values.items():
            if (tuple(state["tokens"][text]) != self._ids(text)
                    or not isinstance(value, torch.Tensor) or value.shape != (len(state["tokens"][text]), 384)
                    or value.dtype != torch.float32 or value.requires_grad or not torch.isfinite(value).all()
                    or tensor_digest(value) != state["tensor_sha256"][text]):
                raise ValueError("token cache tensor/content mismatch")
        for binding in state["bindings"].values():
            if (binding["preprocess_sha256"] != self.preprocess_sha256
                    or any(text not in values for text in (*binding["fact_texts"], binding["question"], binding["candidate"]))):
                raise ValueError("token cache binding mismatch")
        self.values, self.tokens, self.bindings = values, {k: tuple(v) for k, v in state["tokens"].items()}, state["bindings"]
        self.feature_generation_load = state.get("feature_generation_load", state["encoder_load"])
        self.observations = state["observations"]
        self.cache_restore = dict(cpu_ns=time.process_time_ns() - cpu,
                                  wall_ns=time.perf_counter_ns() - wall)
        for name in ("forward_batches", "encoded_sequences", "logical_text_uses", "cpu_ns", "wall_ns"):
            setattr(self, name, state[name])

    def report(self):
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        self.encoder.verify_files()
        verification = verify_loaded_safetensors(torch, self.encoder.model, self.encoder.root)
        result = dict(schema="hepta.reader.token-bank.v1", preprocess_sha256=self.preprocess_sha256,
            model_material=self.encoder.material, exact_tensor_verification=verification,
            encoder_load=self.encoder_load, feature_generation_load=self.feature_generation_load,
            cache_restore=self.cache_restore,
            distinct_public_texts=len(self.values),
            content_tokens=sum(value.shape[0] for value in self.values.values()),
            token_bytes=sum(value.numel() * value.element_size() for value in self.values.values()),
            feature_set_sha256=digest_json({k: tensor_digest(v) for k, v in self.values.items()}),
            observations=self.observations, scope=self.scope, generation=self.generation,
            representation_sufficiency_proven=False, **{name: getattr(self, name) for name in (
                "forward_batches", "encoded_sequences", "logical_text_uses", "cpu_ns", "wall_ns")})
        result["report_verification_cost"] = dict(cpu_ns=time.process_time_ns() - cpu,
                                                   wall_ns=time.perf_counter_ns() - wall)
        return result


class TokenDataset:
    """Source references with dynamic minibatch padding, avoiding full-data expansion."""

    def __init__(self, bank, cases):
        self.bank, self.cases = bank, cases
        self.targets = torch.tensor([case.label for case in cases])
        self.source_groups = tuple(case.source_hash for case in cases)

    def validate(self, input_dim=384):
        if input_dim != 384 or not self.cases or any(self.bank.bindings.get(c.case_id) != self.bank._binding(c) for c in self.cases):
            raise ValueError("registered nonempty 384-dimensional source dataset required")
        return self

    def take(self, indices):
        return self.bank.batch(self.cases[int(index)] for index in indices)

    def __len__(self):
        return len(self.cases)
