//! Fixed startup phase context without emitting paths, buffers or source errors.
use std::error::Error;
use std::fmt;
use std::io;

#[derive(Debug)]
pub(super) enum Stage {
    InitialLaunchAccept,
    MountState,
    FreshRegistry,
    InitializeAuthority,
    SelectSupervisor,
    RegisterAuthority,
    PreparePhysicalSession,
    AgentFilesystemHandoff,
    RecoveryObserverChannel,
    AuthorityLanes,
    ManagerHandoff,
    ManagerRequestChannel,
    FirstCurrent,
}

struct StartupError {
    stage: Stage,
    source: Box<dyn Error>,
}

pub(super) fn at(stage: Stage, source: impl Into<Box<dyn Error>>) -> Box<dyn Error> {
    Box::new(StartupError {
        stage,
        source: source.into(),
    })
}

impl fmt::Debug for StartupError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let errno = self
            .source
            .downcast_ref::<io::Error>()
            .and_then(io::Error::raw_os_error);
        formatter
            .debug_struct("NativeStartupError")
            .field("stage", &self.stage)
            .field("errno", &errno)
            .finish()
    }
}

impl fmt::Display for StartupError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Debug::fmt(self, formatter)
    }
}

impl Error for StartupError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        Some(self.source.as_ref())
    }
}
