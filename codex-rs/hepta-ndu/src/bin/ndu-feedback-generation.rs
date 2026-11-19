//! Persistent local experiment bridge; not a production dispatch endpoint.

use std::io;

fn main() -> io::Result<()> {
    codex_hepta_ndu::run_feedback_generation_protocol(io::stdin().lock(), io::stdout().lock())
}
