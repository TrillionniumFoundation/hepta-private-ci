# Completed Qwen 0.5B Reader JSON/lines: post-seal paired audit

Research-only, no model inference or training. On original PR #1546, this audit
consumes two already completed GitHub Actions ZIPs, refuses unauthenticated
artifacts and reports factual answer yield separately from refusal success.

## Actual source runs

The original pinned 0.5B-Instruct JSON trial, generating source
`dcd799fe0d90e05183701e336af76199dbc52f71`, has ZIP digest
`853afed48368b2c4e562191c7ed6d6bf28492bd80ec95634119b8afc7d43ab37`.
It contributed 160 answer-only results over the old 40 subjects and four
evidence arms. Under the original JSON transport, all 80 sufficiently evidenced
conditions produced prescribed refusal rather than exact TOK answers, and all
80 insufficient conditions refused correctly.

The isolated input-transport study [run 38321223762](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38321223762),
generating exact commit
`c73ea03d6dda2177d1c86f87249ca248e97424ff`, succeeded
with 320 NEW frozen Qwen2.5-0.5B-Instruct model calls and 160 reused old
outputs. GitHub artifact 11779301457 has externally pinned ZIP SHA256
`370181ca80deadf332ee2873ad1a2306038403338d64a726aff9f17bb05b5455`.
Its original candidate disposition was `reader_transport_not_qualified`.
No new subject here is an independent natural-language domain.

## Reproducibility and hard failure checks

`system2_reader_transport_audit.py` downloads neither untrusted weights
nor unpinned sources during scoring. The workflow obtains the EXACT two
finished ZIPs through GitHub Actions and verifies external SHA256, every
internal SHA256SUMS member, original producing commit/tree, both raw answer
seals and the complete 160+320 census.

For all 60 synthetic device/token questions and 4 evidence conditions, it
reconstructs the question, the original selected evidence fragments and
the proof-bound source bytes. It rejects mismatched model/revision,
original question/bundle digests, delivered source IDs, execution status,
input-token hashes, output-token hashes or input/output/CPU costs. It
recomputes the existing original pairing and final admission rule rather
than trusting the saved published summary.

After source sealing it reports exactly 240 paired JSON/lines comparisons,
separately counting:
- both correct, JSON-only correct, lines-only correct, neither correct;
- exact supported TOK answer yield versus appropriate refusal;
- **over-refusal on sufficiently evidenced tasks**, not credited as skill;
- real prompt/decoder token and model CPU deltas (not FLOPs or matched compute).

The audit does not rewrite or fabricate an answer, claim new model inference,
give a qualitative safety/semantic verdict, or move a serving model. Each
repeat arm on the same question is CORRELATED, not an independent test case.
Any missing, failed, duplicate or altered row fails closed. The downstream
task-science decision depends on the archived full 240-pair result, never an
unverified anecdote or post-hoc subgroup selection.

## Execute

From the exact head checkout after pinning both GitHub artifacts:

```sh
PYTHONPATH=scripts/memory_cell python \
  scripts/memory_cell/system2_reader_transport_audit.py \
  /tmp/transport.zip /tmp/original.zip /tmp/transport-audit.json
```

The isolated workflow also retains full MemoryCell regressions, Ruff F/E9,
the output JSON, external/internal checksum records and the exact tested
source/tree hashes. `production_accepted=false`,
`compute_matched=false`, `general_ndu_fbsde_gain=false`. The broader
Reader, Encoder, Cell, Riccati, FBSDE and serving paths are unchanged.
