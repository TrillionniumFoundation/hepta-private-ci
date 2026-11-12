//! Physical data checks beneath the actual Root registration/retention arm.
//! The expected prefix comes from original registration, never peer metadata.

use std::fs::File;
use std::os::unix::fs::FileExt;
use std::os::unix::fs::MetadataExt;

use codex_hepta_learning_ledger::ReadOnlyRunStartViewV1;
use codex_hepta_learning_ledger::RunStartAnchor;
use codex_hepta_learning_ledger::RunStartReadOnlyFrameV1;
use codex_hepta_learning_ledger::observe_original_run_start_prefix_v1;
use codex_hepta_objective::ObjectiveAdmissionProfileV1;
use codex_hepta_objective::decode_admission_profile_json_v1;
use rustix::fs::OFlags;
use rustix::fs::fcntl_getfl;

use super::*;
use crate::AgentdIdentity;
use crate::authbus_trust::TextTrust;

const MAX_RECORDS: usize = 4_096;

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct FilePin {
    device: u64,
    inode: u64,
    uid: u32,
    gid: u32,
    mode: u32,
}

impl FilePin {
    fn read(file: &File, uid: u32, gid: u32) -> io::Result<Self> {
        if fcntl_getfl(file).map_err(io::Error::from)? & OFlags::ACCMODE != OFlags::RDONLY {
            return Err(io::Error::other(
                "original O_RDONLY RunStart input required",
            ));
        }
        let metadata = file.metadata()?;
        if !metadata.is_file()
            || metadata.nlink() != 1
            || ![(0, 0), (uid, gid)].contains(&(metadata.uid(), metadata.gid()))
            || metadata.mode() & 0o7777 != 0o600
        {
            return Err(io::Error::other(
                "original private RunStart input custody differs",
            ));
        }
        Ok(Self {
            device: metadata.dev(),
            inode: metadata.ino(),
            uid: metadata.uid(),
            gid: metadata.gid(),
            mode: metadata.mode(),
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalInputPin {
    files: [FilePin; 3],
    profile_bytes: String,
    trust_bytes: String,
    pub(super) profile_digest: String,
    journal_binding: String,
    prefix_length: u64,
    prefix_digest: String,
}

struct DecodedInputs {
    files: [FilePin; 3],
    profile_bytes: String,
    trust_bytes: String,
    profile: ObjectiveAdmissionProfileV1,
    trust: TextTrust,
}

impl OriginalInputPin {
    pub(super) fn capture(
        files: &RootInitialRunStartFilesV1,
        identity: &AgentdIdentity,
        uid: u32,
        gid: u32,
    ) -> io::Result<Self> {
        RootInitialRunStartFilesV1::with_original_files(files, |journal, profile, trust| {
            let decoded = decode_inputs(journal, profile, trust, identity, uid, gid)?;
            let profile_digest = decoded.profile.digest().map_err(io::Error::other)?;
            let binding = crate::objective_runtime::run_start_binding(identity, profile_digest);
            let prefix = observe_original_run_start_prefix_v1(journal, binding, MAX_RECORDS)
                .map_err(io::Error::other)?;
            let pin = Self {
                files: decoded.files,
                profile_bytes: decoded.profile_bytes,
                trust_bytes: decoded.trust_bytes,
                profile_digest: profile_digest.to_string(),
                journal_binding: binding.to_string(),
                prefix_length: prefix.length,
                prefix_digest: prefix.digest.to_string(),
            };
            pin.require_decoded(&decode_inputs(journal, profile, trust, identity, uid, gid)?)?;
            if observe_original_run_start_prefix_v1(journal, binding, MAX_RECORDS)
                .map_err(io::Error::other)?
                != prefix
            {
                return Err(io::Error::other(
                    "RunStart prefix changed during registration",
                ));
            }
            Ok(pin)
        })
    }

    pub(super) fn observe(
        &self,
        files: &RootInitialRunStartFilesV1,
        identity: &AgentdIdentity,
        target: &CellGenerationOwnerBindingV1,
        publication: &OriginalRunStartPublicationDataV1,
        uid: u32,
        gid: u32,
        now: u64,
    ) -> io::Result<RunStartReadOnlyFrameV1> {
        RootInitialRunStartFilesV1::with_original_files(files, |journal, profile, trust| {
            let decoded = decode_inputs(journal, profile, trust, identity, uid, gid)?;
            self.require_decoded(&decoded)?;
            if publication.run_id != target.scope().run_id
                || publication.profile_digest != self.profile_digest
                || target.scope().agent_id != identity.agent_id.as_str()
            {
                return Err(io::Error::other(
                    "original RunStart target or profile differs",
                ));
            }
            let reader = ReadOnlyRunStartViewV1::open(
                journal.try_clone()?,
                digest(&self.journal_binding)?,
                digest(&self.profile_digest)?,
                MAX_RECORDS,
                RunStartAnchor {
                    sequence: publication.sequence,
                    chain_digest: digest(&publication.chain_digest)?,
                },
            )
            .map_err(io::Error::other)?;
            let run_id = StableId::new(&publication.run_id).map_err(io::Error::other)?;
            let read = || {
                reader
                    .read_with_frame_at_original_prefix(
                        &run_id,
                        self.prefix_length,
                        digest(&self.prefix_digest)?,
                    )
                    .map_err(io::Error::other)?
                    .ok_or_else(|| io::Error::other("original physical RunStart missing"))
            };
            let observed = read()?;
            let actual = &observed.observed;
            let record = &actual.record;
            let now_micros = now
                .checked_mul(1_000)
                .ok_or_else(|| io::Error::other("original Root clock overflow"))?;
            if observed.frame_start < self.prefix_length
                || observed.frame_end <= observed.frame_start
                || observed.frame_end > observed.observed_length
                || actual.publication.sequence != publication.sequence
                || actual.publication.record_digest != digest(&publication.record_digest)?
                || actual.publication.chain_digest != digest(&publication.chain_digest)?
                || record.snapshot.generation != target.generation()
                || record.snapshot.fence_digest
                    != crate::objective_runtime::objective_fence(identity, target.generation())
                || record.admission.profile_id != decoded.profile.profile_id
                || record.admission.profile_revision != decoded.profile.profile_revision.get()
                || record.admission.observed_at_unix_micros > now_micros
                || record.admission.deadline_unix_micros <= now_micros
                || !decoded
                    .profile
                    .allowed_trusted_source_identities
                    .contains(&record.authentication.issuer_id)
                || !crate::objective_runtime::authentication_is_current(
                    record,
                    &decoded.trust,
                    identity,
                    now,
                )
                .map_err(io::Error::other)?
            {
                return Err(io::Error::other(
                    "original RunStart append or authentication differs",
                ));
            }
            if read()? != observed {
                return Err(io::Error::other("RunStart physical observation changed"));
            }
            self.require_decoded(&decode_inputs(journal, profile, trust, identity, uid, gid)?)?;
            Ok(observed)
        })
    }

    fn require_decoded(&self, decoded: &DecodedInputs) -> io::Result<()> {
        if self.files != decoded.files
            || self.profile_bytes != decoded.profile_bytes
            || self.trust_bytes != decoded.trust_bytes
            || self.profile_digest
                != decoded
                    .profile
                    .digest()
                    .map_err(io::Error::other)?
                    .to_string()
        {
            return Err(io::Error::other(
                "original RunStart input bytes or descriptors changed",
            ));
        }
        Ok(())
    }
}

fn decode_inputs(
    journal: &File,
    profile: &File,
    trust: &File,
    identity: &AgentdIdentity,
    uid: u32,
    gid: u32,
) -> io::Result<DecodedInputs> {
    let files = [
        FilePin::read(journal, uid, gid)?,
        FilePin::read(profile, uid, gid)?,
        FilePin::read(trust, uid, gid)?,
    ];
    if files[0] == files[1] || files[0] == files[2] || files[1] == files[2] {
        return Err(io::Error::other(
            "independent original RunStart inputs required",
        ));
    }
    let profile_bytes = read_bytes(profile, /*bound*/ 262_144)?;
    let trust_bytes = read_bytes(trust, /*bound*/ 16_384)?;
    let profile = decode_admission_profile_json_v1(&profile_bytes).map_err(io::Error::other)?;
    if profile.allowed_trusted_source_identities.is_empty() {
        return Err(io::Error::other("original signed adapter profile required"));
    }
    profile.digest().map_err(io::Error::other)?;
    Ok(DecodedInputs {
        files,
        profile_bytes: Digest32::of_bytes(&profile_bytes).to_string(),
        trust_bytes: Digest32::of_bytes(&trust_bytes).to_string(),
        profile,
        trust: TextTrust::from_original_bytes(&trust_bytes, identity).map_err(io::Error::other)?,
    })
}

fn read_bytes(file: &File, bound: u64) -> io::Result<Vec<u8>> {
    let stamp = |metadata: std::fs::Metadata| {
        (
            metadata.len(),
            metadata.mtime(),
            metadata.mtime_nsec(),
            metadata.ctime(),
            metadata.ctime_nsec(),
        )
    };
    let before = stamp(file.metadata()?);
    if before.0 == 0 || before.0 > bound {
        return Err(io::Error::other("original RunStart metadata exceeds bound"));
    }
    let mut bytes = vec![0; usize::try_from(before.0).map_err(io::Error::other)?];
    file.read_exact_at(&mut bytes, /*offset*/ 0)?;
    if stamp(file.metadata()?) != before {
        return Err(io::Error::other(
            "original RunStart metadata changed during read",
        ));
    }
    Ok(bytes)
}
