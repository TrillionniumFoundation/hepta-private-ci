//! Citation storage and framing; HIA owns all marker and EOF decisions.

use std::fmt;

use crate::ExtractedInlineTag;
use crate::InlineTagSpec;
use crate::StreamTextChunk;
use crate::StreamTextParser;
use crate::citation::CITATION_CLOSE;
use crate::citation::CITATION_OPEN;
use crate::citation::CitationTag;
use crate::hia_native_citation_stream_parser_wire as wire;
use wire::Kind;
use wire::NativeResult;
use wire::Operation;

pub(super) struct NativeCitationParser {
    state: wire::State,
    body: Vec<u8>,
}

impl NativeCitationParser {
    pub(super) fn new() -> Self {
        Self {
            state: wire::State::default(),
            body: Vec::new(),
        }
    }

    fn run(
        &mut self,
        operation: Operation,
        payload: &[u8],
    ) -> NativeResult<StreamTextChunk<ExtractedInlineTag<CitationTag>>> {
        let mut visible = Vec::new();
        let mut extracted = Vec::new();
        if payload.is_empty() {
            let reply = wire::call(operation, self.state, payload)?;
            self.apply(reply, &mut visible, &mut extracted)?;
        } else {
            for fragment in payload.chunks(wire::CHUNK_BYTES) {
                let reply = wire::call(operation, self.state, fragment)?;
                self.apply(reply, &mut visible, &mut extracted)?;
            }
        }
        let visible_text = String::from_utf8(visible)
            .map_err(|_| "native citation visible text is not complete UTF-8")?;
        Ok(StreamTextChunk {
            visible_text,
            extracted,
        })
    }

    fn apply(
        &mut self,
        reply: wire::Reply,
        visible: &mut Vec<u8>,
        extracted: &mut Vec<ExtractedInlineTag<CitationTag>>,
    ) -> NativeResult<()> {
        for event in &reply.events {
            let payload = &reply.bytes[event.start..event.end];
            match event.kind {
                Kind::Visible => append(visible, payload)?,
                Kind::Body => append(&mut self.body, payload)?,
                Kind::Commit => {
                    extracted
                        .len()
                        .checked_add(/*rhs*/ 1)
                        .ok_or("native citation count overflow")?;
                    let content = String::from_utf8(std::mem::take(&mut self.body))
                        .map_err(|_| "native citation body is not complete UTF-8")?;
                    extracted.push(ExtractedInlineTag {
                        tag: CitationTag::Citation,
                        content,
                    });
                }
                Kind::Pending => return Err("native citation mutation returned inspection data"),
            }
        }
        if reply.state.active == 0 && !self.body.is_empty() {
            return Err("native citation inactive state retained an uncommitted body");
        }
        self.state = reply.state;
        Ok(())
    }
}

fn append(target: &mut Vec<u8>, fragment: &[u8]) -> NativeResult<()> {
    target
        .len()
        .checked_add(fragment.len())
        .ok_or("native citation container length overflow")?;
    target.extend_from_slice(fragment);
    Ok(())
}

impl StreamTextParser for NativeCitationParser {
    type Extracted = ExtractedInlineTag<CitationTag>;

    fn push_str(&mut self, chunk: &str) -> StreamTextChunk<Self::Extracted> {
        match self.run(Operation::Push, chunk.as_bytes()) {
            Ok(output) => output,
            Err(reason) => panic!("HIA citation parser failed: {reason}"),
        }
    }

    fn finish(&mut self) -> StreamTextChunk<Self::Extracted> {
        match self.run(Operation::Finish, &[]) {
            Ok(output) => output,
            Err(reason) => panic!("HIA citation parser failed: {reason}"),
        }
    }
}

struct ActiveTag<'a> {
    content: &'a str,
}

impl fmt::Debug for ActiveTag<'_> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("ActiveTag")
            .field("tag", &CitationTag::Citation)
            .field("close", &CITATION_CLOSE)
            .field("content", &self.content)
            .finish()
    }
}

impl fmt::Debug for NativeCitationParser {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let reply = wire::call(Operation::Inspect, self.state, &[]).map_err(|_| fmt::Error)?;
        let event = &reply.events[0];
        let pending =
            std::str::from_utf8(&reply.bytes[event.start..event.end]).map_err(|_| fmt::Error)?;
        let body = std::str::from_utf8(&self.body).map_err(|_| fmt::Error)?;
        if reply.state.active == 0 && !body.is_empty() {
            return Err(fmt::Error);
        }
        let specs = [InlineTagSpec {
            tag: CitationTag::Citation,
            open: CITATION_OPEN,
            close: CITATION_CLOSE,
        }];
        let active = (reply.state.active != 0).then_some(ActiveTag { content: body });
        f.debug_struct("InlineHiddenTagParser")
            .field("specs", &specs)
            .field("pending", &pending)
            .field("active", &active)
            .finish()
    }
}
