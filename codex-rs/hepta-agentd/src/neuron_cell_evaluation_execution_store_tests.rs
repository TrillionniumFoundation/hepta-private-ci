//! Real original raw files and independent file witnesses. Fault wrappers
//! inject only lost witness acknowledgements around actual persistent writes.
//! No execution or signature is manufactured by this storage qualification.

use std::fs;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::path::PathBuf;

use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::*;

type Owner = OriginalCellEvaluationExecutionStoreV1<FileAnchorWitnessStore>;

fn d(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}
fn key() -> anyhow::Result<ProductEvaluationExecutionKeyV1> {
    Ok(ProductEvaluationExecutionKeyV1 {
        plan_id: StableId::new("original-execution-plan")?,
        binding_digest: d("original-execution-key"),
    })
}

struct Fixture {
    root: PathBuf,
    _directory: tempfile::TempDir,
}
impl Fixture {
    fn new() -> anyhow::Result<Self> {
        let directory = tempfile::tempdir()?;
        Ok(Self {
            root: directory.path().canonicalize()?,
            _directory: directory,
        })
    }
    fn new_file(&self, name: &str) -> anyhow::Result<File> {
        Ok(OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(self.root.join(name))?)
    }
    fn existing_file(&self, name: &str) -> anyhow::Result<File> {
        Ok(OpenOptions::new()
            .read(true)
            .write(true)
            .open(self.root.join(name))?)
    }
    fn witness(&self, file: File) -> anyhow::Result<FileAnchorWitnessStore> {
        Ok(FileAnchorWitnessStore::open(
            file,
            JournalScope {
                scope_digest: d("original-execution-test-scope"),
                objective_digest: d("original-execution-test-objective"),
            },
            Generation::new(1)?,
            64,
        )?)
    }
    fn create(&self) -> anyhow::Result<Owner> {
        Ok(Owner::create(
            self.new_file("raw")?,
            self.witness(self.new_file("witness")?)?,
            d("original-raw-binding"),
        )?)
    }
    fn recover(&self) -> anyhow::Result<Result<Owner, Error>> {
        Ok(Owner::recover(
            self.existing_file("raw")?,
            self.witness(self.existing_file("witness")?)?,
            d("original-raw-binding"),
        ))
    }
    fn bytes(&self) -> anyhow::Result<[Vec<u8>; 2]> {
        Ok([
            fs::read(self.root.join("raw"))?,
            fs::read(self.root.join("witness"))?,
        ])
    }
    fn overwrite(&self, name: &str, bytes: &[u8]) -> anyhow::Result<()> {
        let mut file = OpenOptions::new().write(true).open(self.root.join(name))?;
        file.set_len(bytes.len() as u64)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        Ok(())
    }
}

#[derive(Clone, Copy)]
enum LostAck {
    BeforeWrite,
    AfterWrite,
}
struct FaultWitness {
    original: FileAnchorWitnessStore,
    sequence: u64,
    fault: LostAck,
}
impl AnchorWitnessStore for FaultWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.original.current()
    }
    fn compare_and_swap(
        &mut self,
        before: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        if next.sequence == self.sequence {
            if matches!(self.fault, LostAck::AfterWrite) {
                self.original.compare_and_swap(before, next)?;
            }
            return Err(WitnessStoreError::Indeterminate);
        }
        self.original.compare_and_swap(before, next)
    }
}

#[test]
fn original_execution_owner_preserves_missing_pending_and_completed_after_recovery()
-> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    let mut owner = fixture.create()?;
    let key = key()?;
    let initial = fixture.bytes()?;
    assert_eq!(owner.require_current()?.sequence, 1);
    assert_eq!(owner.readback(&key), Err(StoreError::Missing));
    assert_eq!(owner.complete(&key, b"unclaimed"), Err(StoreError::Missing));
    let mut invalid = key.clone();
    invalid.binding_digest = Digest32::ZERO;
    assert_eq!(owner.claim(&invalid), Err(StoreError::Rejected));
    assert_eq!(fixture.bytes()?, initial);
    drop(owner);
    let mut owner = fixture.recover()??;
    assert_eq!(owner.readback(&key), Err(StoreError::Missing));
    assert_eq!(fixture.bytes()?, initial);
    assert_eq!(
        owner.claim(&key)?,
        ProductEvaluationExecutionClaimV1::Claimed
    );
    assert_eq!(owner.require_current()?.sequence, 2);
    assert_eq!(owner.readback(&key)?, State::Pending);
    let pending = fixture.bytes()?;
    assert_eq!(
        owner.claim(&key)?,
        ProductEvaluationExecutionClaimV1::Existing(State::Pending)
    );
    let mut other = key.clone();
    other.binding_digest = d("different-original-binding");
    assert_eq!(owner.claim(&other), Err(StoreError::Conflict));
    assert_eq!(
        owner.complete(&other, b"changed"),
        Err(StoreError::Conflict)
    );
    assert_eq!(owner.readback(&other), Err(StoreError::Conflict));
    assert_eq!(owner.complete(&key, b""), Err(StoreError::Rejected));
    assert_eq!(fixture.bytes()?, pending);
    drop(owner);
    let mut owner = fixture.recover()??;
    assert_eq!(owner.readback(&key)?, State::Pending);
    assert_eq!(fixture.bytes()?, pending);
    owner.complete(&key, b"original-completed-execution")?;
    assert_eq!(owner.require_current()?.sequence, 3);
    let complete = State::Completed(b"original-completed-execution".to_vec());
    let completed = fixture.bytes()?;
    assert_eq!(owner.readback(&key)?, complete);
    owner.complete(&key, b"original-completed-execution")?;
    assert_eq!(
        owner.complete(&key, b"different"),
        Err(StoreError::Conflict)
    );
    assert_eq!(
        owner.claim(&key)?,
        ProductEvaluationExecutionClaimV1::Existing(complete.clone())
    );
    assert_eq!(fixture.bytes()?, completed);
    drop(owner);
    let mut owner = fixture.recover()??;
    assert_eq!(owner.readback(&key)?, complete);
    assert_eq!(fixture.bytes()?, completed);
    Ok(())
}

#[test]
fn original_execution_owner_creation_and_recovery_never_repair_partial_anchors()
-> anyhow::Result<()> {
    for fault in [LostAck::BeforeWrite, LostAck::AfterWrite] {
        let fixture = Fixture::new()?;
        let result = OriginalCellEvaluationExecutionStoreV1::create(
            fixture.new_file("raw")?,
            FaultWitness {
                original: fixture.witness(fixture.new_file("witness")?)?,
                sequence: 1,
                fault,
            },
            d("original-raw-binding"),
        );
        assert!(matches!(
            result,
            Err(Error::Witness(WitnessStoreError::Indeterminate))
        ));
        let partial = fixture.bytes()?;
        assert!(!partial[0].is_empty());
        match fault {
            LostAck::BeforeWrite => {
                assert!(matches!(
                    fixture.recover()?,
                    Err(Error::Binding("original execution witness missing"))
                ));
            }
            LostAck::AfterWrite => {
                let mut recovered = fixture.recover()??;
                assert_eq!(recovered.readback(&key()?), Err(StoreError::Missing));
            }
        }
        assert_eq!(fixture.bytes()?, partial);
    }
    let fixture = Fixture::new()?;
    let owner = fixture.create()?;
    drop(owner);
    let initialized = fixture.bytes()?;
    assert!(matches!(
        Owner::create(
            fixture.existing_file("raw")?,
            fixture.witness(fixture.existing_file("witness")?)?,
            d("original-raw-binding")
        ),
        Err(Error::Binding("execution witness already initialized"))
    ));
    assert_eq!(fixture.bytes()?, initialized);
    let empty = fixture.witness(fixture.new_file("empty-witness")?)?;
    let empty_bytes = fs::read(fixture.root.join("empty-witness"))?;
    assert!(matches!(
        Owner::create(
            fixture.existing_file("raw")?,
            empty,
            d("original-raw-binding")
        ),
        Err(Error::File(
            LockedFileProductEvaluationExecutionErrorV1::AlreadyInitialized
        ))
    ));
    assert_eq!(fixture.bytes()?, initialized);
    assert_eq!(fs::read(fixture.root.join("empty-witness"))?, empty_bytes);
    assert!(matches!(
        Owner::recover(
            fixture.existing_file("raw")?,
            fixture.witness(fixture.existing_file("empty-witness")?)?,
            d("original-raw-binding")
        ),
        Err(Error::Binding("original execution witness missing"))
    ));
    assert_eq!(fixture.bytes()?, initialized);
    assert_eq!(fs::read(fixture.root.join("empty-witness"))?, empty_bytes);
    Ok(())
}

#[test]
fn original_execution_owner_lost_claim_ack_preserves_pending_or_uncertainty() -> anyhow::Result<()>
{
    for fault in [LostAck::BeforeWrite, LostAck::AfterWrite] {
        let fixture = Fixture::new()?;
        let mut owner = OriginalCellEvaluationExecutionStoreV1::create(
            fixture.new_file("raw")?,
            FaultWitness {
                original: fixture.witness(fixture.new_file("witness")?)?,
                sequence: 2,
                fault,
            },
            d("original-raw-binding"),
        )?;
        let before = fixture.bytes()?;
        assert_eq!(owner.claim(&key()?), Err(StoreError::Indeterminate));
        let uncertain = fixture.bytes()?;
        assert_ne!(uncertain[0], before[0]);
        assert_eq!(owner.claim(&key()?), Err(StoreError::Indeterminate));
        assert_eq!(
            owner.complete(&key()?, b"must-not-complete"),
            Err(StoreError::Indeterminate)
        );
        assert_eq!(owner.readback(&key()?), Err(StoreError::Indeterminate));
        assert_eq!(fixture.bytes()?, uncertain);
        drop(owner);
        match fault {
            LostAck::BeforeWrite => {
                assert_eq!(uncertain[1], before[1]);
                assert!(matches!(fixture.recover()?, Err(Error::CommitUncertain)));
            }
            LostAck::AfterWrite => {
                assert_ne!(uncertain[1], before[1]);
                let mut recovered = fixture.recover()??;
                assert_eq!(recovered.readback(&key()?)?, State::Pending);
                assert_eq!(
                    recovered.claim(&key()?)?,
                    ProductEvaluationExecutionClaimV1::Existing(State::Pending)
                );
            }
        }
        assert_eq!(fixture.bytes()?, uncertain);
    }
    Ok(())
}

#[test]
fn original_execution_owner_lost_completion_ack_preserves_completed_or_uncertainty()
-> anyhow::Result<()> {
    for fault in [LostAck::BeforeWrite, LostAck::AfterWrite] {
        let fixture = Fixture::new()?;
        let mut owner = OriginalCellEvaluationExecutionStoreV1::create(
            fixture.new_file("raw")?,
            FaultWitness {
                original: fixture.witness(fixture.new_file("witness")?)?,
                sequence: 3,
                fault,
            },
            d("original-raw-binding"),
        )?;
        assert_eq!(
            owner.claim(&key()?)?,
            ProductEvaluationExecutionClaimV1::Claimed
        );
        let before = fixture.bytes()?;
        assert_eq!(
            owner.complete(&key()?, b"original-completed"),
            Err(StoreError::Indeterminate)
        );
        let uncertain = fixture.bytes()?;
        assert_ne!(uncertain[0], before[0]);
        assert_eq!(
            owner.complete(&key()?, b"original-completed"),
            Err(StoreError::Indeterminate)
        );
        assert_eq!(owner.readback(&key()?), Err(StoreError::Indeterminate));
        assert_eq!(fixture.bytes()?, uncertain);
        drop(owner);
        match fault {
            LostAck::BeforeWrite => {
                assert_eq!(uncertain[1], before[1]);
                assert!(matches!(fixture.recover()?, Err(Error::CommitUncertain)));
            }
            LostAck::AfterWrite => {
                assert_ne!(uncertain[1], before[1]);
                let mut recovered = fixture.recover()??;
                assert_eq!(
                    recovered.readback(&key()?)?,
                    State::Completed(b"original-completed".to_vec())
                );
                recovered.complete(&key()?, b"original-completed")?;
            }
        }
        assert_eq!(fixture.bytes()?, uncertain);
    }
    Ok(())
}

#[test]
fn original_execution_owner_physical_corruption_fences_even_after_restore() -> anyhow::Result<()> {
    for name in ["raw", "witness"] {
        let fixture = Fixture::new()?;
        let mut owner = fixture.create()?;
        owner.claim(&key()?)?;
        owner.complete(&key()?, b"actual-retained-execution")?;
        let original = fixture.bytes()?;
        let index = if name == "raw" { 0 } else { 1 };
        let mut corrupt = original[index].clone();
        corrupt[0] ^= 1;
        fixture.overwrite(name, &corrupt)?;
        assert_eq!(
            owner.readback(&key()?),
            Err(StoreError::Indeterminate),
            "physical {name} corruption must fence the original owner"
        );
        fixture.overwrite(name, &original[index])?;
        assert_eq!(fixture.bytes()?, original);
        assert_eq!(owner.readback(&key()?), Err(StoreError::Indeterminate));
        assert_eq!(owner.claim(&key()?), Err(StoreError::Indeterminate));
        assert_eq!(
            owner.complete(&key()?, b"actual-retained-execution"),
            Err(StoreError::Indeterminate)
        );
        assert_eq!(fixture.bytes()?, original);
    }
    Ok(())
}

#[test]
fn original_execution_owner_cold_recovery_refuses_corruption_and_retains_exact_completion()
-> anyhow::Result<()> {
    for name in ["raw", "witness"] {
        let fixture = Fixture::new()?;
        let mut owner = fixture.create()?;
        let key = key()?;
        owner.claim(&key)?;
        owner.complete(&key, b"actual-retained-execution")?;
        let original = fixture.bytes()?;
        let index = if name == "raw" { 0 } else { 1 };
        let mut corrupt = original[index].clone();
        corrupt[0] ^= 1;

        fixture.overwrite(name, &corrupt)?;
        let damaged = fixture.bytes()?;
        assert_eq!(owner.readback(&key), Err(StoreError::Indeterminate));
        assert_eq!(fixture.bytes()?, damaged, "readback must not repair {name}");
        fixture.overwrite(name, &original[index])?;
        assert_eq!(owner.readback(&key), Err(StoreError::Indeterminate));
        assert_eq!(fixture.bytes()?, original);
        drop(owner);

        // Admit the actual original witness before corrupting either input.
        // Recovery must reread it rather than trust this admitted cache.
        let witness = fixture.witness(fixture.existing_file("witness")?)?;
        fixture.overwrite(name, &corrupt)?;
        let damaged = fixture.bytes()?;
        let recovery = Owner::recover(
            fixture.existing_file("raw")?,
            witness,
            d("original-raw-binding"),
        );
        match name {
            "raw" => assert!(matches!(
                recovery,
                Err(Error::File(
                    LockedFileProductEvaluationExecutionErrorV1::Corrupt
                ))
            )),
            "witness" => assert!(matches!(
                recovery,
                Err(Error::Witness(WitnessStoreError::ContextMismatch))
            )),
            _ => unreachable!("fixture input"),
        }
        assert_eq!(fixture.bytes()?, damaged, "recovery must not repair {name}");

        // A fresh owner may accept the exact trusted originals. It must retain
        // Completed, so claiming cannot create a fresh Pending execution.
        fixture.overwrite(name, &original[index])?;
        let mut recovered = fixture.recover()??;
        let completed = State::Completed(b"actual-retained-execution".to_vec());
        assert_eq!(recovered.readback(&key)?, completed);
        assert_eq!(
            recovered.claim(&key)?,
            ProductEvaluationExecutionClaimV1::Existing(completed)
        );
        recovered.complete(&key, b"actual-retained-execution")?;
        assert_eq!(fixture.bytes()?, original);
    }
    Ok(())
}

#[test]
fn original_execution_owner_readback_port_rejects_writes_keys_and_unwitnessed_tail()
-> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    let mut owner = fixture.create()?;
    let key = key()?;
    let mut other = key.clone();
    other.binding_digest = d("substituted-fixed-key");
    let empty = fixture.bytes()?;
    {
        let mut port = owner.readback_only(&key);
        assert_eq!(port.claim(&key), Err(StoreError::Rejected));
        assert_eq!(port.complete(&key, b"forbidden"), Err(StoreError::Rejected));
        assert_eq!(port.readback(&other), Err(StoreError::Conflict));
        assert_eq!(port.readback(&key), Err(StoreError::Missing));
    }
    assert_eq!(fixture.bytes()?, empty);
    assert_eq!(
        owner.claim(&key)?,
        ProductEvaluationExecutionClaimV1::Claimed
    );
    let pending = fixture.bytes()?;
    {
        let mut port = owner.readback_only(&key);
        assert_eq!(port.readback(&key)?, State::Pending);
        assert_eq!(port.complete(&key, b"forbidden"), Err(StoreError::Rejected));
    }
    assert_eq!(fixture.bytes()?, pending);
    owner.complete(&key, b"original-completed")?;
    let completed = fixture.bytes()?;
    {
        let mut port = owner.readback_only(&key);
        assert_eq!(
            port.readback(&key)?,
            State::Completed(b"original-completed".to_vec())
        );
    }
    assert_eq!(fixture.bytes()?, completed);
    drop(owner);
    // Independently roll back only the witness to its valid earlier frame.
    // Raw recover can see this prefix, but the owner must reject its suffix.
    fixture.overwrite("witness", &pending[1])?;
    let unwitnessed = fixture.bytes()?;
    assert!(matches!(fixture.recover()?, Err(Error::CommitUncertain)));
    assert_eq!(fixture.bytes()?, unwitnessed);
    Ok(())
}
