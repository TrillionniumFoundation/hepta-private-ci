# Original archived pretrained BF16 tensors: real numeric forward, no claims

**2026-10-15. Research only / DENY_ALL.** This read-only study advances from
synthetic Head experiments to **actual original pretrained model tensors**. It
never substitutes for matched natural-language Reader runs, official Hugging
Face model/tokenizer parity, an independently signed source/reviewer, or a
production memory claim.

Archive: existing GitHub Actions artifact `11586991191`, original ZIP SHA256
`07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af`
(376,363,859 bytes). This ZIP includes the original LoCoMo dataset, frozen
MiniLM Encoder and a 30-layer Llama-family Reader. Selective safe stream
extraction retains only the two pretrained weights and corresponding configs;
no learned Head, answer, prompt, future score, or provenance assertion is
reconstructed from archive metadata.

- Original MiniLM BERT weights `53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db`, 90,868,376 bytes.
- Original Llama Reader weights `5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`, 269,060,552 bytes.
- Execute original BF16 matrices through FP32 PyTorch numerical implementations
  on fixed **numeric** token IDs, retaining numeric SHA256 of BERT CLS/pooler
  and Reader final hidden/logits, measured wall/RSS, exact input IDs and the
  original weight/source digests. The Llama route exercises GQA, RoPE, 30
  RMSNorm/attention/MLP layers and tied output embeddings; the BERT route
  exercises six full self-attention/FFN layers.
- An independently started second operating-system process must reproduce the
  first process's full numeric output digests on the same pinned weights.
  This is only implementation-level self-consistency, **not** HF parity.

`amcn_original_numeric_probe.py` implements the original tensor forward. The
separate `test_amcn_original_numeric_probe.py` refuses to count physical model
runs if the original files are absent. The new source-pinned read-only Action
`hepta-amcn-original-numeric-probe.yml` downloads only the frozen archive ZIP
by its precommitted SHA, safely extracts enumerated weight/config files,
executes the two real forward processes and records an unsigned numeric
receipt, environment, exact source SHA, self-repeatability and explicit denial.
**The artifact never uploads pretrained weights, raw benchmark data, or labels.**

## Actual sandbox execution, separate from authoritative dot host

On 2026-10-15 an isolated analysis container (not the user's dot host)
physically reloaded the exact archived weights and ran independent CPU
PyTorch 2.10.0 processes twice. Both runs yielded identical digests:

- MiniLM CLS: `8bf8f3919fa6bf315043cca6473f133e98879efd14d4b7a1d54dc8c5ccd3ca78`
- MiniLM pooler: `05e1a97b267a136d176a1503222666d70b5ddf20ee1fcf00ceeec8229aca23d3`
- Llama final hidden: `f4c888f54305f07086819670c046e791e0e7bc5c8fb3b43aed5906d1b7a22055`
- Llama logits: `0e213cba29020f3140dee7e72d5b8737ebcb2ce0e0189e5662b8415a09f71776`
- Llama top-5 numeric token IDs: `[122, 123, 237, 113, 133]`.

The first-process peak RSS was 655,192,064 bytes. First-process observed
per-call forward durations were ~0.09s MiniLM and ~0.52s Reader on this host,
**not** target-host latency or whole-task processing time. Hardware, dtype,
Torch version, optimization and tokenizer differences can change these values.

**Limitations:** no official Transformers forward parity; no verified natural
language tokenization; no original full Reader answer; no original strong hybrid
RAG trial; no source-family true future windows; no independent task/semantic
citation adjudication; no memory model selection/unlearning or production
promotion. The qualified interpretation is only: original archived model
weights are present, loadable and numerically executable under an explicit
research-only PyTorch implementation.
