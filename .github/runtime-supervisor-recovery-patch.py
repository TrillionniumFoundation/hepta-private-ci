from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def read(p): return (ROOT/p).read_text()
def write(p,s): (ROOT/p).write_text(s)
def one(s,old,new,label):
    n=s.count(old)
    if n != 1: raise SystemExit(f"{label}: expected 1, got {n}")
    return s.replace(old,new,1)

# Fix ownership check in the newly added recovery module and make the
# non-durable control revision witness explicit as the successor acknowledged
# by the operator, rather than pretending it can be re-read after restart.
p="codex-rs/hepta-supervisor/src/signed_recovery.rs"; s=read(p)
s=s.replace("matches!(main_adoption, Some(Adoption::Rejected))","matches!(main_adoption.as_ref(), Some(Adoption::Rejected))")
s=s.replace("matches!(matrix_adoption, Some(Adoption::Rejected))","matches!(matrix_adoption.as_ref(), Some(Adoption::Rejected))")
s=one(s,"    expected_control_revision: u64,\n    expected_lifecycle_generation: u64,","    expected_control_revision_successor: u64,\n    expected_lifecycle_generation: u64,","recovery revision argument")
s=one(s,"    if &intent.grant_sha256 != expected_grant_sha256\n        || intent.expected_control_revision != expected_control_revision\n        || intent.expected_lifecycle_generation > expected_lifecycle_generation","    let required_control_revision_successor = intent\n        .expected_control_revision\n        .checked_add(1)\n        .ok_or_else(|| SupervisorError::Invalid(\"signed recovery control revision overflow\".to_string()))?;\n    if &intent.grant_sha256 != expected_grant_sha256\n        || required_control_revision_successor != expected_control_revision_successor\n        || intent.expected_lifecycle_generation > expected_lifecycle_generation","recovery successor witness")
write(p,s)

# Signed intent gets an explicit terminal abort state; terminal states can be overwritten by a new grant.
p="codex-rs/hepta-supervisor/src/signed_intent.rs"; s=read(p)
s=one(s,"    Committed,\n    RecoveryRequired,","    Committed,\n    Aborted,\n    RecoveryRequired,","aborted status")
write(p,s)

# Wire module exports, including public intent/status types used by recovery snapshots.
p="codex-rs/hepta-supervisor/src/lib.rs"; s=read(p)
needle="mod signed_intent;\n"
if s.count(needle)!=1: raise SystemExit("signed_intent module marker")
s=s.replace(needle,needle+"mod signed_recovery;\n",1)
exports='''pub use signed_intent::SignedIntentStatus;\npub use signed_intent::SignedSupervisorIntent;\npub use signed_recovery::SignedRecoveryFenceOutcome;\npub use signed_recovery::SignedRecoveryFenceReport;\npub use signed_recovery::SignedRecoveryResolution;\npub use signed_recovery::SignedRecoverySnapshot;\npub use signed_recovery::fence_signed_recovery;\npub use signed_recovery::inspect_signed_recovery;\npub use signed_recovery::resolve_signed_recovery;\n'''
if exports not in s:
    marker="pub use signed_authority::ProductionMutationReceipt;\n"
    if marker in s: s=s.replace(marker,marker+exports,1)
    else: s += "\n"+exports
write(p,s)

# Register the offline binary.
p="codex-rs/hepta-supervisor/Cargo.toml"; s=read(p)
entry='''\n[[bin]]\nname = "hepta-supervisor-recovery"\npath = "src/bin/hepta-supervisor-recovery.rs"\ntest = false\n'''
if 'name = "hepta-supervisor-recovery"' not in s:
    marker='''[[bin]]\nname = "hepta-supervisord"\npath = "src/main.rs"\ntest = false\n'''
    if marker not in s: raise SystemExit("supervisord bin marker")
    s=s.replace(marker,marker+entry,1)
write(p,s)

# Daemon startup treats committed and explicitly aborted intents as terminal,
# future grants also accept either terminal state, and unresolved recovery fences
# the Matrix companion in addition to the main process.
p="codex-rs/hepta-supervisor/src/supervisor.rs"; s=read(p)
s=one(s,"use crate::runtime::AgentSlot;\nuse crate::runtime::RuntimePhase;","use crate::runtime::AgentSlot;\nuse crate::runtime::MatrixRuntimePhase;\nuse crate::runtime::RuntimePhase;","matrix phase import")
s=one(s,".is_some_and(|intent| !matches!(intent.status, SignedIntentStatus::Committed))",".is_some_and(|intent| {\n                    !matches!(\n                        intent.status,\n                        SignedIntentStatus::Committed | SignedIntentStatus::Aborted\n                    )\n                })","terminal admission states")
s=one(s,"        if matches!(intent.status, SignedIntentStatus::Committed) {","        if matches!(\n            intent.status,\n            SignedIntentStatus::Committed | SignedIntentStatus::Aborted\n        ) {","terminal recovery states")
s=one(s,"            runtime.phase = RuntimePhase::Killing;\n        }\n        Err(SupervisorError::SignedIntentRecoveryRequired(","            runtime.phase = RuntimePhase::Killing;\n        }\n        if let Some(runtime) = slot.matrix.runtime.as_mut() {\n            let _ = runtime.process.kill();\n            runtime.fenced = true;\n            runtime.phase = MatrixRuntimePhase::Killing;\n        }\n        Err(SupervisorError::SignedIntentRecoveryRequired(","matrix recovery fence")
write(p,s)

# CLI conversion errors are explicit and platform-stable, and the revision flag
# names the actual operator acknowledgement: the old epoch's successor revision.
p="codex-rs/hepta-supervisor/src/bin/hepta-supervisor-recovery.rs"; s=read(p)
s=s.replace("PathBuf::from(required(&flags, \"--fleet-root\")?)","PathBuf::from(required(&flags, \"--fleet-root\")?.as_os_str())")
s=s.replace("let agent_id = AgentId::parse(os_text(required(&flags, \"--agent-id\")?, \"--agent-id\")?)?;","let agent_id = AgentId::parse(os_text(required(&flags, \"--agent-id\")?, \"--agent-id\")?)\n        .map_err(|error| anyhow::anyhow!(\"invalid --agent-id: {error}\"))?;")
s=s.replace(")?)?;\n            let control_revision = parse_u64(",")?)\n            .map_err(|error| anyhow::anyhow!(\"invalid --grant-sha256: {error}\"))?;\n            let control_revision = parse_u64(",1)
s=s.replace("let control_revision = parse_u64(\n                required(&flags, \"--control-revision\")?,\n                \"--control-revision\",\n            )?;","let control_revision_successor = parse_u64(\n                required(&flags, \"--control-revision-successor\")?,\n                \"--control-revision-successor\",\n            )?;")
s=s.replace("                control_revision,\n                lifecycle_generation,","                control_revision_successor,\n                lifecycle_generation,")
s=s.replace("--control-revision N --lifecycle-generation N","--control-revision-successor N --lifecycle-generation N")
write(p,s)

# Technical docs point operators at the explicit pre-start ceremony.
p="docs/modules/runtime.supervisor/TECHNICAL.md"; s=read(p)
if "SIGNED_INTENT_RECOVERY.md" not in s:
    s += '''\n\n## Signed production mutation recovery\n\nA non-terminal `supervisor-signed-intent.json` remains fail-closed across daemon restart. Operators must use the pre-start ceremony in [SIGNED_INTENT_RECOVERY.md](./SIGNED_INTENT_RECOVERY.md); the daemon does not infer commit from liveness or from merely observing the target release. The ceremony fences exact main/Matrix leases first and requires explicit grant, old-epoch control-revision successor acknowledgement, current lifecycle/release generations and authority-epoch witnesses before a terminal `committed` or `aborted` journal state is written. `control_revision` is supervisor-epoch memory state rather than a restart-persistent fact; the recovery CLI therefore validates the acknowledged successor against the signed intent instead of claiming to re-read it from disk.\n'''
write(p,s)

p="docs/modules/runtime.supervisor/SIGNED_INTENT_RECOVERY.md"; s=read(p)
s=s.replace("the intent's expected control revision, the current FleetRegistry lifecycle generation","the old epoch's control-revision successor (exactly `intent.expected_control_revision + 1`), the current FleetRegistry lifecycle generation")
s=s.replace("Use the grant digest, expected control revision, and authority epoch from the durable signed intent.","Use the grant digest and authority epoch from the durable signed intent, and acknowledge the old epoch's control-revision successor as `intent.expected_control_revision + 1`. The successor is an explicit recovery witness; it is not represented as restart-persistent supervisor state.")
s=s.replace("--control-revision <n>","--control-revision-successor <n>")
write(p,s)

p="qualification/module-execution-dossiers/detail/runtime.supervisor.md"; s=read(p)
old="- **State and recovery:** Supervisor keeps managed-process phases in memory and uses FleetRegistry lifecycle/release facts for recovery. Generation and release predecessor checks govern drain/restart/upgrade/rollback; process liveness alone is not full readiness.\n"
new="- **State and recovery:** Supervisor keeps managed-process phases in memory and uses FleetRegistry lifecycle/release facts for recovery. Generation and release predecessor checks govern drain/restart/upgrade/rollback; process liveness alone is not full readiness. Non-terminal externally signed intents fail daemon startup closed and are resolved only through the explicit pre-start `hepta-supervisor-recovery` inspect/fence/resolve ceremony; both main and Matrix exact process leases must be fenced before a terminal commit/abort acknowledgement. Because control revision is scoped to one supervisor epoch rather than durable across restart, recovery requires an explicit successor acknowledgement while release/lifecycle generations remain the mechanically checked durable state witnesses.\n"
s=one(s,old,new,"dossier recovery")
write(p,s)

print("signed recovery integration staged")
