//! Durable one-entry tombstones in the original protected issuer CAS.
//! A retained Entered value is uncertain, never a new read opportunity.
use super::*;
use std::collections::BTreeMap;

const MAX_PAIRED_MATERIAL_ENTRIES: usize = 64;

pub(in crate::deployment_issuer) type PairedMaterialEntriesV1 =
    BTreeMap<String, PairedMaterialEntryV1>;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub(in crate::deployment_issuer) enum PairedMaterialEntryStateV1 {
    Entered,
    ReadCommitted { completed_sequence: u64 },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(in crate::deployment_issuer) struct PairedMaterialEntryV1 {
    schema_version: u32,
    original_delivery: String,
    semantic_sha256: String,
    entered_at_unix_ms: u64,
    entered_sequence: u64,
    pub(super) state: PairedMaterialEntryStateV1,
}

pub(super) enum PreparedMaterialEntry {
    Fresh { retained_state: IssuerState },
    Retained(PairedMaterialEntryStateV1),
}

fn validate_entries(state: &IssuerState) -> io::Result<()> {
    if state.paired_material_entries_v1.len() > MAX_PAIRED_MATERIAL_ENTRIES {
        return Err(denied("paired material entry capacity is corrupt"));
    }
    for (delivery, entry) in &state.paired_material_entries_v1 {
        let digest = |text: &str| {
            text.len() == 64
                && text
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
                && text.bytes().any(|b| b != b'0')
        };
        if entry.schema_version != 1
            || &entry.original_delivery != delivery
            || !digest(delivery)
            || !digest(&entry.semantic_sha256)
            || entry.entered_at_unix_ms == 0
            || entry.entered_sequence == 0
            || entry.entered_sequence > state.sequence
            || matches!(entry.state, PairedMaterialEntryStateV1::ReadCommitted { completed_sequence }
                if completed_sequence <= entry.entered_sequence || completed_sequence > state.sequence)
        {
            return Err(denied(
                "paired material entry version or monotonic identity is invalid",
            ));
        }
    }
    Ok(())
}

impl RegisteredRootPaired {
    /// The caller holds the original Registry and issuer request lock. The
    /// returned state proves the successful local CAS only, not a read permit.
    pub(super) fn retain_material_entry(
        &self,
        state: &IssuerState,
        semantic: Digest32,
        now: u64,
    ) -> io::Result<PreparedMaterialEntry> {
        validate_entries(state)?;
        let delivery = self.registration.request.original.delivery_id.to_string();
        if let Some(entry) = state.paired_material_entries_v1.get(&delivery) {
            if entry.semantic_sha256 != semantic.to_string() || now < entry.entered_at_unix_ms {
                return Err(denied(
                    "original paired entry is retained with different semantics",
                ));
            }
            return Ok(PreparedMaterialEntry::Retained(entry.state.clone()));
        }
        if state.paired_material_entries_v1.len() == MAX_PAIRED_MATERIAL_ENTRIES
            || semantic.is_zero()
        {
            return Err(denied(
                "paired material entry has no fresh bounded capacity",
            ));
        }
        let mut next = state.clone();
        next.sequence = state
            .sequence
            .checked_add(1)
            .ok_or_else(|| denied("issuer counter exhausted"))?;
        next.paired_material_entries_v1.insert(
            delivery.clone(),
            PairedMaterialEntryV1 {
                schema_version: 1,
                original_delivery: delivery,
                semantic_sha256: semantic.to_string(),
                entered_at_unix_ms: now,
                entered_sequence: next.sequence,
                state: PairedMaterialEntryStateV1::Entered,
            },
        );
        self.issuer.store.validate_record(STATE_OWNER, &next)?;
        // The nonempty versioned field also fences the old deny_unknown_fields
        // issuer decoder. No older writer may omit these consumed identities.
        self.issuer
            .store
            .compare_and_set(STATE_OWNER, state, &next)
            .map_err(io::Error::other)?;
        Ok(PreparedMaterialEntry::Fresh {
            retained_state: next,
        })
    }

    /// Commit only after all original content hashes and post-read live checks.
    /// Failure remains retained/uncertain; it never clears or reopens an entry.
    pub(super) fn commit_material_read(
        &self,
        retained: &IssuerState,
        semantic: Digest32,
    ) -> io::Result<IssuerState> {
        validate_entries(retained)?;
        let delivery = self.registration.request.original.delivery_id.to_string();
        let mut next = retained.clone();
        let entry = next
            .paired_material_entries_v1
            .get_mut(&delivery)
            .ok_or_else(|| denied("original paired material entry is missing"))?;
        if entry.semantic_sha256 != semantic.to_string()
            || entry.state != PairedMaterialEntryStateV1::Entered
        {
            return Err(denied(
                "original paired material entry is not the one pending read",
            ));
        }
        next.sequence = retained
            .sequence
            .checked_add(1)
            .ok_or_else(|| denied("issuer counter exhausted"))?;
        entry.state = PairedMaterialEntryStateV1::ReadCommitted {
            completed_sequence: next.sequence,
        };
        self.issuer.store.validate_record(STATE_OWNER, &next)?;
        self.issuer
            .store
            .compare_and_set(STATE_OWNER, retained, &next)
            .map_err(io::Error::other)?;
        Ok(next)
    }
}
