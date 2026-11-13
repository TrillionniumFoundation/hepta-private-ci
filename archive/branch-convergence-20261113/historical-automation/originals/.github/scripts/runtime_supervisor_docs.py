#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one replacement, found {count}: {old[:160]!r}")
    write(path, content.replace(old, new, 1))


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


source_commit = git("rev-parse", "HEAD")
source_tree = git("rev-parse", "HEAD^{tree}")

technical = "docs/modules/runtime.supervisor/TECHNICAL.md"
replace_once(
    technical,
    "The current supervisor serializes one Agent mutation at the owner lock, generation-fences every managed process, and persists crash-relevant state below the Agent run root: the exact process lease, bounded automatic-restart budget, unified release transaction and, for externally authorized transitions, a signed intent.\n",
    "The current supervisor preserves one authoritative lifecycle writer, generation-fences every managed process, and persists crash-relevant state below the Agent run root: the exact process lease, bounded automatic-restart budget, unified release transaction and, for externally authorized transitions, a signed intent. The daemon records per-operation lock acquisition count, contended acquisition count, cumulative/max wait time and cumulative/max hold time. Periodic work is collected under a short `TickPlan` lock and applied one Agent at a time under `TickAgent`; the runtime yields between Agents, so one slow process driver no longer holds the owner lock across an entire 256-Agent sweep. This is bounded interleaving, not multi-writer partitioning: every Agent effect and Fleet generation/CAS mutation still passes through the same writer fence.\n",
)
replace_once(
    technical,
    "[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.\n",
    "A qualification-only 256-instance harness covers a healthy fleet, 10%, 50% and 100% contention waves, deliberately slow process-driver and filesystem sections, and concurrent mutation/status traffic. Its JSON receipt reports operation-specific wait/hold totals and maxima and confirms whether injected HOL is visible. This source harness validates instrumentation and ordering; it is not target-host latency evidence. The selected host must still publish p50/p95/p99/max control latency, deadline misses, starvation and per-Agent recovery completion under the real driver and filesystem.\n\n[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.\n",
)
replace_once(
    technical,
    "Supplying the complete external grant/H7 verifier tuple selects the production release-authority posture: ordinary owner-local `Upgrade` and `Rollback` compatibility RPCs are rejected and release changes must use signed variants. Fleet owns the immutable release catalog plus per-Agent allow/revoke markers. The supervisor snapshots their bounded aggregate admission frontier into every registered source/target transaction and rejects any frontier drift at final start/rollback/recovery use. The deterministic compatibility-binding digest proves the exact source/target pair and policy cut used by this transaction; it is not by itself an independent semantic-compatibility approval. External selection/compatibility policy, signer rotation and deployment remain separately governed evidence.\n",
    "Supplying the complete external grant/H7 verifier tuple selects the production release-authority posture: ordinary owner-local `Upgrade` and `Rollback` compatibility RPCs are rejected and release changes must use signed variants. A separately owned `ProductionAuthorityPublisher` may rotate the pinned signer epoch or revoke an exact grant through generation-CAS updates; supervisord receives only the read capability and resolves the current signer/revocation state again immediately before final-use verification. `ProductionSupervisorCaller` provides the typed external dispatch boundary and verifies that the daemon receipt binds the dispatched grant. These source components do not make supervisord its own selector or signer, and they do not establish a deployed product caller. Fleet owns the immutable release catalog plus per-Agent allow/revoke markers. The supervisor snapshots their bounded aggregate admission frontier into every registered source/target transaction and rejects any frontier drift at final start/rollback/recovery use. The deterministic compatibility-binding digest proves the exact source/target pair and policy cut used by this transaction; it is not by itself an independent semantic-compatibility approval. External selection/compatibility policy, signer rotation deployment and independent acceptance remain separately governed evidence.\n\nThe additive read-only `Diagnostics` RPC exposes bounded lock metrics and, for one Agent, a typed recovery blocker plus operator action. Current blocker classes are process ambiguity, release-CAS ambiguity, intent/transaction mismatch, Fleet frontier drift, daemon authority-epoch change, durable-state failure and waiting for an independently signed recovery decision. Only `none` is retry-safe; recovery-required classes never instruct a blind replay.\n",
)
replace_once(
    technical,
    "- [codex-rs/hepta-supervisor/src/signed_intent_publish_tests.rs](../../../codex-rs/hepta-supervisor/src/signed_intent_publish_tests.rs); named case: `cross_directory_publish_rejects_without_changing_either_file`.\n",
    "- [codex-rs/hepta-supervisor/src/signed_intent_publish_tests.rs](../../../codex-rs/hepta-supervisor/src/signed_intent_publish_tests.rs); named case: `cross_directory_publish_rejects_without_changing_either_file`.\n- [codex-rs/hepta-supervisor/src/crash_qualification.rs](../../../codex-rs/hepta-supervisor/src/crash_qualification.rs) — subprocess SIGKILL after durable publication, injected storage/fsync/rename failures and lease/restart/intent/transaction truncation fail-closed checks.\n- [codex-rs/hepta-supervisor/src/lock_qualification.rs](../../../codex-rs/hepta-supervisor/src/lock_qualification.rs) — bounded 256-instance contention/HOL instrumentation harness.\n- [codex-rs/hepta-supervisor/src/production_authority_distribution.rs](../../../codex-rs/hepta-supervisor/src/production_authority_distribution.rs) — generation-fenced signer rotation, exact-grant revocation and stale/wrong signer rejection.\n- [codex-rs/hepta-supervisor/src/recovery_diagnostics.rs](../../../codex-rs/hepta-supervisor/src/recovery_diagnostics.rs) — total blocker-to-operator-action mapping.\n",
)
replace_once(
    technical,
    "| `observe_health` | `pub fn tick(` | `codex-rs/hepta-supervisor/src/supervisor.rs` | `codex-rs/hepta-supervisor/src/supervisor_tests.rs`, `unix_tests.rs` |\n",
    "| `observe_health` | `pub fn tick(` / `tick_agent(` | `codex-rs/hepta-supervisor/src/supervisor.rs` | `codex-rs/hepta-supervisor/src/supervisor_tests.rs`, `unix_tests.rs`, `lock_qualification.rs` |\n",
)

recovery = "docs/modules/runtime.supervisor/RECOVERY_AND_QUALIFICATION.md"
replace_once(
    recovery,
    "The following are required target-host tests. Source/unit tests are not substitutes for receipts from this matrix.\n",
    "The following are required target-host tests. Source/unit tests are not substitutes for receipts from this matrix. The crate now provides qualification-only named failpoints for lease, restart-journal, signed-intent and release-transaction storage, fsync, rename/publication and post-publication SIGKILL cuts. `crash_qualification::tests` runs those cuts in subprocesses and verifies prior-record preservation, old-or-new validity after SIGKILL and fail-closed truncation. That source evidence closes the executable harness gap only; real filesystem, disk-full, kernel and watchdog receipts remain required.\n",
)
replace_once(
    recovery,
    "The daemon currently serializes supervisor mutation/tick work through one async supervisor mutex. This is a correctness-preserving design but has a possible head-of-line latency cost because registry, filesystem and process-driver work occurs while the lock is held.\n",
    "The daemon retains one async supervisor mutex as the authoritative single-writer fence. It now instruments every acquisition by operation and splits periodic work into a short Agent-list collection phase followed by one lock acquisition per Agent, yielding between Agents. Read-only roster and snapshot paths collect Fleet records before taking the supervisor lock. This removes the measured structural cause of an all-fleet hold without inventing per-Agent writers or weakening Fleet generation/CAS ordering. Slow work inside one Agent operation can still delay a concurrent request, so target-host measurement remains mandatory.\n",
)
replace_once(
    recovery,
    "If the evidence shows unacceptable HOL blocking, the next architecture change should split collection/effect/application phases or introduce per-agent serialization while retaining FleetRegistry generation/CAS fences. Do not partition locking before the measurement demonstrates the need and the new ordering rules are specified.\n",
    "The qualification binary `hepta-supervisor-lock-qualification` exercises 256 contenders and emits operation-specific wait/hold metrics. Its deliberately slow sections must show visible HOL, proving the instrumentation detects the condition, while the daemon implementation uses out-of-lock collection plus per-Agent application so an ordinary periodic sweep no longer holds the lock for all Agents. Do not replace the remaining single writer with per-Agent writers unless target-host receipts still show unacceptable latency and a reviewed ordering proof covers FleetRegistry generation/CAS fences, release transactions and daemon-wide authority changes.\n",
)
replace_once(
    recovery,
    "Production completion still requires an independently composed caller/writer/authority path that produces the signed grant consumed by the supervisor. Until that composition has its own execution receipts and independent acceptance, describe this module as having a **native release transition engine**, not a completed production release-selection path.\n",
    "The source now includes a typed `ProductionSupervisorCaller` and a separately owned authority distribution with a write-only publisher/read-only daemon capability split, monotonic signer-epoch rotation, generation CAS and bounded exact-grant revocation. Supervisord repeats distribution lookup at final use, after the caller's preflight, so a racing rotation or revocation fails closed. Production completion still requires a named deployed selector, durable authority-distribution backend, authenticated transport, rotation/revocation propagation receipts and independent acceptance. Continue to describe this as a **native release transition engine with source-composed authority seams**, not a completed production release-selection path.\n",
)
replace_once(
    recovery,
    "- the existing release-transition, Matrix companion, lease/adoption, daemon protocol and production-authority tests.\n",
    "- the existing release-transition, Matrix companion, lease/adoption, daemon protocol and production-authority tests;\n- `crash_qualification::tests` for named storage/fsync/rename/SIGKILL/truncation cuts;\n- `supervisor_lock`, `lock_qualification` and the qualification binary for wait/hold measurement and 256-instance coverage;\n- `production_authority_distribution` for signer rotation, exact-grant revocation, wrong/stale signer and stale generation rejection;\n- `recovery_diagnostics` for exhaustive blocker-to-operator-action mapping.\n",
)

# Refresh the concise implementation dossier without changing external claims.
dossier = "qualification/module-execution-dossiers/detail/runtime.supervisor.md"
replace_once(
    dossier,
    "- **Implementation and operating references:** [docs/readiness/LANE_B_NATIVE_HOST.md](../../../docs/readiness/LANE_B_NATIVE_HOST.md), [docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json](../../../docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json).\n",
    "- **Contention and diagnostics:** supervisord records operation-specific lock wait/hold totals and maxima, collects the periodic Agent plan separately, and applies one Agent per lock acquisition with an async yield between Agents. The read-only diagnostics RPC reports those metrics plus a typed recovery blocker/operator action. The 256-instance harness is source qualification, not target-host latency evidence.\n- **Durability qualification:** qualification-only failpoints cover storage-full, fsync, rename/publication, post-publication SIGKILL and truncation for the process lease, restart record, signed intent and release transaction. Subprocess tests require prior-state preservation or a valid old/new record and reject corrupt bytes.\n- **External authority composition:** a separately owned publisher can rotate signer epochs or revoke exact grant digests under generation CAS; supervisord holds only a reader and resolves it again at final use. A typed external caller checks receipt/grant binding. Deployment, authenticated distribution and independent acceptance remain external.\n- **Implementation and operating references:** [docs/readiness/LANE_B_NATIVE_HOST.md](../../../docs/readiness/LANE_B_NATIVE_HOST.md), [docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json](../../../docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json), [docs/modules/runtime.supervisor/RECOVERY_AND_QUALIFICATION.md](../../../docs/modules/runtime.supervisor/RECOVERY_AND_QUALIFICATION.md).\n",
)
replace_once(
    dossier,
    "- **Remaining work:** exact-candidate CI, target-host/watchdog/drain/restart measurements, deployment of the external release-policy/authority distribution, named production caller evidence and independent operational acceptance remain separate gates. The source implementation does not by itself grant activation, promotion or release.\n",
    "- **Remaining work:** deterministic merge-candidate CI, real target-host/watchdog/drain/restart and filesystem-fault measurements, deployment of an authenticated durable release-policy/authority distribution, named production selector/caller receipts and independent operational acceptance remain separate gates. The source implementation does not by itself grant activation, promotion or release.\n",
)

mapping_path = ROOT / "docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json"
mapping = json.loads(mapping_path.read_text())
mapping["sourceBase"] = {"commit": source_commit, "tree": source_tree}
mapping["observedAtHead"] = {
    "commit": source_commit,
    "tree": source_tree,
    "interpretation": (
        "exact repository-controlled source observation after lock wait/hold instrumentation, "
        "out-of-lock tick planning plus per-Agent application, executable 256-instance source "
        "qualification, named durable fault injection, external authority rotation/revocation "
        "seams and actionable recovery diagnostics. Target-host measurements, deployed durable "
        "authority distribution, named product selection and independent acceptance remain external."
    ),
}
for path in [
    "codex-rs/hepta-supervisor/src/supervisor_lock.rs",
    "codex-rs/hepta-supervisor/src/lock_qualification.rs",
    "codex-rs/hepta-supervisor/src/crash_qualification.rs",
    "codex-rs/hepta-supervisor/src/production_authority_distribution.rs",
    "codex-rs/hepta-supervisor/src/production_caller.rs",
    "codex-rs/hepta-supervisor/src/recovery_diagnostics.rs",
    "codex-rs/hepta-supervisor/src/qualification_fault.rs",
    "qualification/runtime-supervisor/lock-qualification-source.json",
    "qualification/runtime-supervisor/fault-matrix-source.json",
]:
    if path not in mapping["observedSourcePaths"]:
        mapping["observedSourcePaths"].append(path)
mapping_path.write_text(json.dumps(mapping, indent=2) + "\n")

write(
    "qualification/runtime-supervisor/README.md",
    f'''# runtime.supervisor source qualification\n\nSource candidate: `{source_commit}` (`{source_tree}`).\n\n- `lock-qualification-source.json` records the bounded 256-instance synthetic contention harness and operation-specific lock wait/hold counters.\n- `fault-matrix-source.json` records the source tests that exercised named storage, fsync, rename/publication, SIGKILL and truncation cuts.\n\nThese receipts establish that the source harness executed for the recorded candidate. They are not target-host watchdog, latency, filesystem, deployment, independent-acceptance, activation, promotion or release evidence.\n''',
)

print(f"runtime.supervisor documentation rebound to source {source_commit}")
