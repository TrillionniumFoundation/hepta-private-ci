# Reader diagnostic readout must preserve non-citation answer content

Date: 2026-10-13. Parent: `e1ccb07f03da831dbd183759c1425a5e165d0180`.
Continuation of PR #1697. This is a correction to diagnostic scoring, not a
new training method, cohort, model result or independent semantic review.

## Source defect and correction

The previous response readout removed every string matching
`\[([A-Za-z0-9_.:-]+)\]` from an answer before computing exact-body equality.
That could remove bracketed negations, numbers or unsupported source labels,
not just references to evidence actually supplied to the Reader. For example,
`Alpha [not]` could become an exact-body match for target `Alpha` even though
the separate citation-syntax flag was false. Neither flag is semantic grading,
but the exact-body transformation must not discard arbitrary answer content.

`score_rows` now removes a bracketed label ONLY when it is in that raw row's
recorded delivered `evidence_ids`. All other bracketed content remains in the
body. Case, word order, punctuation and numbers remain unchanged except for
the already documented whitespace normalization. The raw answer is immutable.
A valid reference like `[E1]` does not imply its supporting statement is true;
`grounded_and_cited_semantics` is still null. Bracketed content that literally
belongs to a target remains comparable, rather than being erased.

The plan, every score row and the report declare
`readout_profile=registered-citation-only-exact-body-v2`. The plan digest changes
before a new invocation. Historical raw answers are not rewritten or silently
assigned a new evaluation profile. No old score is relabelled here.

Nine regression definitions cover bracketed negations and numbers, unsupported
source IDs, delivered IDs, empty evidence, mixed labels, raw-input immutability,
literal bracketed target content and the explicit readout version. They extend
the EXISTING response test module: 19 previous tests are retained, 28 definitions
in total. Both aligned and permuted controls still receive unchanged training
examples, initialization, token caps, optimizer and family partitions.

The working container/Python execution remains unavailable with ClientError.
These additional tests are submitted, NOT claimed passing. The earlier native
run failed at Group tests before response training; no response-learning efficacy
result has been observed at this correction. New exact-source execution and
independent future-task adjudication remain required. Formal Reader/Group/NDU
qualification and production permissions are unchanged.
