# Frozen Reader answer/refusal format diagnosis (development only)

This is NOT a learned Cell, new source family, independently reviewed sufficient
evidence or a production rollout. It compares a pinned **historical** frozen
Qwen2.5-3B LoCoMo publisher-support baseline (16 real generations at original
commit 2db775a9) with a **new** frozen model call using the same 16 question
identities and the same ordered, privileged publisher-annotated support IDs.
Publisher support selection uses benchmark support annotations and cannot be
used as ordinary online retrieval.

## One intervention, not a memory improvement

The only intentional intervention is a revised **system instruction**:
make a single direct answer with genuinely delivered E-labels, or emit the
exact refusal with no other text. User payload JSON (question, question time,
the original source bytes, source observation times, source order and labels),
Qwen model revision/inventory, tokenizer, max input 2048 and deterministic
64-token decoding remain fixed. The actual prompt token count is recorded;
a longer revised instruction is an input-cost change and is not free. No
LoRA adapter, learned selector or extra evidence is introduced. The historical
baseline is not re-generated in the same run: any observed differences are a
cross-run prompt intervention rather than a paired simultaneous experiment.

The reader job reads the original PUBLIC source/decision ZIPs and the pinned
**ID-only** privileged support plan; it has no access to publisher answer text.
Original answers, failures and signed-by-nobody receipts are journaled, fsynced
and hashed before the separate scoring job opens original reference answers.
The scorer rechecks original plan, model lineage, new original source excerpts,
reader profile, complete 16-row census, original historical ZIP digest and
required success/failure denominator. It separately reports answerable QA,
unanswerable exact refusal, mixed refusal text, structurally undelivered
citation labels, per-call input-token differences and total paired token-F1.
Unknown outcomes widen the all-planned result bounds.

**A supported citation label only establishes structural binding to an actual
delivered source**, never semantic entailment. An exact refusal is a response
format measurement, not an independent judgement of sufficiency. This cohort
contains only two previously exposed public conversation-family proxies; no
independent statistical superiority, 99% citation accuracy, new future window,
old-task retention, learning benefit or production qualification is claimed.

Workflow: .github/workflows/hepta-memory-locomo-publisher-format.yml
Code: scripts/memory_cell/locomo_publisher_format_trial.py
Tests: scripts/memory_cell/test_locomo_publisher_format_trial.py

The reader run may require a pinned BF16-compatible CPU runner. Missing
hardware, dependencies, answer journals, bound original evidence, or publisher
labels are explicit failures, not silently skipped or scored as successes.

## Oct 13 completed Reader original-answer audit — format regression, no-gold decision

On [Actions #38370785532](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38370785532), the first `reader` job rejected an actual Intel Xeon runner with no proven accelerated BF16. A targeted rerun of **that failed job only** retained exact generating source `c34e73312e9ef1626712f984d4c70c50af335aef`, and passed on an actual AMD EPYC 9V45 runner advertising `avx512_bf16`. The protocol and reader jobs passed. This audit reports the **original reader outputs only**; the separately protected `score` job may be pending and its answer-reference metrics must not be guessed.

- New original 16-answer ZIP artifact `11801623797`: outer SHA-256 `25e7fc3d60e53328a49efabcd34df4a6e223a43e16cc2aff1790824a31150b74`.
- Prior original 16-answer publisher-support ZIP artifact `11792880133`: outer SHA-256 `14dc63bfb0e25b8b15f7b48ba8e1afd4cef4d13f8617d08d28a533baa7a202a0`.
- Both original artifact manifests fully checked, **11/11** internal members each, including the original raw-answer journal and reader inventory. All **16/16 paired question IDs** retain the same ordered original source IDs and delivered source excerpts, reader identity and benchmark family proxy.
- 14 original answers changed; no answer was postprocessed. Original exact standalone refusal **1/16** versus strict-format prompt **0/16**. Mixed refusal plus other text increased from **5/16** to **10/16**. Properly delivered citation labels appeared in **14/16** original versus **16/16** strict-format responses; neither condition emitted an undelivered marker.
- Full prompt input token total increased from **3,427** to **3,987** (+560, +16.34%). Generated tokens decreased from **675** to **256**. Recorded Reader-only time decreased from about 201.5s to 108.1s, but those per-job CPU measurements do not establish a production latency/price improvement.

The machine-readable no-gold result is [`locomo-publisher-strict-format-raw-20261013.json`](../../scripts/memory_cell/data/locomo-publisher-strict-format-raw-20261013.json). This intervention **fails the exact-refusal and mixed-refusal format checks**, despite emitting delivered citations more frequently. Do not promote it from shorter answers or label-count alone. Wait for the protected, original-answer-aligned separate score to measure F1; do not open targets in model generation or in this raw-only audit.

The source sets are annotation-privileged and from just two exposed LoCoMo conversation-family proxies. This provides no learned/parametric Cell advantage, no human entailment precision and no production qualification. Keep `production_accepted=false` and require true independent disjoint-family review before further training.
