# Exact comparison history for the original V8 selector

## Actual failure and bounded repair

The V8 metadata job `126091750418` failed on the original three-dot comparison
`adaeb1854c9b2abe3f8c65a4407344d07e1c7589...1ef3216ffb86271d87e6aea049ce7ca7f2b76809`
with `no merge base`. Both exact tips had been fetched at depth one. This was a
history preparation failure before the V8 selection decision, not a V8 build
failure. `original-job-126091750418.log` retains the decoded GitHub job output.

The helper gains an opt-in `--merge-base` mode used only by V8 metadata. Its
existing default exact-tip and full-history modes retain their behavior. The new
mode incrementally deepens the same two validated commit IDs by 1, 2, 4, ...
commits, with no tags or other branch refspecs. It preserves the original
three-dot detector, selected work, token origin checks, and 30-minute deadline.
Unavailable inputs or disconnected complete histories fail the job.

An arbitrary visible merge base is insufficient in a shallow merge graph. A
short second-parent path can reveal an old common ancestor while a better common
ancestor remains behind a shallow first-parent boundary. The helper stops only
when no shallow boundary remains reachable from either tip outside the ancestors
of the known merge bases. Unrelated shallow refs do not force extra fetching.
The regression suite constructs this misleading graph with real Git objects.

## Source-bound local results

`CONTROL_COMMANDS.json` and `controls-*.log` record the exact commands and full
outputs: 59 history/scope/dependency tests, seven original V8 selector tests, and
six existing V8 CI controls all passed. The history count includes six new
actual-Git controls; its total is 11. No Cargo or Bazel build ran for this change.

`ACTUAL_REPLAY.json` records a fresh shallow replay of the precise failed range.
The unchanged old helper first reproduced exit 128 and `no merge base`. The new
mode then fetched the two exact tips with deepen values 1, 2, 4, and 8. It found
the true merge base `adaeb1854c9b2abe3f8c65a4407344d07e1c7589`; all 147 changed
paths matched the GitHub complete-graph comparison. The unchanged V8 detector
produced the same versions and both selection outputs in the repaired shallow
directory and existing source graph. Both canary and Windows source work remain
required. No branch or tag refs were acquired.

The actual replay used the pre-format helper recorded in its source manifest.
`tested-before-format/` preserves the exact two Python files tested. Required
`just fmt` then succeeded; `FORMAT_RECEIPT.json` binds the resulting files and
records identical Python ASTs before and after formatting. Tests were not rerun
after formatting, following the repository instruction. The workflow bytes were
unchanged by formatting. This is an exact-history and selector qualification,
not evidence that any V8 build or unrelated production gate passes.

The independent reviewer read the three-file implementation diff and accepted
the shallow-frontier stopping condition, exact-origin authentication, unchanged
default behavior, and checkout preservation. They did not execute these tests.
A shallow upstream that cannot deepen still reaches the original job timeout
and fails closed; no separate success fallback or extended deadline was added.

## Reproduce

From a checkout containing this candidate, run:

```sh
python3 -m unittest -v scripts.test_hepta_ci_history scripts.tests.test_hepta_ci_scope scripts.tests.test_hepta_ci_dependencies
python3 .github/scripts/test_v8_canary_changes.py
python3 scripts/test_hepta_ci_v8.py
```

For the exact historical negative-to-positive replay, use a new directory. This
performs public Git fetches of only the specified tips and requires the two
historical commits in the candidate source checkout for the second selector
comparison. The saved GitHub oracle provides the independent complete-graph
merge base and path set:

```sh
python3 qualification/ci-merge-base-history-20261103/replay_actual.py \
  --repository "$PWD" \
  --workdir /tmp/v8-exact-history-new-replay \
  --output /tmp/v8-exact-history-replay.json
```

The replay refuses an existing work directory and checks input hashes before and
after execution. Its original helper copy is exactly the file at source `1ef3216`.
It never checks out or modifies the caller's worktree.
