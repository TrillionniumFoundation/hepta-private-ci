# MemoryCell real-project original source bytes: 80/80 SHA-bound audit

**Research-only source acquisition verification (2026-10-12). No reader answers, gold labels, trained memory or production acceptance.**

## What was actually checked

Using the already frozen [`real-project-pr-source-cut-20261012.json`](../scripts/memory_cell/data/real-project-pr-source-cut-20261012.json) source register (raw SHA-256 `ef2a46ce037db4a91affddd2498eb8e089771ae5734bc13c56cb8a97b840a463`, Git blob SHA-1 `656f221b3571aa187ab1c2fb106462ec3032d90c`) and source cutoff **2026-10-12 09:45:00Z**, the verifier read all **80 registered original files** from four public GitHub projects by exact original commit SHA **and path**. Every returned file was independently rehashed with Git's `blob <length>\0<bytes>` SHA-1 framing, against both the frozen file ID and the Contents API response SHA; **80/80 matched, with no missing or mutated refs**. This is beyond trusting a moving default branch or an unbound blob URL.

Each of the eight original PR HEAD Git commit objects was separately fetched and checked for its frozen SHA, root tree, parent SHA list, committer time, and source cutoff: **8/8 matched**. Two HEADs are multi-parent merges; their ambiguity is retained rather than selecting a convenient prior history.

| Partition | Frozen PR histories | Verified original files | Byte-exact UTF-8 source bytes |
| --- | ---: | ---: | ---: |
| Training — rust-lang/rust | 2 | 10 | 85,305 |
| Policy selection — kubernetes/kubernetes | 2 | 22 | 1,457,100 |
| Held-out — numpy/numpy, astral-sh/ruff | 4 | 48 | 4,960,699 |
| **Total** | **8** | **80** | **6,503,104** |

Evidence ledger: [`real-project-all80-original-source-byte-proof-20261012.json`](../../scripts/memory_cell/data/real-project-all80-original-source-byte-proof-20261012.json). Each row binds project, precommitted HEAD, original path, root tree, Git blob SHA-1 and raw byte length; the ledger additionally records the eight HEAD commit receipt and seven intermediate immutable verification receipt hashes. Previously published 48-file held-out byte census also reports **4,960,699 bytes**, exactly matching this independently rerun full path-and-byte check.

## Do not over-promote source-byte evidence

This audit verifies SHA-addressed original **HEAD file bytes and paths**, **not** complete PR branch ancestry, original base-diff reconstruction, unmodified point-in-time review discussions, or independently adjudicated sufficient answers. The source bytes were hashed during this verification but are not embedded in this compact ledger; a separate qualified materialization and sealed, answer-blind review packet must retain exact files before human review. No source code was executed, and no model answer was generated.

Four completed Qwen 40+72 runs remain a **NO-GO** for incremental complex organization task/citation superiority over the simpler full-path filter on eight authored tests. The next step is to materialize the original project sources as a complete hashed artifact, establish blinded human reviewers and independently frozen labels, then compare a frozen reader against tuned RAG, single-hop, full-path and organizer arms under identical budgets and allowed evidence. Treat any missing reviewer, stale discussion, root-tree ambiguity or lifecycle/recovery cost as unqualified, not as zero.

