//! Real resident processes, using the same synthetic numerical assets as V1.

use pretty_assertions::assert_eq;

use super::*;

fn resident(harness: &mut Harness) -> TestResult {
    harness.worker = JointGenerationProcessWorkerV1::open_resident(
        JointGenerationProcessConfigV1 {
            executable: harness.directory.0.join("proposal"),
            executable_digest: harness.manifest.runtime_digest,
            source_digest: harness.manifest.source_digest,
            weights: harness.directory.0.join("weights.hps"),
            weights_digest: harness.worker.weights_digest,
            public: harness.directory.0.join("public.hps"),
            public_digest: harness.worker.public_digest,
            device_digest: harness.manifest.device_digest,
        },
        Arc::clone(&harness.worker.clock),
    )?;
    harness.manifest.profile = harness.worker.profile().into();
    harness.request.predecessor.manifest_digest = harness.manifest.digest()?;
    Ok(())
}

fn execute(
    harness: &mut Harness,
    operation: &str,
    command: JointGenerationCommandV1,
) -> TestResult<CellGenerationProposalV2> {
    harness.request.operation_id = operation.into();
    harness.request.input = serde_json::to_vec(&JointGenerationInputV1 {
        public_digest: harness.worker.public_digest,
        command,
    })?;
    let proposal =
        harness
            .worker
            .execute(&harness.manifest, &harness.request, &AtomicBool::new(false))?;
    assert_eq!(proposal.request_digest, harness.request.digest()?);
    Ok(proposal)
}

fn communication(proposal: &CellGenerationProposalV2) -> TestResult<u64> {
    proposal
        .cost
        .entries()
        .iter()
        .find_map(|entry| entry.metrics.communication_bytes)
        .ok_or_else(|| std::io::Error::other("missing observed IPC bytes").into())
}

#[test]
fn resident_and_one_shot_have_identical_content_with_asset_transfer_only_once() -> TestResult {
    let assets = synthetic::assets()?;
    let asset_bytes = (assets.weights.len() + assets.public.len()) as u64;
    let mut single = Harness::with_assets(
        assets.weights.clone(),
        assets.public.clone(),
        Arc::new(|| 10),
    )?;
    let mut shared = Harness::with_assets(assets.weights, assets.public, Arc::new(|| 10))?;
    resident(&mut shared)?;
    for (index, command) in [
        JointGenerationCommandV1::Init {
            seed: 17,
            sampler: JointGenerationSamplerV1::Mean,
        },
        JointGenerationCommandV1::Advance {
            action: JointGenerationActionV1::Shared,
        },
        JointGenerationCommandV1::Commit {
            modality: JointGenerationModalityV1::Image,
            units: 1,
        },
        JointGenerationCommandV1::Advance {
            action: JointGenerationActionV1::Stop,
        },
    ]
    .into_iter()
    .enumerate()
    {
        let one = execute(&mut single, &format!("single-{index}"), command.clone())?;
        let many = execute(&mut shared, &format!("shared-{index}"), command)?;
        assert_eq!(one.successor_state, many.successor_state);
        assert_eq!(one.output_delta, many.output_delta);
        assert_eq!(one.disposition, many.disposition);
        if index == 0 {
            assert_eq!(communication(&many)?, communication(&one)? + 8);
        } else {
            assert_eq!(
                communication(&many)? + asset_bytes,
                communication(&one)? + 8
            );
        }
        single.adopt_for_next_fixture_request(&one);
        shared.adopt_for_next_fixture_request(&many);
    }
    Ok(())
}

#[test]
fn resident_keeps_concurrent_cells_independent() -> TestResult {
    let assets = synthetic::assets()?;
    let mut harness = Harness::with_assets(assets.weights, assets.public, Arc::new(|| 10))?;
    resident(&mut harness)?;
    let mut first = harness.request.clone();
    first.operation_id = "concurrent-a".into();
    let mut second = first.clone();
    second.operation_id = "concurrent-b".into();
    second.predecessor.scope.cell_id = "other-cell".into();
    second.input = serde_json::to_vec(&JointGenerationInputV1 {
        public_digest: harness.worker.public_digest,
        command: JointGenerationCommandV1::Init {
            seed: 23,
            sampler: JointGenerationSamplerV1::Mean,
        },
    })?;
    let (one, two) = std::thread::scope(|scope| {
        let one = scope.spawn(|| {
            harness
                .worker
                .execute(&harness.manifest, &first, &AtomicBool::new(false))
        });
        let two = scope.spawn(|| {
            harness
                .worker
                .execute(&harness.manifest, &second, &AtomicBool::new(false))
        });
        (one.join(), two.join())
    });
    let one = one.map_err(|_| std::io::Error::other("first caller panicked"))??;
    let two = two.map_err(|_| std::io::Error::other("second caller panicked"))??;
    assert_eq!(one.request_digest, first.digest()?);
    assert_eq!(two.request_digest, second.digest()?);
    assert_eq!(one.disposition, CellGenerationDispositionV2::Advanced);
    assert_eq!(two.disposition, CellGenerationDispositionV2::Advanced);
    assert_ne!(one.successor_state, two.successor_state);
    // Reinitialization must exactly reproduce its own seed after another Cell.
    let again = harness
        .worker
        .execute(&harness.manifest, &first, &AtomicBool::new(false))?;
    assert_eq!(again.successor_state, one.successor_state);
    assert!(again.output_delta.is_empty());
    Ok(())
}

#[test]
fn resident_deadline_after_dispatch_poisoning_requires_explicit_reopen() -> TestResult {
    let calls = Arc::new(AtomicU64::new(0));
    let observed = Arc::clone(&calls);
    let clock = Arc::new(move || {
        if observed.fetch_add(1, Ordering::SeqCst) >= 4 {
            30_000_000
        } else {
            10
        }
    });
    let assets = synthetic::assets()?;
    let mut harness = Harness::with_assets(assets.weights, assets.public, clock)?;
    resident(&mut harness)?;
    let proposal =
        harness
            .worker
            .execute(&harness.manifest, &harness.request, &AtomicBool::new(false))?;
    assert_eq!(
        proposal.disposition,
        CellGenerationDispositionV2::DeadlineExceeded
    );
    assert!(proposal.output_delta.is_empty());
    assert!(proposal.successor_state.is_empty());
    calls.store(0, Ordering::SeqCst);
    assert!(matches!(
        harness
            .worker
            .execute(&harness.manifest, &harness.request, &AtomicBool::new(false)),
        Err(CellGenerationErrorV2::Unavailable)
    ));
    harness.worker.clock = Arc::new(|| 10);
    resident(&mut harness)?;
    let proposal =
        harness
            .worker
            .execute(&harness.manifest, &harness.request, &AtomicBool::new(false))?;
    assert_eq!(proposal.disposition, CellGenerationDispositionV2::Advanced);
    Ok(())
}

#[test]
fn resident_predispatch_cancellation_does_not_launch_or_poison() -> TestResult {
    let assets = synthetic::assets()?;
    let mut harness = Harness::with_assets(assets.weights, assets.public, Arc::new(|| 10))?;
    resident(&mut harness)?;
    let cancelled =
        harness
            .worker
            .execute(&harness.manifest, &harness.request, &AtomicBool::new(true))?;
    assert_eq!(
        cancelled.disposition,
        CellGenerationDispositionV2::Cancelled
    );
    assert_eq!(communication(&cancelled)?, 0);
    let proposal =
        harness
            .worker
            .execute(&harness.manifest, &harness.request, &AtomicBool::new(false))?;
    assert_eq!(proposal.disposition, CellGenerationDispositionV2::Advanced);
    let mut wrong_profile = harness.manifest.clone();
    wrong_profile.profile = JointGenerationProcessWorkerV1::PROFILE.into();
    assert!(
        harness
            .worker
            .execute(&wrong_profile, &harness.request, &AtomicBool::new(false))
            .is_err()
    );
    Ok(())
}

#[test]
fn resident_cancellation_after_dispatch_never_replays_the_exchange() -> TestResult {
    let cancelled = Arc::new(AtomicBool::new(false));
    let calls = Arc::new(AtomicU64::new(0));
    let signal = Arc::clone(&cancelled);
    let count = Arc::clone(&calls);
    let clock = Arc::new(move || {
        if count.fetch_add(1, Ordering::SeqCst) >= 4 {
            signal.store(true, Ordering::Release);
        }
        10
    });
    let assets = synthetic::assets()?;
    let mut harness = Harness::with_assets(assets.weights, assets.public, clock)?;
    resident(&mut harness)?;
    let proposal = harness
        .worker
        .execute(&harness.manifest, &harness.request, &cancelled)?;
    assert_eq!(proposal.disposition, CellGenerationDispositionV2::Cancelled);
    assert!(proposal.successor_state.is_empty());
    assert!(proposal.output_delta.is_empty());
    cancelled.store(false, Ordering::Release);
    calls.store(0, Ordering::SeqCst);
    assert!(matches!(
        harness
            .worker
            .execute(&harness.manifest, &harness.request, &cancelled),
        Err(CellGenerationErrorV2::Unavailable)
    ));
    Ok(())
}

#[test]
fn resident_failure_keeps_cost_but_requires_a_new_owner_open() -> TestResult {
    let mut harness = Harness::new(32, Arc::new(|| 10))?;
    resident(&mut harness)?;
    let proposal =
        harness
            .worker
            .execute(&harness.manifest, &harness.request, &AtomicBool::new(false))?;
    assert_eq!(proposal.disposition, CellGenerationDispositionV2::Failed);
    assert!(communication(&proposal)? > 0);
    assert!(proposal.successor_state.is_empty());
    assert!(proposal.output_delta.is_empty());
    assert!(matches!(
        harness
            .worker
            .execute(&harness.manifest, &harness.request, &AtomicBool::new(false)),
        Err(CellGenerationErrorV2::Unavailable)
    ));
    Ok(())
}

#[derive(Clone, Copy)]
enum BoundaryInterruption {
    Cancellation,
    Deadline,
}

#[test]
fn resident_rechecks_after_hashing_and_before_send_without_poisoning_a_warm_model() -> TestResult {
    let assets = synthetic::assets()?;
    let asset_bytes = (assets.weights.len() + assets.public.len()) as u64;
    let mut harness = Harness::with_assets(assets.weights, assets.public, Arc::new(|| 10))?;
    resident(&mut harness)?;
    let first =
        harness
            .worker
            .execute(&harness.manifest, &harness.request, &AtomicBool::new(false))?;
    assert_eq!(first.disposition, CellGenerationDispositionV2::Advanced);

    // Clock samples 0/1 surround lock admission; 2 follows actual ELF hashing
    // and asset preparation, and 3 is the final check after frame allocation.
    for boundary in [2, 3] {
        for interruption in [
            BoundaryInterruption::Cancellation,
            BoundaryInterruption::Deadline,
        ] {
            let cancelled = Arc::new(AtomicBool::new(false));
            let signal = Arc::clone(&cancelled);
            let calls = AtomicU64::new(0);
            harness.worker.clock = Arc::new(move || {
                if calls.fetch_add(1, Ordering::SeqCst) >= boundary {
                    match interruption {
                        BoundaryInterruption::Cancellation => signal.store(true, Ordering::Release),
                        BoundaryInterruption::Deadline => return 30_000_000,
                    }
                }
                10
            });
            let stopped =
                harness
                    .worker
                    .execute(&harness.manifest, &harness.request, &cancelled)?;
            assert_eq!(
                stopped.disposition,
                match interruption {
                    BoundaryInterruption::Cancellation => CellGenerationDispositionV2::Cancelled,
                    BoundaryInterruption::Deadline => CellGenerationDispositionV2::DeadlineExceeded,
                }
            );
            assert_eq!(communication(&stopped)?, 0);
            assert!(stopped.successor_state.is_empty());
            assert!(stopped.output_delta.is_empty());

            harness.worker.clock = Arc::new(|| 10);
            let resumed = harness.worker.execute(
                &harness.manifest,
                &harness.request,
                &AtomicBool::new(false),
            )?;
            assert_eq!(resumed.disposition, CellGenerationDispositionV2::Advanced);
            assert_eq!(resumed.successor_state, first.successor_state);
            // A restarted/poisoned session cannot satisfy this exact omitted
            // asset count. This uses the actual resident helper, not a mock.
            assert_eq!(
                communication(&resumed)? + asset_bytes,
                communication(&first)?
            );
        }
    }
    Ok(())
}

#[test]
fn resident_cancelled_before_first_frame_still_loads_assets_on_the_next_request() -> TestResult {
    let assets = synthetic::assets()?;
    let asset_bytes = (assets.weights.len() + assets.public.len()) as u64;
    let cancelled = Arc::new(AtomicBool::new(false));
    let signal = Arc::clone(&cancelled);
    let calls = AtomicU64::new(0);
    let clock = Arc::new(move || {
        // The child exists, but no frame has entered its writer queue yet.
        if calls.fetch_add(1, Ordering::SeqCst) >= 3 {
            signal.store(true, Ordering::Release);
        }
        10
    });
    let mut harness = Harness::with_assets(assets.weights, assets.public, clock)?;
    resident(&mut harness)?;
    let stopped = harness
        .worker
        .execute(&harness.manifest, &harness.request, &cancelled)?;
    assert_eq!(stopped.disposition, CellGenerationDispositionV2::Cancelled);
    assert_eq!(communication(&stopped)?, 0);
    harness.worker.clock = Arc::new(|| 10);
    let loaded =
        harness
            .worker
            .execute(&harness.manifest, &harness.request, &AtomicBool::new(false))?;
    let reused =
        harness
            .worker
            .execute(&harness.manifest, &harness.request, &AtomicBool::new(false))?;
    assert_eq!(loaded.disposition, CellGenerationDispositionV2::Advanced);
    assert_eq!(loaded.successor_state, reused.successor_state);
    assert_eq!(
        communication(&reused)? + asset_bytes,
        communication(&loaded)?
    );
    Ok(())
}
