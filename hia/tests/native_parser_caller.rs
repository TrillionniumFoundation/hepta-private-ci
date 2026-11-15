//! Same public observations for independently compiled original and actual native owners.
//! No patch grammar or fallback is implemented by this caller.

use codex_utils_path_uri::PathUri;
use serde_json::json;
use serde_json::Value;
use std::collections::BTreeMap;
use std::path::Path;
use std::path::PathBuf;

#[cfg(feature = "hia-native")]
extern crate parser_native as parser_under_test;
#[cfg(not(feature = "hia-native"))]
extern crate parser_reference as parser_under_test;
use parser_under_test::parse_patch;
use parser_under_test::Hunk;
use parser_under_test::ParseError;
use parser_under_test::StreamingPatchParser;
use parser_under_test::UpdateFileChunk;

fn snapshot(parser: &mut StreamingPatchParser, cwd: &PathUri) -> Value {
    let before = format!("{parser:?}");
    let hunks = parser
        .push_delta("")
        .expect("empty push cannot produce a syntax error");
    let after = format!("{parser:?}");
    assert_eq!(
        before, after,
        "observing state with an empty push must not change it"
    );
    json!({"debug": before, "environment_id": parser.environment_id(), "hunks": hunks_value(&hunks, cwd)})
}

fn path_value(path: &Path) -> Value {
    json!({
        "display": path.display().to_string(),
        "encoded_bytes": path.as_os_str().as_encoded_bytes(),
    })
}

fn resolution_value(hunk: &Hunk, cwd: &PathUri) -> Value {
    match hunk.resolve_path(cwd) {
        Ok(uri) => json!({"ok": uri.to_string()}),
        Err(error) => json!({
            "error": {"display": error.to_string(), "debug": format!("{error:?}")},
        }),
    }
}

fn chunk_value(chunk: &UpdateFileChunk) -> Value {
    json!({
        "change_context": chunk.change_context,
        "old_lines": chunk.old_lines,
        "new_lines": chunk.new_lines,
        "context_line_indices": chunk.context_line_indices,
        "is_end_of_file": chunk.is_end_of_file,
    })
}

pub fn hunk_value(hunk: &Hunk, cwd: &PathUri) -> Value {
    let ast = match hunk {
        Hunk::AddFile { path, contents } => json!({
            "kind": "AddFile", "path": path_value(path), "contents": contents,
        }),
        Hunk::DeleteFile { path } => json!({
            "kind": "DeleteFile", "path": path_value(path),
        }),
        Hunk::UpdateFile {
            path,
            move_path,
            chunks,
        } => json!({
            "kind": "UpdateFile", "path": path_value(path),
            "move_path": move_path.as_deref().map(path_value),
            "chunks": chunks.iter().map(chunk_value).collect::<Vec<_>>(),
        }),
    };
    json!({
        "ast": ast,
        "path_method": path_value(hunk.path()),
        "resolve_path_method": resolution_value(hunk, cwd),
    })
}

pub fn hunks_value(hunks: &[Hunk], cwd: &PathUri) -> Value {
    Value::Array(hunks.iter().map(|hunk| hunk_value(hunk, cwd)).collect())
}

pub fn error_value(error: &ParseError) -> Value {
    let (variant, message, line_number) = match error {
        ParseError::InvalidPatchError(message) => ("InvalidPatchError", message, None),
        ParseError::InvalidHunkError {
            message,
            line_number,
        } => ("InvalidHunkError", message, Some(*line_number)),
    };
    json!({
        "variant": variant,
        "message": message,
        "line_number": line_number,
        "display": error.to_string(),
        "debug": format!("{error:?}"),
    })
}

fn result_value(result: &Result<Vec<Hunk>, ParseError>, cwd: &PathUri) -> Value {
    match result {
        Ok(hunks) => json!({"ok": hunks_value(hunks, cwd)}),
        Err(error) => json!({"error": error_value(error)}),
    }
}

fn required_str<'a>(value: &'a Value, key: &str) -> &'a str {
    value[key]
        .as_str()
        .unwrap_or_else(|| panic!("missing string field {key}"))
}

fn input_path(value: &Value) -> PathBuf {
    if let Some(text) = value.as_str() {
        return PathBuf::from(text);
    }
    let bytes = value["unix_bytes"]
        .as_array()
        .expect("path text or unix_bytes");
    let bytes: Vec<u8> = bytes
        .iter()
        .map(|b| u8::try_from(b.as_u64().unwrap()).unwrap())
        .collect();
    #[cfg(unix)]
    {
        use std::os::unix::ffi::OsStringExt;
        PathBuf::from(std::ffi::OsString::from_vec(bytes))
    }
    #[cfg(not(unix))]
    {
        let _ = bytes;
        panic!("unix_bytes path fixture requires Unix")
    }
}

fn path_request(request: &Value, cwd: &PathUri) -> Value {
    let value = &request["hunk"];
    let path = input_path(&value["path"]);
    let hunk = match required_str(value, "kind") {
        "AddFile" => Hunk::AddFile {
            path,
            contents: String::new(),
        },
        "DeleteFile" => Hunk::DeleteFile { path },
        "UpdateFile" => Hunk::UpdateFile {
            path,
            move_path: (!value["move_path"].is_null()).then(|| input_path(&value["move_path"])),
            chunks: Vec::new(),
        },
        other => panic!("unknown fixture hunk kind {other}"),
    };
    hunk_value(&hunk, cwd)
}

fn batch_request(request: &Value, cwd: &PathUri) -> Value {
    match parse_patch(required_str(request, "input")) {
        Ok(args) => json!({"ok": {
            "patch": args.patch,
            "workdir": args.workdir,
            "environment_id": args.environment_id,
            "hunks": hunks_value(&args.hunks, cwd),
        }}),
        Err(error) => json!({"error": error_value(&error)}),
    }
}

fn stream_request(request: &Value, cwd: &PathUri) -> Value {
    let mut parsers = BTreeMap::from([("main".to_string(), StreamingPatchParser::default())]);
    let mut trace = Vec::new();
    for operation in request["operations"].as_array().expect("operations array") {
        let name = operation["parser"].as_str().unwrap_or("main");
        let kind = required_str(operation, "op");
        if kind == "clone" {
            let target = required_str(operation, "to");
            assert!(!parsers.contains_key(target), "clone target already exists");
            let copied = parsers.get(name).expect("existing parser").clone();
            parsers.insert(target.to_string(), copied);
            trace.push(json!({
                "op": "clone", "from": name, "to": target,
                "state": snapshot(parsers.get_mut(target).unwrap(), cwd),
            }));
            continue;
        }
        let parser = parsers.get_mut(name).expect("existing parser");
        let result = match kind {
            "push" => result_value(&parser.push_delta(required_str(operation, "text")), cwd),
            "finish" => result_value(&parser.finish(), cwd),
            "environment" => json!({"environment_id": parser.environment_id()}),
            "snapshot" => Value::Null,
            "mutate_returned" => {
                // Check the ownership of a successful public result, without changing parser state.
                let mut returned = parser.push_delta("").expect("empty push succeeds");
                let before = hunks_value(&returned, cwd);
                if let Some(first) = returned.first_mut() {
                    *first = Hunk::DeleteFile {
                        path: PathBuf::from("mutated-returned-only"),
                    };
                }
                returned.clear();
                json!({"returned_before_mutation": before})
            }
            other => panic!("unknown fixture operation {other}"),
        };
        trace.push(json!({
            "op": kind, "parser": name, "result": result,
            "state": snapshot(parser, cwd),
        }));
    }
    json!({"trace": trace})
}

/// Executes only the original public API and serializes its complete observations.
pub fn execute_request(request: &Value) -> Value {
    let cwd_text = request["cwd"].as_str().unwrap_or("file:///oracle/root");
    let cwd = PathUri::parse(cwd_text).expect("valid fixture cwd PathUri");
    let observation = match required_str(request, "kind") {
        "batch" => batch_request(request, &cwd),
        "stream" => stream_request(request, &cwd),
        "path" => path_request(request, &cwd),
        other => panic!("unknown fixture kind {other}"),
    };
    json!({"case_id": required_str(request, "case_id"), "observation": observation})
}

use std::io::BufRead;
use std::io::Write;

#[cfg(feature = "hia-native")]
static NATIVE_OPERATIONS: [std::sync::atomic::AtomicU64; 19] =
    [const { std::sync::atomic::AtomicU64::new(0) }; 19];

#[cfg(feature = "hia-native")]
unsafe extern "C" {
    fn __real_codex_hia_parser(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_len: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

/// The linker forwards every counted invocation to the real HIA machine entry.
#[cfg(feature = "hia-native")]
#[unsafe(no_mangle)]
unsafe extern "C" fn __wrap_codex_hia_parser(
    source: *const u8,
    source_len: u64,
    output: *mut u8,
    output_len: u64,
    workspace: *mut u8,
    workspace_len: u64,
) -> u64 {
    let operation = if workspace_len >= 16 {
        // Production callers provide a live buffer; decoding does not alter it.
        u64::from_le(unsafe { workspace.add(8).cast::<u64>().read_unaligned() })
    } else {
        u64::MAX
    };
    let index = usize::try_from(operation).unwrap_or(18).min(18);
    NATIVE_OPERATIONS[index].fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    unsafe {
        __real_codex_hia_parser(
            source,
            source_len,
            output,
            output_len,
            workspace,
            workspace_len,
        )
    }
}

#[cfg(feature = "hia-native")]
fn report_native_calls() {
    let counts: Vec<_> = NATIVE_OPERATIONS
        .iter()
        .map(|counter| counter.load(std::sync::atomic::Ordering::Relaxed))
        .collect();
    // Public grammar and both path policies must actually enter the native code.
    for operation in [4, 6, 14, 16, 17] {
        assert!(
            counts[operation] > 0,
            "public operation {operation} never entered HIA"
        );
    }
    assert_eq!(
        counts[18], 0,
        "public caller issued an unknown HIA operation"
    );
    eprintln!(
        "parser_native_operations={}",
        serde_json::to_string(&counts).unwrap()
    );
}

fn main() {
    let stdin = std::io::stdin();
    let stdout = std::io::stdout();
    let mut out = std::io::BufWriter::new(stdout.lock());
    for line in stdin.lock().lines() {
        let line = line.expect("read fixture line");
        let request = serde_json::from_str(&line).expect("valid fixture JSON");
        serde_json::to_writer(&mut out, &execute_request(&request)).expect("write observation");
        writeln!(&mut out).expect("write observation newline");
    }
    out.flush().expect("flush observations");
    #[cfg(feature = "hia-native")]
    report_native_calls();
}
