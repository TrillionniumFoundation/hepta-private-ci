# Qwen Reader equal-token label placebo: post-seal no-go

Research-only extension of [PR #1546](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1546). This audit **does not call any model, alter archived answers, train an Encoder or Cell, or authorize production**.

## Immutable generating evidence

Original [GitHub Actions run 38492538390](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38492538390) completed successfully. Artifact 11862571176 is pinned by externally reported ZIP SHA256 `90094839a30638f8d47b9047520c455af1a41974e61f3bfbde64b02a10a74802`, generating source `10fce5ee7f8f1fc97b59fc17ad719b1a888c2c1b` and tree `fa68a95bfbcbfcad3e6c1656cea9215c3153a7e5`. The replay independently checks **21 internal SHA256 entries**, an immutable **200-row** raw-answer seal `578098efc9e0dad7ee387538fd07eb10a9ce6e3de0f1492723dfe9f6dbd601a5`, the **200-row input preflight seal** `6ae1cb8cbfd78700ebb86eed4646925984280e93a5c0606fea1dce261fe567a9`, and every start record. It checks input IDs, source bytes/digests, original source-order permutations, one frozen Qwen identity, output costs and regenerated exact scores against the producer's published score table. It fails on duplicate/extra/missing rows and mismatched provenance.

## Actual outcomes — 20 correlated synthetic questions per condition

| Condition | E1/E2 labels | Same-token-count neutral alias | No labels |
|---|---:|---:|---:|
| Target fact first: exact TAG | 2/20 | 1/20 | **19/20** |
| Target fact last: exact TAG | 0/20 | 0/20 | **19/20** |
| Only irrelevant TAG fact: correct refusals | 0/20 | 0/20 | **0/20** |
| Only irrelevant TAG fact: unsupported TAG copies | 20/20 | 20/20 | **20/20** |
| No evidence: correct refusals | — | — | **20/20** |

The E-label and neutral alias prompts are matched on **input-token count for every paired question**. Their answer extraction remains poor. Removing the metadata fields restores literal extraction in 38 of 40 sufficient-source cases, but shortens the two-source prompt by 10 input tokens per question and changes decoder work; it is **not a compute-matched or isolated label-semantics causal conclusion**. All three insufficient-source decoy-only views copy an unsupported TAG in 20/20 cases. Successful zero-evidence refusal therefore does **not** establish actual evidence-sufficiency judgment. The declared `no_safe_reader_adequacy_gain` conclusion is retained.

This replay derives the expected target from the source-bound relation, not from a separate unverified answer-label table. The closed-grammar source itself makes a deterministic symbolic parser possible; **no Reader superiority over that parser** follows. Neither citation semantics nor natural-language transfer is human-reviewed. Repetitions and arms are not independent subjects; there are only 20 fixed synthetic tasks.

## Exact local tests and hosted gates

`system2_equal_token_postseal_audit.py` is standard-library-only. `test_system2_equal_token_postseal_audit.py` includes tampered ZIP/member tests; rehashed original-answer, producer-score, model-identity and token-accounting attacks must fail closed. With `HEPTA_QWEN_EQUAL_TOKEN_ARCHIVE` set to the exact original ZIP, **13/13 local tests passed**, with no new model calls. The targeted GitHub workflow re-downloads the original artifact, verifies its external SHA, runs the tests and scoped Ruff lint/format checks, stores immutable source/receipt hashes, and does **not** bypass the inherited full Cell matrix or the separate repository `blocking-ci`.

To reproduce on an exact source checkout:

```bash
export HEPTA_QWEN_EQUAL_TOKEN_ARCHIVE=/path/to/original-11862571176.zip
PYTHONPATH=scripts/memory_cell python -m unittest -v test_system2_equal_token_postseal_audit
python scripts/memory_cell/system2_equal_token_postseal_audit.py \
  "$HEPTA_QWEN_EQUAL_TOKEN_ARCHIVE" /new/read-only-summary.json
```

**Go/no-go:** insufficient-evidence TAG copying remains unmitigated; independent original-source reviews and strong Reader adequacy are required before NDU/FBSDE claims, semantic citation acceptance or deployment. `production_accepted=false`.
