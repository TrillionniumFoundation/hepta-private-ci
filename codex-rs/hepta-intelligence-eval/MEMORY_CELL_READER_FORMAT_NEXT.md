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
