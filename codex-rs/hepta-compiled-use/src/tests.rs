    use super::*;
    use crate::action::ACTION_PAYLOAD_OFFSET;

    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }
    fn grant() -> CapabilityGrantV1 {
        CapabilityGrantV1 {
            digest: digest(b"grant"),
            allowed: 1 | 2 | 4 | 8 | 16,
        }
    }
    fn verifier() -> ActionVerifierV1 {
        ActionVerifierV1 {
            generation: 7,
            grant: grant(),
        }
    }
    fn click(sequence: u64) -> ActionFrameV1 {
        ActionFrameV1 {
            generation: 7,
            sequence,
            capability_digest: grant().digest,
            arguments: ActionArgumentsV1::Click {
                target_digest: digest(b"element"),
                x: 3,
                y: 4,
            },
        }
    }

    #[test]
    fn fixed_abi_round_trips_without_executable_payload() {
        let frame = click(1).encode().expect("encode");
        assert_eq!(frame.len(), ACTION_FRAME_BYTES_V1);
        assert!(frame[ACTION_PAYLOAD_OFFSET + 40..].iter().all(|b| *b == 0));
        assert_eq!(ActionFrameV1::decode(&frame).expect("decode"), click(1));
    }

    #[test]
    fn queue_is_bounded_and_sequence_fenced() {
        let mut queue = SharedMemoryQueueV1::new(verifier(), 1).expect("queue");
        queue.push(click(1)).expect("first");
        assert_eq!(queue.push(click(3)), Err(ActionErrorV1::SequenceMismatch));
        assert_eq!(queue.push(click(2)), Err(ActionErrorV1::QueueFull));
        assert_eq!(queue.pop().expect("pop").frame(), &click(1));
        queue.push(click(2)).expect("second");
    }

    #[test]
    fn verifier_rejects_wrong_capability_and_generation() {
        let mut action = click(1);
        action.capability_digest = digest(b"other");
        assert_eq!(verifier().verify(&action), Err(ActionErrorV1::CapabilityDenied));
        action = click(1);
        action.generation = 8;
        assert_eq!(verifier().verify(&action), Err(ActionErrorV1::GenerationMismatch));
    }

    #[test]
    fn malformed_padding_and_digest_are_rejected() {
        let mut frame = click(1).encode().expect("encode");
        frame[ACTION_PAYLOAD_OFFSET + 40] = 1;
        assert_eq!(ActionFrameV1::decode(&frame), Err(ActionErrorV1::NonCanonicalPadding));
        let mut frame = click(1).encode().expect("encode");
        frame[56] ^= 1;
        assert_eq!(ActionFrameV1::decode(&frame), Err(ActionErrorV1::DigestMismatch));
    }

    #[test]
    fn compiled_plan_is_proposal_only_and_sequence_bound() {
        let proposal = propose_compiled_use_v1(verifier(), vec![click(1), click(2)])
            .expect("proposal");
        assert_eq!(proposal.actions.len(), 2);
        assert!(!proposal.authority.grants_any());
        assert!(!proposal.proposal_digest.is_zero());
        assert_eq!(
            propose_compiled_use_v1(verifier(), vec![click(1), click(3)]),
            Err(ActionErrorV1::SequenceMismatch)
        );
        verify_compiled_use_proposal_v1(verifier(), &proposal).expect("verify proposal");
        let mut tampered = proposal;
        tampered.actions[0].arguments = ActionArgumentsV1::Click {
            target_digest: digest(b"other-element"),
            x: 9,
            y: 9,
        };
        assert_eq!(
            verify_compiled_use_proposal_v1(verifier(), &tampered),
            Err(ActionErrorV1::DigestMismatch)
        );
    }

    #[test]
    fn default_sandbox_never_executes() {
        let mut sandbox = DenyByDefaultSandboxV1;
        let verified = verifier().verify_and_bind(&click(1)).expect("verified");
        assert_eq!(sandbox.submit(verified), Err(SandboxErrorV1::NotConfigured));
    }


    #[test]
    fn atomic_batch_has_the_same_fixed_wires_as_scalar_pushes() {
        let mut scalar = SharedMemoryQueueV1::new(verifier(), 8).expect("scalar queue");
        let mut batch = SharedMemoryQueueV1::new(verifier(), 8).expect("batch queue");
        let actions: Vec<_> = (1..=6).map(click).collect();
        for action in &actions {
            scalar.push(action.clone()).expect("single action");
        }
        batch.push_batch(&actions).expect("verified atomic batch");
        assert_eq!(batch.len(), 6);
        for expected in &actions {
            assert_eq!(scalar.pop().expect("scalar pop").frame(), expected);
            assert_eq!(batch.pop().expect("batch pop").frame(), expected);
        }
        assert!(batch.is_empty());
    }

    #[test]
    fn atomic_batch_rejects_a_late_sequence_gap_without_partial_effect() {
        let mut queue = SharedMemoryQueueV1::new(verifier(), 4).expect("queue");
        queue.push(click(1)).expect("existing prefix");
        assert_eq!(
            queue.push_batch(&[click(2), click(4)]),
            Err(ActionErrorV1::SequenceMismatch)
        );
        assert_eq!(queue.len(), 1);
        queue.push_batch(&[click(2), click(3)]).expect("retry clean batch");
        for expected in 1..=3 {
            assert_eq!(queue.pop().expect("pop").frame(), &click(expected));
        }
    }

    #[test]
    fn atomic_batch_rejects_capacity_without_consuming_sequence() {
        let mut queue = SharedMemoryQueueV1::new(verifier(), 2).expect("queue");
        assert_eq!(
            queue.push_batch(&[click(1), click(2), click(3)]),
            Err(ActionErrorV1::QueueFull)
        );
        assert!(queue.is_empty());
        queue.push_batch(&[click(1), click(2)]).expect("valid retry");
        assert_eq!(queue.len(), 2);
    }

    #[test]
    fn atomic_batch_rejects_late_capability_mismatch() {
        let mut queue = SharedMemoryQueueV1::new(verifier(), 3).expect("queue");
        let mut wrong = click(2);
        wrong.capability_digest = digest(b"not-the-current-grant");
        assert_eq!(
            queue.push_batch(&[click(1), wrong]),
            Err(ActionErrorV1::CapabilityDenied)
        );
        assert!(queue.is_empty());
        queue.push(click(1)).expect("sequence was not consumed");
    }

    #[test]
    fn atomic_batch_does_not_wrap_sequence_or_accept_empty_batches() {
        let mut queue = SharedMemoryQueueV1::new(verifier(), 2).expect("queue");
        assert_eq!(queue.push_batch(&[]), Err(ActionErrorV1::ProposalLimit));
        queue.next_sequence = u64::MAX;
        let mut last = click(1);
        last.sequence = u64::MAX;
        assert_eq!(
            queue.push_batch(&[last]),
            Err(ActionErrorV1::SequenceMismatch)
        );
        assert!(queue.is_empty());
    }
