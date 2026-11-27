//! Own placeholder strings in the canonical order chosen by the HIA index.
//!
//! The index compares ranges in the parser's original borrowed source. Rust
//! only retains accepted strings and moves them according to native node IDs.

use super::hia_native_index::Index;
use super::hia_native_index::Insert;
use std::fmt;
use std::ops::Range;
use std::slice;

#[derive(Clone, PartialEq, Eq)]
pub(super) struct Placeholders {
    names: Vec<String>,
}

impl Placeholders {
    pub(super) fn iter(&self) -> slice::Iter<'_, String> {
        self.names.iter()
    }
}

impl fmt::Debug for Placeholders {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        // Preserve the public Template Debug representation of its old set.
        formatter.debug_set().entries(&self.names).finish()
    }
}

pub(super) struct Builder<'a> {
    source: &'a str,
    index: Index,
    names: Vec<Option<String>>,
}

impl<'a> Builder<'a> {
    pub(super) fn new(source: &'a str) -> Self {
        Self {
            source,
            index: Index::new(),
            names: Vec::new(),
        }
    }

    pub(super) fn insert(&mut self, range: Range<usize>, name: &str) {
        match self
            .index
            .insert_range(self.source.as_bytes(), range.start, range.end)
        {
            Insert::New { id } => {
                assert_eq!(id, self.names.len(), "invalid HIA placeholder node ID");
                self.names.push(Some(name.to_owned()));
            }
            Insert::Existing { id } => {
                assert!(id < self.names.len(), "invalid HIA duplicate node ID");
            }
        }
    }

    pub(super) fn finish(mut self) -> Placeholders {
        let order = self.index.ordered_ids();
        assert_eq!(order.len(), self.names.len(), "invalid HIA index length");
        let mut names = Vec::with_capacity(order.len());
        for id in order {
            let Some(slot) = self.names.get_mut(id) else {
                panic!("invalid HIA ordered node ID");
            };
            let Some(name) = slot.take() else {
                panic!("repeated HIA ordered node ID");
            };
            names.push(name);
        }
        Placeholders { names }
    }
}
