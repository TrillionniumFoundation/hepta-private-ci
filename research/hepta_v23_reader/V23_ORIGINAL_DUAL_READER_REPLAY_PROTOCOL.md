# V23 — Original Qwen3 vs 135M: authentic sanitized evidence replay

**DRAFT / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL / NO MAIN MERGE / NO MODEL OR CELL PROMOTION.**

## Exact parent and original physical evidence

V23 is an additive research-only descendant of [V22 PR #2560](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2560) at `14c597392dcf0b9382922fe333731320b0101b58`. It does not modify original model execution, input prompts, publisher results, Neuron/NDU code, model selection, CNS, CAS, FinalUse or the shared Encoder.

**A genuine previously missing milestone completed before this V23 code was authored:** original [GitHub Actions run 38986155653](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38986155653) reached `success` and the `original-135m-and-qwen3-private-physical` job completed, not merely the source-contract job. Original [artifact 12084082227](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38986155653/artifacts/12084082227) (ZIP SHA-256 `3ef61dad3b4a7bc58f35597d26e1c92c3df02e250aae8cf4072a128b7545724d`) contains **four sanitized JSON members only**. V23 reopens and checks that artifact physically in a separate local process. It does **not** run another pretrained model or claim an independently signed model host.

The run validated the original historical LoCoMo publisher file SHA, Qwen material SHA `e748e2efe1880f9e312eb31e8929e0fff8e46a575cbcf6788f9399960748d273`, the exact V17/V19 source-first request manifests and Qwen native tokenization before opening publisher answers. Qwen3-0.6B was loaded with its original public publisher revision and made **96 unique actual model requests, 1,970 counted root model forwards**; 135M Reader made **96 unique requests, 1,777 model forwards** on the same fixed source-first question panel. All **120 logical arms per model** were represented. Real Qwen CPU/wall 565.749/302.895 seconds, original 135M 171.883/86.205 seconds; their tokenizer/precision/operators differ. Do **not** treat these as equal-token latency tests or an isolated weight-size improvement.

Original publisher labels remained withheld until both outputs were sealed. The original source-independent reviewer published only numeric and SHA digests; no raw LoCoMo utterances, model answers, per-case route scores or annotations appear in this new Git branch.

## Independent, strict V23 replay

`dual_reader_artifact_replay.py` is a new zero-dependency artifact auditor. It is **not** the V19/V20 producer/reviewer reused with a different label. Two modes:

1. `--archive`: physically reread the exact SHA-pinned 3.5KB original GitHub Actions ZIP, reject duplicate/symlink/foreign members and JSON duplicate keys or nonfinite fields, then independently cross-check four-arm source/label/Forward/cost/authority summaries.
2. `--members-dir`: read an exact separate, pinned four-member cross-run artifact extraction and verify the **original per-member byte SHA256**. This is not equivalent to ZIP byte identity, which is verified in the first mode; it makes the GitHub read-only CI reproducible without model weights or private questions. Reject missing/replaced/foreign members.

The public committed `V23_ORIGINAL_SANITIZED_MEMBER_SNAPSHOT_20261016.json` is an archival source-only copy of those four **already sanitized** original numeric/digest-only JSON members for local tests, not raw answers. The derived `V23_ORIGINAL_DUAL_READER_REPLAY_20261016.json` binds original artifact/run/head and discloses explicit scientific NO-GO. Source-only tests never claim a new Qwen physical forward or a second independent human evaluator.

### Actual observed descriptive contrast

| Evidence arm | Original 135M weak answer substring / 22 labeled | Qwen3-0.6B weak answer substring / 22 | Strict full-answer matches / 22 |
|---|---:|---:|---:|
| None | 0 | 0 | 0 both |
| BM25 retrieved | 3 | 3 | 0 both |
| Publisher annotated | 5 | 4 | 0 both |
| First-source lesion | 0 | 0 | 0 both |

All four arms contain 30 historical original questions, **8 with missing publisher answer**. Missing publisher answers are **unknown labels** rather than automatic incorrect outcomes. Literal substring and strict string equality are not human-semantic correctness; publisher annotations are not independently certified sufficient evidence. In the annotated Qwen arm, **25 syntactically valid cited addresses** are not 25 entailed answers. The no-evidence arm had **13 foreign-citation cases**. No Qwen model capacity superiority is shown.

Qwen unique physical input tokens were **12,008**, not the **13,663** logical-with-duplicate total. Neither number is token-matched to the 135M Reader. The raw Qwen/135M CPU ratio is **about 3.29**, wall ratio **about 3.51** for these distinct model stacks, sequential in one hosted job. The ratio is descriptive, not full lifecycle energy/throughput equivalence.

No per-case paired outcome table exists in the sanitized artifact, so no source-clustered confidence interval, strict semantic score, cross-model case-paired win count, citation entailment, human-certified sufficiency, or adaptive NDU benefit can be derived from it. SHA pins verify preservation of producer-reported counters, **not the unobservable truth of withheld raw answers or host signatures**.

## Exact scientific gate

Before calling a Reader or a new Hepta Cell/Stem/Organ improved: obtain independent source-root-blinded adjudication on whether the delivered sources suffice, then independent and source-bound semantic final-answer **and** cited-evidence entailment judgments, with a separately pinned stronger comparator and matched full lifecycle budgets. Current source family count is ten historical roots, not 120 independent future examples; new prospective windows and old-task retention are also missing.

`main` must not be merged from this branch. The V22 `blocking-ci` at run `38986183602` finished **failure**. Actual logs identify unrelated repository-wide Prettier failures (14 `.github/workflows/*.yml`), Rust advisories (`rustls`, `zip`, and unmaintained `unsafe-libyaml`), plus Windows Bazel/Clippy and integration-test failures. This V23 research patch does not bypass, suppress, or claim repair of any such check; treat each as a separate exact-head security/owner repair.

## Local replay and CI

```bash
PYTHONPATH=research/hepta_v23_reader python -S -m unittest discover -s research/hepta_v23_reader -p 'test_*.py' -v
PYTHONPATH=research/hepta_v23_reader python -O -S -m unittest discover -s research/hepta_v23_reader -p 'test_*.py' -v
python -S research/hepta_v23_reader/dual_reader_artifact_replay.py \
  --archive /path/to/original-GitHub-Artifact-12084082227.zip \
  --output /path/to/new-sanitized-replay.json
```

The source job checks only the immutable published sanitized numeric member snapshot. The optional original artifact read-only CI downloads **only artifact 12084082227 from run 38986155653**; when retention expires it must fail closed, not fabricate source results or fetch a replacement from a different run. It never fetches weights, calls models, uploads raw answers or changes policy/authority.
