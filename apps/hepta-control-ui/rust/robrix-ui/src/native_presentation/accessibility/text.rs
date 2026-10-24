//! Accessibility positions use the SDK's pinned grapheme boundaries, not UTF-16
//! indices or Rust byte offsets. Large clusters remain readable without a
//! fabricated caret mapping when AccessKit's u8 lengths cannot represent them.
use accesskit::Node;
use accesskit::NodeId;
use accesskit::Role;
use accesskit::TextPosition;
use accesskit::TextSelection;
use makepad_unicode_segmentation::UnicodeSegmentation;

pub(super) struct Run {
    pub(super) id: NodeId,
    pub(super) start: usize,
    pub(super) boundaries: Vec<usize>,
}

pub(super) fn build(
    value: &str,
    mut allocate: impl FnMut(usize) -> NodeId,
) -> (Vec<(NodeId, Node)>, Vec<Run>) {
    let mut nodes = Vec::new();
    let mut runs = Vec::new();
    let mut start = 0;
    let mut lines: Vec<&str> = if value.is_empty() {
        vec![""]
    } else {
        value.split_inclusive('\n').collect()
    };
    if value.ends_with('\n') {
        lines.push("");
    }
    for (index, line) in lines.into_iter().enumerate() {
        let id = allocate(index);
        let mut node = Node::new(Role::TextRun);
        node.set_value(line);
        let mut boundaries: Vec<usize> = line
            .grapheme_indices(true)
            .map(|(offset, _)| offset)
            .collect();
        boundaries.push(line.len());
        let lengths: Option<Vec<u8>> = boundaries
            .windows(2)
            .map(|range| u8::try_from(range[1] - range[0]).ok())
            .collect();
        if let Some(lengths) = lengths {
            node.set_character_lengths(lengths);
            runs.push(Run {
                id,
                start,
                boundaries,
            });
        }
        nodes.push((id, node));
        start += line.len();
    }
    (nodes, runs)
}

pub(super) fn position(runs: &[Run], byte: usize) -> Option<TextPosition> {
    let run = runs.iter().rev().find(|run| run.start <= byte)?;
    let character_index = run
        .boundaries
        .iter()
        .position(|offset| run.start + offset == byte)?;
    Some(TextPosition {
        node: run.id,
        character_index,
    })
}

pub(super) fn selection(runs: &[Run], selection: TextSelection) -> Option<(usize, usize)> {
    let byte = |position: TextPosition| {
        let run = runs.iter().find(|run| run.id == position.node)?;
        run.boundaries
            .get(position.character_index)
            .map(|index| run.start + index)
    };
    Some((byte(selection.anchor)?, byte(selection.focus)?))
}

#[cfg(test)]
#[path = "text_tests.rs"]
mod tests;
