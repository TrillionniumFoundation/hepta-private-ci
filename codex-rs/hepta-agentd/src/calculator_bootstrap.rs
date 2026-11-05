//! Exact Calculator handoff into the original recovered writer/runtime.
use crate::AgentdCalculatorChannel;
use crate::AgentdCalculatorStateObserver;
use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdProductionOperationRuntimeConfig;
use crate::AgentdProductionWriterHost;
use crate::calculator_deadline::Deadline;
use crate::notes_bootstrap::received_descriptors;
use crate::notes_bootstrap::require_socket;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_memory::CalculatorTargetIdentity;
use codex_hepta_memory::ProductionCalculatorTarget;
use serde::Deserialize;
use serde::Serialize;
use std::io;
use std::mem;
use std::os::fd::AsRawFd;
use std::os::unix::net::UnixDatagram;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::time::Duration;

const MAX_BYTES: usize = 1024;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Offer {
    schema_version: u16,
    action: OfferAction,
    target: CalculatorTargetIdentity,
    destination_id: String,
}
#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum OfferAction {
    OfferCalculatorTarget,
}
#[derive(Serialize)]
#[serde(rename_all = "snake_case")]
enum Status {
    Attached,
    Rejected,
}

impl AgentdProductionOperationRuntimeConfig {
    pub(crate) async fn with_calculator_from_session_expected_before(
        self,
        config: &AgentdConfig,
        host: &AgentdProductionWriterHost,
        bootstrap: UnixDatagram,
        final_use: FinalUseAuthority,
        expected: &CalculatorTargetIdentity,
        end: Deadline,
    ) -> Result<(Self, AgentdCalculatorStateObserver), AgentdError> {
        let end = end.capped(Duration::from_secs(2))?;
        self.validate_for(config)?;
        if host.destination_count() != 0 {
            return Err(invalid(
                "Calculator requires the unregistered recovered writer",
            ));
        }
        tokio::time::timeout(remaining(end)?, self.validate_recovered_host(host))
            .await
            .map_err(|_| invalid("Calculator owner validation deadline"))??;
        let (offer, effect, recovery) = receive(&bootstrap, expected, end)?;
        let channel = Arc::new(AgentdCalculatorChannel::from_private_channels(
            effect, recovery,
        )?);
        let target = ProductionCalculatorTarget::new(offer.target.clone(), channel)
            .map_err(AgentdError::Invalid)?;
        let observer = AgentdCalculatorStateObserver::new(target.state_observer());
        let configured = match self.with_additional_target(final_use, Arc::new(target)) {
            Ok(configured) => configured,
            Err(error) => {
                let _ = acknowledge(&bootstrap, &offer, Status::Rejected, end);
                return Err(error);
            }
        };
        tokio::time::timeout(remaining(end)?, configured.validate_recovered_host(host))
            .await
            .map_err(|_| invalid("Calculator final owner deadline"))??;
        acknowledge(&bootstrap, &offer, Status::Attached, end)?;
        Ok((configured, observer))
    }
}

fn receive(
    channel: &UnixDatagram,
    expected: &CalculatorTargetIdentity,
    end: Deadline,
) -> Result<(Offer, UnixStream, UnixDatagram), AgentdError> {
    expected.validate().map_err(AgentdError::Invalid)?;
    require_socket(channel.as_raw_fd(), libc::SOCK_DGRAM)?;
    if !channel.local_addr()?.is_unnamed() || !channel.peer_addr()?.is_unnamed() {
        return Err(invalid(
            "Calculator bootstrap requires the original unnamed pair",
        ));
    }
    channel.set_nonblocking(false)?;
    channel.set_read_timeout(Some(remaining(end)?))?;
    let mut bytes = [0_u8; MAX_BYTES + 1];
    let mut control = [0_usize; 32];
    let mut vector = libc::iovec {
        iov_base: bytes.as_mut_ptr().cast(),
        iov_len: bytes.len(),
    };
    // SAFETY: this zeroed message receives only the bounded, live buffers below.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut vector;
    message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast();
    message.msg_controllen = mem::size_of_val(&control);
    // SAFETY: recvmsg retains no buffer reference and applies CLOEXEC atomically.
    let length =
        unsafe { libc::recvmsg(channel.as_raw_fd(), &mut message, libc::MSG_CMSG_CLOEXEC) };
    if length < 0 {
        return Err(io::Error::last_os_error().into());
    }
    // SAFETY: the original helper adopts every right in this completed aligned
    // recvmsg buffer exactly once, including descriptors in rejected frames.
    let (mut descriptors, valid) = unsafe { received_descriptors(&message) };
    remaining(end)?;
    if message.msg_flags & (libc::MSG_TRUNC | libc::MSG_CTRUNC) != 0
        || !valid
        || descriptors.len() != 2
        || length == 0
        || length as usize > MAX_BYTES
    {
        return Err(invalid("Calculator bootstrap frame or descriptor count"));
    }
    let offer: Offer = serde_json::from_slice(&bytes[..length as usize])
        .map_err(|_| invalid("Calculator bootstrap schema"))?;
    offer.target.validate().map_err(AgentdError::Invalid)?;
    if offer.schema_version != 1
        || !matches!(offer.action, OfferAction::OfferCalculatorTarget)
        || offer.target.task_id != 2
        || offer.destination_id != offer.target.destination_id()
        || offer.target != *expected
    {
        return Err(invalid(
            "Calculator offer differs from Root's exact reservation",
        ));
    }
    let recovery = descriptors
        .pop()
        .ok_or_else(|| invalid("Calculator recovery FD absent"))?;
    require_socket(recovery.as_raw_fd(), libc::SOCK_DGRAM)?;
    let effect = descriptors
        .pop()
        .ok_or_else(|| invalid("Calculator effect FD absent"))?;
    require_socket(effect.as_raw_fd(), libc::SOCK_STREAM)?;
    let effect = UnixStream::from(effect);
    let recovery = UnixDatagram::from(recovery);
    if !effect.local_addr()?.is_unnamed()
        || !effect.peer_addr()?.is_unnamed()
        || !recovery.local_addr()?.is_unnamed()
        || !recovery.peer_addr()?.is_unnamed()
    {
        return Err(invalid(
            "Calculator endpoints must be inherited unnamed pairs",
        ));
    }
    remaining(end)?;
    Ok((offer, effect, recovery))
}

fn acknowledge(
    channel: &UnixDatagram,
    offer: &Offer,
    status: Status,
    end: Deadline,
) -> Result<(), AgentdError> {
    let bytes = serde_json::to_vec(&serde_json::json!({
        "schema_version":1,"action":"calculator_target_ack","target":offer.target,
        "destination_id":offer.destination_id,"status":status
    }))?;
    channel.set_write_timeout(Some(remaining(end)?))?;
    if channel.send(&bytes)? != bytes.len() {
        return Err(invalid("partial Calculator bootstrap acknowledgement"));
    }
    remaining(end)?;
    Ok(())
}
fn remaining(end: Deadline) -> io::Result<Duration> {
    end.remaining()
}
fn invalid(message: &str) -> AgentdError {
    AgentdError::Protocol(message.into())
}
