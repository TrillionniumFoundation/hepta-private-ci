//! This component has no independent production host.
fn main() {
    eprintln!(
        "Use hepta-matrixd, which owns the durable Matrix inbox/outbox and real SDK transport."
    );
    std::process::exit(64);
}
