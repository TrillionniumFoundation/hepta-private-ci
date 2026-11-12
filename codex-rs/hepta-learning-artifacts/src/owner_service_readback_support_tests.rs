//! Actual original artifact files and signatures for read-only recovery tests.

use std::collections::BTreeMap;
use std::path::Path;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use super::*;

pub(super) struct OriginalPublicationReadbackFixture {
    pub(super) directory: TestDir,
    pub(super) key: SigningKey,
    pub(super) service: LearningArtifactOwnerService,
    pub(super) config: LearningArtifactOwnerServiceConfigV1,
    pub(super) baseline: LearningArtifactPublishRequestV1,
    pub(super) baseline_intent: Digest32,
}

enum CurrentWindow {
    Fresh,
    Expired,
}

impl OriginalPublicationReadbackFixture {
    pub(super) fn fresh() -> Self {
        Self::new(CurrentWindow::Fresh)
    }

    pub(super) fn expired_current() -> Self {
        Self::new(CurrentWindow::Expired)
    }

    fn new(window: CurrentWindow) -> Self {
        let directory = TestDir::new();
        let key = key();
        let clock = now_millis();
        let issued = clock - 60_000;
        let expires = clock + 120_000;
        let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
        let scope_digest = withdrawals.scope_digest().fixture("original scope");
        let mut original_trust = trust(&key, scope_digest);
        for signer in original_trust
            .writer_signers
            .iter_mut()
            .chain(original_trust.head_signers.iter_mut())
        {
            signer.valid_from = issued - 1;
            signer.expires_at = expires;
        }
        let mut original_lease = lease(&key, scope_digest);
        original_lease.issued_at = issued;
        original_lease.expires_at = expires;
        original_lease.signature = key.sign(&original_lease.signing_bytes()).to_bytes();
        let (observed, head_expires) = match window {
            CurrentWindow::Fresh => (clock, clock + 60_000),
            CurrentWindow::Expired => (clock - 10_000, clock - 1_000),
        };
        let config = LearningArtifactOwnerServiceConfigV1 {
            root: directory.0.clone(),
            trust: original_trust,
            writer_lease: original_lease,
            required_current_head: None,
            withdrawal_registry: withdrawals,
            storage_binding: digest("binding"),
            now: observed,
        };
        let mut service =
            LearningArtifactOwnerService::open(config.clone()).fixture("original owner");
        let (baseline, baseline_intent) = request_for(
            &service,
            &key,
            "readback-baseline",
            issued,
            expires,
            observed,
            head_expires,
        );
        service
            .publish(baseline.clone())
            .fixture("original baseline publication");
        Self {
            directory,
            key,
            service,
            config,
            baseline,
            baseline_intent,
        }
    }

    pub(super) fn pending_request(&self) -> (LearningArtifactPublishRequestV1, Digest32) {
        let clock = now_millis();
        request_for(
            &self.service,
            &self.key,
            "readback-pending",
            clock - 1_000,
            clock + 60_000,
            clock,
            clock + 60_000,
        )
    }

    pub(super) fn begin_pending(&mut self) -> (LearningArtifactPublishRequestV1, Digest32) {
        let (request, intent) = self.pending_request();
        let mut failed = request.clone();
        failed.payload = b"wrong-original-payload".to_vec();
        assert!(self.service.publish(failed).is_err());
        assert_eq!(
            self.service.recovery_required(),
            Some(&request.operation_id)
        );
        (request, intent)
    }

    pub(super) fn reopen(self) -> Self {
        let Self {
            directory,
            key,
            service,
            mut config,
            baseline,
            baseline_intent,
        } = self;
        drop(service);
        config.required_current_head = Some(baseline.signed_current_head.clone());
        config.now = now_millis();
        let service = LearningArtifactOwnerService::open(config.clone()).fixture("original reopen");
        Self {
            directory,
            key,
            service,
            config,
            baseline,
            baseline_intent,
        }
    }

    pub(super) fn bytes(&self) -> BTreeMap<std::path::PathBuf, Vec<u8>> {
        fn visit(root: &Path, at: &Path, out: &mut BTreeMap<std::path::PathBuf, Vec<u8>>) {
            for entry in fs::read_dir(at).fixture("original files") {
                let path = entry.fixture("original entry").path();
                if path.is_dir() {
                    visit(root, &path, out);
                } else {
                    out.insert(
                        path.strip_prefix(root).fixture("owned path").to_owned(),
                        fs::read(&path).fixture("original bytes"),
                    );
                }
            }
        }
        let mut result = BTreeMap::new();
        visit(&self.directory.0, &self.directory.0, &mut result);
        result
    }

    pub(super) fn checkpoint_file(&self, operation: &StableId, phase: &str) -> std::path::PathBuf {
        fs::read_dir(self.directory.0.join("transactions"))
            .fixture("transactions")
            .map(|entry| entry.fixture("transaction").path())
            .find(|path| {
                let bytes = fs::read_to_string(path).fixture("checkpoint text");
                let mut lines = bytes.lines();
                let _ = lines.next();
                lines.next() == Some(operation.as_str()) && lines.next() == Some(phase)
            })
            .fixture("actual original phase file")
    }
}

fn request_for(
    service: &LearningArtifactOwnerService,
    key: &SigningKey,
    name: &str,
    created: u64,
    expires: u64,
    observed: u64,
    head_expires: u64,
) -> (LearningArtifactPublishRequestV1, Digest32) {
    let mut model = manifest();
    model.artifact_id = id(name);
    model.created_at = created;
    model.expires_at = expires;
    let predecessor = service.registry().snapshot().head_digest;
    let admission = admit_manifest_at_withdrawal_head_v3(
        service.withdrawal_registry(),
        service.withdrawal_registry().head_digest(),
        model,
        observed,
    )
    .fixture("original admission");
    let operation = id(&format!("{name}-operation"));
    let mut staged = service.registry().clone();
    let preview = ArtifactPublicationTransactionV1::begin(
        operation.clone(),
        admission.clone(),
        service.withdrawal_registry(),
        &staged,
        predecessor,
        observed,
    )
    .fixture("original intent");
    service
        .host
        .stage_compatibility_registration(&preview, &mut staged, observed)
        .fixture("in-memory original registration preview");
    let mut signed = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: service
            .withdrawal_registry()
            .scope_digest()
            .fixture("scope"),
        binding: digest("binding"),
        witness: RegistryHeadWitnessV1 {
            registry_id: id("learning-artifacts"),
            generation: Generation::new(staged.records().len() as u64).fixture("generation"),
            head_digest: staged.snapshot().head_digest,
            predecessor_head_digest: predecessor,
            authority_epoch: 1,
            signer_id: id("owner-authority"),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            issued_at: observed,
            expires_at: head_expires,
        },
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    (
        LearningArtifactPublishRequestV1 {
            operation_id: operation,
            admission,
            payload: b"payload".to_vec(),
            signed_current_head: signed,
            expected_registry_predecessor_head: predecessor,
            now: observed,
        },
        preview.intent().intent_digest,
    )
}

pub(super) fn now_millis() -> u64 {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .fixture("clock")
            .as_millis(),
    )
    .fixture("bounded clock")
}
