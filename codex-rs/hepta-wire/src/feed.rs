//! Bounded decoder progress with explicit ownership of the unconsumed suffix.

#[must_use = "process the batch and resubmit input after bytes_consumed"]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DecodeFeed<B> {
    batch: B,
    bytes_consumed: usize,
}

impl<B> DecodeFeed<B> {
    pub(crate) fn new(batch: B, bytes_consumed: usize) -> Self {
        Self {
            batch,
            bytes_consumed,
        }
    }

    pub fn batch(&self) -> &B {
        &self.batch
    }

    pub const fn bytes_consumed(&self) -> usize {
        self.bytes_consumed
    }

    pub fn into_parts(self) -> (B, usize) {
        (self.batch, self.bytes_consumed)
    }
}
