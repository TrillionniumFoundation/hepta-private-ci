from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def read(p): return (ROOT/p).read_text()
def write(p,s): (ROOT/p).write_text(s)
def one(s,old,new,label):
    n=s.count(old)
    if n != 1: raise SystemExit(f"{label}: expected 1 occurrence, got {n}")
    return s.replace(old,new,1)

# apply_production_grant runs inside with_slot(), which removes the agent slot
# from self.slots for the duration of the closure. Any map-based revision lookup
# from inside that closure therefore reports UnknownAgent. Resolve the successor
# before entering with_slot and advance the slot held by the closure directly
# after durable intent publication.
p="codex-rs/hepta-supervisor/src/supervisor.rs"; s=read(p)
old='''    ) -> Result<ProductionMutationReceipt, SupervisorError> {
        self.with_slot(agent_id, |supervisor, slot| {
'''
new='''    ) -> Result<ProductionMutationReceipt, SupervisorError> {
        let next_control_revision = self.next_control_revision(agent_id)?;
        self.with_slot(agent_id, |supervisor, slot| {
'''
s=one(s,old,new,"precompute signed control revision")
s=one(s,"            let next_control_revision = supervisor.next_control_revision(agent_id)?;\n            let intent = SignedSupervisorIntent::new(","            let intent = SignedSupervisorIntent::new(","remove map lookup inside with_slot")
s=one(s,"            slot.signed_intent = Some(intent.clone());\n            supervisor.set_control_revision(agent_id, next_control_revision)?;","            slot.signed_intent = Some(intent.clone());\n            if next_control_revision != slot.control_revision.saturating_add(1) {\n                return Err(SupervisorError::Invalid(\n                    \"signed mutation control revision successor drifted\".to_string(),\n                ));\n            }\n            slot.control_revision = next_control_revision;","advance detached slot revision")
write(p,s)

# Add a narrow structural regression that specifically protects this ownership
# invariant even before the heavier signed-authority product test executes.
p="codex-rs/hepta-supervisor/src/supervisor_tests.rs"; s=read(p)
if "signed_control_revision_advances_on_detached_slot" not in s:
    s += r'''

#[test]
fn signed_control_revision_advances_on_detached_slot() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(supervisor.next_control_revision(&fleet.first)?, 1);
    supervisor.with_slot(&fleet.first, |_supervisor, slot| {
        let next = slot
            .control_revision
            .checked_add(1)
            .ok_or_else(|| SupervisorError::Invalid("control revision overflow".to_string()))?;
        slot.control_revision = next;
        Ok(())
    })?;
    assert_eq!(supervisor.next_control_revision(&fleet.first)?, 2);
    Ok(())
}
'''
write(p,s)

print("patch C staged")
