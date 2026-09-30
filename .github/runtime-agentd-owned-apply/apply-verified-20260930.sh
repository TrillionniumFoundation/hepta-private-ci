#!/usr/bin/env bash
set -Eeuo pipefail

trap 'rc=$?; printf "::error title=runtime.agentd carrier reconstruction failed::line=%s exit=%s command=%q\n" "$LINENO" "$rc" "$BASH_COMMAND" >&2; exit "$rc"' ERR

: "${TARGET_BRANCH:?}"
: "${EXPECTED_TARGET_HEAD:?}"
: "${MAIN_PATCH_SHA256:?}"
: "${AMENDMENT_SHA256:?}"
: "${RUNNER_TEMP:?}"

carrier_root=.github/runtime-agentd-owned-apply
remote_head="$(git ls-remote --heads origin "refs/heads/$TARGET_BRANCH" | cut -f1)"
if [[ "$remote_head" != "$EXPECTED_TARGET_HEAD" ]]; then
  echo "target branch drifted: expected $EXPECTED_TARGET_HEAD, observed $remote_head" >&2
  exit 1
fi

python3 - <<'PY'
from hashlib import sha256
from pathlib import Path
import os
import sys


def fail(message: str) -> None:
    print(f"::error title=runtime.agentd carrier integrity::{message}", file=sys.stderr)
    raise SystemExit(1)


expected = {
    'part-000.patch': 'b73eb90040a37b19a48d90c558b696da2ff9dc8e0835e7687bccf1880b3c0e9c',
    'part-001.patch': '19fc5a0e25b0b2110bd19e7b7c5a80508a61416514855642e1108cde1aa092d2',
    'part-002.patch': 'f2c95a4669cca4a0144e0b859fe08c50656a6518fe0448d0652fd7d1f09de965',
    'part-003.patch': '880dfa3f9b4b948198079d6a01f6eead334b099f41e9f14d2da1d5c25dfbf21a',
    'part-004.patch': '7bac3d5a1a2c248ba57b4d6c15c7b147ac1a3117e9dd3ffd3e341cc09101e135',
    'part-005.patch': 'b72bdb21ac539304f292273d368f150a021760e4acaa49f448922b4ec04e7a9c',
    'part-006.patch': '692876fcb5897cb2e41694775847729925b527437b9ffd8b82f80069003a3483',
    'part-007.patch': '22f830634a649b4a325bdbe5c1bf0c9ff45fde2ac6919204659738b58f7b7b3f',
    'part-008.patch': 'c8c3bae749e9b43ae8752235555343dc5d5c11308eb3220b03d5f02b9266ab33',
    'part-009.patch': 'f110b0ebbcd02261fcc66018d11f8008bb97ffe294725e9d43278ec399f7d634',
    'part-010.patch': '8389b76fac25e1b1064b20d038ebb2c6730dc02f28b4a277e52f59f246f3b909',
    'part-011.patch': '9c1d2606979893f221395b9f9e21d6511382b6a0013bedee72a608117955b146',
    'part-012.patch': '18e813b8755372474cebdc5cf89c0f0fc00030bbc69d9c726d2c2949cb4c4dce',
    'part-013.patch': '1927192c15d18f18219314241e300e0a7611c70dc708e3f2b09455166675f29c',
    'part-014.patch': '91402f2b9455c92f9f448b13137f8eee43fa7021ab5fed7e4907c4890e51a9b0',
    'part-015.patch': '5e5b15fa143d1dfffff42b05e027438f2cae93a8db210a46f14f407497b6e612',
    'part-016.patch': 'b256fab2a9eaba5aa4a32d4156a3dece27a506868a3642bc3745be4c04bef193',
    'part-017.patch': 'cdb61c6a7ef6eb98ef11ef997e49e19fc0185bcc55565072e478466209d66c37',
    'part-018.patch': '612a17174c21cdf23826293f9e608ec63957482ce892e168e9d90ba0f4794dc8',
    'part-019.patch': '5ba9279a45fe61118b2b3ac0dfb9405178c4396e2a7768732709b9cfb8d56318',
    'amend-000.patch': os.environ['AMENDMENT_SHA256'],
}
root = Path('.github/runtime-agentd-owned-apply')
observed = {path.name for path in root.glob('*.patch')}
if observed != set(expected):
    fail(
        f'carrier patch set mismatch: missing={sorted(set(expected)-observed)} '
        f'extra={sorted(observed-set(expected))}'
    )
for name, digest in expected.items():
    actual = sha256((root / name).read_bytes()).hexdigest()
    if actual != digest:
        fail(f'carrier digest mismatch for {name}: expected={digest} actual={actual}')
main = b''.join((root / f'part-{index:03d}.patch').read_bytes() for index in range(20))
main_digest = sha256(main).hexdigest()
if main_digest != os.environ['MAIN_PATCH_SHA256']:
    fail(
        'combined main patch digest mismatch: '
        f"expected={os.environ['MAIN_PATCH_SHA256']} actual={main_digest}"
    )
temp = Path(os.environ['RUNNER_TEMP'])
(temp / 'runtime-agentd-main.patch').write_bytes(main)
(temp / 'runtime-agentd-amendment.patch').write_bytes((root / 'amend-000.patch').read_bytes())
PY

git fetch --no-tags origin "$EXPECTED_TARGET_HEAD"
git reset --hard "$EXPECTED_TARGET_HEAD"
git clean -ffd
git apply --check --whitespace=error "$RUNNER_TEMP/runtime-agentd-main.patch"
git apply --whitespace=error "$RUNNER_TEMP/runtime-agentd-main.patch"
git apply --check --whitespace=error "$RUNNER_TEMP/runtime-agentd-amendment.patch"
git apply --whitespace=error "$RUNNER_TEMP/runtime-agentd-amendment.patch"
test "$(git rev-parse HEAD)" = "$EXPECTED_TARGET_HEAD"
git diff --check

python3 - <<'PY'
from pathlib import Path
import subprocess
import sys


def fail(message: str) -> None:
    print(f"::error title=runtime.agentd carrier source delta::{message}", file=sys.stderr)
    raise SystemExit(1)


expected = {
    '.github/workflows/hepta-agentd-exact-head.yml',
    '.github/workflows/hepta-agentd-prospective-merge.yml',
    '.github/workflows/runtime-agentd-format-repair.yml',
    '.github/workflows/runtime-agentd-source-capsule.yml',
    '.github/workflows/runtime-agentd-trust-boundary.yml',
    'codex-rs/hepta-agentd/DEPENDENCY_BOUNDARY.json',
    'codex-rs/hepta-agentd/src/error.rs',
    'codex-rs/hepta-agentd/src/lib.rs',
    'codex-rs/hepta-agentd/src/runtime_codex_executor_persistence.rs',
    'codex-rs/hepta-agentd/src/runtime_codex_executor_process.rs',
    'codex-rs/hepta-agentd/src/runtime_codex_executor_process_base.rs',
    'codex-rs/hepta-agentd/src/runtime_codex_executor_tests.rs',
    'codex-rs/hepta-agentd/src/runtime_codex_policy.rs',
    'codex-rs/hepta-agentd/src/runtime_codex_policy_tests.rs',
    'codex-rs/hepta-agentd/src/runtime_codex_supervisor.rs',
    'codex-rs/hepta-agentd/src/runtime_codex_supervisor_maintenance.rs',
    'codex-rs/hepta-agentd/src/state.rs',
    'codex-rs/hepta-agentd/src/state_isolation_tests.rs',
    'codex-rs/hepta-infer-worker-host/tests/native_host_process_e2e.rs',
    'docs/modules/runtime.agentd/REMEDIATION_EXECUTION_20260927.md',
    'docs/modules/runtime.agentd/TECHNICAL.md',
    'qualification/module-execution-dossiers/detail/runtime.agentd.md',
    'qualification/runtime-agentd-core/Cargo.lock',
    'qualification/runtime-agentd-core/Cargo.toml',
    'qualification/runtime-agentd-core/src/lib.rs',
    'scripts/qualification/agentd_exact_head.py',
    'scripts/qualification/runtime_agentd_dependency_boundary.py',
    'scripts/qualification/runtime_agentd_scope.py',
    'scripts/qualification/test_agentd_exact_head.py',
    'scripts/qualification/test_runtime_agentd_dependency_boundary.py',
    'scripts/qualification/test_runtime_agentd_scope.py',
}
observed = set(subprocess.check_output(['git', 'diff', '--name-only'], text=True).splitlines())
if observed != expected:
    fail(
        f'unexpected source delta: missing={sorted(expected-observed)} '
        f'extra={sorted(observed-expected)}'
    )
for path in expected:
    if not Path(path).exists():
        fail(f'expected path missing after apply: {path}')
PY
