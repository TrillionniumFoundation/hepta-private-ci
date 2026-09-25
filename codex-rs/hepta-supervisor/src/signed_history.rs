//! Immutable terminal history belonging to the existing signed-intent owner.
//! History is queryable evidence, never a grant or a second mutation authority.
use crate::ProductionMutationReceipt;
use crate::ProductionMutationState;
use crate::ProductionMutationStatus;
use crate::signed_intent::SignedIntentError as Error;
use crate::signed_intent::SignedIntentStatus;
use crate::signed_intent::SignedSupervisorIntent;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;

const PREFIX: &str = "supervisor-signed-history-";
const MAX_ARCHIVES: usize = 1_024;
const MAX_ARCHIVE_BYTES: u64 = 16_384;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct Archive {
    schema_version: u32,
    intent: SignedSupervisorIntent,
    transaction_sha256: Option<Sha256Digest>,
    archive_sha256: Sha256Digest,
}
impl Archive {
    fn digest(&self) -> Result<Sha256Digest, Error> {
        let mut bytes = b"hepta-supervisor:signed-history:v1".to_vec();
        bytes.extend(serde_json::to_vec(&(
            self.schema_version,
            &self.intent,
            &self.transaction_sha256,
        ))?);
        Ok(Sha256Digest::for_bytes(&bytes))
    }
    fn validate(&self) -> Result<(), Error> {
        self.intent.validate()?;
        if self.schema_version != 1
            || !terminal(self.intent.status)
            || self.archive_sha256 != self.digest()?
        {
            return Err(Error::Invalid(
                "invalid immutable signed history".to_string(),
            ));
        }
        Ok(())
    }
}
fn terminal(status: SignedIntentStatus) -> bool {
    matches!(
        status,
        SignedIntentStatus::Committed
            | SignedIntentStatus::RolledBack
            | SignedIntentStatus::Aborted
    )
}
fn options() -> OpenOptions {
    let mut value = OpenOptions::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        value
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .mode(0o600);
    }
    value
}
fn read(path: &Path) -> Result<Option<Archive>, Error> {
    match std::fs::symlink_metadata(path) {
        Ok(meta) if !meta.file_type().is_file() || meta.len() > MAX_ARCHIVE_BYTES => {
            return Err(Error::Invalid(
                "history is not a bounded regular file".to_string(),
            ));
        }
        Ok(_) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
    }
    let file = options().read(true).open(path)?;
    if !file.metadata()?.is_file() {
        return Err(Error::Invalid("history file identity changed".to_string()));
    }
    let mut bytes = Vec::new();
    file.take(MAX_ARCHIVE_BYTES + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_ARCHIVE_BYTES {
        return Err(Error::Invalid("history grew beyond bound".to_string()));
    }
    let archive: Archive = serde_json::from_slice(&bytes)?;
    archive.validate()?;
    Ok(Some(archive))
}

pub(crate) fn archive_terminal(run: &Path, intent: &SignedSupervisorIntent) -> Result<(), Error> {
    if !terminal(intent.status) {
        return Err(Error::Invalid(
            "cannot archive unresolved intent".to_string(),
        ));
    }
    let transaction = crate::release_transaction::read_release_transaction(run)
        .map_err(|error| Error::Invalid(error.to_string()))?;
    let transaction_sha256 = transaction
        .filter(|transaction| {
            transaction.grant_sha256.as_ref() == Some(&intent.grant_sha256)
                && transaction.agent_id == intent.agent_id
                && transaction.source_release == intent.source_release
                && transaction.target_release == intent.target_release
        })
        .map(|transaction| transaction.transaction_sha256);
    let mut archive = Archive {
        schema_version: 1,
        intent: intent.clone(),
        transaction_sha256,
        archive_sha256: Sha256Digest::for_bytes(b"pending"),
    };
    archive.archive_sha256 = archive.digest()?;
    archive.validate()?;
    let destination = run.join(format!("{PREFIX}{}.json", intent.grant_sha256.as_str()));
    if let Some(existing) = read(&destination)? {
        if existing != archive {
            return Err(Error::Invalid(
                "conflicting terminal grant identity".to_string(),
            ));
        }
        // Re-establish the publication barrier after a possibly lost sync ACK.
        #[cfg(unix)]
        std::fs::File::open(run)?.sync_all()?;
        #[cfg(windows)]
        options()
            .read(true)
            .write(true)
            .open(&destination)?
            .sync_all()?;
        return Ok(());
    }
    let mut count = 0;
    for entry in std::fs::read_dir(run)? {
        let name = entry?.file_name();
        if name.to_string_lossy().starts_with(PREFIX) {
            count += 1;
            if count >= MAX_ARCHIVES {
                return Err(Error::Invalid(
                    "signed history capacity reached; retain old receipts".to_string(),
                ));
            }
        }
    }
    let bytes = serde_json::to_vec(&archive)?;
    if bytes.len() as u64 > MAX_ARCHIVE_BYTES {
        return Err(Error::Invalid("signed archive exceeds bound".to_string()));
    }
    let staging = run.join(format!(".signed-history-{}.tmp", uuid::Uuid::new_v4()));
    let result = (|| {
        let mut file = options().create_new(true).write(true).open(&staging)?;
        file.write_all(&bytes)?;
        file.sync_all()?;
        crate::durable_publish::publish_new(&staging, &destination)?;
        Ok::<(), Error>(())
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&staging);
    }
    result
}

pub(crate) fn lookup(
    run: &Path,
    agent: &str,
    grant: &Sha256Digest,
) -> Result<Option<ProductionMutationState>, Error> {
    let path = run.join(format!("{PREFIX}{}.json", grant.as_str()));
    let Some(archive) = read(&path)? else {
        return Ok(None);
    };
    if archive.intent.agent_id != agent || &archive.intent.grant_sha256 != grant {
        return Err(Error::Invalid(
            "history does not bind requested agent/grant".to_string(),
        ));
    }
    state(archive.intent, archive.transaction_sha256).map(Some)
}

pub(crate) fn state(
    intent: SignedSupervisorIntent,
    transaction: Option<Sha256Digest>,
) -> Result<ProductionMutationState, Error> {
    let status = match intent.status {
        SignedIntentStatus::Prepared | SignedIntentStatus::Queued => {
            ProductionMutationStatus::Queued
        }
        SignedIntentStatus::Committed => ProductionMutationStatus::Committed,
        SignedIntentStatus::RolledBack => ProductionMutationStatus::RolledBack,
        SignedIntentStatus::RecoveryRequired => ProductionMutationStatus::RecoveryRequired,
        SignedIntentStatus::Aborted => ProductionMutationStatus::Aborted,
    };
    let control_revision = intent
        .expected_control_revision
        .checked_add(1)
        .ok_or_else(|| Error::Invalid("control revision overflow".to_string()))?;
    Ok(ProductionMutationState {
        receipt: ProductionMutationReceipt {
            grant_sha256: intent.grant_sha256,
            agent_id: intent.agent_id,
            transition: intent.transition,
            source_release: intent.source_release,
            target_release: intent.target_release,
            control_revision,
            status,
            production_authority: true,
            external_effects: true,
            operator_acceptance: true,
            promotion: true,
        },
        intent_sha256: intent.intent_sha256,
        release_transaction_sha256: transaction,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::H7H89ProductionTransition;
    use crate::signed_intent::read_intent;
    use crate::signed_intent::write_intent;

    fn intent(grant: &[u8]) -> SignedSupervisorIntent {
        SignedSupervisorIntent::new(
            Sha256Digest::for_bytes(grant),
            "agent-a",
            H7H89ProductionTransition::Upgrade,
            "source",
            "target",
            3,
            2,
            1,
            SignedIntentStatus::Committed,
        )
        .expect("intent")
    }

    #[test]
    fn new_grant_cannot_destroy_a_previous_terminal_result() -> Result<(), Error> {
        let temp = tempfile::tempdir()?;
        let original = intent(b"first");
        write_intent(temp.path(), &original)?;
        let newer = intent(b"second").with_status(SignedIntentStatus::Prepared)?;
        write_intent(temp.path(), &newer)?;
        let result =
            lookup(temp.path(), "agent-a", &original.grant_sha256)?.expect("historical terminal");
        assert_eq!(result.receipt.status, ProductionMutationStatus::Committed);
        assert_eq!(result.receipt.control_revision, 4);
        assert_eq!(result.receipt.grant_sha256, original.grant_sha256);
        assert_eq!(read_intent(temp.path())?, Some(newer));
        archive_terminal(temp.path(), &original)?;
        assert_eq!(
            lookup(temp.path(), "agent-a", &original.grant_sha256)?,
            Some(result)
        );
        assert!(lookup(temp.path(), "agent-b", &original.grant_sha256).is_err());
        Ok(())
    }

    #[test]
    fn retained_history_rejects_tampering_and_conflicting_terminal() -> Result<(), Error> {
        let temp = tempfile::tempdir()?;
        let original = intent(b"original");
        archive_terminal(temp.path(), &original)?;
        assert!(
            archive_terminal(
                temp.path(),
                &original.with_status(SignedIntentStatus::RolledBack)?
            )
            .is_err()
        );
        let path = temp
            .path()
            .join(format!("{PREFIX}{}.json", original.grant_sha256.as_str()));
        let mut bytes = std::fs::read(&path)?;
        bytes[10] ^= 1;
        std::fs::write(&path, bytes)?;
        assert!(lookup(temp.path(), "agent-a", &original.grant_sha256).is_err());
        Ok(())
    }

    #[test]
    fn full_history_preserves_the_previous_current_journal() -> Result<(), Error> {
        let temp = tempfile::tempdir()?;
        let original = intent(b"current");
        write_intent(temp.path(), &original)?;
        for index in 0..MAX_ARCHIVES {
            std::fs::write(
                temp.path().join(format!("{PREFIX}reserved-{index}.json")),
                b"reserved",
            )?;
        }
        let next = intent(b"next").with_status(SignedIntentStatus::Prepared)?;
        assert!(write_intent(temp.path(), &next).is_err());
        assert_eq!(read_intent(temp.path())?, Some(original));
        Ok(())
    }
}
