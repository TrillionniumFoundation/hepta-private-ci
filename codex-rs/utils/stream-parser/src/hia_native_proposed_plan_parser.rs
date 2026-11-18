//! Borrowed native ProposedPlan transport; parsing decisions stay in HIA.

#[path = "hia_native_proposed_plan_parser_commands.rs"]
mod commands;
#[path = "hia_native_proposed_plan_parser_wire.rs"]
mod wire;

use super::CLOSE_TAG;
use super::OPEN_TAG;
use super::PlanTag;
use crate::tagged_line_parser::TagSpec;
use crate::tagged_line_parser::TaggedLineSegment;
use commands::Command;
use std::fmt;
use wire::FINAL;
use wire::FIRST;
use wire::FRAME_BYTES;
use wire::Operation;
use wire::Request;
use wire::State;
use wire::WireError;

unsafe extern "C" {
    fn codex_hia_proposed_plan_parser(
        source: *const u8,
        source_len: usize,
        output: *mut u8,
        output_len: usize,
        workspace: *mut u8,
        workspace_len: usize,
    ) -> u64;
}

pub(super) struct NativeProposedPlanParser {
    state: State,
    pending: String,
}

impl NativeProposedPlanParser {
    pub(super) fn new() -> Self {
        Self {
            state: State::INITIAL,
            pending: String::new(),
        }
    }

    pub(super) fn parse(&mut self, delta: &str) -> Vec<TaggedLineSegment<PlanTag>> {
        let mut segments = Vec::new();
        let mut remaining = delta;
        let mut first = true;
        loop {
            let mut end = remaining.len().min(FRAME_BYTES);
            while !remaining.is_char_boundary(end) {
                end -= 1;
            }
            let (payload, tail) = remaining.split_at(end);
            let mut flags = if first { FIRST } else { 0 };
            if tail.is_empty() {
                flags |= FINAL;
            }
            let request = Request {
                operation: Operation::Push,
                flags,
                state: self.state,
                payload,
            };
            let (state, commands) = match invoke(&request, &self.pending, &segments) {
                Ok(frame) => frame,
                Err(error) => panic!("HIA proposed plan parser: {error:?}"),
            };
            commands::apply(commands, payload, &mut self.pending, &mut segments);
            self.state = state;
            if tail.is_empty() {
                return segments;
            }
            remaining = tail;
            first = false;
        }
    }

    pub(super) fn finish(&mut self) -> Vec<TaggedLineSegment<PlanTag>> {
        let mut segments = Vec::new();
        let request = Request {
            operation: Operation::Finish,
            flags: 0,
            state: self.state,
            payload: "",
        };
        let (state, commands) = match invoke(&request, &self.pending, &segments) {
            Ok(frame) => frame,
            Err(error) => panic!("HIA proposed plan parser: {error:?}"),
        };
        commands::apply(commands, "", &mut self.pending, &mut segments);
        self.state = state;
        segments
    }
}

fn invoke(
    request: &Request<'_>,
    pending: &str,
    segments: &[TaggedLineSegment<PlanTag>],
) -> Result<(State, Vec<Command>), WireError> {
    let source = request.encode(pending.len())?;
    let mut output = vec![0; request.capacity()?];
    let mut workspace = [0; 1];
    // All buffers are separate, live allocations for this synchronous borrowed call.
    // The native entry retains no pointers; the full u64 wrapper result is checked below.
    let returned = unsafe {
        codex_hia_proposed_plan_parser(
            source.as_ptr(),
            source.len(),
            output.as_mut_ptr(),
            output.len(),
            workspace.as_mut_ptr(),
            workspace.len(),
        )
    };
    let response = wire::decode(request, pending.len(), returned, &output)?;
    let commands = commands::decode(request, &response, pending.len(), segments)?;
    Ok((response.state, commands))
}

/// The original TagSpec value projected through the standard Debug formatter.
struct TagSpecDebug(TagSpec<PlanTag>);

impl fmt::Debug for TagSpecDebug {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("TagSpec")
            .field("open", &self.0.open)
            .field("close", &self.0.close)
            .field("tag", &self.0.tag)
            .finish()
    }
}

impl fmt::Debug for NativeProposedPlanParser {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let request = Request {
            operation: Operation::Inspect,
            flags: 0,
            state: self.state,
            payload: "",
        };
        let (state, _) = invoke(&request, &self.pending, &[]).map_err(|_| fmt::Error)?;
        let specs = [TagSpecDebug(TagSpec {
            open: OPEN_TAG,
            close: CLOSE_TAG,
            tag: PlanTag::ProposedPlan,
        })];
        let active_tag = if state.active == 0 {
            None
        } else {
            Some(PlanTag::ProposedPlan)
        };
        formatter
            .debug_struct("TaggedLineParser")
            .field("specs", &specs)
            .field("active_tag", &active_tag)
            .field("detect_tag", &(state.detect != 0))
            .field("line_buffer", &self.pending)
            .finish()
    }
}

#[cfg(test)]
#[path = "hia_native_proposed_plan_parser_wire_tests.rs"]
mod tests;
