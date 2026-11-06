# LoCoMo uploaded reviewer packet — separate original-source audit

**October 13, 2026 · Frozen published source · Research-only, not human-adjudicated.**

This audit inspects the **actual GitHub-uploaded reviewer packets**, not just the
worklist generator's local output. It re-reads their original ZIP transport bytes,
the generation manifest, and the **unaltered original 32-answer Qwen journal**.
No pretrained model call, citation correction, benchmark answer/target download,
new model training, source signature or human verdict is performed by this audit.

## Pinned original source artifacts

| Source | GitHub artifact | Outer ZIP SHA-256 |
| --- | ---: | --- |
| Uploaded source-only sufficiency cards | `11779535979` | `d0d2fc3ed8ed4ad01ad34beb2764954051dfad19dd2a7fd9673169b2709c2b63` |
| Uploaded later answer/citation cards | `11779431120` | `0f57e7d79208dd6cf7e56ae13cc804bc3e41421641e7410a743b5423b327eb45` |
| Original generator's reviewer-manifest ZIP | `11779426223` | `0c16df842da612856d89cc6719d191634f300934d7e1b52bd0615cfaadd08955` |
| Original actual Qwen generation, 32 calls | `11763718022` | `7160ede72114b04135e544fb687a804dc0c4852834cf1695440a75b85214bf48` |

The original real Qwen source commit was
`96b5ec37b82f87d445740403e07e3705e9850955`. Worklists were emitted by
source `72a145cc5f12586035d3728374264c0c7a830778` in completed
[GitHub Actions #38322297571](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38322297571).
The reader is the same frozen BF16 research-only Qwen2.5-3B inventory, model
digest `f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225`.

## Actual uploaded-content findings

| Byte-verified observation | Original files |
| --- | ---: |
| Original distinct public development questions | 16 |
| Original published source-family proxies | 2 |
| Source-first sufficiency cases | 32 |
| Later answer and citation cases | 32 |
| Later model answer texts equal to original raw Qwen answers | **32/32** |
| Delivered original UTF-8 source excerpts exactly matched | **192/192** |
| Original Qwen ZIP inner files authenticated | 13 |
| Model answers supplied in source-first packet | **0** |
| Actual independent human sufficiency/citation verdicts | **0** |

`locomo_handoff_upload_audit.py` additionally checks the uploaded transport
hashes, all original reader ZIP member hashes, the original manifest's cross-ZIP
SHA-256 bindings, reviewer-case mapping and cardinalities, ordered selected
source IDs, original question/time digest, copied source-root/offset excerpt
bytes, unmodified generated answer and citation labels. Every uploaded case's
reviewer verdict must remain **unset**. It explicitly rejects a missing case,
a changed answer, a forged source excerpt, a changed question, added model
answers to source-first cards, changed citations, and invented human verdicts
(including attempts that re-pin the adversarial ZIPs and their manifests).

The offline regression suite includes 14 model-free integrity/tamper tests.
The opt-in workflow
[`.github/workflows/hepta-memory-locomo-upload-integrity.yml`](../../.github/workflows/hepta-memory-locomo-upload-integrity.yml)
refetches precisely these four published artifacts, runs those tests, and
compares the independently regenerated receipt to the committed JSON. Its
artifact deliberately contains **only hashes, counts, provenance and test
outcomes**; no question texts, answers or sensitive reviewer notes are
republished by the verifier.

## What has *not* happened and the next hard gate

**This is a secure-hash/structural handoff check, not a human review.** Both
packets are still accessible through the originating repository's artifact
access. Merely placing them in two ZIP files cannot demonstrate distinct
reviewer access permissions, ordering, blindness or independent judgment.
The observed reviewer decisions are zero, and the original 16 questions span
only two previously published source-family proxies. The audit marks
`reviewer_access_separation_certified=false`,
`actual_independent_reviewer_decisions=0`,
`parametric_memory_training_qualified=false`, and
`production_accepted=false`.

Next, the actual designated reviewer/owner must enforce restricted first-stage
access and review source sufficiency **before** exposing the model answer
stage. They must return source-grounded answer and exact UTF-8 evidence spans,
then separately adjudicate original answer support and complete citations.
Only after that, perform same-reader matched tests on genuinely new, disjoint
source-family tasks with sealed controls, actual lifecycle costs, independent
semantic validation and authorized production recovery/rollback. No 99%
precision or parameter-memory benefit is inferred from structural provenance.

To replay from the original downloaded ZIPs without models:

```bash
PYTHONPATH=scripts/memory_cell \
HEPTA_LOCOMO_SOURCE_REVIEW_ZIP=source.zip \
HEPTA_LOCOMO_ANSWER_REVIEW_ZIP=answer.zip \
HEPTA_LOCOMO_REVIEW_MANIFEST_ZIP=manifest.zip \
HEPTA_LOCOMO_ORIGINAL_READER_ZIP=reader.zip \
python3 -m unittest discover -s scripts/memory_cell \
  -p 'test_locomo_handoff_upload_audit.py' -v

python3 scripts/memory_cell/locomo_handoff_upload_audit.py \
  source.zip answer.zip manifest.zip reader.zip --output receipt.json
```

Human sufficiency and citation semantics remain **UNREVIEWED**. No training or
production promotion is authorized by this result.
