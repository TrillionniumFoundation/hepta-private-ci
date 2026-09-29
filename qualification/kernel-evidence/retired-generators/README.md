# Retired source-mutation workflows

The active qualification surface for `kernel.evidence` is read-only with respect
to the tested source. Historical source-repair and metadata-finalization jobs are
not CI checks, executable module implementation, or completion evidence.

The first retired batch is byte-preserved in this directory. The phase-two and
phase-three Python generators remain historical plans and MUST NOT be blindly
applied to the now-diverged source. In particular, a registry signing itself
with signers it supplies is not an independent trust root.

A second batch was removed from `.github/workflows` at convergence source
`4c51bb91c98d1415497ce5b8b02bf56519166b8c`; its exact bytes remain recoverable
from Git history:

- `kernel-evidence-exact-head-repair.yml`;
- `kernel-evidence-exact-head-repair-arm.yml`;
- `kernel-evidence-native-repair-arm.yml`;
- `kernel-evidence-native-repair-macos.yml`;
- `kernel-evidence-native-repair-v2.yml`;
- `kernel-evidence-one-shot-native-maintenance.yml`;
- `kernel-evidence-finalize-candidate.yml`.

Those jobs had repository-write authority and were bound to the superseded
`fix/kernel-evidence-production-closure` branch or fixed historical parent
commits. Leaving them in the executable workflow directory would preserve manual
source-mutation entry points and generate skipped/noisy checks on the dedicated
integration candidate.

The retained active workflows instead:

- evaluate immutable source-head and fixed-base synthetic-merge objects;
- retain diagnostics and fail closed on skipped or incomplete execution;
- synchronize canonical status projections and the implementation map through a
  branch-bound, race-checked two-commit finalizer;
- never grant independent acceptance, deployment, canary, promotion, merge, or
  release authority.
