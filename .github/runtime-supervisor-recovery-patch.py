from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def read(p): return (ROOT/p).read_text()
def write(p,s): (ROOT/p).write_text(s)
def one(s,old,new,label):
    n=s.count(old)
    if n != 1: raise SystemExit(f"{label}: expected 1, got {n}")
    return s.replace(old,new,1)

# Fix ownership check in the newly added recovery module.
p="codex-rs/hepta-supervisor/src/signed_recovery.rs"; s=read(p)
s=s.replace("matches!(main_adoption, Some(Adoption::Rejected))","matches!(main_adoption.as_ref(), Some(Adoption::Rejected))")
s=s.replace("matches!(matrix_adoption, Some(Adoption::Rejected))","matches!(matrix_adoption.as_ref(), Some(Adoption::Rejected))")
write(p,s)

# Signed intent gets an explicit terminal abort state; terminal states can be overwritten by a new grant.
p="codex-rs/hepta-supervisor/src/signed_intent.rs"; s=read(p)
s=one(s,"    Committed,\n    RecoveryRequired,","    Committed,\n    Aborted,\n    RecoveryRequired,","aborted status")
write(p,s)

# Wire module exports.
p="codex-rs/hepta-supervisor/src/lib.rs"; s=read(p)
needle="mod signed_intent;\n"
if s.count(needle)!=1: raise SystemExit("signed_intent module marker")
s=s.replace(needle,needle+"mod signed_recovery;\n",1)
# Place exports next to signed authority exports if possible, otherwise append.
exports='''pub use signed_recovery::SignedRecoveryFenceOutcome;\npub use signed_recovery::SignedRecoveryFenceReport;\npub use signed_recovery::SignedRecoveryResolution;\npub use signed_recovery::SignedRecoverySnapshot;\npub use signed_recovery::fence_signed_recovery;\npub use signed_recovery::inspect_signed_recovery;\npub use signed_recovery::resolve_signed_recovery;\n'''
if exports not in s:
    marker="pub use signed_authority::ProductionMutationReceipt;\n"
    if marker in s: s=s.replace(marker,marker+exports,1)
    else: s += "\n"+exports
write(p,s)

# Register the offline binary.
p="codex-rs/hepta-supervisor/Cargo.toml"; s=read(p)
entry='''\n[[bin]]\nname = "hepta-supervisor-recovery"\npath = "src/bin/hepta-supervisor-recovery.rs"\n'''
if 'name = "hepta-supervisor-recovery"' not in s:
    # Insert after supervisord binary declaration.
    marker='''[[bin]]\nname = "hepta-supervisord"\npath = "src/main.rs"\n'''
    if marker not in s: raise SystemExit("supervisord bin marker")
    s=s.replace(marker,marker+entry,1)
write(p,s)

# Daemon startup treats both committed and explicitly aborted intents as terminal,
# and unresolved recovery fences the Matrix companion too.
p="codex-rs/hepta-supervisor/src/supervisor.rs"; s=read(p)
s=one(s,"use crate::runtime::AgentSlot;\nuse crate::runtime::RuntimePhase;","use crate::runtime::AgentSlot;\nuse crate::runtime::MatrixRuntimePhase;\nuse crate::runtime::RuntimePhase;","matrix phase import")
s=one(s,"        if matches!(intent.status, SignedIntentStatus::Committed) {","        if matches!(\n            intent.status,\n            SignedIntentStatus::Committed | SignedIntentStatus::Aborted\n        ) {","terminal recovery states")
s=one(s,"            runtime.phase = RuntimePhase::Killing;\n        }\n        Err(SupervisorError::SignedIntentRecoveryRequired(","            runtime.phase = RuntimePhase::Killing;\n        }\n        if let Some(runtime) = slot.matrix.runtime.as_mut() {\n            let _ = runtime.process.kill();\n            runtime.fenced = true;\n            runtime.phase = MatrixRuntimePhase::Killing;\n        }\n        Err(SupervisorError::SignedIntentRecoveryRequired(","matrix recovery fence")
write(p,s)

# CLI conversion errors are explicit and platform-stable.
p="codex-rs/hepta-supervisor/src/bin/hepta-supervisor-recovery.rs"; s=read(p)
s=s.replace("PathBuf::from(required(&flags, \"--fleet-root\")?)","PathBuf::from(required(&flags, \"--fleet-root\")?.as_os_str())")
s=s.replace("let agent_id = AgentId::parse(os_text(required(&flags, \"--agent-id\")?, \"--agent-id\")?)?;","let agent_id = AgentId::parse(os_text(required(&flags, \"--agent-id\")?, \"--agent-id\")?)\n        .map_err(|error| anyhow::anyhow!(\"invalid --agent-id: {error}\"))?;")
s=s.replace(")?)?;\n            let control_revision = parse_u64(",")?)\n            .map_err(|error| anyhow::anyhow!(\"invalid --grant-sha256: {error}\"))?;\n            let control_revision = parse_u64(",1)
write(p,s)

# Technical docs point operators at the explicit pre-start ceremony.
p="docs/modules/runtime.supervisor/TECHNICAL.md"; s=read(p)
if "SIGNED_INTENT_RECOVERY.md" not in s:
    s += '''\n\n## Signed production mutation recovery\n\nA non-terminal `supervisor-signed-intent.json` remains fail-closed across daemon restart. Operators must use the pre-start ceremony in [SIGNED_INTENT_RECOVERY.md](./SIGNED_INTENT_RECOVERY.md); the daemon does not infer commit from liveness or from merely observing the target release. The ceremony fences exact main/Matrix leases first and requires explicit grant/control/lifecycle/release/authority witnesses before a terminal `committed` or `aborted` journal state is written.\n'''
write(p,s)

p="qualification/module-execution-dossiers/detail/runtime.supervisor.md"; s=read(p)
old="- **State and recovery:** Supervisor keeps managed-process phases in memory and uses FleetRegistry lifecycle/release facts for recovery. Generation and release predecessor checks govern drain/restart/upgrade/rollback; process liveness alone is not full readiness.\n"
new="- **State and recovery:** Supervisor keeps managed-process phases in memory and uses FleetRegistry lifecycle/release facts for recovery. Generation and release predecessor checks govern drain/restart/upgrade/rollback; process liveness alone is not full readiness. Non-terminal externally signed intents fail daemon startup closed and are resolved only through the explicit pre-start `hepta-supervisor-recovery` inspect/fence/resolve ceremony; both main and Matrix exact process leases must be fenced before a terminal commit/abort acknowledgement.\n"
s=one(s,old,new,"dossier recovery")
write(p,s)

print("signed recovery integration staged")
