use super::*;
use tempfile::tempfile;

const TEST_MAGIC: [u8; 8] = *b"HPAJINT1";

struct Fixture {
    journal: AdaptiveAnchorJournalV1,
    retained_file: File,
    scope: Digest32,
    acknowledged: AdaptiveAnchorV1,
}

impl Fixture {
    fn new() -> Self {
        let retained_file = tempfile().expect("journal file");
        let scope = Digest32::of_bytes(b"live-journal-integrity-scope");
        let mut journal = AdaptiveAnchorJournalV1::open(
            retained_file.try_clone().expect("retained handle"),
            scope,
            TEST_MAGIC,
        )
        .expect("open journal");
        journal.issue_new_registry_fence().expect("initial fence");
        let acknowledged = AdaptiveAnchorV1 {
            sequence: 1,
            frame_digest: Digest32::of_bytes(b"acknowledged-frame"),
        };
        journal
            .persist_anchor(scope, 1, acknowledged)
            .expect("initial acknowledgement");
        Self {
            journal,
            retained_file,
            scope,
            acknowledged,
        }
    }

    fn bytes(&mut self) -> Vec<u8> {
        self.retained_file
            .seek(SeekFrom::Start(0))
            .expect("seek retained file");
        let mut bytes = Vec::new();
        self.retained_file
            .read_to_end(&mut bytes)
            .expect("read retained file");
        bytes
    }

    fn assert_sticky_and_preserved(&mut self, corrupted_bytes: Vec<u8>) {
        assert!(self.journal.poisoned);
        assert_eq!(
            self.journal.issue_new_registry_fence(),
            Err(AdaptiveAnchorJournalErrorV1::Poisoned),
        );
        assert_eq!(
            self.journal
                .persist_anchor(self.scope, 1, self.acknowledged),
            Err(AdaptiveAnchorJournalErrorV1::Poisoned),
        );
        assert_eq!(self.bytes(), corrupted_bytes);
        // This getter is explicitly a cached diagnostic snapshot, not a new ACK.
        assert_eq!(
            self.journal.state(),
            AdaptiveAnchorJournalStateV1 {
                writer_fence: 1,
                anchor: Some(self.acknowledged),
                previous_anchor: None,
            },
        );
    }
}

#[derive(Clone, Copy)]
enum Mutation {
    TruncateToValidHeader,
    HeaderByte,
    FrameBodyByte,
    FrameFooterByte,
    ValidChecksummedAnchorReplacement,
    ExtraSuffix,
}

const MUTATIONS: [Mutation; 6] = [
    Mutation::TruncateToValidHeader,
    Mutation::HeaderByte,
    Mutation::FrameBodyByte,
    Mutation::FrameFooterByte,
    Mutation::ValidChecksummedAnchorReplacement,
    Mutation::ExtraSuffix,
];

fn mutate(fixture: &mut Fixture, mutation: Mutation) -> Vec<u8> {
    match mutation {
        Mutation::TruncateToValidHeader => fixture
            .retained_file
            .set_len(HEADER_BYTES as u64)
            .expect("truncate journal history"),
        Mutation::HeaderByte | Mutation::FrameBodyByte | Mutation::FrameFooterByte => {
            let offset = match mutation {
                Mutation::HeaderByte => 0,
                Mutation::FrameBodyByte => HEADER_BYTES + 1,
                Mutation::FrameFooterByte => HEADER_BYTES + FRAME_BYTES - 1,
                Mutation::TruncateToValidHeader
                | Mutation::ValidChecksummedAnchorReplacement
                | Mutation::ExtraSuffix => unreachable!("single-byte mutation"),
            };
            fixture
                .retained_file
                .seek(SeekFrom::Start(offset as u64))
                .expect("seek mutation");
            let mut byte = [0_u8; 1];
            fixture
                .retained_file
                .read_exact(&mut byte)
                .expect("read mutation byte");
            byte[0] ^= 0x80;
            fixture
                .retained_file
                .seek(SeekFrom::Start(offset as u64))
                .expect("rewind mutation");
            fixture
                .retained_file
                .write_all(&byte)
                .expect("write mutation byte");
        }
        Mutation::ValidChecksummedAnchorReplacement => {
            let replacement = encode_frame(
                TAG_ANCHOR,
                1,
                Some(AdaptiveAnchorV1 {
                    sequence: 1,
                    frame_digest: Digest32::of_bytes(b"replacement-frame"),
                }),
            );
            fixture
                .retained_file
                .seek(SeekFrom::Start((HEADER_BYTES + FRAME_BYTES) as u64))
                .expect("seek anchor frame");
            fixture
                .retained_file
                .write_all(&replacement)
                .expect("replace complete valid frame");
        }
        Mutation::ExtraSuffix => {
            fixture
                .retained_file
                .seek(SeekFrom::End(0))
                .expect("seek suffix");
            fixture
                .retained_file
                .write_all(&[0x51, 0x52])
                .expect("write suffix");
        }
    }
    fixture.retained_file.sync_all().expect("sync mutation");
    fixture.bytes()
}

#[test]
fn live_journal_identical_ack_authenticates_the_full_trusted_history() {
    for mutation in MUTATIONS {
        let mut fixture = Fixture::new();
        let corrupted_bytes = mutate(&mut fixture, mutation);
        assert_eq!(
            fixture
                .journal
                .persist_anchor(fixture.scope, 1, fixture.acknowledged),
            Err(AdaptiveAnchorJournalErrorV1::Corrupt),
        );
        fixture.assert_sticky_and_preserved(corrupted_bytes);
    }
}

#[test]
fn live_journal_anchor_advance_rejects_lost_or_replaced_history_before_writing() {
    for mutation in MUTATIONS {
        let mut fixture = Fixture::new();
        let corrupted_bytes = mutate(&mut fixture, mutation);
        assert_eq!(
            fixture.journal.persist_anchor(
                fixture.scope,
                1,
                AdaptiveAnchorV1 {
                    sequence: 2,
                    frame_digest: Digest32::of_bytes(b"next-frame"),
                },
            ),
            Err(AdaptiveAnchorJournalErrorV1::Corrupt),
        );
        fixture.assert_sticky_and_preserved(corrupted_bytes);
    }
}

#[test]
fn live_journal_fence_advance_rejects_lost_or_replaced_history_before_writing() {
    for mutation in MUTATIONS {
        let mut fixture = Fixture::new();
        let corrupted_bytes = mutate(&mut fixture, mutation);
        assert_eq!(
            fixture.journal.issue_new_registry_fence(),
            Err(AdaptiveAnchorJournalErrorV1::Corrupt),
        );
        fixture.assert_sticky_and_preserved(corrupted_bytes);
    }
}

#[test]
fn live_journal_retry_append_and_rollover_preserve_authenticated_history() {
    let mut fixture = Fixture::new();
    let before_retry = fixture.bytes();
    fixture
        .journal
        .persist_anchor(fixture.scope, 1, fixture.acknowledged)
        .expect("authenticated identical acknowledgement");
    assert_eq!(fixture.bytes(), before_retry);
    let next_anchor = AdaptiveAnchorV1 {
        sequence: 2,
        frame_digest: Digest32::of_bytes(b"next-frame"),
    };
    fixture
        .journal
        .persist_anchor(fixture.scope, 1, next_anchor)
        .expect("authenticated anchor advance");
    assert_eq!(
        fixture
            .journal
            .issue_new_registry_fence()
            .expect("next fence"),
        2
    );
    let successor_anchor = AdaptiveAnchorV1 {
        sequence: 1,
        frame_digest: Digest32::of_bytes(b"successor-frame"),
    };
    fixture
        .journal
        .persist_anchor(fixture.scope, 2, successor_anchor)
        .expect("authenticated successor acknowledgement");
    let expected_state = AdaptiveAnchorJournalStateV1 {
        writer_fence: 2,
        anchor: Some(successor_anchor),
        previous_anchor: Some(next_anchor),
    };
    assert_eq!(fixture.journal.state(), expected_state);
    assert_eq!(fixture.journal.trusted_frame_digests.len(), 5);
    assert!(!fixture.journal.poisoned);
    drop(fixture.journal);
    let reopened = AdaptiveAnchorJournalV1::open(fixture.retained_file, fixture.scope, TEST_MAGIC)
        .expect("reopen authenticated complete history");
    assert_eq!(reopened.state(), expected_state);
    assert_eq!(reopened.trusted_frame_digests.len(), 5);
}

#[test]
fn live_journal_detects_valid_replacement_that_reopen_alone_cannot_authenticate() {
    let mut fixture = Fixture::new();
    let corrupted_bytes = mutate(&mut fixture, Mutation::ValidChecksummedAnchorReplacement);
    assert_eq!(
        fixture
            .journal
            .persist_anchor(fixture.scope, 1, fixture.acknowledged),
        Err(AdaptiveAnchorJournalErrorV1::Corrupt),
    );
    fixture.assert_sticky_and_preserved(corrupted_bytes);
    drop(fixture.journal);
    // Reopen verifies local syntax/checksums; it has no independent journal head.
    let reopened = AdaptiveAnchorJournalV1::open(fixture.retained_file, fixture.scope, TEST_MAGIC)
        .expect("self-consistent replacement requires external reconciliation");
    assert_ne!(reopened.state().anchor, Some(fixture.acknowledged));
}
