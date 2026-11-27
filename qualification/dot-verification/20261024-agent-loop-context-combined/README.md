# Native loop cancellation + context-v2 combination

Frozen new source parent: 0ec18791d970190578b55234036f3a30dc7d560b, tree 0a84fa8407fb78ad0dce73eb67ccc71cb22d3f06. It advanced #3649 while #3652 was being published. GitHub comparison showed exactly one new commit and six context-adapter/dependency/docs files; none overlap the reviewed cancellation runner/test patch.

This separate real Git worktree starts at that new parent, then adds the exact two independently reviewed source files from #3652 (8bd8cf63619ac845a56eba62de83c2d7a569f5e1). The original #3652 history and 12 baseline / 8 red / 20 green evidence remain unchanged. This combination is newly executed, not inferred from the older 20-test result.

## Results
- Initial offline attempt stopped before compilation because bitflags 2.13.2 was not cached. Retained. Normal official-registry fetch with --locked then succeeded; no dependency/lock edits.
- just test --locked -p codex-hepta-agent-loop --features context-v2: 24 passed, 0 skipped. Includes original12 loop, new8 cancellation regressions, and4 actual context-compiler adapter tests.
- just fmt exit0 and git diff --check passed. Both changed source files remain byte-identical to reviewed #3652.
- Broad strict Clippy FAILED (exit101) in unchanged dependency hepta-context-compiler/src/v2.rs: line99 empty_line_after_doc_comments and line1995 observe_delivery has8 arguments versus threshold7. No allow or dependency/API change was introduced.
- Supplemental scoped --no-deps all-targets strict Clippy with context-v2 PASSED. This validates the changed loop crate, not the failed dependency-wide lint. The broad strict-lint blocker remains OPEN.

## Bounds
The context adapter calls the existing compiler delivery preparation and retains owner-serialized bytes. Its four tests cover mandatory instruction/tool retention, revoked context, foreign objective, and output-reservation bound. The verifier/tokenizer/serializer used in fixtures are controlled test adapters, not a real product admission authority or semantic summarization/compaction acceptance. The loop still lacks a concrete durable TurnOwner/InferenceOwner/EffectOwner product composition. Cancellation checks returned owner frames after commit and do not roll back bad-owner durable writes.

No live provider, sockets, production activation, credentials, model weights, cloud quota use, merge/deployment, or security changes. SHADOW/DENY_ALL unchanged. Hosted exact-head/merge CI is separate and not inferred from local results. #3652 also has a zero-job ui-product-foundation workflow failure whose root cause is not diagnosed; plain YAML parsing does not establish GitHub schema validity.

Earlier defect/reproduction evidence: https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3652
