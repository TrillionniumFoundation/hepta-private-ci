//! Observe the real public print_summary API using in-memory Write contracts.

use std::ffi::OsString;
use std::fmt;
use std::io::Write;
use std::io::{self};
use std::os::unix::ffi::OsStrExt;
use std::os::unix::ffi::OsStringExt;
use std::path::PathBuf;

use codex_apply_patch::print_summary;
use codex_apply_patch::AffectedPaths;

#[cfg(native_summary)]
use std::sync::atomic::AtomicU64;
#[cfg(native_summary)]
use std::sync::atomic::Ordering;

#[cfg(native_summary)]
static CALLS: AtomicU64 = AtomicU64::new(0);

#[cfg(native_summary)]
unsafe extern "C" {
    fn __real_codex_hia_patch_summary(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_len: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

#[cfg(native_summary)]
#[unsafe(no_mangle)]
unsafe extern "C" fn __wrap_codex_hia_patch_summary(
    source: *const u8,
    source_len: u64,
    output: *mut u8,
    output_len: u64,
    workspace: *mut u8,
    workspace_len: u64,
) -> u64 {
    CALLS.fetch_add(1, Ordering::Relaxed);
    unsafe {
        __real_codex_hia_patch_summary(
            source,
            source_len,
            output,
            output_len,
            workspace,
            workspace_len,
        )
    }
}

fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut value = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        value.push(DIGITS[(byte >> 4) as usize] as char);
        value.push(DIGITS[(byte & 15) as usize] as char);
    }
    value
}

fn native_path(bytes: &[u8]) -> PathBuf {
    PathBuf::from(OsString::from_vec(bytes.to_vec()))
}

fn affected(case: usize) -> AffectedPaths {
    let mut groups: [Vec<PathBuf>; 3] = std::array::from_fn(|_| Vec::new());
    match case {
        0..=26 => {
            let mut value = case;
            for (group, paths) in groups.iter_mut().enumerate() {
                let count = value % 3;
                value /= 3;
                for index in 0..count {
                    paths.push(PathBuf::from(format!("group-{group}/item-{index}")));
                }
            }
        }
        27 => {
            for (group, paths) in groups.iter_mut().enumerate() {
                for path in ["甲/乙", "😀", "e\u{301}", "文件 name", "a\\b"] {
                    paths.push(PathBuf::from(format!("{group}/{path}")));
                }
            }
        }
        28 => {
            for paths in &mut groups {
                for path in ["same", "same", "", "same", "same"] {
                    paths.push(PathBuf::from(path));
                }
            }
        }
        29 => {
            let paths: &[&[u8]] = &[
                b"\xff",
                b"a\x80b",
                b"\xc0\xaf",
                b"\xe2\x82",
                b"\xed\xa0\x80",
                b"\xf4\x90\x80\x80",
                b"\xef\xbf\xbd",
                b"before\xffafter\xfe",
            ];
            for group in &mut groups {
                group.extend(paths.iter().map(|path| native_path(path)));
            }
        }
        30 => {
            let paths: &[&[u8]] = &[
                b"",
                b".",
                b"..",
                b"/",
                b"//srv//a/../b/",
                b"line\nfile",
                b"tab\tfile",
                b"nul\0byte",
                b"\r\n",
                b"A misleading-prefix",
            ];
            for group in &mut groups {
                group.extend(paths.iter().map(|path| native_path(path)));
            }
        }
        31 => {
            groups[0].push(PathBuf::from("x".repeat(2 * 1024 * 1024)));
            groups[1].push(PathBuf::from("after-long-path"));
        }
        32 => {
            groups[2].push(PathBuf::from("甲".repeat(2 * 1024 * 1024 / 3)));
        }
        _ => panic!("unknown fixed case"),
    }
    let [added, modified, deleted] = groups;
    AffectedPaths {
        added,
        modified,
        deleted,
    }
}

struct WriteCall {
    input: Vec<u8>,
    result: String,
}

struct Trace {
    policy: usize,
    point: usize,
    fragment: usize,
    bytes: Vec<u8>,
    writes: Vec<WriteCall>,
    formats: Vec<Option<String>>,
    flushes: usize,
}

impl Trace {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        let ordinal = self.writes.len() + 1;
        let result = if self.policy == 1 && ordinal == self.point {
            Err(io::Error::new(
                io::ErrorKind::BrokenPipe,
                "summary write sentinel",
            ))
        } else if self.policy == 3 && ordinal == self.point {
            Err(io::Error::new(
                io::ErrorKind::Interrupted,
                "summary write interrupted",
            ))
        } else {
            let remaining = if self.policy == 2 {
                self.point.saturating_sub(self.bytes.len())
            } else {
                usize::MAX
            };
            let accepted = bytes.len().min(self.fragment).min(remaining);
            self.bytes.extend_from_slice(&bytes[..accepted]);
            Ok(accepted)
        };
        let description = match &result {
            Ok(count) => format!("ok:{count}"),
            Err(error) => format!("error:{:?}:{}", error.kind(), error),
        };
        self.writes.push(WriteCall {
            input: bytes.to_vec(),
            result: description,
        });
        result
    }
}

// This type deliberately retains std::io::Write's default write_fmt/write_all.
struct DefaultWriter<'a>(&'a mut Trace);

impl Write for DefaultWriter<'_> {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        self.0.write(bytes)
    }

    fn flush(&mut self) -> io::Result<()> {
        self.0.flushes += 1;
        Ok(())
    }
}

// Observe custom write_fmt calls before delegating formatting to the real std
// implementation through DefaultWriter. No path formatting is substituted.
struct FormatWriter<'a>(&'a mut Trace);

impl Write for FormatWriter<'_> {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        self.0.write(bytes)
    }

    fn flush(&mut self) -> io::Result<()> {
        self.0.flushes += 1;
        Ok(())
    }

    fn write_fmt(&mut self, arguments: fmt::Arguments<'_>) -> io::Result<()> {
        self.0.formats.push(arguments.as_str().map(str::to_owned));
        if self.0.formats.len() == self.0.point {
            if self.0.policy == 4 {
                return Err(io::Error::other("summary format sentinel"));
            }
            if self.0.policy == 5 {
                return Err(io::Error::new(
                    io::ErrorKind::Interrupted,
                    "summary format interrupted",
                ));
            }
        }
        DefaultWriter(self.0).write_fmt(arguments)
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = std::env::args()
        .skip(1)
        .map(|argument| argument.parse::<usize>())
        .collect::<Result<Vec<_>, _>>()?;
    assert_eq!(args.len(), 5);
    let [case, style, policy, point, fragment] = args.as_slice() else {
        unreachable!()
    };
    assert!(*case <= 32 && *style <= 1 && *policy <= 5 && *fragment > 0);
    assert!(*style == 1 || *policy < 4);
    let paths = affected(*case);
    let mut trace = Trace {
        policy: *policy,
        point: *point,
        fragment: *fragment,
        bytes: Vec::new(),
        writes: Vec::new(),
        formats: Vec::new(),
        flushes: 0,
    };
    let result = if *style == 0 {
        print_summary(&paths, &mut DefaultWriter(&mut trace))
    } else {
        print_summary(&paths, &mut FormatWriter(&mut trace))
    };
    println!("protocol=HPSO0001");
    println!("case={case}");
    println!("style={style}");
    println!("policy={policy}");
    println!("point={point}");
    println!("fragment={fragment}");
    for (name, values) in [
        ("added", &paths.added),
        ("modified", &paths.modified),
        ("deleted", &paths.deleted),
    ] {
        println!("input_{name}_count={}", values.len());
        for (index, path) in values.iter().enumerate() {
            println!(
                "input_{name}_{index}_hex={}",
                hex(path.as_os_str().as_bytes())
            );
        }
    }
    match result {
        Ok(()) => println!("result=ok"),
        Err(error) => {
            println!("result=error");
            println!("error_kind={:?}", error.kind());
            println!("error_display_hex={}", hex(error.to_string().as_bytes()));
            println!("error_debug_hex={}", hex(format!("{error:?}").as_bytes()));
        }
    }
    println!("output_hex={}", hex(&trace.bytes));
    println!("write_calls={}", trace.writes.len());
    for (index, call) in trace.writes.iter().enumerate() {
        println!("write_{index}_input_hex={}", hex(&call.input));
        println!("write_{index}_result_hex={}", hex(call.result.as_bytes()));
    }
    println!("format_calls={}", trace.formats.len());
    for (index, value) in trace.formats.iter().enumerate() {
        println!("format_{index}_static={}", value.is_some());
        if let Some(value) = value {
            println!("format_{index}_literal_hex={}", hex(value.as_bytes()));
        }
    }
    println!("flush_calls={}", trace.flushes);
    println!("observation_complete=true");
    #[cfg(native_summary)]
    println!("native_calls={}", CALLS.load(Ordering::Relaxed));
    #[cfg(not(native_summary))]
    println!("native_calls=0");
    Ok(())
}
