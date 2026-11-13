//! Real FD transport mechanism tests. These create no Root grant, original
//! role owner, independent evaluation, or successful A/B/C task.

use super::*;
use pretty_assertions::assert_eq;
use std::io::Read;
use std::io::Write;

fn descriptors() -> anyhow::Result<(Vec<UnixStream>, Vec<UnixStream>)> {
    (0..21).map(|_| UnixStream::pair()).collect::<Result<Vec<_>, _>>()
        .map(|pairs| pairs.into_iter().unzip()).map_err(Into::into)
}

#[test]
fn candidate_wire_preserves_all_original_fd_objects_and_cloexec() -> anyhow::Result<()> {
    let (sender, receiver) = UnixDatagram::pair()?;
    let (streams, mut peers) = descriptors()?;
    let raw = streams.iter().map(AsRawFd::as_raw_fd).collect::<Vec<_>>();
    wire::send(&sender, b"mechanism-only-frame", &raw, Duration::from_secs(1))?;
    drop(streams);
    let (body, rights) = wire::receive(&receiver, Duration::from_secs(1))?;
    assert_eq!(body, b"mechanism-only-frame");
    let mut observed = Vec::new();
    let mut cloexec = Vec::new();
    for (index, (right, peer)) in rights.into_iter().zip(&mut peers).enumerate() {
        // SAFETY: F_GETFD observes the live received FD only.
        cloexec.push(unsafe { libc::fcntl(right.as_raw_fd(), libc::F_GETFD) } & libc::FD_CLOEXEC != 0);
        peer.write_all(&[index as u8])?;
        let mut stream = UnixStream::from(right);
        let mut value = [0_u8];
        stream.read_exact(&mut value)?;
        observed.push(value[0]);
    }
    assert_eq!((observed, cloexec), ((0_u8..21).collect::<Vec<_>>(), vec![true; 21]));
    Ok(())
}

#[test]
fn candidate_wire_and_old_two_right_packet_cannot_consume_each_other() -> anyhow::Result<()> {
    let (sender, receiver) = UnixDatagram::pair()?;
    let (streams, mut peers) = descriptors()?;
    let raw = streams.iter().map(AsRawFd::as_raw_fd).collect::<Vec<_>>();
    wire::send(&sender, b"wrong-for-old-purpose", &raw, Duration::from_secs(1))?;
    drop(streams);
    assert!(super::super::receive_packet(&receiver, Duration::from_secs(1)).is_err());
    for peer in &mut peers {
        peer.set_read_timeout(Some(Duration::from_secs(1)))?;
        assert_eq!(peer.read(&mut [0])?, 0);
    }
    let (sender, receiver) = UnixDatagram::pair()?;
    let (first, mut first_peer) = UnixStream::pair()?;
    let (second, mut second_peer) = UnixStream::pair()?;
    super::super::send_packet(&sender, super::super::FRAME,
        &[first.as_raw_fd(), second.as_raw_fd()], Duration::from_secs(1))?;
    drop((first, second));
    assert!(wire::receive(&receiver, Duration::from_secs(1)).is_err());
    for peer in [&mut first_peer, &mut second_peer] {
        peer.set_read_timeout(Some(Duration::from_secs(1)))?;
        assert_eq!(peer.read(&mut [0])?, 0);
    }
    Ok(())
}

#[test]
fn candidate_wire_rejects_role_socket_alias_and_closes_all_received_rights() -> anyhow::Result<()> {
    let (sender, receiver) = UnixDatagram::pair()?;
    let (mut streams, mut peers) = descriptors()?;
    streams[3] = streams[1].try_clone()?;
    let raw = streams.iter().map(AsRawFd::as_raw_fd).collect::<Vec<_>>();
    wire::send(&sender, b"aliased-role-purpose", &raw, Duration::from_secs(1))?;
    drop(streams);
    assert!(wire::receive(&receiver, Duration::from_secs(1)).is_err());
    for peer in &mut peers {
        peer.set_read_timeout(Some(Duration::from_secs(1)))?;
        assert_eq!(peer.read(&mut [0])?, 0);
    }
    Ok(())
}

fn packet() -> anyhow::Result<(Packet, Digest32)> {
    let pid = std::process::id();
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat"))?;
    let start = stat.rsplit_once(") ").and_then(|(_, fields)| fields.split_whitespace().nth(19))
        .ok_or_else(|| anyhow::anyhow!("actual process stat"))?.parse()?;
    let boot = std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?.trim().to_string();
    let binding = Digest32::of_bytes(b"explicit synthetic framing profile");
    let now = wire::monotonic_ns()?;
    let lanes = ROLES.iter().map(|name| Lane { role: (*name).into(), uid: 1000,
        process: Process { pid, boot_id: boot.clone(), process_start_ticks: start },
        timeout_ns: 100_000_000, end_ns: now + 10_000_000_000 }).collect();
    Ok((Packet { purpose: PURPOSE.into(), profile: binding.to_string(),
        recipient: Process { pid, boot_id: boot, process_start_ticks: start }, lanes }, binding))
}

#[test]
fn candidate_packet_refuses_changed_binding_role_process_and_original_timing() -> anyhow::Result<()> {
    let (packet, binding) = packet()?;
    validate_packet(&packet, binding)?;
    let baseline = serde_json::to_value(&packet)?;
    let mut attacks = Vec::new();
    for (pointer, value) in [
        ("/purpose", serde_json::json!("HEPTA_ROOT_LEARNING_INPUTS_V1")),
        ("/profile", serde_json::json!(Digest32::of_bytes(b"another profile").to_string())),
        ("/recipient/pid", serde_json::json!(0)),
        ("/recipient/boot_id", serde_json::json!("other boot")),
        ("/recipient/process_start_ticks", serde_json::json!(0)),
        ("/lanes/1/role", serde_json::json!("experience")),
        ("/lanes/0/timeout_ns", serde_json::json!(0)),
        ("/lanes/0/timeout_ns", serde_json::json!(30_000_000_001_u64)),
        ("/lanes/6/timeout_ns", serde_json::json!(500_000_001_u64)),
        ("/lanes/0/end_ns", serde_json::json!(0)),
        ("/lanes/0/end_ns", serde_json::json!(u64::MAX)),
    ] {
        let mut changed = baseline.clone();
        *changed.pointer_mut(pointer).ok_or_else(|| anyhow::anyhow!("actual field missing"))? = value;
        let changed: Packet = serde_json::from_value(changed)?;
        attacks.push(validate_packet(&changed, binding).is_err());
    }
    let mut changed: Packet = serde_json::from_value(baseline.clone())?;
    changed.lanes.pop();
    attacks.push(validate_packet(&changed, binding).is_err());
    let mut changed: Packet = serde_json::from_value(baseline.clone())?;
    changed.lanes.swap(0, 1);
    attacks.push(validate_packet(&changed, binding).is_err());
    let mut changed = baseline;
    changed["fresh"] = serde_json::json!(true);
    attacks.push(serde_json::from_value::<Packet>(changed).is_err());
    assert_eq!(attacks, vec![true; 14]);
    Ok(())
}
