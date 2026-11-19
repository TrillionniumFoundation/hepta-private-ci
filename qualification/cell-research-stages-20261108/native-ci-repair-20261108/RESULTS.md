# Native CI repair evidence

The memory product qualification now reads the immutable revision facts used by
fresh G14 projections. The old helper read the copied generation tables, which
G14 no longer populates. It still requires the storage witness, current
generation, exact memory revision and source, active verified facts, immutable
fact-set receipt, canonical digests, and the existing physical-send assertions.

The original f251 source failed the targeted test on both nextest attempts with
the same generation-receipt mismatch. The patched product target passed 9 tests
with 4 tests skipped by the existing configuration. The tests exercise memory
publication, restart, correction, forgetting, isolation, revocation and actual
request observations. Formatting removed one trailing blank line only; the
tested and formatted hashes and exact format diff remain in the archive.

The six-file CI repair canonicalizes temporary owner paths before creating
automation stores, retains scoped composition evidence before the full
workspace phase, and provisions native OpenSSH for the sandboxed operator
acceptance test action. All 163 tests in the automation and operator-acceptance
packages passed on native Linux. Official formatting passed with the six tested
file hashes unchanged. No production trust rule or test assertion was removed.

MANIFEST.json binds the baseline, tested candidates, integrated source files,
job identities, raw logs and format records. raw-evidence.tar.gz retains the
original failure as well as successful results. The Linux result does not prove
the Windows correction or the exact GitHub RBE routing; those remain CI checks.
The early upload change does not retrospectively establish why the earlier
composition job lost its logs.

S0 through S5 remain HOLD. These are engineering and evidence-retention repairs,
not equal-budget experimental results, owner authentication, or a joint
cross-stage executable qualification.
