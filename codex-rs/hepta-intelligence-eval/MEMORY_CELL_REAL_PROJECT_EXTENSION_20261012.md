# MemoryCell: additional public project source-family proxies

This is a source-only, research-only extension, NOT a qualified memory
evaluation or authorization to serve new parameters.

The original four public-project cohorts remain fixed at the original source
manifest SHA-256
ef2a46ce037db4a91affddd2498eb8e089771ae5734bc13c56cb8a97b840a463.
The added source manifest is located at
scripts/memory_cell/data/real-project-pr-independent-extension-20261012.json.
The new register declares an upper bound of 2026-10-12 16:05:00Z. That bound
does not independently authenticate historical PR discussion, prospective
tasks, author identity or source-family independence.

Additional original public PRs:

| Partition | Project | PR |
|---|---|---:|
| Train | pandas-dev/pandas | 71038 |
| Train | tokio-rs/tokio | 8630 |
| Selection | prometheus/prometheus | 19991 |
| Evaluation | python/cpython | 159216 |
| Evaluation | scikit-learn/scikit-learn | 35053 |
| Evaluation | denoland/deno | 37014 |

The added cases record six repository-level independence PROXIES, 14 pinned
Git commit references and 32 original changed-file Git blob IDs. With the
four original projects, ten distinct repository labels are registered.
This is NOT an independently certified effective N of ten, much less the
production floor N>=200.

The source manifest excludes PR descriptions, answer labels, model outputs,
reviewer findings and mutable natural-language task gold. The source-only
admission script checks its exact schema, fixed partitions, original
baseline digest, UTC time ceilings, complete file/commit census and no
cross-project blob reuse. It emits twelve unsigned review questions and
explicitly marks them NOT READY for a model.

Git SHA references alone do not prove that original file bytes were acquired
or matched their parent diffs. Before any reader experiment, a separately
bounded immutable Git-object fetch must verify every tree, parent and blob,
reopen complete source bytes and bind every question to actual evidence.
Then separate authenticated human reviewers must judge evidence sufficiency,
grounded answers, claim entailment and appropriate abstention. The model
must never see the held-out review targets.

Reproduction of only this source-identity stage:

    PYTHONPATH=scripts/memory_cell python3 -m unittest discover \
      -s scripts/memory_cell -p test_project_pr_family_extension.py -v

    manifest=scripts/memory_cell/data/real-project-pr-independent-extension-20261012.json
    PYTHONPATH=scripts/memory_cell python3 \
      scripts/memory_cell/project_pr_family_extension.py \
      "$manifest" \
      scripts/memory_cell/data/real-project-pr-source-cut-20261012.json \
      /tmp/unsigned-review-worklist.json \
      --source-sha256 "$(sha256sum "$manifest" | cut -d ' ' -f1)"

Next research-only steps: finish independent original-source byte validation;
freeze a fair strong hybrid-RAG reader and simple time/relationship filter;
evaluate organized/learned/parameter-only methods on newly judged held-out
projects, with failure denominators, cited full prerequisite chains and
complete lifecycle costs. This cohort is retrospective public software
history, NOT a new real future production observation or signed independent
semantic judgment. Production qualification remains false.
