# MemoryCell: admitted LoCoMo-only source-family pilot

**2026-10-12 — Public, source-only, research pilot. Not model accuracy evidence or production admission.**

## Why the existing two-corpus workflow is still blocked

The real source-only capacity receipt from [run 38161049078](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38161049078), artifact `11711575563`, documents **10 native LoCoMo conversation-family proxies** (6 train, 2 selection, 2 evaluation) and only **1 LongMemEval source-family proxy**. The latter is not ten independent histories merely because the dataset contains 500 questions or tens of thousands of source documents. The existing `external_family_population.py` two-corpus flow remains correctly **NO-GO** until the inadequate native-source grouping is remedied with real source evidence, rather than renaming question IDs.

The LoCoMo-only pilot is a **separate, narrower experiment**. It invokes the *unchanged* `_corpus_rows` original-source guard and its ten-family minimum only on the published LoCoMo corpus. No LongMemEval source, label or score enters the pilot. It does not silently accept one-source-family LongMemEval as a separate split and does not promote the rejected two-corpus candidate.

## Precommitted public source cut

The new `external_locomo_pilot.py` takes only a SHA-256-pinned published LoCoMo source and the generating Git commit. `native.load` preserves original dated session and source-root identity, with malformed histories quarantined. `PublicCorpus.from_native` projects away native QA targets before the source split. `_corpus_rows` performs the existing exact-root and family disjointness checks. A deterministic hashed 60/20/20 family-level split allocates six LoCoMo conversation-family proxies for development, two for policy selection and **two for evaluation**. At most eight questions per family are selected by label-blind hash ordering, yielding at most 48 / 16 / 16 question rows, with each query retaining original source IDs and source-byte census hashes. No answer, gold support or unanswerability label is used to choose queries, families or document sets.

The source-only capacity JSON is fsynced first, then `publish_and_seal` fsyncs `public/population.json` **before** calling the original target supplier. Only then may original answer labels be copied into a distinct `targets/targets.json` artifact. `sealed-manifest.json` binds both exact SHA-256 digests. Publication fails if a label is missing or extra, if a document root leaks between partitions, if fewer than ten original families exist, if the source pin changes or if files are replaced.

The opt-in `.github/workflows/hepta-memory-external-locomo-pilot.yml` uses the same immutable original [snap-research LoCoMo revision](https://github.com/snap-research/locomo) and SHA-256 `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`, downloads **no model weights**, checks both new pilot tests and original dual-corpus admission tests, and uploads three separately named artifacts: **public input only**, **target values only**, and **source-capacity/seal receipt**. A future reader must be given the public artifact and original pinned source bytes **without** the target artifact; a separate scoring process may open private targets only after the complete raw output journal is durable.

## What this permits — and does not

It permits a bounded, transparent **feasibility study on two held-out published LoCoMo conversation proxies**, with identical frozen reader, tool access, input budget and calibrated hybrid RAG versus the strongest lawful simple history organization. It does **not** establish statistically convincing source-family generalization, genuinely independent future-window observations, human-certified semantic source entailment, a `>=99%` citation-quality rate or learning that beats nonparametric controls. These published histories may have pretraining contamination. Group identities are leakage *proxies*, not independently authenticated participants or source custodians.

Four independently archived Qwen repeats of the old eight *authored* development tasks have already demonstrated **0/8 incremental organized-over-full-path accuracy**, **0/8 incremental complete declared citation chains**, and only 573 saved input tokens across eight reads. Repeating or training on those same eight questions is **NO-GO** for claiming graph or parametric memory superiority. No learned Cell or deployment change is approved by this pilot.

**Next hard gate after source-only precommit:** exact-source, frozen-reader evaluation on public LoCoMo held-out families with labels opened only after original answers are committed; human-assisted independent source-chain adjudication, uncertainty at the conversation-family level, cross-family leak checks, calibrated RAG/full-history controls and lifecycle retention/revocation/recovery costs remain mandatory for higher qualification.
