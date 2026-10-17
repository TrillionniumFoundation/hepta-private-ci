# LoCoMo neighbor retrieval: actual frozen Qwen answer effect

**Development-only; no memory-learning or serving-promotion claim.**

The exposed 16 evaluation questions span two published family proxies. The existing
label-blind neighboring-turn retriever improved *publisher document-ID coverage*
from **9/13** (frozen lexical k8) to **10/13**, using **16,007** versus
**17,085** original source UTF-8 bytes. This is NOT final answer correctness,
independent source sufficiency, or a parameter-memory gain.

This continuation freezes the original retrieval algorithm, Qwen2.5-3B BF16
reference reader, tokenizer, prompts, 2,048-input/64-output budget, deterministic
decoder, original source visibility, and all query identities. A source-only
stage persists the complete 80-question × two-arm decision journal before any
publisher target ZIP is staged. The new model stage receives only those original
public sources and this source-only selection. It makes 16 actual model calls.

The separate scorer verifies the new SHA-bound complete answer journal,
source bytes, Qwen identity/profile, prompt budget and frozen selections BEFORE
opening publisher targets. It independently verifies the original 32 Qwen
outputs from run 38280267308 and its hosted original score, without regenerating
or editing them. Paired quality is computed on actual answers separately for
answerable and unanswerable questions. The original exact-refusal scoring remains
unchanged. Failures are not filtered; missing-outcome effect bounds are NOT
statistical confidence intervals.

| Input role | GitHub artifact | Exact ZIP SHA-256 |
| --- | ---: | --- |
| Original public source | 11728164433 | 51e18514c68f31220f4dcd072914f6e015aa9733b6c5b4a4d4e3b14dac25ec37 |
| Original frozen decisions | 11729394703 | 3fb1c3272314d31b42ece1c74aa0250e2ecb06c6060cb011071d4654fef6f097 |
| Original 32 Qwen responses | 11763718022 | 7160ede72114b04135e544fb687a804dc0c4852834cf1695440a75b85214bf48 |
| Original hosted score | 11766482516 | 5c36103c506367de2ba42ea242bc81b53ad9734f1417132ce2945d0473ed391e |
| Original targets, offline scorer only | 11728856834 | d09823324003ab431301e60fbbb280e216ca03b686e178d4f36fb6d492981978 |

Code: scripts/memory_cell/locomo_neighbor_reader_pair.py
Workflow: .github/workflows/hepta-memory-locomo-neighbor-reader.yml

If the frozen reader does not improve actual answer quality under its matched
retrieval controls, reject the neighbor packing improvement as a Reader-quality
candidate even if publisher-ID coverage rises. If it does improve the answer
metric, credit nonparametric evidence selection, NOT adapter learning.
Publisher IDs are weak document-level labels, not independently reviewed
sufficient evidence. Citation entailment precision remains undefined/null.
The previous public test cases have been exposed. No N_eff>=200, human reviewer,
independent future window, production cost/recovery, or deployment admission
follows; production_accepted remains false.
