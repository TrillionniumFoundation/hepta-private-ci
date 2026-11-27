// SPDX-License-Identifier: MPL-2.0

//! Read-only HOS2 bootstrap at /dev/hepta-control. No management authority is
//! granted by open, dup, fork, or this QueryAbi operation. The native resource
//! effects must be wired to a trusted CapSpace/ResourceDomain before enabling
//! any additional opcode. This is deliberately an experimental ioctl number.

use device_id::{DeviceId, MinorId};
use ostd::mm::VmIo;
use spin::Once;

use crate::{
    context::current_userspace,
    device::{Device, DeviceType, registry::char},
    events::IoEvents,
    fs::{
        devtmpfs::DevtmpfsNodeMeta,
        file::{PerOpenFileOps, StatusFlags},
        vfs::{inode::FileOps, path::Path},
    },
    hos2_os_abi::{
        self as wire, Opcode, QueryAbiResponse, RequestPayload, Response, ResponsePayload, Status,
        Transport,
    },
    prelude::*,
    process::{
        Process, ProcessImageKey,
        signal::{PollHandle, Pollable},
    },
    util::{ioctl::RawIoctl, random},
};

// _IOWR('H', 2, sizeof(Transport32)).  This number is test-only until A00
// assigns a public ioctl. It does not silently reuse the old HOS1 command.
const EXPERIMENTAL_HOS2_IOCTL: u32 = 0xC020_4802;
// Fixed experimental HOS2 operations have at most 40 input payload bytes.
// Accept a bounded snapshot for known but disabled opcodes, so that
// unsupported operations produce EOPNOTSUPP rather than an invented ENOTTY.
const MAX_KNOWN_REQUEST_BYTES: usize = wire::HEADER_LEN + 40;
const QUERY_RESPONSE_BYTES: usize = wire::HEADER_LEN + 48;

static MAJOR: Once<char::MajorIdOwner> = Once::new();
static BOOT_ID: Once<[u8; 16]> = Once::new();

fn nonzero_random_id() -> [u8; 16] {
    let mut id = [0u8; 16];
    random::getrandom(&mut id);
    // Even if an early emulator RNG were to return zeroes, never produce an
    // invalid HOS2 identity. No identity here is an authorization token.
    id[0] |= 1;
    id
}

// CapSpace wire identities MUST NEVER alias after PID reuse or execve.
// Assign a checked boot-local full u64 nonce on the authoritative Process
// object and pair it atomically with that image's exec epoch. The full boot
// identity is separately returned in HOSR and included in delivery D.
fn process_session_id(process: &Process) -> Result<([u8; 16], ProcessImageKey)> {
    let key = process.hepta_capspace_session()?;
    let mut id = [0u8; 16];
    id[..8].copy_from_slice(&BOOT_ID.get().unwrap()[..8]);
    id[8..].copy_from_slice(&key.nonce().to_le_bytes());
    Ok((id, key))
}

#[derive(Debug)]
struct HeptaControlDevice {
    id: DeviceId,
}

impl Device for HeptaControlDevice {
    fn type_(&self) -> DeviceType {
        DeviceType::Char
    }

    fn id(&self) -> DeviceId {
        self.id
    }

    fn devtmpfs_meta(&self) -> Option<DevtmpfsNodeMeta> {
        // Default devtmpfs ownership is root:root and mode 0600; actual
        // kernel CapSpace grants must be verified separately for effects.
        Some(DevtmpfsNodeMeta::new("hepta-control").unwrap())
    }

    fn open(&self) -> Result<Box<dyn PerOpenFileOps>> {
        let process = Process::current().ok_or_else(|| {
            Error::with_message(Errno::EPERM, "HOS2 control requires a process session")
        })?;
        let (space_id, image_key) = process_session_id(&process)?;
        Ok(Box::new(HeptaControlFile {
            space_id,
            process: Arc::downgrade(&process),
            image_key,
        }))
    }
}

struct HeptaControlFile {
    space_id: [u8; 16],
    process: Weak<Process>,
    image_key: ProcessImageKey,
}

impl HeptaControlFile {
    /// Verify the current caller is the exact process image that opened this
    /// file. Fork has another Process allocation; irreversible exec or exit
    /// closes the old image before teardown. Neither can reuse an inherited fd.
    fn check_session(&self) -> Result<()> {
        let current = Process::current().ok_or_else(|| {
            Error::with_message(Errno::EPERM, "HOS2 control requires a process session")
        })?;
        let Some(owner) = self.process.upgrade() else {
            return_errno_with_message!(Errno::EPERM, "HOS2 control process lifetime ended")
        };
        if !Arc::ptr_eq(&owner, &current) {
            return_errno_with_message!(Errno::EPERM, "HOS2 control fd belongs to another process")
        }
        current.check_hepta_capspace_session(self.image_key)
    }
}

impl Pollable for HeptaControlFile {
    fn poll(&self, mask: IoEvents, _poller: Option<&mut PollHandle>) -> IoEvents {
        mask & (IoEvents::IN | IoEvents::OUT)
    }
}

impl FileOps for HeptaControlFile {
    fn read_at(
        &self,
        _offset: usize,
        _writer: &mut VmWriter,
        _status_flags: StatusFlags,
    ) -> Result<usize> {
        return_errno_with_message!(Errno::EINVAL, "HOS2 requires the ioctl transport")
    }

    fn write_at(
        &self,
        _offset: usize,
        _reader: &mut VmReader,
        _status_flags: StatusFlags,
    ) -> Result<usize> {
        return_errno_with_message!(Errno::EINVAL, "HOS2 does not accept stream writes")
    }
}

impl PerOpenFileOps for HeptaControlFile {
    fn check_seekable(&self) -> Result<()> {
        return_errno_with_message!(Errno::ESPIPE, "HOS2 sessions are not seekable")
    }

    fn is_offset_aware(&self) -> bool {
        false
    }

    fn ioctl(&self, _path: &Path, raw_ioctl: RawIoctl) -> Result<i32> {
        if raw_ioctl.cmd() != EXPERIMENTAL_HOS2_IOCTL {
            return_errno_with_message!(Errno::ENOTTY, "not a recognized HOS2 ioctl")
        }
        self.check_session()?;

        // Copy the transport once. Every address and length is validated
        // before copying the nested request; no effect can occur on failure.
        let mut transport_bytes = [0u8; wire::TRANSPORT_LEN];
        current_userspace!().read_bytes(raw_ioctl.arg(), &mut transport_bytes)?;
        let transport = Transport::decode(&transport_bytes)
            .map_err(|_| Error::with_message(Errno::EINVAL, "malformed HOS2 transport"))?;
        let request_len = usize::try_from(transport.request_bytes)
            .map_err(|_| Error::with_message(Errno::EINVAL, "invalid request length"))?;
        if request_len > MAX_KNOWN_REQUEST_BYTES {
            return_errno_with_message!(Errno::EINVAL, "HOS2 request exceeds known N0 operations")
        }
        let request_ptr = usize::try_from(transport.request_addr)
            .map_err(|_| Error::with_message(Errno::EINVAL, "invalid request address"))?;
        let response_ptr = usize::try_from(transport.response_addr)
            .map_err(|_| Error::with_message(Errno::EINVAL, "invalid response address"))?;
        // Copy the complete bounded request BEFORE interpreting bytes. The
        // driver has no effectful opcodes, including when copyout later fails.
        let mut input = [0u8; MAX_KNOWN_REQUEST_BYTES];
        current_userspace!().read_bytes(request_ptr, &mut input[..request_len])?;
        let request = transport
            .decode_request_snapshot(&input[..request_len])
            .map_err(|err| {
                // The experimental HOS2 native ABI explicitly distinguishes
                // protocol, operation and capacity errors. Do not report a
                // known opcode as an unknown ioctl or collapse a short output
                // into malformed input.
                let code = match err {
                    wire::Error::InvalidMagic | wire::Error::UnknownVersion => {
                        Errno::EPROTONOSUPPORT
                    }
                    wire::Error::UnknownOpcode => Errno::EOPNOTSUPP,
                    wire::Error::InsufficientCapacity => Errno::EMSGSIZE,
                    _ => Errno::EINVAL,
                };
                Error::with_message(code, "invalid HOS2 request/capacity")
            })?;
        if request.opcode != Opcode::QueryAbi || request.payload != RequestPayload::QueryAbi {
            return_errno_with_message!(
                Errno::EOPNOTSUPP,
                "recognized HOS2 resource operation not implemented"
            )
        }

        // The advertised mask has *only* QueryAbi (bit 1). This creates no
        // grant, does not install a CPU budget and cannot retire delivery.
        let response = Response {
            opcode: Opcode::QueryAbi,
            status: Status::Ok,
            request_id: request.request_id,
            boot_id: *BOOT_ID.get().unwrap(),
            revision: 0,
            payload: ResponsePayload::QueryAbi(QueryAbiResponse {
                space_id: self.space_id,
                page_size: u32::try_from(PAGE_SIZE).unwrap(),
                max_request_payload: 0,
                max_response_payload: 48,
                supported_ops: 1u64 << Opcode::QueryAbi.as_u16(),
                features: 0,
            }),
        };
        let mut output = [0u8; QUERY_RESPONSE_BYTES];
        let bytes = wire::encode_response(&response, &mut output)
            .map_err(|_| Error::with_message(Errno::EINVAL, "invalid HOS2 response"))?;
        current_userspace!().write_bytes(response_ptr, &output[..bytes])?;
        Ok(0)
    }
}

pub(super) fn init_in_first_kthread() {
    BOOT_ID.call_once(nonzero_random_id);
    let major = MAJOR.call_once(|| char::allocate_major().unwrap()).get();
    char::register(Arc::new(HeptaControlDevice {
        id: DeviceId::new(major, MinorId::new(0)),
    }))
    .expect("register read-only HOS2 bootstrap");
}
