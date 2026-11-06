# Frozen reader — answer-space capacity diagnosis (2026-10-15)

Generation source: `cc05b9572eba0e57938341be733cef8dbbec0777`.
This is eight **previously exposed authored development cases**, not an
independent reader or semantic-memory benchmark.

- Original SmolLM2-135M pretrained weights, frozen.
- Six existing evidence arms, unchanged original prompts, 2048-token limit.
- Candidate identifiers collected from the **entire original question scope**,
  before label access; exactly the same 3–4 options across all evidence arms.
- Score each option through the model's **actual conditional token log probability**.
  Primary rule registered before generation: highest mean token log probability.
- First fsync all 48 responses and 156 candidate evaluations, then open answer labels.
- Full raw journal SHA-256: `15051eddc59a3bcd99c29b6065fea7ade4271f62b1484aae0a07752150a09d06`.
  Local full raw journal is 66,462 bytes; XZ is 6,304 bytes (SHA-256
  `2ee30312b1d49e8aa64374d083bcedce6a43e76aa84c113d7b2388108ddf6683`).
- Replayed all original prompts, candidate token IDs, score normalization and winners
  with an independent **read-only process**, zero model calls. Tampered scores rejected.
- Real original-weight numeric tests and source/negative regression tests: 14/14
  passed locally. This is **not** exact-head green CI.

| Evidence | Strict original text-generation success | Oracle-assisted candidate-choice top-1 |
|---|---:|---:|
| No evidence | 0/8 | 0/8 |
| Hybrid | 0/8 | 5/8 |
| Entity/time | 0/8 | 8/8 |
| Organized | 0/8 | 8/8 |
| Authored program support | 0/8 | 8/8 |
| Missing prerequisite | 0/8 | 4/8 |

**Interpretation:** the frozen reader can conditionally distinguish answer options
under this **supplied answer-space oracle**. It cannot reliably generate valid
answers/citations for these tasks. The missing-premise arm still getting 4/8
shows prior and answer-space leakage: this is NOT proof that the missing premise
is unnecessary. Treat 8/8 as an upper-bound diagnostic, not strong-RAG task
success, live program execution, a learned parameter-memory benefit, or production
admission.

**Next necessary test:** derive the candidate set from *only delivered permitted*
evidence, add a strict independent abstention arm, and measure real project
execution outcomes with the SAME tools available to a strong RAG baseline.
Independent source families, future-window evidence, lifecycle/revocation cost,
and human semantic/citation verification remain missing.
