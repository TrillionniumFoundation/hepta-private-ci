use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Write;
use std::os::fd::AsRawFd;
use std::os::fd::BorrowedFd;
use std::os::fd::RawFd;
use std::sync::Arc;

use tokio::io::Interest;
use tokio::io::unix::AsyncFd;
use tokio::sync::mpsc;
use tokio::task::JoinHandle;

#[cfg(test)]
#[path = "unix_io_diagnostics.rs"]
mod diagnostics;
#[cfg(test)]
pub(crate) use diagnostics::PtyIoDiagnostics;
#[cfg(test)]
use diagnostics::ReaderEvent;
#[cfg(test)]
use diagnostics::WriterEvent;

pub(crate) enum StdinCloseBehavior {
    SendEof,
    NoEof,
}

pub(crate) struct PtyIo {
    fd: Arc<AsyncFd<File>>,
    #[cfg(test)]
    diagnostics: Arc<PtyIoDiagnostics>,
}

impl PtyIo {
    pub(crate) fn new(master_fd: RawFd) -> io::Result<Self> {
        // The PTY owner remains alive while its descriptor is duplicated.
        let fd = unsafe { BorrowedFd::borrow_raw(master_fd) }.try_clone_to_owned()?;
        let flags = unsafe { libc::fcntl(fd.as_raw_fd(), libc::F_GETFL) };
        if flags == -1
            || unsafe { libc::fcntl(fd.as_raw_fd(), libc::F_SETFL, flags | libc::O_NONBLOCK) } == -1
        {
            return Err(io::Error::last_os_error());
        }
        // Duplicates share O_NONBLOCK, so both reads and writes must use readiness.
        // Async tasks can be aborted even when a detached child keeps the PTY open
        // or the output channel is full; blocking read/send tasks cannot.
        // AsyncFd panics if the current runtime has no I/O driver.
        let fd = std::panic::catch_unwind(move || {
            // SAFETY: The File owns the duplicated descriptor. This private
            // AsyncFd only exposes shared access, so its descriptor is never
            // closed or replaced while AsyncFd owns it.
            unsafe { AsyncFd::register(File::from(fd)) }
        })
        .map_err(|_| io::Error::other("PTY I/O requires a Tokio runtime with I/O enabled"))??;
        let fd = Arc::new(fd);
        Ok(Self {
            #[cfg(test)]
            diagnostics: Arc::new(PtyIoDiagnostics::new(Arc::downgrade(&fd))),
            fd,
        })
    }

    #[cfg(test)]
    pub(crate) fn diagnostics(&self) -> Arc<PtyIoDiagnostics> {
        Arc::clone(&self.diagnostics)
    }

    pub(crate) fn spawn(
        self,
        stdout_tx: mpsc::Sender<Vec<u8>>,
        mut writer_rx: mpsc::Receiver<Vec<u8>>,
        stdin_close: StdinCloseBehavior,
    ) -> (JoinHandle<()>, JoinHandle<()>) {
        let fd = self.fd;
        #[cfg(test)]
        let diagnostics = self.diagnostics;
        #[cfg(test)]
        let writer_diagnostics = Arc::clone(&diagnostics);
        let reader = Arc::clone(&fd);
        let reader_handle = tokio::spawn(async move {
            let mut buf = [0u8; 8_192];
            loop {
                #[cfg(test)]
                diagnostics.observe(ReaderEvent::WaitingForRead);
                match reader
                    .async_io(Interest::READABLE, |mut file| {
                        #[cfg(test)]
                        diagnostics.observe(ReaderEvent::ReadStarted);
                        let result = file.read(&mut buf);
                        #[cfg(test)]
                        diagnostics.observe(ReaderEvent::ReadResult(&result));
                        result
                    })
                    .await
                {
                    Ok(0) => {
                        #[cfg(test)]
                        diagnostics.observe(ReaderEvent::Eof);
                        break;
                    }
                    Ok(count) => {
                        // Output caps may close the receiver before the child exits.
                        // Keep draining without allocating a message or polling a send
                        // that can no longer succeed once the channel is closed.
                        if stdout_tx.is_closed() {
                            #[cfg(test)]
                            diagnostics.observe(ReaderEvent::Discarded(count));
                            continue;
                        }
                        #[cfg(test)]
                        {
                            diagnostics.observe(ReaderEvent::Sending);
                            if stdout_tx.send(buf[..count].to_vec()).await.is_err() {
                                diagnostics.observe(ReaderEvent::Discarded(count));
                            }
                        }
                        #[cfg(not(test))]
                        let _ = stdout_tx.send(buf[..count].to_vec()).await;
                    }
                    Err(err) if err.kind() == io::ErrorKind::Interrupted => continue,
                    // Unix PTYs may report EIO rather than EOF when the slave closes.
                    Err(err) => {
                        #[cfg(test)]
                        diagnostics.observe(ReaderEvent::Failed(&err));
                        #[cfg(not(test))]
                        let _ = err;
                        break;
                    }
                }
            }
        });
        let writer_handle = tokio::spawn(async move {
            #[cfg(test)]
            writer_diagnostics.observe_writer(WriterEvent::WaitingForMessage);
            while let Some(bytes) = writer_rx.recv().await {
                #[cfg(test)]
                writer_diagnostics.observe_writer(WriterEvent::MessageReceived(bytes.len()));
                if write_all(
                    &fd,
                    &bytes,
                    #[cfg(test)]
                    &writer_diagnostics,
                )
                .await
                .is_err()
                {
                    return;
                }
                #[cfg(test)]
                {
                    writer_diagnostics.observe_writer(WriterEvent::MessageComplete);
                    writer_diagnostics.observe_writer(WriterEvent::WaitingForMessage);
                }
            }
            #[cfg(test)]
            writer_diagnostics.observe_writer(WriterEvent::QueueClosed);
            match stdin_close {
                StdinCloseBehavior::SendEof => {
                    // Preserve portable-pty's newline + current VEOF on stdin close,
                    // including when the terminal input queue requires waiting.
                    let mut termios = std::mem::MaybeUninit::<libc::termios>::uninit();
                    if unsafe { libc::tcgetattr(fd.get_ref().as_raw_fd(), termios.as_mut_ptr()) }
                        == 0
                    {
                        let termios = unsafe { termios.assume_init() };
                        let eof = termios.c_cc[libc::VEOF];
                        #[cfg(test)]
                        writer_diagnostics.observe_writer(WriterEvent::Termios {
                            canonical: termios.c_lflag & libc::ICANON != 0,
                            eof,
                        });
                        if eof != 0 {
                            #[cfg(test)]
                            writer_diagnostics.observe_writer(WriterEvent::EofStarted);
                            let result = write_all(
                                &fd,
                                &[b'\n', eof],
                                #[cfg(test)]
                                &writer_diagnostics,
                            )
                            .await;
                            #[cfg(test)]
                            writer_diagnostics.observe_writer(WriterEvent::EofResult(&result));
                            let _ = result;
                        } else {
                            #[cfg(test)]
                            writer_diagnostics.observe_writer(WriterEvent::EofDisabled);
                        }
                    } else {
                        #[cfg(test)]
                        writer_diagnostics.observe_writer(WriterEvent::TermiosFailed(
                            &io::Error::last_os_error(),
                        ));
                    }
                }
                StdinCloseBehavior::NoEof => {
                    #[cfg(test)]
                    writer_diagnostics.observe_writer(WriterEvent::NoEofRequested);
                }
            }
            #[cfg(test)]
            writer_diagnostics.observe_writer(WriterEvent::Finished);
        });
        (reader_handle, writer_handle)
    }
}

async fn write_all(
    fd: &AsyncFd<File>,
    mut bytes: &[u8],
    #[cfg(test)] diagnostics: &PtyIoDiagnostics,
) -> io::Result<()> {
    while !bytes.is_empty() {
        #[cfg(test)]
        diagnostics.observe_writer(WriterEvent::WaitingForWrite);
        match fd
            .async_io(Interest::WRITABLE, |mut file| file.write(bytes))
            .await
        {
            Ok(0) => {
                #[cfg(test)]
                diagnostics.observe_writer(WriterEvent::Failed(&io::ErrorKind::WriteZero.into()));
                return Err(io::ErrorKind::WriteZero.into());
            }
            Ok(count) => {
                #[cfg(test)]
                diagnostics.observe_writer(WriterEvent::Written(count));
                bytes = &bytes[count..];
            }
            Err(err) if err.kind() == io::ErrorKind::Interrupted => {
                #[cfg(test)]
                diagnostics.observe_writer(WriterEvent::Interrupted(&err));
                continue;
            }
            Err(err) => {
                #[cfg(test)]
                diagnostics.observe_writer(WriterEvent::Failed(&err));
                return Err(err);
            }
        }
    }
    Ok(())
}
