//! Actual in-memory Write implementations, including the real default write_fmt.
use std::cell::RefCell;
use std::fmt;
use std::io;
use std::io::Write;
use std::rc::Rc;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Policy {
    pub style: usize,
    pub mode: usize,
    pub point: usize,
    pub fragment: usize,
}

impl Policy {
    pub fn validate(self) -> Result<Self, String> {
        if self.style > 1
            || self.mode > 5
            || self.fragment == 0
            || (self.style == 0 && self.mode >= 4)
        {
            return Err("invalid fixed writer policy".to_string());
        }
        Ok(self)
    }
}

#[derive(Debug)]
struct WriterSentinel {
    stream: &'static str,
    site: &'static str,
    ordinal: usize,
}

impl fmt::Display for WriterSentinel {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "application writer sentinel: {}:{}:{}",
            self.stream, self.site, self.ordinal
        )
    }
}

impl std::error::Error for WriterSentinel {}

pub type Events = Rc<RefCell<Vec<String>>>;

pub struct Trace<'a> {
    pub policy: Policy,
    pub bytes: Vec<u8>,
    pub writes: usize,
    pub formats: usize,
    pub flushes: usize,
    stream: &'static str,
    events: Events,
    fs_events: &'a dyn Fn() -> usize,
}

impl<'a> Trace<'a> {
    pub fn new(
        stream: &'static str,
        policy: Policy,
        events: Events,
        fs_events: &'a dyn Fn() -> usize,
    ) -> Self {
        Self {
            policy,
            bytes: Vec::new(),
            writes: 0,
            formats: 0,
            flushes: 0,
            stream,
            events,
            fs_events,
        }
    }

    fn event(&self, fields: &str) {
        let mut events = self.events.borrow_mut();
        let index = events.len();
        events.push(format!(
            "ordinal={index};stream={};fs_events={};{fields}",
            self.stream,
            (self.fs_events)()
        ));
    }

    fn failure(&self, site: &'static str, ordinal: usize, kind: io::ErrorKind) -> io::Error {
        io::Error::new(
            kind,
            WriterSentinel {
                stream: self.stream,
                site,
                ordinal,
            },
        )
    }

    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        self.writes += 1;
        let ordinal = self.writes;
        self.event(&format!(
            "kind=write_begin;call={ordinal};input_hex={}",
            crate::hex(bytes)
        ));
        let result = match self.policy.mode {
            1 if ordinal == self.policy.point => {
                Err(self.failure("write", ordinal, io::ErrorKind::BrokenPipe))
            }
            3 if ordinal == self.policy.point => {
                Err(self.failure("write", ordinal, io::ErrorKind::Interrupted))
            }
            _ => {
                let quota = if self.policy.mode == 2 {
                    self.policy.point.saturating_sub(self.bytes.len())
                } else {
                    usize::MAX
                };
                let accepted = bytes.len().min(quota).min(self.policy.fragment);
                self.bytes.extend_from_slice(&bytes[..accepted]);
                Ok(accepted)
            }
        };
        self.event(&format!(
            "kind=write_end;call={ordinal};{}",
            result_description(&result)
        ));
        result
    }

    fn flush(&mut self) -> io::Result<()> {
        self.flushes += 1;
        self.event("kind=flush;result=ok");
        Ok(())
    }
}

fn result_description<T: fmt::Debug>(result: &io::Result<T>) -> String {
    match result {
        Ok(value) => format!(
            "result=ok;value_hex={}",
            crate::hex(format!("{value:?}").as_bytes())
        ),
        Err(error) => format!(
            "result=error;error_kind={:?};display_hex={};debug_hex={}",
            error.kind(),
            crate::hex(error.to_string().as_bytes()),
            crate::hex(format!("{error:?}").as_bytes())
        ),
    }
}

// No write_all or write_fmt override: std owns retrying Interrupted, WriteZero,
// and the original formatting chunk boundaries for this writer.
struct DefaultWriter<'a, 'b>(&'a mut Trace<'b>);

impl Write for DefaultWriter<'_, '_> {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        self.0.write(bytes)
    }
    fn flush(&mut self) -> io::Result<()> {
        self.0.flush()
    }
}

struct FormatWriter<'a, 'b>(&'a mut Trace<'b>);

impl Write for FormatWriter<'_, '_> {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        self.0.write(bytes)
    }
    fn flush(&mut self) -> io::Result<()> {
        self.0.flush()
    }

    fn write_fmt(&mut self, arguments: fmt::Arguments<'_>) -> io::Result<()> {
        self.0.formats += 1;
        let ordinal = self.0.formats;
        self.0.event(&format!(
            "kind=format_begin;call={ordinal};literal_present={};literal_hex={}",
            arguments.as_str().is_some(),
            crate::hex(arguments.as_str().unwrap_or_default().as_bytes())
        ));
        let result = match self.0.policy.mode {
            4 if ordinal == self.0.policy.point => {
                Err(self
                    .0
                    .failure("write_fmt", ordinal, io::ErrorKind::PermissionDenied))
            }
            5 if ordinal == self.0.policy.point => {
                Err(self
                    .0
                    .failure("write_fmt", ordinal, io::ErrorKind::Interrupted))
            }
            _ => DefaultWriter(self.0).write_fmt(arguments),
        };
        self.0.event(&format!(
            "kind=format_end;call={ordinal};{}",
            result_description(&result)
        ));
        result
    }
}

/// Select the actual writer contract without changing the invoked public API.
pub struct Writer<'a, 'b>(pub &'a mut Trace<'b>);

impl Write for Writer<'_, '_> {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        self.0.write(bytes)
    }
    fn flush(&mut self) -> io::Result<()> {
        self.0.flush()
    }
    fn write_fmt(&mut self, arguments: fmt::Arguments<'_>) -> io::Result<()> {
        match self.0.policy.style {
            0 => DefaultWriter(self.0).write_fmt(arguments),
            1 => FormatWriter(self.0).write_fmt(arguments),
            _ => unreachable!("validated writer style"),
        }
    }
}
