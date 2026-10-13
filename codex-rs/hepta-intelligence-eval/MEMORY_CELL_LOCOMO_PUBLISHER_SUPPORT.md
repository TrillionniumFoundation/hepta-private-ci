# LoCoMo frozen Qwen: publisher-support-only diagnostic

**Research-only, explicitly privileged label-conditioned evidence selection.**

The same Qwen2.5-3B frozen reader, tokenizer, 2,048 input/64 output tokens,
prompt construction, original source bytes and deterministic decoder are used
to diagnose original lexical k4/k8 failures. The baseline 32 original Qwen
answers are replayed unchanged from frozen generating source 96b5ec37,
not regenerated under a different model. The 16 previously exposed
evaluation questions span two conversation-family proxies.

**Privilege boundary:** a separate plan job opens publisher support-ID
annotations and writes *only original source IDs*. It does not export answer
text or semantics into the Reader plan. The Reader job gets neither targets
ZIP nor expected answers. This is NOT a fair retrieval strategy: choosing
source IDs from publisher annotations is a privileged causal intervention.
It cannot prove online superiority, human-certified sufficiency, independent
transfer or new-memory learning.

Every original question remains in the census. Unresolved, empty or too-large
support lists are unavailable, NOT relabelled unanswerable. Explicitly
unanswerable questions receive zero evidence, but the same frozen Reader
must still actually generate. Context overflow and model errors remain
failed outcomes with their original attempted denominators.

The separate scorer opens gold only after generation is committed. It verifies
the original untouched 32-response archive, Qwen model and Reader prompt profile,
all original selected/actually delivered source bytes, and exact publisher
support-ID reconstruction before computing the diagnostic token F1.
It stratifies by whether the frozen original k4 already included every
annotated source, and reports answerable versus unanswerable cases separately.
Unknown/missing cases widen all-planned bounds, which are NOT confidence
intervals. Publisher source IDs are NOT independent semantic entailment votes.

The bounded experiment is .github/workflows/hepta-memory-locomo-publisher-support.yml.
It never changes the default memory consumer or the production reader.
No model training, human review, citation 99% claim, prospective family,
N_eff >= 200, production cutover or production qualification follows.
