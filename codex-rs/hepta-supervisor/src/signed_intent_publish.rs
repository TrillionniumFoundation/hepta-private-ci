//! Publish an already-synchronized signed-intent staging file without a
//! cross-volume copy. A reported failure never acknowledges the new state.

use std::io;
use std::path::Path;

pub(crate) fn publish(staging: &Path, destination: &Path) -> io::Result<()> {
    crate::durable_publish::publish_at(staging, destination, "signed_intent")
}

#[cfg(test)]
#[path = "signed_intent_publish_tests.rs"]
mod tests;
