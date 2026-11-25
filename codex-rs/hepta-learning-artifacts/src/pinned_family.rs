//! Read-only all-or-nothing parameter-family artifact guard.
//! The host must own the initial pins, expected IDs and trust identity.
//! This guard is not a selection or installation authority.
use super::*;
use crate::{ArtifactKind, LearningArtifactOwnerHost};
use codex_hepta_types::StableId;

#[derive(Debug)]
pub struct ParameterFamilyGuardV1 {
    parent: LoadedPinnedCandidate,
    updates: Vec<LoadedPinnedCandidate>,
    trust_digest: Digest32,
    unavailable: bool,
}
impl ParameterFamilyGuardV1 {
    /// All pins must have been independently loaded from the same exact receipt.
    /// Expected IDs come from the registered finite profile, not a proposal.
    pub fn new(
        parent: LoadedPinnedCandidate,
        updates: Vec<LoadedPinnedCandidate>,
        expected: &[StableId],
        trust_digest: Digest32,
    ) -> Result<Self, PinnedCandidateLoadError> {
        let p = &parent.spec.manifest;
        let next = p.generation.next().map_err(|_| PinnedCandidateLoadError::PinMismatch)?;
        if p.kind != ArtifactKind::Parameters || trust_digest.is_zero()
            || parent.spec.registry_receipt.records == 0
            || updates.len() > 31 || updates.len() != expected.len()
            || !expected.windows(2).all(|w| w[0] < w[1])
        {
            return Err(PinnedCandidateLoadError::PinMismatch);
        }
        for (u, id) in updates.iter().zip(expected) {
            let m = &u.spec.manifest;
            if &m.artifact_id != id || m.kind != ArtifactKind::Parameters
                || m.predecessor_id.as_ref() != Some(&p.artifact_id)
                || m.generation != next || m.objective_digest != p.objective_digest
                || m.compatibility_digest != p.compatibility_digest
                || u.spec.registry_receipt != parent.spec.registry_receipt
            {
                return Err(PinnedCandidateLoadError::PinMismatch);
            }
        }
        Ok(Self { parent, updates, trust_digest, unavailable: false })
    }

    /// Obtain CURRENT from the actual artifact owner, not from request data.
    /// Callback must be read-only; caller still owns effect fencing and trusted
    /// time. One authenticated view covers the entire family. No partial
    /// callback, no fallback to cached bytes after any error or panic.
    pub fn with_owner<T>(
        &mut self, owner: &LearningArtifactOwnerHost, now: u64,
        consume: impl FnOnce(&LoadedPinnedCandidate, &[LoadedPinnedCandidate], Digest32) -> T,
    ) -> Result<T, PinnedCandidateLoadError> {
        if self.unavailable { return Err(PinnedCandidateLoadError::Unavailable); }
        self.unavailable = true;
        let current = owner.current_registry_view(now)
            .map_err(|_| PinnedCandidateLoadError::Unavailable)?;
        self.check_current(current, consume)
    }

    /// Read one complete family through the named product writer service.
    /// A pending publication blocks family delivery. This is read-only and
    /// does not grant authority to install parameters or perform effects.
    pub fn with_service<T>(
        &mut self, owner: &crate::LearningArtifactOwnerService, now: u64,
        consume: impl FnOnce(&LoadedPinnedCandidate, &[LoadedPinnedCandidate], Digest32) -> T,
    ) -> Result<T, PinnedCandidateLoadError> {
        if self.unavailable { return Err(PinnedCandidateLoadError::Unavailable); }
        self.unavailable = true;
        if owner.recovery_required().is_some() {
            return Err(PinnedCandidateLoadError::Unavailable);
        }
        let current = owner.current_registry_view(now)
            .map_err(|_| PinnedCandidateLoadError::Unavailable)?;
        self.check_current(current, consume)
    }

    fn check_current<T>(
        &mut self, current: VerifiedCurrentRegistryViewV1,
        consume: impl FnOnce(&LoadedPinnedCandidate, &[LoadedPinnedCandidate], Digest32) -> T,
    ) -> Result<T, PinnedCandidateLoadError> {
        // Called only after the public entry point has closed the latch.
        let previous = self.parent.spec.registry_receipt;
        let receipt = current.receipt();
        let registry = current.registry();
        if current.trust_digest() != self.trust_digest
            || current.witness_digest().is_zero()
            || receipt.binding != previous.binding || receipt.records < previous.records
            || registry.records().get(previous.records - 1)
                .map(|record| record.chain_digest) != Some(previous.head_digest)
        {
            return Err(PinnedCandidateLoadError::FrontierMismatch);
        }
        for pin in std::iter::once(&self.parent).chain(self.updates.iter()) {
            let m = &pin.spec.manifest;
            if registry.manifest(&m.artifact_id) != Some(m) {
                return Err(PinnedCandidateLoadError::PinMismatch);
            }
            if !registry.is_eligible(&m.artifact_id) {
                return Err(PinnedCandidateLoadError::Ineligible);
            }
        }
        // Mutate all pins only after all validations succeed.
        self.parent.spec.registry_receipt = receipt;
        for pin in &mut self.updates { pin.spec.registry_receipt = receipt; }
        let result = consume(&self.parent, &self.updates, current.witness_digest());
        self.unavailable = false;
        Ok(result)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{ArtifactEvent, ArtifactRegistry, ArtifactState, CreateOnlyArtifactFile,
        StateChange, write_candidate_payload, write_registry_snapshot};
    use codex_hepta_types::Generation;
    use std::fs::File;
    fn id(s:&str)->StableId { StableId::new(s).unwrap() }
    fn d(s:&str)->Digest32 { Digest32::of_bytes(s.as_bytes()) }
    fn manifest(name:&str,g:u64,parent:Option<&str>,bytes:&[u8])->ArtifactManifest {
        ArtifactManifest { artifact_id:id(name), kind:ArtifactKind::Parameters,
            generation:Generation::new(g).unwrap(), predecessor_id:parent.map(id),
            content_digest:Digest32::of_bytes(bytes), objective_digest:d("objective"),
            support_digest:d("support"), producer_id:id("producer"),
            compatibility_digest:d("compatibility"), encoded_size_bytes:bytes.len() as u64 }
    }
    fn register(r:&mut ArtifactRegistry,m:ArtifactManifest) {
        r.append(ArtifactEvent::Register{event_id:id(&format!("register-{}",m.artifact_id.as_str())),manifest:m}).unwrap();
    }
    fn snapshot(r:&ArtifactRegistry,dir:&std::path::Path,name:&str)->RegistrySnapshotReceipt {
        write_registry_snapshot(CreateOnlyArtifactFile::create(dir.join(name)).unwrap(),r,d("binding")).unwrap()
    }
    struct TestDir(std::path::PathBuf);
    impl TestDir {
        fn new()->Self {
            static NEXT:std::sync::atomic::AtomicU64=std::sync::atomic::AtomicU64::new(0);
            let path=std::env::temp_dir().join(format!("hepta-family-{}-{}",std::process::id(),NEXT.fetch_add(1,std::sync::atomic::Ordering::Relaxed)));
            std::fs::create_dir(&path).unwrap(); Self(path)
        }
        fn path(&self)->&std::path::Path {&self.0}
    }
    impl Drop for TestDir {fn drop(&mut self){let _=std::fs::remove_dir_all(&self.0);}}
    fn setup()->(TestDir,ArtifactRegistry,ParameterFamilyGuardV1) {
        let dir=TestDir::new();
        let mut r=ArtifactRegistry::new();
        let entries=[(manifest("parent",1,None,b"parent"),b"parent".as_slice()),
            (manifest("a",2,Some("parent"),b"alpha"),b"alpha".as_slice()),
            (manifest("b",2,Some("parent"),b"beta"),b"beta".as_slice())];
        for (m,_) in &entries { register(&mut r,m.clone()); }
        let receipt=snapshot(&r,dir.path(),"initial");
        let mut pins=Vec::new();
        for (m,bytes) in entries {
            let path=dir.path().join(m.artifact_id.as_str());
            write_candidate_payload(CreateOnlyArtifactFile::create(&path).unwrap(),&r,&m.artifact_id,bytes).unwrap();
            pins.push(load_pinned_candidate(File::open(dir.path().join("initial")).unwrap(),
                File::open(path).unwrap(),PinnedCandidateSpec{registry_receipt:receipt,manifest:m}).unwrap());
        }
        let parent=pins.remove(0);
        let guard=ParameterFamilyGuardV1::new(parent,pins,&[id("a"),id("b")],d("trust")).unwrap();
        (dir,r,guard)
    }
    // Fixture view constructor only: no claim of production owner signing.
    fn view(r:&ArtifactRegistry,dir:&std::path::Path,name:&str,trust:Digest32)->VerifiedCurrentRegistryViewV1 {
        VerifiedCurrentRegistryViewV1::new(snapshot(r,dir,name),r.clone(),d("witness"),trust)
    }
    fn check<T>(g:&mut ParameterFamilyGuardV1,v:VerifiedCurrentRegistryViewV1,
        f:impl FnOnce(&LoadedPinnedCandidate,&[LoadedPinnedCandidate],Digest32)->T)
        ->Result<T,PinnedCandidateLoadError> {
        if g.unavailable {return Err(PinnedCandidateLoadError::Unavailable);}
        g.unavailable=true;g.check_current(v,f)
    }
    #[test]
    fn complete_family_and_monotonic_extension() {
        let (dir,mut r,mut g)=setup();
        let n=check(&mut g,view(&r,dir.path(),"same",d("trust")),|p,u,w|{
            assert_eq!(p.bytes(),b"parent"); assert_eq!(u[0].bytes(),b"alpha");
            assert_eq!(u[1].bytes(),b"beta"); assert_eq!(w,d("witness"));u.len()
        }).unwrap();assert_eq!(n,2);
        register(&mut r,manifest("other",2,Some("parent"),b"other"));
        check(&mut g,view(&r,dir.path(),"next",d("trust")),|p,u,_|{
            assert_eq!(p.spec().registry_receipt.records,4);
            assert!(u.iter().all(|x|x.spec().registry_receipt==p.spec().registry_receipt));
        }).unwrap();
    }
    #[test]
    fn one_revoked_member_blocks_all_and_latches() {
        let (dir,mut r,mut g)=setup(); let old=r.clone();
        r.append(ArtifactEvent::Revoke(StateChange{event_id:id("revoke-b"),artifact_id:id("b"),evaluator_id:id("eval"),reason_digest:d("reason")})).unwrap();
        assert_eq!(r.state(&id("b")),Some(ArtifactState::Revoked));
        assert!(matches!(check(&mut g,view(&r,dir.path(),"revoked",d("trust")),|_,_,_|panic!("partial callback")),Err(PinnedCandidateLoadError::Ineligible)));
        assert!(matches!(check(&mut g,view(&old,dir.path(),"old",d("trust")),|_,_,_|panic!("reopened")),Err(PinnedCandidateLoadError::Unavailable)));
    }
    #[test]
    fn rollback_and_wrong_trust_rejected() {
        let (dir,mut r,mut g)=setup(); let old=r.clone();
        register(&mut r,manifest("other",2,Some("parent"),b"other"));
        check(&mut g,view(&r,dir.path(),"next",d("trust")),|_,_,_|()).unwrap();
        assert!(matches!(check(&mut g,view(&old,dir.path(),"old",d("trust")),|_,_,_|panic!("rollback")),Err(PinnedCandidateLoadError::FrontierMismatch)));
        let (dir,r,mut g)=setup();
        assert!(matches!(check(&mut g,view(&r,dir.path(),"wrong",d("wrong")),|_,_,_|panic!("wrong trust")),Err(PinnedCandidateLoadError::FrontierMismatch)));
    }
    #[test]
    fn equal_length_fork_and_missing_family_rejected() {
        let (dir,_,mut g)=setup();
        let mut fork=ArtifactRegistry::new();
        register(&mut fork,manifest("parent",1,None,b"parent"));
        register(&mut fork,manifest("a",2,Some("parent"),b"alpha"));
        register(&mut fork,manifest("b",2,Some("parent"),b"other"));
        assert!(matches!(check(&mut g,view(&fork,dir.path(),"fork",d("trust")),|_,_,_|panic!("fork")),Err(PinnedCandidateLoadError::FrontierMismatch)));
        let (_,_,g)=setup();
        assert!(matches!(ParameterFamilyGuardV1::new(g.parent,g.updates,&[id("a")],d("trust")),Err(PinnedCandidateLoadError::PinMismatch)));
    }
    #[test]
    fn consumer_panic_permanently_closes() {
        let (dir,r,mut g)=setup();
        let panicked=std::panic::catch_unwind(std::panic::AssertUnwindSafe(||{
            let _=check(&mut g,view(&r,dir.path(),"panic",d("trust")),|_,_,_|panic!("consumer panic"));
        }));
        assert!(panicked.is_err());
        assert!(matches!(check(&mut g,view(&r,dir.path(),"later",d("trust")),|_,_,_|panic!("reopened")),Err(PinnedCandidateLoadError::Unavailable)));
    }
    #[test]
    fn actual_signed_registry_view_and_missing_owner_fail_closed() {
        use crate::{ArtifactOwnerVerifierV1,ArtifactOwnerTrustV1,TrustedArtifactSignerV1,
            SignedCurrentArtifactHeadV1,SignedArtifactWriterLeaseV1,RegistryHeadWitnessV1,RegistryHeadRequirementV1};
        use ed25519_dalek::{SigningKey,Signer};
        let (dir,r,mut g)=setup();
        // Isolated test authority, never a production credential.
        let key=SigningKey::from_bytes(&[41u8;32]);
        let trusted=TrustedArtifactSignerV1{signer_id:id("authority"),verifying_key:key.verifying_key().to_bytes(),
            minimum_authority_epoch:1,maximum_authority_epoch:2,valid_from:1,expires_at:1000,revoked_at:None};
        let trust=ArtifactOwnerTrustV1{registry_id:id("registry"),withdrawal_scope_digest:d("scope"),
            minimum_registry_generation:Generation::new(1).unwrap(),genesis_predecessor_head_digest:Digest32::ZERO,
            minimum_authority_epoch:1,writer_signers:vec![trusted.clone()],head_signers:vec![trusted]};
        let verifier=ArtifactOwnerVerifierV1::new(trust.clone()).unwrap();
        g.trust_digest=verifier.trust_digest();
        let receipt=snapshot(&r,dir.path(),"signed");
        let mut signed=SignedCurrentArtifactHeadV1{withdrawal_scope_digest:d("scope"),binding:receipt.binding,
            witness:RegistryHeadWitnessV1{registry_id:id("registry"),generation:Generation::new(1).unwrap(),
                head_digest:receipt.head_digest,predecessor_head_digest:Digest32::ZERO,authority_epoch:1,
                signer_id:id("authority"),signing_key_digest:Digest32::of_bytes(&key.verifying_key().to_bytes()),
                issued_at:20,expires_at:1000},signature:[0;64]};
        signed.signature=key.sign(&signed.signing_bytes()).to_bytes();
        let requirement=RegistryHeadRequirementV1{registry_id:id("registry"),minimum_generation:Generation::new(1).unwrap(),
            expected_predecessor_head_digest:Digest32::ZERO,minimum_authority_epoch:1,now:20};
        let v=verifier.verify_current_registry_view(File::open(dir.path().join("signed")).unwrap(),receipt,&signed,&requirement).unwrap();
        check(&mut g,v,|p,u,w|{assert_eq!(p.bytes(),b"parent");assert_eq!(u.len(),2);assert!(!w.is_zero());}).unwrap();
        signed.signature[0]^=1;
        assert!(verifier.verify_current_registry_view(File::open(dir.path().join("signed")).unwrap(),receipt,&signed,&requirement).is_err());
        let mut lease=SignedArtifactWriterLeaseV1{lease_id:id("lease"),producer_id:id("producer"),registry_id:id("registry"),
            withdrawal_scope_digest:d("scope"),signer_id:id("authority"),
            signing_key_digest:Digest32::of_bytes(&key.verifying_key().to_bytes()),authority_epoch:1,
            lease_generation:1,issued_at:10,expires_at:1000,signature:[0;64]};
        lease.signature=key.sign(&lease.signing_bytes()).to_bytes();
        let ownerdir=TestDir::new();
        let owner=LearningArtifactOwnerHost::open(ownerdir.path(),trust,lease,20).unwrap();
        // A genuine owner with no CURRENT must not authorize cached family bytes.
        assert!(matches!(g.with_owner(&owner,20,|_,_,_|panic!("no CURRENT")),Err(PinnedCandidateLoadError::Unavailable)));
        assert!(matches!(g.with_owner(&owner,20,|_,_,_|panic!("latched")),Err(PinnedCandidateLoadError::Unavailable)));
    }
    #[test]
    fn explicitly_empty_host_family_is_readable_but_not_an_activation() {
        let (dir,r,g)=setup();
        let mut hold=ParameterFamilyGuardV1::new(g.parent,vec![],&[],d("trust")).unwrap();
        check(&mut hold,view(&r,dir.path(),"hold",d("trust")),|p,u,_|{assert_eq!(p.bytes(),b"parent");assert!(u.is_empty());}).unwrap();
    }
}
