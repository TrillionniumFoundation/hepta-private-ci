//! This component has no independent production host.
fn main() {
    eprintln!(
        "The durable control component requires an owning host with real reservation and worker authorities; none is configured by this entry point."
    );
    std::process::exit(64);
}
