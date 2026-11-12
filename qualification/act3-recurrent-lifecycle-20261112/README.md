# ACT3 recurrent lifecycle: original process-death recovery

This record qualifies one concrete engineering stage: the archived trained GRU,
its exact post-inference hidden bytes and pending invocation resume with the
original synchronous filesystem lifecycle controls after a real controller
process death. It does not qualify a production deployment or learned advantage.

## Frozen execution identity

| Field | Original value |
| --- | --- |
| Implementation PR | #6152 |
| Qualification PR | #6155 |
| Tested commit | `505e03b49c4ff0a4630751dbe05664b93fc87320` |
| Tested complete tree | `0cbd1592344ad62114c1e1d160837f4107835a86` |
| Parent ACT3 source | `8c11ca58559f0fc05678387e09588bf2368d4d84` |
| Runtime | CPython 3.12.14, NumPy 2.3.5, Linux; details in MANIFEST.json |
| Original local result | 46 planned, 46 started, 46 passed, 0 skipped/errors/failures |
| Test wall time | 8.252046420 seconds; engineering test time, not policy efficiency |
| Source before/after | Identical commit/tree, clean worktree and source/model hashes |

The evidence commit adds this record after the tested code commit. It does not
rename the original test source or transfer a result from a different code tree.
`RESULT.json`, `PLAN.json` and `tests.log` preserve the complete exact identities.

The six selected suites contain 9 lifecycle, 3 filesystem-owner, 9 durable
lifecycle, 5 durable-async-owner, 8 recurrent and 12 independent adversarial tests.
These are engineering cases; they are not 46 independent real application tasks.

## What changed and what actually ran

`RecurrentLifecycle` uses the existing guarded `inspect` / `ensure` / `stop`
options. One original SQLite checkpoint row atomically contains lifecycle
controls, exact 12 x little-endian float64 hidden bytes, decision sequence,
selected/proposed action and original invocation/goal binding. A prepared
decision resumes without a second inference. An entered operation is only
reconciled through its original owner. Missing readback retains UNKNOWN and
cannot authorize resending an effect or applying the decision to the next key.

The loader hashes and decodes one bounded model snapshot. It validates archive
membership and expanded sizes, exact tensor shape/dtype and finite values.
Model, feature/model/guard/driver source, configuration, UID, boot, original
directory and owner identities are bound. A cooperative immutable admission
record rejects foreign model/source/configuration/boot before writable SQLite
open; it is not an independently authenticated anti-rollback witness.

Five actual SIGKILL executions cover prepared decision, before apply, after
publication, opaque published effect and full prepared continuation. Original
child exit codes are -9. Separate restored processes retain the original hidden
bytes, sequence and pending decision. A fail-on-inference guard proves that
settling the pending operation does not run that GRU decision again.

The full prepared-resume run matches an uninterrupted learned-policy reference
in final hidden bytes, sequence, decisions, primitive calls, original effects and
goal result. This is continuity equivalence on a controlled task, not an efficacy
comparison against the fixed workflow.

`INDEPENDENT_READBACK.json` separately checks the raw originals: 14 retained
control databases have intact state digests and matching tested source bindings;
the five original SIGKILL records and restored hidden/pending bytes agree; the
full reference/restored behavior coordinates agree. No database is opened for
writing during this independent audit.

## A development failure is retained

Independent review found a live CONFIG alias in an intermediate new driver:
changing CONFIG.hidden to 13 then pausing rewrote the saved declared size while
the loaded GRU still had hidden size 12. The fixed driver retains its own
geometry-derived supported configuration snapshot and returns copied bindings.

`development-originals.tar.xz` preserves the original RED log, a frozen isolated
reproduction (11 cases, one failure), GREEN controls, source postimages and
prepublication runs. The source-retention note explicitly discloses that the
red bytes were reconstructed by reversing concurrent edits and then matched
the independently observed pre-fix SHA-256. They were rerun in a frozen isolated
directory with unchanged before/after source hashes. This is a development
regression fixed before publication, not a newly attributed historical defect.

## Original artifacts and reproduction

- `originals-and-source.tar.xz`: exact tested Python source, child inputs,
  actual model, exit codes/stdout/stderr, interrupted checkpoint, original
  SQLite records, effect intent/value bytes, reference and restored reports.
- `SHA256SUMS.json`: original runner's per-file hashes for its uncompressed
  output. `FILES_SHA256.json` separately binds files committed in this directory.
- `development-originals.tar.xz`: preserved earlier development attempts.
- `RESOURCE_OBSERVATIONS.json`: the one original `h.host_list` request timed
  out with MCP -32603; original dot/Root runtime access was not established.

On a clean checkout of the exact tested source, with NumPy 2.3.5:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
python scripts/act2_learning/qualify_recurrent_lifecycle.py \
  --output /absolute/new-directory-outside-checkout
```

The output path must not exist. The runner rejects dirty source, missing suites,
zero-test suites, duplicate test identities, any skip or failure, changed source,
and any difference between the planned and actually completed test identities.
Original owner directory inodes are intentionally bound. Archived copies are
read-only evidence, not a claim that arbitrary copied directories can be resumed.

## Production and scientific boundaries

The finite Notes path at #6127 / `b02850c04dcd40f2703e95cc670df531468fd0e3`
already has `with_root_notes_thread_tools`, original Core callback verification,
AuthBus human input, Root/FinalUse, protected original sender and fresh Notes
goal readback. Its accurate status is implemented / full product execution
unverified. The generic opaque HTTP host remains a separate path that must
reject ActionSkill without a registered independent goal-checking host.

`NOTES_ORIGINAL_THREAD.md` explicitly retains full product acceptance. The
seed-only test creates an unused original thread and asserts zero model contact;
the actual-App fixture tests are not the full original callback/authorization
chain. A real original human delivery, Core turn, Root signer/session, protected
writer, live Notes incarnation and fresh readback must appear in one execution.

This record does not qualify joint GRU plus asynchronous owner continuation,
actual new-boot continuation, common rollback, hostile-owner authentication,
power loss, new learned skill composition, new application/version/fault-family
benefit or complete lifetime cost. Cross-boot mismatch rejection is a constructed
negative control, not an actual reboot-and-resume result. New model fits and
independent real-task episodes are both zero. Historical ACT2/ACT3 negative and
tied results remain unchanged; promotion and production adoption remain false.

See `BLOCKERS.json` for source-specific status and original CI observations.
