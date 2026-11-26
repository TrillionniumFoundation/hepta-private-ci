//! Mechanical application of HIA decisions to the original parser fields.

use super::ActiveTag;
use super::ExtractedInlineTag;
use super::InlineHiddenTagParser;
use crate::StreamTextChunk;

#[path = "hia_native_inline_hidden_tag_wire.rs"]
mod wire;

pub(super) fn push<T>(
    parser: &mut InlineHiddenTagParser<T>,
    chunk: &str,
) -> StreamTextChunk<ExtractedInlineTag<T>>
where
    T: Clone + Eq,
{
    parser.pending.push_str(chunk);
    let mut out = StreamTextChunk::default();
    loop {
        let decision = match parser.active.as_ref() {
            Some(active) => wire::close(&parser.pending, active.close),
            None => wire::open(&parser.pending, &parser.specs),
        };
        match decision {
            wire::Decision::Visible { take } => {
                if take > 0 {
                    out.visible_text.push_str(&parser.pending[..take]);
                    parser.pending.drain(..take);
                }
                break;
            }
            wire::Decision::Open {
                take,
                consume,
                spec_index,
            } => {
                if take > 0 {
                    out.visible_text.push_str(&parser.pending[..take]);
                }
                let spec = &parser.specs[spec_index];
                // Retain the original order: drain before cloning the tag.
                // A user-defined Clone may panic or have observable effects.
                parser.pending.drain(..consume);
                parser.active = Some(ActiveTag {
                    tag: spec.tag.clone(),
                    close: spec.close,
                    content: String::new(),
                });
            }
            wire::Decision::Body { take } => {
                if take > 0 {
                    if let Some(active) = parser.active.as_mut() {
                        active.content.push_str(&parser.pending[..take]);
                    }
                    parser.pending.drain(..take);
                }
                break;
            }
            wire::Decision::Close { take, consume } => {
                let Some(mut active) = parser.active.take() else {
                    continue;
                };
                active.content.push_str(&parser.pending[..take]);
                out.extracted.push(ExtractedInlineTag {
                    tag: active.tag,
                    content: active.content,
                });
                parser.pending.drain(..consume);
            }
        }
    }
    out
}

pub(super) fn finish<T>(
    parser: &mut InlineHiddenTagParser<T>,
) -> StreamTextChunk<ExtractedInlineTag<T>>
where
    T: Clone + Eq,
{
    let channel = match parser.active {
        Some(_) => wire::FinishChannel::Tag,
        None => wire::FinishChannel::Visible,
    };
    let decision = wire::finish(&parser.pending, channel);
    let mut out = StreamTextChunk::default();
    match decision {
        wire::FinishChannel::Tag => {
            if let Some(mut active) = parser.active.take() {
                if !parser.pending.is_empty() {
                    active.content.push_str(&parser.pending);
                    parser.pending.clear();
                }
                out.extracted.push(ExtractedInlineTag {
                    tag: active.tag,
                    content: active.content,
                });
            }
        }
        wire::FinishChannel::Visible => {
            if !parser.pending.is_empty() {
                out.visible_text.push_str(&parser.pending);
                parser.pending.clear();
            }
        }
    }
    out
}
