//! Full original Candidate data belongs to one bounded readonly transfer.
//! Native/source owners are read at Begin and Finish. No native lane or source
//! permit is held while the original peer requests the intervening pages.
use super::*;

struct OriginalCandidateTransfer {
    material: OriginalCellQ24CandidateMaterialV1,
    transfer: u64,
    next_page: u8,
    last_at: u64,
}

pub(in super::super) struct Session {
    original: Option<OriginalCandidateTransfer>,
    completion: Option<String>,
    owner: Option<usize>,
    failed: bool,
}

impl Session {
    pub(in super::super) fn new() -> Self {
        Self { original: None, completion: None, owner: None, failed: false }
    }

    pub(in super::super) fn unfinished(&self) -> bool { self.original.is_some() }

    pub(in super::super) fn require_owner(&mut self, owner: usize) -> Result<(), Error> {
        if self.failed || self.owner.is_some_and(|original| original != owner) {
            self.fail();
            return Err(Error::CommitUncertain);
        }
        self.owner = Some(owner);
        Ok(())
    }

    pub(in super::super) fn fail(&mut self) {
        self.failed = true;
        self.original = None;
    }

    pub(in super::super) fn require_request(&mut self, request: &Request) -> Result<(), Error> {
        let checked = self.check_request(request);
        if checked.is_err() { self.fail(); }
        checked
    }

    fn check_request(&self, request: &Request) -> Result<(), Error> {
        if self.failed || self.completion.as_ref().is_some_and(|prior| prior != &request.completion) {
            return Err(Error::CommitUncertain);
        }
        match request.phase {
            Phase::Begin if self.original.is_none()
                && request.page == 0 && request.transfer == request.request_id => Ok(()),
            Phase::Page | Phase::Finish => {
                let original = self.original.as_ref().ok_or(Error::ReadbackRequired)?;
                let pages = original.material.heads().len().div_ceil(PAGE_BYTES);
                if request.transfer != original.transfer
                    || request.completion != completion_digest(
                        original.material.receipt(), original.material.attestation(),
                    )?.to_string()
                {
                    return Err(Error::Binding("same original Candidate transfer"));
                }
                match request.phase {
                    Phase::Page if request.page == original.next_page
                        && request.page > 0 && usize::from(request.page) < pages
                        && request.request_id == original.transfer + u64::from(request.page) => Ok(()),
                    Phase::Finish if request.page == 0
                        && usize::from(original.next_page) == pages
                        && request.request_id == original.transfer + pages as u64 => Ok(()),
                    _ => Err(Error::Binding("complete sequential Candidate transfer")),
                }
            }
            _ => Err(Error::Binding("one original Candidate Begin")),
        }
    }

    pub(in super::super) fn begin(
        &mut self,
        request: &Request,
        material: OriginalCellQ24CandidateMaterialV1,
        at: u64,
    ) -> Result<MaterialResult, Error> {
        self.require_request(request)?;
        if request.phase != Phase::Begin
            || request.completion != completion_digest(
                material.receipt(), material.attestation(),
            )?.to_string()
            || !(12..=32_780).contains(&material.heads().len())
            || material.authority() != codex_hepta_types::AuthorityPosture::DENY_ALL
        {
            self.fail();
            return Err(Error::Binding("same complete original Candidate Begin"));
        }
        let pages = material.heads().len().div_ceil(PAGE_BYTES);
        if request.transfer.checked_add(pages as u64).is_none_or(|last| last > 128) {
            self.fail();
            return Err(Error::Unavailable);
        }
        let result = original_page(request, &material)?;
        self.original = Some(OriginalCandidateTransfer {
            material, transfer: request.transfer, next_page: 0, last_at: at,
        });
        Ok(result)
    }

    pub(in super::super) fn require_current(
        &mut self,
        context: &OriginalCellQ24TrainingCommandContextV1,
        lower: u64,
    ) -> Result<u64, Error> {
        let original = self.original.as_mut().ok_or(Error::ReadbackRequired)?;
        let current = super::super::now()?;
        if current < lower || current < original.last_at {
            self.fail();
            return Err(Error::CommitUncertain);
        }
        let checked = super::super::wire::authenticate_receipt(
            context,
            original.material.receipt().clone(),
            original.material.attestation().clone(),
            current,
        )?;
        if checked.receipt() != original.material.receipt()
            || checked.attestation() != original.material.attestation()
        {
            self.fail();
            return Err(Error::CommitUncertain);
        }
        original.last_at = current;
        Ok(current)
    }

    pub(in super::super) fn page(&mut self, request: &Request) -> Result<MaterialResult, Error> {
        self.require_request(request)?;
        if request.phase != Phase::Page {
            self.fail();
            return Err(Error::Binding("original Candidate Page"));
        }
        original_page(request, &self.original.as_ref().ok_or(Error::ReadbackRequired)?.material)
    }

    pub(in super::super) fn finish(
        &mut self,
        request: &Request,
        current: OriginalCellQ24CandidateMaterialV1,
    ) -> Result<MaterialResult, Error> {
        self.require_request(request)?;
        let original = &self.original.as_ref().ok_or(Error::ReadbackRequired)?.material;
        if request.phase != Phase::Finish
            || current.heads() != original.heads()
            || current.bundle() != original.bundle()
            || current.model().components() != original.model().components()
            || current.receipt() != original.receipt()
            || current.attestation() != original.attestation()
            || current.authority() != codex_hepta_types::AuthorityPosture::DENY_ALL
        {
            self.fail();
            return Err(Error::CommitUncertain);
        }
        Ok(MaterialResult::Finished {
            total: current.heads().len() as u32,
            heads_digest: Digest32::of_bytes(current.heads()).to_string(),
        })
    }

    pub(in super::super) fn encode_response(
        &mut self,
        request: Request,
        result: MaterialResult,
    ) -> Result<(Vec<u8>, SessionDisposition), Error> {
        // Begin has already pinned its actual material, so it cannot be
        // admitted as another Begin. Validate only its exact first response.
        let first = request.phase == Phase::Begin
            && self.original.as_ref().is_some_and(|original|
                original.next_page == 0 && original.transfer == request.transfer
                && request.request_id == original.transfer && request.page == 0);
        if !first { self.require_request(&request)?; }
        let disposition = match &result {
            MaterialResult::Page { offset, total, heads, heads_digest } => {
                let original = self.original.as_mut().ok_or(Error::ReadbackRequired)?;
                let material = &original.material;
                let bytes = STANDARD_NO_PAD.decode(heads)
                    .map_err(|_| Error::Binding("canonical original Candidate page"))?;
                if !matches!(request.phase, Phase::Begin | Phase::Page)
                    || usize::from(request.page) != usize::from(original.next_page)
                    || request.completion != completion_digest(
                        material.receipt(), material.attestation(),
                    )?.to_string()
                    || *total as usize != material.heads().len()
                    || *offset as usize != usize::from(request.page) * PAGE_BYTES
                    || *offset as usize >= *total as usize
                    || bytes.len() != PAGE_BYTES.min(*total as usize - *offset as usize)
                    || STANDARD_NO_PAD.encode(&bytes) != *heads
                    || *heads_digest != Digest32::of_bytes(material.heads()).to_string()
                    || bytes.as_slice() != &material.heads()[
                        *offset as usize..*offset as usize + bytes.len()
                    ]
                {
                    self.fail();
                    return Err(Error::Binding("one complete canonical Candidate page"));
                }
                original.next_page += 1;
                self.completion = Some(request.completion.clone());
                SessionDisposition::ContinueReadback
            }
            MaterialResult::Finished { total, heads_digest } => {
                let original = self.original.as_ref().ok_or(Error::ReadbackRequired)?;
                if request.phase != Phase::Finish || *total as usize != original.material.heads().len()
                    || *heads_digest != Digest32::of_bytes(original.material.heads()).to_string()
                {
                    self.fail();
                    return Err(Error::CommitUncertain);
                }
                self.original = None;
                SessionDisposition::ContinueReadback
            }
            _ => {
                self.fail();
                SessionDisposition::CloseReadback
            }
        };
        let bytes = serde_json::to_vec(&Response { request, result })?;
        if bytes.len() > FRAME_BYTES {
            self.fail();
            return Err(Error::Binding("existing Candidate frame bound"));
        }
        Ok((bytes, disposition))
    }
}
