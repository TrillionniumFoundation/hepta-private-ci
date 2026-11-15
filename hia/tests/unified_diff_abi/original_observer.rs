use similar::algorithms::myers;
use similar::algorithms::Capture;
use similar::algorithms::Replace;
use similar::TextDiff;
use std::any::Any;
use std::fmt::Write as _;
use std::io::Read;
use std::io::Write;
use std::panic::catch_unwind;
use std::panic::AssertUnwindSafe;

fn hex(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(bytes.len().saturating_mul(2));
    for byte in bytes {
        let _ = write!(&mut out, "{byte:02x}");
    }
    out
}
fn take<'a>(input: &'a [u8], at: &mut usize, len: usize) -> Result<&'a [u8], &'static str> {
    let end = at.checked_add(len).ok_or("length overflow")?;
    let value = input.get(*at..end).ok_or("short input")?;
    *at = end;
    Ok(value)
}
fn word(input: &[u8], at: &mut usize) -> Result<u64, &'static str> {
    let value: [u8; 8] = take(input, at, 8)?.try_into().map_err(|_| "word width")?;
    Ok(u64::from_le_bytes(value))
}
fn panic_text(payload: &(dyn Any + Send)) -> &str {
    if let Some(text) = payload.downcast_ref::<String>() {
        text
    } else if let Some(text) = payload.downcast_ref::<&'static str>() {
        text
    } else {
        "non-string panic"
    }
}
fn outcome(value: Result<String, Box<dyn Any + Send>>) -> String {
    match value {
        Ok(text) => format!(r#"{{"ok":true,"bytes_hex":"{}"}}"#, hex(text.as_bytes())),
        Err(error) => format!(
            r#"{{"ok":false,"panic_hex":"{}"}}"#,
            hex(panic_text(error.as_ref()).as_bytes())
        ),
    }
}
fn tokens(values: &[&str]) -> String {
    let values: Vec<String> = values
        .iter()
        .map(|value| format!(r#""{}""#, hex(value.as_bytes())))
        .collect();
    format!("[{}]", values.join(","))
}
fn observe(id: u64, old: &str, new: &str, context: usize) -> String {
    let observed = catch_unwind(AssertUnwindSafe(|| {
        let diff = TextDiff::from_lines(old, new);
        let mut raw = Capture::new();
        match myers::diff(
            &mut raw,
            diff.old_slices(),
            0..diff.old_slices().len(),
            diff.new_slices(),
            0..diff.new_slices().len(),
        ) {
            Ok(()) => {}
            Err(never) => match never {},
        }
        let mut replaced = Replace::new(Capture::new());
        match myers::diff(
            &mut replaced,
            diff.old_slices(),
            0..diff.old_slices().len(),
            diff.new_slices(),
            0..diff.new_slices().len(),
        ) {
            Ok(()) => {}
            Err(never) => match never {},
        }
        let replaced = replaced.into_inner();
        let formatted = outcome(catch_unwind(AssertUnwindSafe(|| {
            diff.unified_diff().context_radius(context).to_string()
        })));
        let grouped = outcome(catch_unwind(AssertUnwindSafe(|| {
            format!("{:?}", diff.grouped_ops(context))
        })));
        format!(
            r#"{{"id":{id},"context":{context},"algorithm":"{:?}","newline_terminated":{},"old_tokens":{},"new_tokens":{},"raw_myers_ops_hex":"{}","raw_replace_ops_hex":"{}","text_ops_hex":"{}","grouped":{},"formatted":{}}}"#,
            diff.algorithm(),
            diff.newline_terminated(),
            tokens(diff.old_slices()),
            tokens(diff.new_slices()),
            hex(format!("{:?}", raw.ops()).as_bytes()),
            hex(format!("{:?}", replaced.ops()).as_bytes()),
            hex(format!("{:?}", diff.ops()).as_bytes()),
            grouped,
            formatted
        )
    }));
    match observed {
        Ok(text) => text,
        Err(error) => format!(
            r#"{{"id":{id},"context":{context},"construction_panic_hex":"{}"}}"#,
            hex(panic_text(error.as_ref()).as_bytes())
        ),
    }
}
fn main() -> Result<(), Box<dyn std::error::Error>> {
    std::panic::set_hook(Box::new(|_| {}));
    let mut input = Vec::new();
    std::io::stdin().read_to_end(&mut input)?;
    let mut at = 0;
    let mut output = std::io::BufWriter::new(std::io::stdout().lock());
    while at < input.len() {
        let id = word(&input, &mut at)?;
        let context = usize::try_from(word(&input, &mut at)?)?;
        let old_len = usize::try_from(word(&input, &mut at)?)?;
        let new_len = usize::try_from(word(&input, &mut at)?)?;
        let old = std::str::from_utf8(take(&input, &mut at, old_len)?)?;
        let new = std::str::from_utf8(take(&input, &mut at, new_len)?)?;
        writeln!(output, "{}", observe(id, old, new, context))?;
    }
    Ok(())
}
