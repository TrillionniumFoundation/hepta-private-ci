//! Count real kernel open events; do not instrument the registry implementation.
use std::collections::BTreeMap;
use std::ffi::CString;
use std::fs::File;
use std::io::Error;
use std::io::ErrorKind;
use std::io::Read;
use std::os::fd::FromRawFd;
use std::os::unix::ffi::OsStrExt;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::FleetRegistry;

pub(super) struct HistoryOpens {
    file: File,
    agents: BTreeMap<i32, AgentId>,
}

impl HistoryOpens {
    pub(super) fn new(registry: &FleetRegistry, agents: &[AgentId]) -> std::io::Result<Self> {
        // SAFETY: inotify_init1 owns a new descriptor on success.
        let fd = unsafe { libc::inotify_init1(libc::IN_CLOEXEC | libc::IN_NONBLOCK) };
        if fd < 0 {
            return Err(Error::last_os_error());
        }
        // SAFETY: this is the unique owner of the successful descriptor.
        let file = unsafe { File::from_raw_fd(fd) };
        let mut watches = BTreeMap::new();
        for agent in agents {
            let layout = registry.layout().agent(agent);
            let path = CString::new(layout.owner_run_root().as_os_str().as_bytes())?;
            // SAFETY: the descriptor and NUL-terminated path remain live.
            let watch = unsafe { libc::inotify_add_watch(fd, path.as_ptr(), libc::IN_OPEN) };
            if watch < 0 {
                return Err(Error::last_os_error());
            }
            watches.insert(watch, agent.clone());
        }
        Ok(Self {
            file,
            agents: watches,
        })
    }

    pub(super) fn drain(&mut self) -> std::io::Result<BTreeMap<AgentId, usize>> {
        let mut counts = self
            .agents
            .values()
            .cloned()
            .map(|id| (id, 0))
            .collect::<BTreeMap<_, _>>();
        let mut bytes = [0_u8; 16_384];
        loop {
            let len = match self.file.read(&mut bytes) {
                Ok(0) => return Err(Error::new(ErrorKind::UnexpectedEof, "inotify closed")),
                Ok(len) => len,
                Err(error) if error.kind() == ErrorKind::WouldBlock => return Ok(counts),
                Err(error) => return Err(error),
            };
            let mut offset = 0;
            while offset < len {
                let size = std::mem::size_of::<libc::inotify_event>();
                if len - offset < size {
                    return Err(Error::new(
                        ErrorKind::InvalidData,
                        "truncated inotify header",
                    ));
                }
                // SAFETY: the bounds above hold for an unaligned event header.
                let event = unsafe {
                    bytes
                        .as_ptr()
                        .add(offset)
                        .cast::<libc::inotify_event>()
                        .read_unaligned()
                };
                let end = offset + size + event.len as usize;
                if end > len || event.mask & libc::IN_Q_OVERFLOW != 0 {
                    return Err(Error::new(ErrorKind::InvalidData, "inotify events lost"));
                }
                let name = &bytes[offset + size..end];
                if event.mask & libc::IN_OPEN != 0 && name.starts_with(b"lifecycle-") {
                    let agent = self.agents.get(&event.wd).ok_or_else(|| {
                        Error::new(ErrorKind::InvalidData, "unknown inotify watch")
                    })?;
                    *counts.get_mut(agent).expect("registered watch") += 1;
                }
                offset = end;
            }
        }
    }
}
