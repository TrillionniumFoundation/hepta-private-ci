# Counterfactual Reader: isolate token-ceiling truncation from answer competence

Research branch in PR #1546. No production usage, no Encoder, learned Cell, NDU,
Riccati or FBSDE interface change. This is **not** a stronger model and does
not use the historical outputs as few-shot prompts.

## Verified source before intervention

Hosted run [38234318024](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38234318024)
completed **160/160** frozen Reader calls without execution failures. Artifact
`11744278119`, externally checked ZIP SHA256
`9ee9e63a725b3a5598ba6e89d728d6b17582d60853ee994151c1b58a15bf4a95`,
generating source `f3609d11cbe715c0202cb09e1463fa4ad002bd3d`, tree
`4846438b33ccf78ef715011f9c181488848f850b`; the original answer seal is
`cf3c06d54d86d6a9ea44e08a86083cd583fb319774468e6ad1acae7c57d4ec40`.
All 21 internal source and data entries pass the parent manifest check.

These 160 Reader outputs represent only **32 distinct synthetic question variants**
from 16 related causal pairs. There were **zero** strict grounded answer+
complete-citation successes and **zero** exact refusals in all five evidence
conditions. There were **99/160** responses at the 64-token output ceiling.
For the three arms chosen for this length experiment, 49 of 96 historical
responses reached 64 tokens: joined path 11/32, reverse-joined 16/32, missing
first relationship 22/32. The previously observed 64-token cap makes
truncation a plausible confound, NOT a confirmed explanation for the failure.

## Fixed experiment: only decoder ceiling changes

Keep the exact earlier 32 questions, same source documents, source chronology,
original `EvidenceBundle` mode, identical frozen Reader weights, tokenizer,
64-token system prompt, original 1024-input-token limit and greedy
`do_sample=False`, `num_beams=1` settings. Use only three frozen arms:

* `joined_top3`: fully sufficient 2-/3-hop evidence;
* `reversed_join_top3`: same sufficient evidence in reverse order;
* `missing_start_top3`: insufficient evidence with a tempting target string.

The original **96** 64-token responses for these three conditions are not
rerun. Produce exactly **96 new responses** with **max_new_tokens=128**.
The Reader identity, prompt input token IDs, source-validated bundled evidence,
question digest and delivered source fragments must match the archived 64-token
receipts byte-for-byte. The new generation profile records its different
maximum length; no trained parameter may change. If the old 64-token run
reached the cap, the first 64 **generated token IDs** in the new response must
have the original SHA256 digest. If it stopped early at EOS, all token IDs and
the raw answer must remain identical. Any divergence fails the trial rather
than being counted as a model improvement.

The historical parent ZIP, raw outputs, internal file hashes, complete 160-row
census and original programmatic scoring are independently verified **before
loading the Reader**. Each new result is journaled; the entire new raw output
is sealed before looking at synthetic target answers. Failures remain unknown,
not free or negative labels. Score separately: original and extended exact
Token, citation completeness, strict answer utility, incorrect target copying,
correct abstention and cap incidence. No semantic-human label is inferred.

**This comparison deliberately permits more model inference.** It is NOT equal
CPU, FLOPs, token budget or wall time, and the extra 128-token output must be
charged. A new citation appearing after token 64 may identify a truncation
problem; a missing or wrong answer after 128 would instead support a Reader
adequacy/format issue. Syntactic citations alone do not certify semantic support.

## Verification status

Local source-slice: 12/12 dedicated tests passed, including original 21-member
archive verification, all 160 original responses and original post-seal scores,
the complete 96-position control run with fake decoding, forced prefix/early-EOS
mismatches, tampered ZIP failure and incomplete-work journaling. No new
pretrained Reader call was performed locally. Hosted PyTorch 2.5.1, complete
MemoryCell regression, Ruff and actual 96 new Reader calls are separate gates.

To reproduce from the exact research checkout with the historical archive and
pinned Reader directory:

```sh
export HEPTA_MEMORY_TESTED_COMMIT="$(git rev-parse HEAD)"
export HEPTA_SYSTEM2_DECODE_PARENT=/tmp/parent-counterfactual.zip
python scripts/memory_cell/system2_reader_decode_ceiling.py \
  "$HEPTA_SYSTEM2_DECODE_PARENT" /tmp/memory-inputs/reader \
  /tmp/reader-decode-ceiling --development
```

The previously completed older Reader tests and the strongly negative 64-token
baseline remain unchanged. Passing this study is **not** NDU/FBSDE reasoning
emergence, language generalization, independent reviewer sufficiency, or
production admission.
