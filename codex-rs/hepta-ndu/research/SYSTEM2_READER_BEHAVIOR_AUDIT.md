# Historical Reader obligation audit: citation and no-evidence refusal

Research-only, read-only inspection of **genuine completed frozen-Reader answers**.
It is intentionally separate from queued synthetic multi-hop/counterfactual
workflows. No model inference, new Reader weights, trained Cell, policy change,
production release or rewritten historical answer is involved.

## Immutable source

- Hosted historical job: [GitHub Actions run 38189628380](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38189628380).
- GitHub artifact: `11721757214`, ZIP SHA256 `53dff155f79d4b333ba30060022cc38d351807993f09812ee94e0d8f5f24aee3`.
- Generating commit: `920aede3ccc4c39ced56c90c6c6936a7245c533c`, tree `a58aaff0da1cc548f9fff1d7788b7028a8537585`.
- Exact original answer seal: `065b365b78b3ce91210dbdd25d825ccd0559e27060de1ddb0bf45890181b96e8`.
- Pinned frozen Reader inventory: `afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c`.

`system2_reader_behavior_audit.py` relies on the repository's bounded
`system2_native_receipt.verified_archive` to reject archive/hash/member/manifest
drift. It independently verifies the full 48 questions by eight arms and the
original scored/raw row identity; it maps all 384 original `reader-inputs.jsonl`
entries to answers via original source-byte spans, scope, query and bundle
hashes, and checks the deterministic frozen model/profile/generation receipts.

## Observed actual Reader behavior

| Metric | Recorded |
| --- | ---: |
| Real Reader calls / planned | **384/384** |
| Distinct questions | **48** |
| Distinct deterministic prompts | **160** |
| Answers containing `[E<number>]` references all bound to delivered evidence | **4/384** |
| Exact prescribed refusals (`I do not have enough evidence.`) | **0/384** |
| Entire `no_evidence` arm with no supplied evidence | **48/48** |
| Exact prescribed refusals in that arm | **0/48** |
| All zero-evidence inputs across eight arms | **54/54** |
| Non-refusal outputs on those zero-evidence inputs | **54/54** |
| Previously reported best conditional token-F1 (`ranked3`) | **0.06591137** on **37/48** annotated questions |

**Interpretation is intentionally narrow.** A syntactically bound citation is
not a validated semantic attribution. No-evidence non-refusals show that the
Reader disobeys the registered abstention requirement; these outputs must not
be independently labeled hallucinations without a human semantic judgment.
The eleven original missing F1 annotations per arm remain unknown. The 384
answers are observations across only 48 native questions and six source families,
not 384 independent tasks. Repeated deterministic prompts are not separate
samples. No new language-task quality gain is attributed to NDU/FBSDE.

This is a **Reader adequacy stop signal**: do not treat improved retrieval
coverage, local symbolic graph success or the deterministic positive control as
proving usable end-to-end answers. The two required primary gates are (a)
correct, grounded answers with supported citations when sufficient evidence is
provided and (b) appropriate refusal with incomplete evidence. Existing
model outputs did not meet these behavioral requirements. Future research must
verify the frozen Reader's prompt/output interface and alternatives under
matched budgets before advancing a learned multi-Cell controller.

## Reproduce

Download the pinned GitHub artifact and verify its SHA256; no archive member
is extracted or executed by the analyzer:

```bash
python scripts/memory_cell/system2_reader_behavior_audit.py \
  /path/to/hepta-system2-new-questions.zip /new/audit-output
HEPTA_SYSTEM2_NEW_ARCHIVE=/path/to/hepta-system2-new-questions.zip \
  PYTHONPATH=scripts/memory_cell \
  python -m unittest discover -s scripts/memory_cell \
  -p 'test_system2_reader_behavior_audit.py' -v
```

The dedicated GitHub workflow pins artifact ID and SHA, runs only standard
library audit/tests, and publishes an exact source, environment, archive
identity and SHA256SUMS. It does **not** replace the full native research CI.

`production_accepted=false`, `reader_adequacy_established=false`,
`citation_semantics_independently_verified=false`,
`new_neural_calls=0`, `reasoning_emergence_established=false`.
