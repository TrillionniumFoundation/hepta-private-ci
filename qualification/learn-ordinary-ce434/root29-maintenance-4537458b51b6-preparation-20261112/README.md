# Fixed 453 source: Root29 preparation and final maintenance

This directory is a prepared, documentation-only delivery. It does not dispatch H, run Python/Rust, change the PR, grant cleanup permission, or claim a native or ordinary result.

## Fixed source

- Source: `4537458b51b6ca936264aecea7cfe384b941d0d1`
- Tree: `8cbd7b269c9c39df4ee3ffcefed8473060696184`
- Source parents: `58bb796c285e47a049423390a3bdd44607e6c44b` and `6e7f8bf879afb1b6b3de88089d7103c252c68a5c`
- Expected separate inventory: 443 source methods, 201 default native cases in 43 groups, and the original 29 ignored Root cases. These are expected counts, not pass results.

This delivery commit is not the tested source and must not replace the source SHA in a request. The separate main request preparation is `1cb4cefd51814736075af23519f878decf27563b`; its contract is `3b8d4d86629d134b324d65eed78ced952f1ef42d`.

## Root29

Read `root29-4537458b51b6-contract.json`. The full runner is `root29-4537458b51b6-runner.py`; the complete, reversible 16-line change from the original de90 runner is `root29-4537458b51b6-runner.patch`.

The runner preserves the original 29 names, their order, exact just-test command, 7200-second recorder and minimum-test gate, one test thread, no retries, original sudo environment, helper verify-only checks, strict JUnit multiset, and original terminal-before-cleanup requirements. It retains the old v1 dependency provenance and separately checks the actual v2 target creation record. The source stamp does not turn a historical recovery record into a new source result.

Before any Root test dispatch it requires the actual same-source main result from:

`/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/live-owners-full-4537458b51b6-v1/result.json`

That complete receipt must prove exact SHA/tree, terminal pass, all 201 cases, exact selected/observer coverage, no failed or skipped case, native and collector integer exits zero, successful original helper steps, and clean final source. The full receipt bytes and source identity are rechecked before Root dispatch and after. A prepared request, old-source pass or unknown execution cannot satisfy the gate.

The normal-user runner still takes a new explicit `vN` attempt argument. The evidence prefix is `root-uid-29-4537458b51b6-`; the owned fixture prefix is `/run/hepta-learn-root29-4537458b51b6-`. This delivery neither chooses an attempt nor creates a typed H request. Root freezes dispatch after the real prerequisite is observed.

A returned sudo/Python wrapper does not by itself permit cleanup. The original `root.json` must prove the matching actual terminal execution before scoped chown or owned unmount. Uncertain completion leaves the owned fixture intact. The unchanged original recorder may stop only the new process group it created under its existing limits; this preparation introduces no signals or access to existing Rust/daemon processes.

## Source evidence without deduplication

`root29-4537458b51b6-source-provenance.json` preserves all 57 original complete records in their original order, including four repeated paths. It adds each fixed-source observation beside the historical record. Fifty-five records retain the original a671 blob; the Host carrier and B source objective-preimage records have explicit peer reviews. All 29 case-definition files remain byte-identical to a671.

The Panel carrier is separately pinned as a supplemental dependency; it is not inserted into or counted as the legacy 57 records. `root29-a671-original-parents.json` is the unchanged original name list. Its source fields intentionally remain historical; the new binding is in the new contract.

## Final maintenance

The unchanged `maintenance-static-contract.json` and `maintenance-checklist.md` preserve the reviewed AGENTS/justfile semantics. `maintenance-4537458b51b6-binding.json` binds their input to this candidate and leaves actual validation receipts, attempt, evidence location, command outcomes and post-maintenance SHA/tree unset.

After all Root-required validation has actual completed results, run from the existing repository's `codex-rs` directory in this order:

```text
just fix --locked --offline -p codex-hepta-agentd -p codex-hepta-learning-ledger -p codex-hepta-learning-artifacts -p codex-hepta-intelligence-eval -p codex-hepta-neuron
just fmt --base be8adcbb5e9925f72e05330b8fb30509cba4544b
```

The explicit formatting base includes committed PR changes that a default HEAD comparison would omit. Record the exact source SHA/tree/status before and after, complete original command logs and actual exits, and all changed-file postimages. A dirty working tree is not the unchanged HEAD tree. If maintenance changes bytes, a real postimage publication must identify the resulting source; earlier validation remains evidence for the original tested SHA.

No tests are invoked or scheduled after fix or fmt. No new environment, budget, dependency or authority is introduced. Native pass and ordinary A/B/C acceptance remain unclaimed by this preparation.
