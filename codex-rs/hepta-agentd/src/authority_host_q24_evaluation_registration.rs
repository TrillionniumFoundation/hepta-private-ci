//! Explicit original registration versus reopen. Raw Initial data only selects
//! the refusal namespace. The first actual proof and primary I/O are armed.

use super::*;

impl OriginalRootIndependentBEvaluationFilesV1 {
    pub(crate) fn register_original_b(
        path: &Path,
        initial: &LearningIterationSnapshotV1,
        service: &HostAuthorityService,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        learning: &RegisteredHostLearningCheckpointV1,
        request_end: Instant,
        session_end: Instant,
    ) -> io::Result<Arc<Self>> {
        if request_end > session_end {
            return Err(io::Error::other(
                "original B registration exceeds its session",
            ));
        }
        let root =
            Arc::new(RootAuthorityDirectory::open(&config.state_dir).map_err(io::Error::other)?);
        let (record, files) = OriginalBRecord::register(root, initial, request_end, || {
            let result = service.with_learning_profile(
                config,
                registration,
                owner,
                &learning.profile,
                |actual, proof| {
                    owner_alive(owner, request_end)?;
                    require_learning(initial, &actual, learning)?;
                    let before = learning
                        .backend
                        .restore(&actual.request)
                        .map_err(io::Error::other)?;
                    if before.as_ref().is_some_and(|snapshot| snapshot != &actual) {
                        return Err(io::Error::other(
                            "original B must be registered before learning work",
                        ));
                    }
                    let files = OriginalBInputs::open(path)?;
                    let now = service.original_learning_unix_seconds()?;
                    let (_, authorities) = files.admitted_protocol(&actual, now)?;
                    files.require_empty_reservation()?;
                    authorities.original_key(&files.evaluator_key)?;
                    let namespace = Digest32::of_parts(&[
                        b"hepta.root.independent-b.namespace.v1\0",
                        actual.head_digest.as_array(),
                        files.deployment_digest().as_array(),
                    ]);
                    let enrollment = OriginalBEnrollment {
                        initial_head: actual.head_digest.into_array(),
                        protocol: actual.request.evaluation_profile.into_array(),
                        trust: actual.owners.evidence_trust_digest.into_array(),
                        deployment: files.deployment_digest().into_array(),
                        protocol_statement: files.protocol_statement_digest().into_array(),
                        files: files.file_identities(),
                        registered_at_seconds: now,
                        expires_at_seconds: actual.request.envelope.expiry_unix_seconds,
                        namespace: namespace.into_array(),
                        original_generation: authorities.evaluator.principal.authority_epoch,
                        original_lease: Digest32::of_parts(&[
                            b"hepta.root.independent-b.original-lease.v1\0",
                            proof.as_bytes(),
                            namespace.as_array(),
                        ])
                        .into_array(),
                        heads: None,
                        realized_training_head: None,
                        realized_plan: None,
                        completed_receipt: None,
                        released_source: None,
                        output_images: Vec::new(),
                        realized_plan_statement: None,
                        original_training_attestation: None,
                    };
                    require_files(
                        &files,
                        &enrollment,
                        service.original_learning_unix_seconds()?,
                    )?;
                    if learning
                        .backend
                        .restore(&actual.request)
                        .map_err(io::Error::other)?
                        != before
                    {
                        return Err(io::Error::other(
                            "original B initial checkpoint changed during registration",
                        ));
                    }
                    Ok((enrollment, files))
                },
            )?;
            owner_alive(owner, request_end)?;
            require_files(
                &result.1,
                &result.0,
                service.original_learning_unix_seconds()?,
            )?;
            // Both checks remain after the full original Root context returns.
            result.1.require_empty_reservation()?;
            Ok(result)
        })?;
        Ok(Arc::new(Self {
            record,
            initial: initial.clone(),
            backend: Arc::clone(&learning.backend),
            profile: learning.profile.clone(),
            state: Mutex::new(OriginalBState {
                files,
                execution: None,
            }),
            end: session_end,
        }))
    }

    pub(crate) fn reopen_original_b(
        path: &Path,
        initial: &LearningIterationSnapshotV1,
        service: &HostAuthorityService,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        learning: &RegisteredHostLearningCheckpointV1,
        request_end: Instant,
        session_end: Instant,
    ) -> io::Result<Arc<Self>> {
        if request_end > session_end {
            return Err(io::Error::other("original B reopen exceeds its session"));
        }
        let root =
            Arc::new(RootAuthorityDirectory::open(&config.state_dir).map_err(io::Error::other)?);
        let record = OriginalBRecord::open(root, initial)?;
        let files = record.inspect(request_end, |enrollment| {
            let files = service.with_learning_profile(
                config,
                registration,
                owner,
                &learning.profile,
                |actual, _| {
                    owner_alive(owner, request_end)?;
                    require_learning(initial, &actual, learning)?;
                    let files = OriginalBInputs::open(path)?;
                    let now = service.original_learning_unix_seconds()?;
                    require_files(&files, enrollment, now)?;
                    files.admitted_protocol(&actual, now)?;
                    Ok(files)
                },
            )?;
            owner_alive(owner, request_end)?;
            require_files(
                &files,
                enrollment,
                service.original_learning_unix_seconds()?,
            )?;
            Ok(files)
        })?;
        Ok(Arc::new(Self {
            record,
            initial: initial.clone(),
            backend: Arc::clone(&learning.backend),
            profile: learning.profile.clone(),
            state: Mutex::new(OriginalBState {
                files,
                execution: None,
            }),
            end: session_end,
        }))
    }
}
