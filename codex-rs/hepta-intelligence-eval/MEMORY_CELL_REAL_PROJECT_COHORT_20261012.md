# MemoryCell — four real-project source families, pre-review cut

**Status: source-only admission / no model result / NO-GO for promotion.**
This is the next population after the four already completed Qwen 40+72 runs
returned **zero incremental answer or complete declared-citation wins** for
`organized` over the simpler full-path filter on the same eight authored cases.
The four repeats (448 original model generations) were a reproducibility study,
**not 32 independent tests**. Re-running those eight cases does not establish
transfer, newly learned memory, semantic entailment or production readiness.

## Actual externally sourced software histories

Frozen, externally SHA-256-pinned *metadata*:

- Source file: `scripts/memory_cell/data/real-project-pr-source-cut-20261012.json`
- **Raw file SHA-256:** `ef2a46ce037db4a91affddd2498eb8e089771ae5734bc13c56cb8a97b840a463`
- **Git blob SHA-1:** `656f221b3571aa187ab1c2fb106462ec3032d90c`
- Strict UTC source commit cut: **2026-10-12 09:45:00Z**.
- Four distinct public upstream repositories, **eight open PR histories**, **49**
  commit SHA references, **80** original changed-file Git blob references.
- Two distinct PR histories per project; no project occurs in more than one cut:

| Partition | Public project history | Frozen PR numbers |
| --- | --- | --- |
| Training source families | `rust-lang/rust` | #164037, #162467 |
| Retrieval policy selection | `kubernetes/kubernetes` | #142136, #142932 |
| Held-out source families | `numpy/numpy` | #32523, #32910 |
| Held-out source families | `astral-sh/ruff` | #29127, #28828 |

The exact captured head commits, root trees, parent links, per-PR commit lists,
file paths and blob identities appear in the immutable source file. Heads and
commits are **no later than the cut**. PR descriptions are not republished:
only their source SHA-256 fingerprints are retained. Upstream Git object URLs
resolve the code without silently replacing a prior head with the current
moving branch. Public PR titles and status are mutable GitHub API metadata,
not cryptographic proof of the complete historical discussion at the cut;
reopening and retrospective pretraining contamination are **uncertified**.
This cut intentionally does not pretend that a PR metadata snapshot alone is
complete sufficient task evidence: exact code bytes and time-bounded review
comments must be independently materialized and authenticated before a Reader
can be evaluated on a particular development-diagnostic question.

## Source-only registered tasks, not post-hoc gold answers

`project_pr_source_precommit.py` constructs an **unsigned 16-task review
worklist**: for each source PR it asks for change intent and concrete verification
or regression gaps. These are proposed tasks; no benchmark target, semantic
evidence verdict, model answer or reviewer identity is present. Case assignments
and task types are frozen by the source file before target writing or model
output. Published project histories are not future observations just because
we assign them evaluation partitions.

Before treating this as an independent ability test, a separate qualified owner
must freeze full original source bytes at these exact commit/tree/blob refs,
create a point-in-time review-and-question set, supply controlled source scope
and abstention criteria, secure different human reviewers' actual identity and
blindness to candidate model responses, and separately seal the resulting gold
or graded sufficiency labels. Reader and hybrid RAG / full-path-filter / graph
organization arms must then use identical model, tokenizer, budget, source
permissions, cut time and independent held-out repositories. Full lifecycle
retention, revocation and recovery costs remain unknown. No invented future
merge result or externally authenticated citation precision is admitted here.

**Fail-closed controls:** eight histories and four project groups are an exact
census; train 2, select 2, evaluation 4; unique original PRs and file refs;
commits, PR update times and files constrained to the registered cut; no
answer/gold/score fields in source input; no trained models, reviewer verdicts,
independent semantic review or production acceptance. Paths, sha1 and SHA-256
pins are checked before creating the unsigned worklist. A test fixture can
never substitute for the original external GitHub source records.

## Reproduce without models or privileged APIs

```sh
python3 -m unittest discover -s scripts/memory_cell -p 'test_project_pr_source_precommit.py' -v
python3 scripts/memory_cell/project_pr_source_precommit.py \
  scripts/memory_cell/data/real-project-pr-source-cut-20261012.json \
  --source-sha256 ef2a46ce037db4a91affddd2498eb8e089771ae5734bc13c56cb8a97b840a463 \
  --worklist /tmp/project-pr-unsigned-worklist.json
```

The lightweight scoped CI executes these checks and uploads **only unsigned
research source/review-worklist receipts**, not any made-up independent verdict.
The prior 8-case Qwen and LoCoMo/Stem **NO-GO gates remain in force**; this new
source cut is a valid next *data-acquisition step*, not an accepted memory system
or license to scale training.
