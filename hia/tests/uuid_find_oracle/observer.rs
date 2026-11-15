use std::error::Error;
use std::fs::File;
use std::io::BufReader;
use std::io::BufWriter;
use std::io::Read;
use std::io::Write;

#[cfg(native_observer)]
mod forwarding_counter {
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;

    static QUERY: AtomicU64 = AtomicU64::new(0);
    static EMIT: AtomicU64 = AtomicU64::new(0);

    unsafe extern "C" {
        fn __real_codex_hia_uuid_find(
            source: *const u8,
            length: u64,
            output: *mut u8,
            capacity: u64,
            workspace: *mut u8,
            workspace_length: u64,
        ) -> u64;
    }

    #[unsafe(no_mangle)]
    pub unsafe extern "C" fn __wrap_codex_hia_uuid_find(
        source: *const u8,
        length: u64,
        output: *mut u8,
        capacity: u64,
        workspace: *mut u8,
        workspace_length: u64,
    ) -> u64 {
        assert_eq!(workspace_length, 32);
        // SAFETY: the actual adapter supplies a live frame for the forwarded call.
        let encoded = unsafe { std::slice::from_raw_parts(workspace.add(8), 8) };
        let mut bytes = [0; 8];
        bytes.copy_from_slice(encoded);
        match u64::from_le_bytes(bytes) {
            0 => QUERY.fetch_add(1, Ordering::Relaxed),
            1 => EMIT.fetch_add(1, Ordering::Relaxed),
            _ => panic!("actual public adapter submitted an unknown operation"),
        };
        // SAFETY: forward all six exact arguments to the real compiled HIA entry.
        unsafe {
            __real_codex_hia_uuid_find(
                source,
                length,
                output,
                capacity,
                workspace,
                workspace_length,
            )
        }
    }

    pub fn counts() -> (u64, u64) {
        (QUERY.load(Ordering::Relaxed), EMIT.load(Ordering::Relaxed))
    }
}

fn word(input: &mut impl Read) -> std::io::Result<u64> {
    let mut encoded = [0; 8];
    input.read_exact(&mut encoded)?;
    Ok(u64::from_le_bytes(encoded))
}

fn put(output: &mut impl Write, value: usize) -> std::io::Result<()> {
    output.write_all(&(value as u64).to_le_bytes())
}

fn main() -> Result<(), Box<dyn Error>> {
    let arguments: Vec<_> = std::env::args_os().collect();
    if arguments.len() != 4 {
        return Err("expected fixture, public-output and spans-output paths".into());
    }
    let mut input = BufReader::new(File::open(&arguments[1])?);
    let mut output = BufWriter::new(File::create(&arguments[2])?);
    #[cfg(not(native_observer))]
    let mut spans_output = BufWriter::new(File::create(&arguments[3])?);
    let mut magic = [0; 8];
    input.read_exact(&mut magic)?;
    assert_eq!(&magic, b"UUIDv1\0\0");
    let cases = usize::try_from(word(&mut input)?)?;
    put(&mut output, cases)?;
    #[cfg(not(native_observer))]
    put(&mut spans_output, cases)?;
    #[cfg(not(native_observer))]
    let regex = regex_lite::Regex::new(
        r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}",
    )?;
    let mut matches = 0;
    let mut nonempty = 0;
    for _ in 0..cases {
        let length = usize::try_from(word(&mut input)?)?;
        let mut bytes = vec![0; length];
        input.read_exact(&mut bytes)?;
        let mut source = String::from_utf8(bytes)?;
        #[cfg(native_observer)]
        let before = forwarding_counter::counts();
        let result = uuid_owner::find_uuids(&source);
        #[cfg(native_observer)]
        {
            let after = forwarding_counter::counts();
            assert_eq!(after.0 - before.0, 1);
            assert_eq!(after.1 - before.1, u64::from(!result.is_empty()));
        }
        #[cfg(not(native_observer))]
        {
            let spans: Vec<_> = regex.find_iter(&source).collect();
            assert_eq!(spans.len(), result.len());
            put(&mut spans_output, spans.len())?;
            for (span, value) in spans.iter().zip(&result) {
                assert_eq!(span.as_str(), value);
                put(&mut spans_output, span.start())?;
                put(&mut spans_output, span.end())?;
            }
        }
        // Observe returned String ownership after overwriting and dropping input.
        source.replace_range(.., &"~".repeat(length));
        drop(source);
        matches += result.len();
        nonempty += usize::from(!result.is_empty());
        put(&mut output, result.len())?;
        for value in result {
            put(&mut output, value.len())?;
            output.write_all(value.as_bytes())?;
        }
    }
    let mut extra = [0];
    assert_eq!(input.read(&mut extra)?, 0);
    output.flush()?;
    #[cfg(not(native_observer))]
    spans_output.flush()?;
    #[cfg(native_observer)]
    let (queries, emits) = forwarding_counter::counts();
    #[cfg(not(native_observer))]
    let (queries, emits) = (0, 0);
    println!(
        "{{\"cases\":{cases},\"matches\":{matches},\"nonempty_cases\":{nonempty},\"ownership_checks\":{cases},\"actual_hia_queries\":{queries},\"actual_hia_emits\":{emits}}}"
    );
    Ok(())
}
