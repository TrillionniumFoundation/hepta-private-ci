//! Transport and real filesystem fixtures for the complete public owner.
use codex_apply_patch::UpdateFileChunk;
use codex_exec_server::LOCAL_FS;
use codex_utils_path_uri::PathUri;
use std::io::Read;
use std::io::Write;

#[cfg(hia_count)]
mod calls {
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;

    static COUNT: AtomicU64 = AtomicU64::new(0);
    unsafe extern "C" {
        fn __real_codex_hia_unified_diff(
            source: *const u8,
            source_len: usize,
            output: *mut u8,
            output_len: usize,
            workspace: *mut u8,
            workspace_len: usize,
        ) -> u32;
    }

    #[unsafe(no_mangle)]
    unsafe extern "C" fn __wrap_codex_hia_unified_diff(
        source: *const u8,
        source_len: usize,
        output: *mut u8,
        output_len: usize,
        workspace: *mut u8,
        workspace_len: usize,
    ) -> u32 {
        COUNT.fetch_add(1, Ordering::Relaxed);
        unsafe {
            __real_codex_hia_unified_diff(
                source,
                source_len,
                output,
                output_len,
                workspace,
                workspace_len,
            )
        }
    }

    pub fn count() -> u64 {
        COUNT.load(Ordering::Relaxed)
    }
}

struct Input<'a> {
    remaining: &'a [u8],
}

impl<'a> Input<'a> {
    fn take(&mut self, len: usize) -> &'a [u8] {
        let (head, tail) = self.remaining.split_at(len);
        self.remaining = tail;
        head
    }

    fn number(&mut self) -> usize {
        let bytes: [u8; 8] = self.take(8).try_into().unwrap();
        usize::try_from(u64::from_le_bytes(bytes)).unwrap()
    }

    fn bytes(&mut self) -> &'a [u8] {
        let length = self.number();
        self.take(length)
    }

    fn string(&mut self) -> String {
        String::from_utf8(self.bytes().to_vec()).unwrap()
    }

    fn strings(&mut self) -> Vec<String> {
        let count = self.number();
        (0..count).map(|_| self.string()).collect()
    }
}

fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for &value in bytes {
        output.push(DIGITS[usize::from(value >> 4)] as char);
        output.push(DIGITS[usize::from(value & 15)] as char);
    }
    output
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    std::panic::set_hook(Box::new(|_| {}));
    let mut bytes = Vec::new();
    std::io::stdin().read_to_end(&mut bytes)?;
    let mut input = Input { remaining: &bytes };
    assert_eq!(input.take(8), b"UDOWN001");
    let count = input.number();
    let root = std::path::PathBuf::from(std::env::args_os().nth(1).unwrap());
    assert!(root.is_absolute());
    std::fs::create_dir_all(&root)?;
    let path = root.join("input.txt");
    let uri = PathUri::from_host_native_path(&path)?;
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    let stdout = std::io::stdout();
    let mut stdout = stdout.lock();
    #[cfg(hia_count)]
    let mut counts = std::fs::File::create_new(std::env::args_os().nth(2).unwrap())?;
    for _ in 0..count {
        let id = input.number();
        let route = input.number();
        let context = input.number();
        let file_kind = input.number();
        let old = input.bytes();
        let count = input.number();
        let mut chunks = Vec::with_capacity(count);
        for _ in 0..count {
            let change_context = match input.number() {
                0 => None,
                1 => Some(input.string()),
                _ => panic!("invalid fixture context tag"),
            };
            let old_lines = input.strings();
            let new_lines = input.strings();
            let count = input.number();
            let context_line_indices = (0..count)
                .map(|_| (input.number(), input.number()))
                .collect();
            let is_end_of_file = match input.number() {
                0 => false,
                1 => true,
                _ => panic!("invalid fixture EOF tag"),
            };
            chunks.push(UpdateFileChunk {
                change_context,
                old_lines,
                new_lines,
                context_line_indices,
                is_end_of_file,
            });
        }
        if path.is_dir() {
            std::fs::remove_dir(&path)?;
        } else if path.exists() {
            std::fs::remove_file(&path)?;
        }
        match file_kind {
            0 => std::fs::write(&path, old)?,
            1 => {}
            2 => std::fs::create_dir(&path)?,
            _ => panic!("invalid fixture file kind"),
        }
        #[cfg(hia_count)]
        let calls_before = calls::count();
        let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            runtime.block_on(async {
                match route {
                    0 => {
                        codex_apply_patch::unified_diff_from_chunks(
                            &uri,
                            &chunks,
                            LOCAL_FS.as_ref(),
                            None,
                        )
                        .await
                    }
                    1 => {
                        codex_apply_patch::unified_diff_from_chunks_with_context(
                            &uri,
                            &chunks,
                            context,
                            LOCAL_FS.as_ref(),
                            None,
                        )
                        .await
                    }
                    _ => panic!("invalid fixture public route"),
                }
            })
        }));
        let (kind, debug, display) = match outcome {
            Ok(Ok(value)) => ("ok", format!("{value:?}"), String::new()),
            Ok(Err(error)) => ("error", format!("{error:?}"), error.to_string()),
            Err(error) => {
                let message = if let Some(message) = error.downcast_ref::<String>() {
                    message.clone()
                } else if let Some(message) = error.downcast_ref::<&str>() {
                    (*message).to_string()
                } else {
                    panic!("non-string semantic panic");
                };
                ("panic", message, String::new())
            }
        };
        let after = match std::fs::read(&path) {
            Ok(data) => format!("bytes:{}", hex(&data)),
            Err(error) => format!("error:{:?}", error.kind()),
        };
        writeln!(
            stdout,
            "{id}\t{kind}\t{}\t{}\t{}\t{}\t{after}",
            hex(debug.as_bytes()),
            hex(display.as_bytes()),
            path.exists(),
            path.is_dir(),
        )?;
        stdout.flush()?;
        #[cfg(hia_count)]
        writeln!(counts, "{id}\t{}", calls::count() - calls_before)?;
    }
    assert!(input.remaining.is_empty());
    Ok(())
}
