//! This component has no independent production host.
fn main() {
    eprintln!(
        "Use the supervisor-owned FleetRegistry. No physical capacity observer or lease authority is configured."
    );
    std::process::exit(64);
}
