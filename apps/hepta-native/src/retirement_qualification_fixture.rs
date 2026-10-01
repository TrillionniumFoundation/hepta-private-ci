//! Canonical authority-only legacy fixtures. Sorting is confined to each real
//! chronological batch; it never groups the entire lifetime by index prefix.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::path::Path;

use super::Checkpoint;
use super::Head;
use super::SEGMENT_BYTES;
use super::SEGMENT_ENTRIES;
use super::SEGMENT_SCHEMA;
use super::Segment;
use super::directory;
use super::read_segment;
use super::write_content_addressed;
use crate::model::sha256_hex;
use crate::private_state::PrivateStateRoot;

pub(crate) const REBUILD_SCOPE: &str =
    "fresh-process-mixed-prefix-authority-chain-with-no-derived-assets";
pub(crate) const AUTHORITY_SCOPE: &str = "mixed-prefix-chronological-legacy-identity-batches";

pub(crate) struct AuthorityShape {
    pub(crate) segment_count: usize,
    pub(crate) mixed_prefix_segments: usize,
    pub(crate) minimum_prefixes_per_segment: usize,
}

pub(crate) struct MixedAuthority {
    root: PrivateStateRoot,
    segment_names: Vec<String>,
    pub(crate) checkpoint: Checkpoint,
    pub(crate) first_identity: String,
    pub(crate) last_identity: String,
    pub(crate) shape: AuthorityShape,
}

impl MixedAuthority {
    pub(crate) fn build(journal: &Path, identities: usize) -> Self {
        assert!(
            identities > 1,
            "mixed authority subject must contain multiple identities"
        );
        let root = PrivateStateRoot::open(directory(journal)).expect("create mixed authority root");
        let mut checkpoint = Checkpoint::default();
        let mut segment_names = Vec::new();
        let mut mixed_prefix_segments = 0;
        let mut minimum_prefixes_per_segment = 256;
        for start in (0..identities).step_by(SEGMENT_ENTRIES) {
            let mut digests = (start..(start + SEGMENT_ENTRIES).min(identities))
                .map(|index| sha256_hex(format!("hepta-retired-qualification-{index}")))
                .collect::<Vec<_>>();
            digests.sort_unstable();
            let prefixes = digests
                .iter()
                .map(|id| &id[..2])
                .collect::<BTreeSet<_>>()
                .len();
            mixed_prefix_segments += usize::from(prefixes > 1);
            minimum_prefixes_per_segment = minimum_prefixes_per_segment.min(prefixes);
            let segment = Segment {
                schema: SEGMENT_SCHEMA.to_owned(),
                previous: checkpoint.clone(),
                digests,
                record_digests: BTreeMap::new(),
            };
            let digest = write_content_addressed(
                &root,
                "segment",
                &serde_json::to_vec(&segment).expect("encode mixed authority segment"),
                SEGMENT_BYTES,
            )
            .expect("persist mixed authority segment");
            checkpoint.count += segment.digests.len();
            checkpoint.head = Some(digest.clone());
            segment_names.push(format!("{digest}.json"));
        }
        crate::journal_storage::write_private(
            &root,
            &root.path().join("head.json"),
            &legacy_head(&checkpoint),
        )
        .expect("publish authority-only legacy head");
        let segment_count = segment_names.len();
        Self {
            root,
            segment_names,
            checkpoint,
            first_identity: sha256_hex("hepta-retired-qualification-0"),
            last_identity: sha256_hex(format!("hepta-retired-qualification-{}", identities - 1)),
            shape: AuthorityShape {
                segment_count,
                mixed_prefix_segments,
                minimum_prefixes_per_segment,
            },
        }
    }

    /// Each sample shares only immutable authoritative segment bytes. Its head
    /// is copied and all derived index/bucket/scratch assets start absent.
    pub(crate) fn clone_cold(&self, journal: &Path) {
        self.root
            .verify()
            .expect("verify mixed authority fixture root");
        let root = PrivateStateRoot::open(directory(journal))
            .expect("create independent cold rebuild root");
        for name in &self.segment_names {
            std::fs::hard_link(self.root.path().join(name), root.path().join(name))
                .expect("share only immutable authority segment");
        }
        crate::journal_storage::write_private(
            &root,
            &root.path().join("head.json"),
            &legacy_head(&self.checkpoint),
        )
        .expect("copy private mutable legacy head");
        assert_eq!(derived_assets_before_rebuild(journal), 0);
    }
}

fn legacy_head(checkpoint: &Checkpoint) -> Vec<u8> {
    serde_json::to_vec(&Head {
        schema: SEGMENT_SCHEMA.to_owned(),
        checkpoint: checkpoint.clone(),
        index_manifest: None,
    })
    .expect("encode legacy authority head")
}

pub(crate) fn derived_assets_before_rebuild(journal: &Path) -> usize {
    std::fs::read_dir(directory(journal))
        .expect("inspect cold rebuild root")
        .map(|entry| entry.expect("inspect cold rebuild asset").file_name())
        .filter(|name| {
            let name = name.to_string_lossy();
            name.starts_with("bucket-")
                || name.starts_with("index-")
                || name.starts_with(".retirement-rebuild-")
        })
        .count()
}

pub(crate) fn inspect_shape(journal: &Path, checkpoint: &Checkpoint) -> AuthorityShape {
    let root = PrivateStateRoot::open_existing(directory(journal))
        .expect("inspect authoritative shape root");
    let mut cursor = checkpoint.clone();
    let mut shape = AuthorityShape {
        segment_count: 0,
        mixed_prefix_segments: 0,
        minimum_prefixes_per_segment: 256,
    };
    while let Some(digest) = cursor.head.clone() {
        let segment = read_segment(&root, &digest, Some(cursor.count))
            .expect("validate observed authority segment");
        let prefixes = segment
            .digests
            .iter()
            .map(|id| &id[..2])
            .collect::<BTreeSet<_>>()
            .len();
        shape.segment_count += 1;
        shape.mixed_prefix_segments += usize::from(prefixes > 1);
        shape.minimum_prefixes_per_segment = shape.minimum_prefixes_per_segment.min(prefixes);
        cursor = segment.previous;
    }
    assert_eq!(cursor.count, 0);
    shape
}
