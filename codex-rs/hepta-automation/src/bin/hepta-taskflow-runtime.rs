//! This component has no independent production host.
fn main() {
    eprintln!(
        "Use the agentd-owned AutomationScheduler. Durable TaskFlow effect dispatch is not configured."
    );
    std::process::exit(64);
}
