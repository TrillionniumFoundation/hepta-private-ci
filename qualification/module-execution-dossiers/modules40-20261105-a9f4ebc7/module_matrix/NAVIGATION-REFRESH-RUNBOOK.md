# Final-candidate navigation refresh

This is an integration instruction, not a runtime or production qualification.
The baseline reviewed here is `f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55`, tree
`1f3d38ee52320bba1f345da2f2c54b23a36832ee`. The tree was read from the Git
commit object's `tree.sha`; do not reuse the recursive tree endpoint's echoed
top-level request SHA as a tree identity.

## Ready files

- `module-status-consistency.patch`: six unsupported registry qualification
  flags, the derived count, and the existing consistency test's Map coverage.
- `source-pin-qualification-guard.patch`: cumulative repair for legacy execution
  claim spellings and original manifest/operation/caller pins. If the older
  `legacy-execution-claim-rebind.patch` was already applied, use only
  `original-source-pin-guard.incremental.patch` to add the original-pin guard.
- `refresh-navigation.py`: temporary integration helper. It imports and reuses
  the candidate checkout's own strict implementation-map functions. It does not
  change the verifier or run product tests.

## What the helper preserves

Every original `sourceBase` remains exactly equal, including modules that call
it historical provenance. `exactSourceCandidate`,
`productCompositionSourceCandidate`, other historical evidence, all claim and
completion fields, product caller/writer status, ownership, source paths,
operation meaning, repository gaps and external gates remain equal.

Only current navigation fields may change: `sourceObjects`, operation
`sourceBlob`, exact-manifest blob hashes, caller blob hashes, `observedAtHead`,
`observedSourcePaths`, and the supported `mappingSourceIdentityMode`. Existing
evidence paths may not be removed.

When a path-only source anchor is stale, the helper selects the verifier's
existing `exact_blob` mode. That mode keeps historical `sourceBase` as immutable
provenance while requiring every mapped operation blob and a new explicit source
observation to match. It does not relax ancestry, clean-tree, caller/test/delegate,
or workspace-input checks. Original executable claims must already match before
any refresh is admitted; stale true claims cause a refusal.

The new source observation is navigation only. A separate new ledger records the
complete previous map blob, commit/tree, SHA-256, byte count, previous source
observation, unchanged historical source base and claim boundary. Old execution
candidate records remain untouched. An observation carrying extra non-identity
fields is rejected by default. The one narrowly reviewed Supervisor record below
has a separate explicit opt-in; its old interpretation is archived and is never
attached to the new identity.

## One explicitly reviewed Supervisor observation

The old `runtime.supervisor.observedAtHead` describes historical repository source
convergence and explicitly excludes product activation, deployed trust roots,
target-host qualification and independent acceptance. Its observed scope includes
Agentd and agent-protocol, which changed in this integration. It cannot keep its
old interpretation while changing its commit/tree.

Only `--archive-reviewed-supervisor-observation` permits archival of this exact
reviewed record. The helper requires all of:

- module `runtime.supervisor`;
- original Map Git blob `0ebfc4d68fd9cc6c60b9e612d3003f55bb97b89c`;
- original Map SHA-256 `362f4f5ca0a88f603099f4c0f02c434945d81b3210fa2af833de4be4332f4d69`;
- canonical old observation SHA-256
  `68b7b5826763ebc54617a46d4d48b19fb4baa4a183f5b382923e5f56dc7a7be3`;
- the parsed original Map bytes equal the loaded row.

The ledger retains the complete old Map reference, complete old observation,
these bindings and the review reason. The new `observedAtHead` is strictly the
current commit/tree pair. All other extra observation fields remain rejected,
even with the flag. Existing true execution claims must still pass the unchanged
original verifier before planning any refresh. `sourceBase`, historical execution
candidates, ownership, claims and all non-navigation semantics remain unchanged.

Append this flag to both preview and apply commands only for the reviewed case.
The integration helper remains outside the source checkout. This addition does
not modify the product verifier or confer execution qualification.

## Explicit operation-pin drift without a changed source anchor

The actual `learning.artifacts` Map provides a second, narrower drift case:
its historical source anchor and `sourceObjects` already point to the current
`pinned.rs` blob `3a097702ef7294467e2a16b5ae8624b716372c41`, while two
operation `sourceBlob` values remain at
`3ff1450b5111706d737643351fb5692ee657726c`. Its default mode is `path_only`,
so the existing migrator leaves those optional operation pins unchanged.
Source-identity verification alone therefore does not trigger the supported
`exact_blob` refresh path.

The final helper also verifies the migrated explicit pins inside the existing
`SourceDrift`-only catch. This one-line change sends this navigation-only drift
through the same existing exact-blob path. Original true execution claims still
undergo both original identity and explicit-pin checks before the catch or any
migration; the final explicit-pin guard is also retained. Invalid formats and
structures are not caught. No claim, qualification rule, or historical anchor is
changed.

Current helper SHA-256:
`940f0fe0d5fccf53dc8d00dacbd4f572cf9b02419704dba0cde35d495f9e7e3b`.
The precise change from the reviewed Supervisor helper is retained in
`explicit-pin-fallback.patch`. Actual C58 source bytes and the original two
Map operations are exercised in an isolated Git fixture, not represented as
execution of the complete product candidate.

## Sequence on the isolated integration checkout

1. Apply the status patch and the complete pin-qualification guard, finish Rust/product integration, run
   the repository formatter, and commit all source changes. The helper requires
   both the legacy-claim and original-pin guards in the actual candidate verifier.
2. Capture `SOURCE_COMMIT = git rev-parse HEAD` and
   `SOURCE_TREE = git rev-parse HEAD^{tree}`. Require a clean checkout. Put the
   helper outside the checkout. For this integration, the frozen source is C58,
   commit `58c81ccdd25002ae0f481d434af067a56fa7ddb8`, tree
   `57809be09ef01c02389ef37a817f1447d13d167b`. Finish its running full four-package
   suite before writing any Map, and retain that execution under C58's identity.
3. Preview using that exact source identity, then apply the same command with
   `--apply`:

   ```bash
   python /absolute/path/refresh-navigation.py \
     --root /absolute/path/integration-checkout \
     --expected-sha "$SOURCE_COMMIT" \
     --expected-tree "$SOURCE_TREE" \
     --ledger qualification/module-execution-dossiers/SOURCE_NAVIGATION_REBIND_20261105.json
   ```

   The helper prepares and checks all selected maps before writing. It refuses
   identity changes, dirty source, non-ancestor/invalid anchors, old true execution
   claims, removal of evidence paths, non-navigation edits and ledger overwrite.
4. Review the diff. The only changes in this step should be implementation maps
   plus the new navigation ledger. Commit this navigation-only change as C1.
   C1 is allowed to contain the preceding frozen source observation because C1
   changes no mapped implementation, tests, guide or build inputs. Verify that
   diff explicitly. No self-referential commit hash is inserted into a map, and
   the preceding source's test receipt is not relabeled as execution on C1.
5. On clean C1, run the original verifier, and retain its actual exit and JSON:

   ```bash
   python scripts/hepta-implementation-maps.py verify \
     --profile qualification \
     --expected-sha "$C1" \
     --expected-tree "$T1"
   python scripts/test_hepta_module_status_facts.py
   python scripts/hepta_module_registry.py --strict --pretty
   python scripts/hepta-module-docs.py verify --profile qualification
   ```

   The helpers' planning/preview checks do not replace these final-candidate
   commands. If a genuine source inventory or semantic gate fails, keep HOLD;
   do not downgrade the profile or relabel a navigation PASS as product execution.
6. A second preview at C1 with a new unused ledger filename should report zero
   changed maps. No new ledger should be written for a no-op.

## Registry and derived metadata

`SOURCE_BINDINGS.json` carries ownership/source-location and qualification facts,
not `sourceObjects` or current tree/blob observations. A navigation-only refresh
does not require changing its ownership, interpretations, evidence roots or
bootstrap states. The status patch already synchronizes its two false production
flags with `MODULES.json`, `MODULE_DOCS.json` and their implementation maps.

`PLAN_AUDIT.json`'s `moduleStatusFacts.production_implementation` must be recomputed
from canonical MODULES facts; it is zero for this candidate. Its legacy bounded
V8 `implementedModuleCount` is 14 and must not be changed to 40: that value has its
own explicit subset. Source navigation refresh alone changes neither count.

Use `hepta-module-docs.py refresh-derived --check` if canonical ownership or
module membership actually changes. The non-writing check preserves the current
claim boundary. Its writer preserves per-module `interpretation` and evidence
roots while rebuilding duplicate ownership projections, but can expose unrelated
existing drift; review any resulting change rather than applying it blindly.

Do not use `hepta_source_registry_closure.normalize()` merely to refresh pins.
That historical V8 normalizer rewrites source-evidence roots, interpretations,
technical prose and bootstrap states (`source_implemented`) for fourteen modules.
Those changes exceed this navigation refresh. Similarly, prose hash/index refresh
is unnecessary when no technical guide changes.

## Executed validation of the method

- Legacy guard: 27 real-Git negative cases fail against the original tool (nine
  schema spellings in three claim locations). Independent review found eight
  additional real-Git counterexamples: changed sourceObjects/exactSourceEvidence
  witnesses, and stale operation/caller pins despite newer observations. The
  complete original-pin guard rejects these before any rewrite, keeps legitimate
  unchanged true claims, and accepts tree as well as blob source objects. The
  final mechanism suite comprises 159 tests.
- A manifest-only regression also proves that refreshing a nested manifest must
  not mutate the original map in memory and suppress its pending disk write.
- Initial helper: four real-Git tests PASS, covering dry run/no writes, historical source
  preservation, exact-blob current observation, recoverable original-map ledger,
  original strict post-commit verification, idempotence, stale true-claim refusal,
  wrong candidate identity, dirty-source refusal, and refusal of a verifier that
  has only the older alias guard. Independent execution-pin counterexamples live
  separately in lifecycle_review/navigation_independent.
- The narrowly reviewed Supervisor extension reruns those four tests and adds
  four tests: exact original-record/hash binding; default refusal and real-Git
  opt-in archival with strict post-commit verification; rejection of every other
  module or changed original Map; and stale true-claim refusal despite opt-in.
  All eight tests pass on helper SHA-256
  `790d124c85dc299f6254fcd0427461881023bf60fcc4943713867eacd3dba438`.
- The explicit-operation-pin fallback adds three real-data Git cases and reruns
  those eight tests: **11/11 PASS** on current helper SHA-256 `940f0fe0…`.
  Navigation-only stale pins can be archived and rebound, then pass the original
  post-commit qualifier. Standard and legacy true claims still refuse before
  writes, and malformed pins still refuse. Independent review retained both the
  original helper's RED and corrected GREEN on the same-shaped Git scenario.
- Both patches apply cleanly to their exact original files and produce the
  expected byte-identical output.

These tests validate the migration mechanism. They do not prove the final
integration checkout's 40-module qualifier or any runtime product behavior.
