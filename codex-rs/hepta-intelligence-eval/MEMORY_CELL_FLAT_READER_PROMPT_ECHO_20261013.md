# MemoryCell: original flat Reader citation markers are prompt echoes

**October 13, 2026 · SHA-pinned, source-only post-generation audit · production NO-GO**

The real frozen-Reader **JSON-versus-flat** experiment
[run 38239517996](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38239517996)
completed successfully with 32/32 new Reader generations. The new prompt
reduced some JSON-shaped output and produced 17 structural `[E1]` markers;
it did **not** reliably increase answer token-F1.

The original strict native Reader artifact is `11741082077`, transport
SHA-256 `65fe5e99c90a10dba916598dc2a83f164ef6275d7cb6c783aa6edbe3722d2563`
(source `1578121eb24cbb3d50fbe0ae27f2d48f870bb364`; 151 internal
manifest members). The actual frozen flat-run artifact is `11746473791`,
transport SHA-256 `4d28ee07ec9425e3fe3288c9eaf79362fc23d64ec50ad359279d2f9ddca7389b`
(source `9d23a30d1204837767131856cd8f20542f1ddc68`; 15 members).
Both external transport hashes and both complete internal SHA256SUMS manifests
were independently rechecked against actual ZIP bytes.

## What all 17 markers really show

| Source phase | Actual structural markers | Valid delivered `E1` label | ≥24 exact prompt-overlap characters |
| --- | ---: | ---: | ---: |
| select | 7 | 7 | 7 |
| retention | 4 | 4 | 4 |
| test | 2 | 2 | 2 |
| transfer | 4 | 4 | 4 |
| **Total** | **17** | **17** | **17** |

The generated text containing every marker has a **contiguous exact character
substring of at least 24 characters enclosing the marker** in one of the
original prompts. Fifteen marker contexts occur verbatim in the original
flat user message, primarily the `Evidence [E1], observed at ...` source
header, and two occur verbatim in the frozen system instruction to cite `[E1]`.
The longest matches in the actual samples are 26–204 characters.

This is strong *structural copying* evidence, **not** a human semantic
entailment verdict. Crucially, **17/17 structurally bound source labels do
not become 17 authored citations**: zero of these 17 examples can be credited
as demonstrated independent answer-generated citations under this rule.
It is still possible the accompanying answer words are factual by coincidence
or evidence; this separate semantic question remains unreviewed.

The already hosted [flat Reader format comparison](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38239517996)
also measured paired flat-minus-JSON answer token-F1 means of approximately
−0.0386 (select), −0.0139 (retention), −0.0282 (test), +0.0027 (transfer).
The change in citation *appearance* therefore cannot justify Reader, Head,
Encoder or production deployment.

## Independent, reproducible gate

`stem_flat_prompt_echo_audit.py` and 5 synthetic guard regressions bind all
32 original final-checkpoint frozen questions, the original 576 policy-row
census, original delivered evidence and fixed Reader/prompt identity to
the same frozen flat-run answers. The algorithm reconstructs the **exact
old user prompt**, parses the original `SYSTEM` literal without importing
or executing a model, and detects maximal exact overlap surrounding each
`[E#]` marker. It separately reports delivered-label matching versus
prompt copying, with salted-free hashes of question IDs but no raw answer
or source text copied to the new report.

The independent GitHub workflow
`.github/workflows/hepta-memory-stem-flat-echo-audit.yml` downloads the
two *specific* published ZIPs, checks both outer digests and full inner
manifests, runs tests without a model, and fails closed if the observed
17/17 citation census changes. This does not re-run any pretrained model
or open gold answer targets. Local verification passed 6/6 analogous
fixture/tampering tests; the GitHub workflow must supply its own terminal
status before any hosted acceptance is claimed.

**Disposition:** prioritize **Reader capacity and independently reviewed
sufficient-evidence/citation controls** before expanding Cells or treating
prompt-template labels as citations. No semantic precision denominator has
been independently adjudicated; `semantic_citation_precision=null`,
`production_accepted=false`. No serving cutover, approval or main merge.
