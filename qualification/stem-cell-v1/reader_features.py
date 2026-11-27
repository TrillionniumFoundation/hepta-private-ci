"""Batched frozen sentence features with complete public-evidence bindings.

Sentence pooling is an explicit new representation candidate, not a proof of
sufficiency. Each original fact is preserved as one or more bounded chunks;
question/candidate text is encoded separately and no evaluation label is read.
"""
import hashlib
import json
from pathlib import Path
import time

import torch

from execution_meter import TRANSFORMER_POLICY_SCHEMA, WorkLedger
from group_encoder import digest_json
from hf_encoder_kernel import verify_loaded_safetensors
from paired_execution import PHASES
from transformer_work import PROFILE


def tensor_digest(value):
    value = value.detach().cpu().contiguous()
    return hashlib.sha256(value.numpy().tobytes()).hexdigest()


class SentenceBank:
    """One frozen Encoder and deduplicated, scoped pooled evidence records."""

    def __init__(self, encoder, *, batch_size=16, chunk_tokens=96, scope="reader-v3", generation=0):
        if not 1 <= batch_size <= 64 or not 8 <= chunk_tokens <= encoder.max_tokens:
            raise ValueError("bounded batch and complete text chunks required")
        self.encoder, self.batch_size, self.chunk_tokens = encoder, batch_size, chunk_tokens
        self.scope, self.generation = scope, generation
        self.vectors, self.bindings = {}, {}
        self.forward_batches, self.encoded_sequences, self.logical_text_uses = 0, 0, 0
        self.cpu_ns, self.wall_ns, self.observations = 0, 0, []
        self.preprocess_sha256 = digest_json(dict(
            schema="hepta.reader.sentence-pooling.v1", pooling="masked-mean-last-hidden-state",
            base=encoder.preprocess_digest, word_chunk_tokens=chunk_tokens,
            scope=scope, generation=generation, query="Question: {question} Candidate answer: {candidate}"))

    def chunks(self, text):
        """Split only at whitespace, preserving every word and its original order."""
        words = text.split()
        if not words:
            raise ValueError("empty public text")
        result, current = [], []
        for word in words:
            proposed = " ".join([*current, word])
            count = len(self.encoder.tokenizer(proposed, truncation=False)["input_ids"])
            if count > self.chunk_tokens:
                if not current:
                    raise ValueError("one public word exceeds registered token chunk bound")
                result.append(" ".join(current))
                current = [word]
                if len(self.encoder.tokenizer(word, truncation=False)["input_ids"]) > self.chunk_tokens:
                    raise ValueError("one public word exceeds registered token chunk bound")
            else:
                current.append(word)
        if current:
            result.append(" ".join(current))
        if " ".join(result).split() != words:
            raise ValueError("chunking lost public evidence")
        return tuple(result)

    @staticmethod
    def query_text(case):
        return f"Question: {case.question} Candidate answer: {case.candidate}"

    def register(self, cases):
        """Encode all missing public strings; callers own train/final chronology."""
        start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
        texts = set()
        for case in cases:
            chunks = tuple(chunk for fact in case.facts for chunk in self.chunks(fact))
            if not 1 <= len(chunks) <= 128:
                raise ValueError("complete paragraph exceeds registered 128 fact chunks")
            query = self.query_text(case)
            if len(self.encoder.tokenizer(query, truncation=False)["input_ids"]) > self.encoder.max_tokens:
                raise ValueError("complete question/candidate exceeds token bound")
            binding = dict(source_sha256=case.source_hash, fact_texts=chunks, query_text=query,
                           preprocess_sha256=self.preprocess_sha256)
            if case.case_id in self.bindings and self.bindings[case.case_id] != binding:
                raise ValueError("case identity changed public input")
            self.bindings[case.case_id] = binding
            self.logical_text_uses += len(chunks) + 1
            texts.update((*chunks, query))
        missing = sorted(texts.difference(self.vectors),
                         key=lambda s: (len(self.encoder.tokenizer(s)["input_ids"]), s))
        policy = dict(schema=TRANSFORMER_POLICY_SCHEMA, arithmetic_profile=PROFILE, mode="observe",
                      wall_time_ns=3_600_000_000_000, max_process_rss_bytes=None,
                      rapl_zone=None, rapl_max_power_watts=None)
        meter = WorkLedger(policy, dict.fromkeys(PHASES, 10**18))
        for offset in range(0, len(missing), self.batch_size):
            batch = missing[offset:offset + self.batch_size]
            tokens = self.encoder.tokenizer(batch, return_tensors="pt", padding=True, truncation=False)
            if tokens["input_ids"].shape[1] > self.encoder.max_tokens:
                raise ValueError("batch encoder would truncate public evidence")
            with meter.scope("inference", "encoder"), torch.no_grad():
                features = self.encoder.model(**tokens).last_hidden_state
                weights = tokens["attention_mask"].to(features.dtype).unsqueeze(-1)
                pooled = (features * weights).sum(1) / weights.sum(1)
            if pooled.shape != (len(batch), 384) or not torch.isfinite(pooled).all():
                raise ValueError("invalid frozen feature geometry")
            for text, vector in zip(batch, pooled):
                self.vectors[text] = vector.detach().clone()
            self.forward_batches += 1
            self.encoded_sequences += len(batch)
        self.observations.append(meter.report())
        self.cpu_ns += time.process_time_ns() - start_cpu
        self.wall_ns += time.perf_counter_ns() - start_wall

    def public(self, case, *, deleted=False, permuted=False):
        """Strict public-only loop input; target/annotation never enters this dict."""
        binding = self.bindings[case.case_id]
        texts = binding["fact_texts"]
        if permuted:
            texts = tuple(reversed(texts))
        facts = torch.stack([self.vectors[text] for text in texts]).unsqueeze(0)
        mask = torch.ones((1, len(texts)), dtype=torch.bool)
        if deleted:
            mask.zero_()
            facts.zero_()
        query = self.vectors[binding["query_text"]].unsqueeze(0).clone()
        identity = dict(binding, fact_texts=texts, deleted=deleted,
                        facts_sha256=tensor_digest(facts), query_sha256=tensor_digest(query),
                        mask_sha256=tensor_digest(mask))
        return dict(facts=facts, query=query, mask=mask, feature_sha256=digest_json(identity),
                    source_sha256=case.source_hash)

    def batch(self, cases):
        from group_reader_training import ReaderBatch
        records = [self.public(case) for case in cases]
        count = max(row["facts"].shape[1] for row in records)
        facts = torch.zeros((len(cases), count, 384), dtype=torch.float32)
        mask = torch.zeros((len(cases), count), dtype=torch.bool)
        for i, row in enumerate(records):
            n = row["facts"].shape[1]
            facts[i, :n], mask[i, :n] = row["facts"][0], row["mask"][0]
        return ReaderBatch(facts=facts, query=torch.cat([row["query"] for row in records]),
                           mask=mask, targets=torch.tensor([case.label for case in cases]),
                           source_groups=tuple(case.source_hash for case in cases))

    def save_local(self, folder):
        """Local intermediate cache; never uploaded as research evidence."""
        root = Path(folder)
        root.mkdir(parents=True, exist_ok=False)
        keys = sorted(self.vectors)
        values = torch.stack([self.vectors[key] for key in keys])
        torch.save(values, root / "vectors.pt")
        state = dict(preprocess_sha256=self.preprocess_sha256, keys=keys, bindings=self.bindings,
                     vectors_sha256=tensor_digest(values), forward_batches=self.forward_batches,
                     encoded_sequences=self.encoded_sequences, logical_text_uses=self.logical_text_uses,
                     cpu_ns=self.cpu_ns, wall_ns=self.wall_ns, observations=self.observations)
        (root / "metadata.json").write_text(json.dumps(state, sort_keys=True))

    def restore_local(self, folder):
        """Restore only our detached tensor cache, validating public bindings."""
        if self.vectors or self.bindings:
            raise ValueError("cache restore requires a fresh bank")
        root = Path(folder)
        state = json.loads((root / "metadata.json").read_text())
        values = torch.load(root / "vectors.pt", map_location="cpu", weights_only=True)
        if (state["preprocess_sha256"] != self.preprocess_sha256
                or not isinstance(values, torch.Tensor) or values.shape != (len(state["keys"]), 384)
                or values.dtype != torch.float32 or not torch.isfinite(values).all()
                or tensor_digest(values) != state["vectors_sha256"]
                or len(set(state["keys"])) != len(state["keys"])):
            raise ValueError("local cache material or tensor binding mismatch")
        self.vectors = {key: value.clone() for key, value in zip(state["keys"], values)}
        self.bindings = {key: dict(value, fact_texts=tuple(value["fact_texts"]))
                         for key, value in state["bindings"].items()}
        if any(binding["preprocess_sha256"] != self.preprocess_sha256
               or binding["query_text"] not in self.vectors
               or any(text not in self.vectors for text in binding["fact_texts"])
               for binding in self.bindings.values()):
            raise ValueError("local cache references missing public features")
        for name in ("forward_batches", "encoded_sequences", "logical_text_uses", "cpu_ns", "wall_ns"):
            setattr(self, name, state[name])
        self.observations = state["observations"]

    def report(self):
        self.encoder.verify_files()
        verification = verify_loaded_safetensors(torch, self.encoder.model, self.encoder.root)
        return dict(schema="hepta.reader.feature-bank.v1", preprocess_sha256=self.preprocess_sha256,
                    model_material=self.encoder.material, exact_tensor_verification=verification,
                    forward_batches=self.forward_batches, encoded_sequences=self.encoded_sequences,
                    logical_text_uses=self.logical_text_uses, distinct_public_texts=len(self.vectors),
                    vector_bytes=sum(v.numel() * v.element_size() for v in self.vectors.values()),
                    cpu_ns=self.cpu_ns, wall_ns=self.wall_ns, observations=self.observations,
                    scope=self.scope, generation=self.generation,
                    feature_set_sha256=digest_json({k: tensor_digest(v) for k, v in self.vectors.items()}),
                    representation_sufficiency_proven=False)
