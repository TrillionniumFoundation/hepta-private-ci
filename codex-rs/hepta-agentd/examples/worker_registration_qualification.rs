//! Explicit no-effect child for privileged Worker registration qualification.
//! It cannot serve a provider, create a local FinalUse owner or activate a Cell.

#[cfg(target_os = "linux")]
#[path = "worker_registration_qualification/lanes.rs"]
mod lanes;

#[cfg(target_os = "linux")]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    use codex_hepta_agentd::receive_root_production_handoff;
    use codex_hepta_agentd::receive_worker_root_registration;
    use codex_hepta_contracts::AgentId;
    use std::io::Read;
    use std::io::Write;
    use std::os::fd::FromRawFd;
    use std::os::unix::net::UnixDatagram;
    use std::time::Duration;

    let arguments = std::env::args().collect::<Vec<_>>();
    assert_eq!(arguments.len(), 4);
    let mode = arguments[1].as_str();
    let agent = AgentId::parse(arguments[2].clone())?;
    let generation = arguments[3].parse::<u64>()?;
    let mut stdout = std::io::stdout().lock();
    stdout.write_all(b"R")?;
    stdout.flush()?;
    if mode == "owner" {
        let mut stop = [0];
        std::io::stdin().read_exact(&mut stop)?;
        assert_eq!(stop, [1]);
        return Ok(());
    }
    // SAFETY: this explicit fixture is launched by Root with one inherited
    // anonymous socket at 198. It adopts it once; no path or numeric PID is
    // accepted as production authority by the receiver called below.
    let socket = unsafe { UnixDatagram::from_raw_fd(198) };
    if mode.starts_with("lanes-") {
        drop(stdout);
        return lanes::run(mode, socket, &agent, generation);
    }
    let mut receipt = None;
    let message = match mode {
        "receive" | "wrong-agent" => {
            match receive_worker_root_registration(socket, &agent, generation, Duration::from_secs(10)) {
                Ok(value) => {
                    let message = serde_json::json!({"kind":"receipt", "observation":value.observation()});
                    receipt = Some(value);
                    message
                }
                Err(error) => serde_json::json!({"kind":"refused", "error":error.to_string()}),
            }
        }
        "drop-ack" | "exit-after-offer" => {
            let (sealed, root) = receive_root_production_handoff(socket, Duration::from_secs(10))?;
            // This test intentionally stops after the real original transport.
            // Raw sealed custody is not a Worker registration receipt.
            serde_json::json!({"kind":"offered_unacknowledged", "sealed_bytes":sealed.metadata()?.len(), "root_pidfd_retained_until_message":std::os::fd::AsRawFd::as_raw_fd(&root)>=0})
        }
        "closed-receiver" => {
            drop(socket);
            serde_json::json!({"kind":"receiver_closed_before_offer"})
        }
        _ => return Err("unknown explicit qualification child mode".into()),
    };
    let bytes = serde_json::to_vec(&message)?;
    assert!(bytes.len() <= 64 * 1024);
    stdout.write_all(&(bytes.len() as u32).to_be_bytes())?;
    stdout.write_all(&bytes)?;
    stdout.flush()?;
    if mode == "exit-after-offer" {
        return Ok(());
    }
    let mut stop = [0];
    std::io::stdin().read_exact(&mut stop)?;
    assert_eq!(stop, [1]);
    drop(receipt);
    Ok(())
}

#[cfg(not(target_os = "linux"))]
fn main() {
    panic!("the explicit Root Worker qualification requires Linux");
}
