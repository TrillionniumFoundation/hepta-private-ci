# MemoryCell — cross-population frozen reader admission, 13 October 2026

**Disposition: NO-GO for parameter-memory training or production.** This model-free
reconciliation verifies already completed original Qwen2.5-3B reader executions
across two **different** populations and preserves incompatible metrics separately.
It does not create model answers, validate independent human semantics or claim
longitudinal future observations.

## Original, independent artifacts

| Research observation | Generating commit | Model artifact ZIP / SHA-256 | Independent scoring/replay ZIP / SHA-256 |
| --- | --- | --- | --- |
| 8 authored controlled event tests, 40 + 72 real calls | `6304b451268c73f3d1a605985226b102df841bbf` | Artifact `11743043427`, `7a99db30fb5b1202fcd43073d22589b84315046dd34044277cc46351f1cbece8` | Artifact `11748040166`, `2445895a7d51e3173837471aa462cebede29eb3ec89653af3bd17e73b6114071` |
| 16 published LoCoMo evaluation questions, 32 real calls | `96b5ec37b82f87d445740403e07e3705e9850955` | Artifact `11763718022`, `7160ede72114b04135e544fb687a804dc0c4852834cf1695440a75b85214bf48` | Artifact `11766482516`, `5c36103c506367de2ba42ea242bc81b53ad9734f1417132ce2945d0473ed391e` |

LoCoMo additionally binds original **source** ZIP `11728164433` (SHA-256
`51e18514c68f31220f4dcd072914f6e015aa9733b6c5b4a4d4e3b14dac25ec37`),
source-only **retrieval** ZIP `11729394703` (`3fb1c3272314d31b42ece1c74aa0250e2ecb06c6060cb011071d4654fef6f097`),
and separately protected **targets** ZIP `11728856834`
(`d09823324003ab431301e60fbbb280e216ca03b686e178d4f36fb6d492981978`).
The complete original source and score ZIP contents and manifests were verified;
all model-generated answers were left unchanged. The reader model-inventory
SHA is identical between the two runs:
`f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225`.
The prompt/view **profiles and task scoring grammars are not identical**.

## Causal reading of the completed evidence

| Controlled event task, same Qwen | Strict correct / 8 | Correct + complete public event citation path / 8 | Prompt tokens |
| --- | ---: | ---: | ---: |
| Frozen top-k selected on calibration (`k=1`) | 5 | 3 | 3,961 |
| Fixed hybrid `k=4` | 3 | 1 | 10,806 |
| Actual single hop | 4 | 4 | 4,575 |
| Complete entity/time path | **8** | **4** | 5,752 |
| Correction-aware organizer | **8** | **4** | 5,179 |

The additional relation path yields 4/8 net correct relative to single hop on
this authored population, while the organizer yields **zero** additional correct
or complete-citation-chain outcomes relative to the full-path filter. It saves
573 input tokens across the eight reads, excluding ingestion and lifecycle costs.
Calibration selected `k=1` but leave-one-question-out choices were not all
identical; do not extrapolate the policy from eight previously published cases.

| LoCoMo 16 questions, two source-family proxies | BM25 lexical k4 | BM25 lexical k8 |
| --- | ---: | ---: |
| Mean diagnostic answer **token-F1** | **0.172082581** | 0.111481901 |
| Original model-generated answers | 16 | 16 |
| Prompt tokens | 6,254 | 10,473 |
| Independent human-certified sufficient contexts | 0 | 0 |

The 16 paired F1 comparisons are 3 k8 wins, 7 losses and 6 ties. This is a
published development slice (two source-family proxies, 5,882 original history
documents), not an authenticated prospective new-family test. The retrieval
supports are **publisher annotated source IDs**, not independently certified
sufficient evidence. Strict event task accuracy and normalized LoCoMo token-F1
must **never be averaged or pooled**. Their prompts are also distinct; same
model weights do not imply an identical reader task protocol.

## Executable refusal, next experimental gate

`reader_cross_population_gate.py` verifies each of the seven entire original
ZIPs against externally registered SHA-256 pins, all available inner manifests,
40+72 and 16x2 original output censuses, exact source/model identity,
no-generation-time target reading, no weight updates, frozen policy instability,
independent event replay and LoCoMo hosted-scoring lineage. It compares original
vs scored-answer immutability, source-path citation counts and measured prompt
tokens. It emits **only** aggregated numbers and fixed source hashes; it never
copies publisher reference answers or model-generated answer text.

The companion `test_reader_cross_population_gate.py` includes fail-closed
manifests, malformed JSON, missing/duplicate/failed reader calls, model identity
mixing and non-comparable metric tests. `hepta-memory-cross-population-gate.yml`
re-runs a pinned model-free verifier and emits an artifact, without loading
Qwen weights or touching production control surfaces.

The **next warranted actual inference** is the same frozen reader on a
privileged **publisher-support-only** LoCoMo intervention against unchanged
lexical k4/k8 controls. The publisher-provided support is a diagnostic ceiling,
not a verified minimal-sufficient oracle; genuine human source-sufficiency
judgments and disjoint newly admitted histories must follow. The separate
LoCoMo publisher-reader CI already exists; this gate does **not** counterfeit
its pending outputs or use them in these historical results.

**No-go remains mandatory:** `parametric_memory_training_qualified=false`,
`production_accepted=false`, independent semantic citation precision remains
unknown, and deployed retention/revocation/recovery costs are not zero merely
because they have not been observed.
