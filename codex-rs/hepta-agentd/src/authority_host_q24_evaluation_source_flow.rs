//! Private once-only sequencing between B frames. No state lock is held while
//! waiting for a source, and no wait starts or renews a protocol frame/lifetime.

use super::*;
use crate::root_independent_b_candidate_notice::CandidateNotice;
use crate::root_independent_b_notice::OriginalBNoticeWriter;
use crate::root_independent_b_source_protocol::SourceAcknowledgement;
use crate::root_independent_b_source_protocol::SourceMode;
use crate::root_independent_b_source_ready::SourceReadyData;

#[derive(Clone, Copy, Eq, PartialEq)]
enum Phase {
    Pending,
    Prepared,
    Admitted,
    Refused,
}

struct State {
    phase: Phase,
    candidate: Option<CandidateNotice>,
    admitted: Option<SourceReadyData>,
    candidate_writer: Option<OriginalBNoticeWriter>,
    admitted_writer: Option<OriginalBNoticeWriter>,
    finalized_writer: Option<OriginalBNoticeWriter>,
}

pub(super) struct OriginalBSourceNotices {
    pub(super) candidate: Option<File>,
    pub(super) finalized: Option<File>,
    pub(super) admitted: File,
}

pub(super) struct OriginalBSourceFlow {
    state: Mutex<State>,
    mode: SourceMode,
    retained: Option<SourceAcknowledgement>,
}

impl OriginalBSourceFlow {
    pub(super) fn prepare(
        mode: SourceMode,
        retained: Option<SourceAcknowledgement>,
    ) -> io::Result<(Self, OriginalBSourceNotices)> {
        if (mode == SourceMode::Retained) != retained.is_some() {
            return Err(io::Error::other(
                "original B retained source identity differs",
            ));
        }
        let (candidate_writer, candidate_reader) = if mode == SourceMode::FreshInput {
            let (writer, reader) = OriginalBNoticeWriter::pair()?;
            (Some(writer), Some(reader))
        } else {
            (None, None)
        };
        let (finalized_writer, finalized_reader) = if mode == SourceMode::FreshInput {
            let (writer, reader) = OriginalBNoticeWriter::pair()?;
            (Some(writer), Some(reader))
        } else {
            (None, None)
        };
        let (admitted_writer, admitted_reader) = OriginalBNoticeWriter::pair()?;
        Ok((
            Self {
                state: Mutex::new(State {
                    phase: Phase::Pending,
                    candidate: None,
                    admitted: None,
                    candidate_writer,
                    admitted_writer: Some(admitted_writer),
                    finalized_writer,
                }),
                mode,
                retained,
            },
            OriginalBSourceNotices {
                candidate: candidate_reader,
                finalized: finalized_reader,
                admitted: admitted_reader,
            },
        ))
    }

    pub(super) fn publish_candidate(
        &self,
        candidate: CandidateNotice,
        end: Instant,
        mut require_original: impl FnMut() -> io::Result<()>,
    ) -> io::Result<()> {
        let result = (|| {
            require_original()?;
            let writer = {
                let mut state = self
                    .state
                    .lock()
                    .map_err(|_| io::Error::other("B source flow poisoned"))?;
                if state.phase != Phase::Pending || self.mode == SourceMode::NoUpdate {
                    return Err(io::Error::other(
                        "original B candidate notification already consumed",
                    ));
                }
                state.phase = Phase::Prepared;
                state.candidate = Some(candidate.clone());
                state.candidate_writer.take()
            };
            if let Some(writer) = writer {
                writer.send(&candidate.encode()?, end, &mut require_original)?;
            } else {
                let retained = self
                    .retained
                    .clone()
                    .ok_or_else(|| io::Error::other("retained original B source absent"))?;
                self.publish_admitted(retained, end, &mut require_original)?;
            }
            require_original()?;
            if Instant::now() >= end {
                return Err(io::Error::other("original B candidate end elapsed"));
            }
            Ok(())
        })();
        if result.is_err() {
            self.refuse();
        }
        result
    }

    pub(super) fn require_prepared(&self) -> io::Result<CandidateNotice> {
        let state = self
            .state
            .lock()
            .map_err(|_| io::Error::other("B source flow poisoned"))?;
        if state.phase != Phase::Prepared {
            return Err(io::Error::other(
                "original B source has no prepared candidate",
            ));
        }
        state
            .candidate
            .clone()
            .ok_or_else(|| io::Error::other("original B candidate notice missing"))
    }

    pub(super) fn publish_admitted(
        &self,
        source: SourceAcknowledgement,
        end: Instant,
        mut require_original: impl FnMut() -> io::Result<()>,
    ) -> io::Result<()> {
        let result = (|| {
            let candidate = self.require_prepared()?;
            if self
                .retained
                .as_ref()
                .is_some_and(|retained| retained != &source)
            {
                return Err(io::Error::other("retained B source notification differs"));
            }
            let ready = SourceReadyData::from_original_source(&candidate, source)?;
            let (writer, finalized) = {
                let mut state = self
                    .state
                    .lock()
                    .map_err(|_| io::Error::other("B source flow poisoned"))?;
                if state.phase != Phase::Prepared {
                    return Err(io::Error::other("original B source opportunity ended"));
                }
                let writer = state.admitted_writer.take().ok_or_else(|| {
                    io::Error::other("original B source readiness already consumed")
                })?;
                (writer, state.finalized_writer.take())
            };
            if let Some(finalized) = finalized {
                // The source remains alive until this EOF. Every source-pidfd
                // check in its original frame has already returned successfully.
                let bytes =
                    crate::root_independent_b_source_finalized::encode_original_source_finalized(
                        &ready,
                    )?;
                finalized.send(&bytes, end, &mut require_original)?;
            }
            writer.send(&ready.encode()?, end, &mut require_original)?;
            require_original()?;
            if Instant::now() >= end {
                return Err(io::Error::other("original B source end elapsed"));
            }
            let mut state = self
                .state
                .lock()
                .map_err(|_| io::Error::other("B source flow poisoned"))?;
            if state.phase != Phase::Prepared {
                return Err(io::Error::other("original B source opportunity ended"));
            }
            state.admitted = Some(ready);
            state.phase = Phase::Admitted;
            Ok(())
        })();
        if result.is_err() {
            self.refuse();
        }
        result
    }

    pub(super) fn wait_admitted(
        &self,
        end: Instant,
        mut require_original: impl FnMut() -> io::Result<()>,
    ) -> io::Result<()> {
        loop {
            require_original()?;
            let left = end
                .checked_duration_since(Instant::now())
                .filter(|left| !left.is_zero())
                .ok_or_else(|| io::Error::other("original B source wait ended"))?;
            {
                let state = self
                    .state
                    .lock()
                    .map_err(|_| io::Error::other("B source flow poisoned"))?;
                match state.phase {
                    Phase::Admitted if state.admitted.is_some() => return Ok(()),
                    Phase::Prepared => {}
                    Phase::Pending | Phase::Admitted | Phase::Refused => {
                        return Err(io::Error::other("original B source was not retained"));
                    }
                }
            }
            std::thread::sleep(left.min(std::time::Duration::from_millis(5)));
        }
    }

    pub(super) fn require_admitted(&self, data: &SourceReadyData) -> io::Result<()> {
        let state = self
            .state
            .lock()
            .map_err(|_| io::Error::other("B source flow poisoned"))?;
        if state.phase != Phase::Admitted || state.admitted.as_ref() != Some(data) {
            return Err(io::Error::other("original B source completion cut differs"));
        }
        Ok(())
    }

    pub(super) fn refuse(&self) {
        if let Ok(mut state) = self.state.lock() {
            state.phase = Phase::Refused;
            state.candidate_writer.take();
            state.admitted_writer.take();
            state.finalized_writer.take();
        }
    }
}
