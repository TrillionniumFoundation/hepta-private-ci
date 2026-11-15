//! Observe trait boundaries without substituting any filesystem result.
use codex_exec_server::CopyOptions;
use codex_exec_server::CreateDirectoryOptions;
use codex_exec_server::ExecutorFileSystem;
use codex_exec_server::ExecutorFileSystemFuture;
use codex_exec_server::FileMetadata;
use codex_exec_server::FileSystemReadStream;
use codex_exec_server::FileSystemSandboxContext;
use codex_exec_server::GetMetadataOptions;
use codex_exec_server::LOCAL_FS;
use codex_exec_server::ReadDirectoryEntry;
use codex_exec_server::ReadFileOptions;
use codex_exec_server::RemoveOptions;
use codex_exec_server::WalkOptions;
use codex_exec_server::WalkOutcome;
use codex_exec_server::WriteFileOptions;
use codex_utils_path_uri::PathUri;
use std::fmt::Debug;
use std::io;
use std::sync::Mutex;
use std::sync::MutexGuard;

use crate::hex;

pub struct ObservedFs<'context> {
    inner: &'context dyn ExecutorFileSystem,
    expected_sandbox: Option<&'context FileSystemSandboxContext>,
    events: Mutex<Vec<String>>,
}

impl<'context> ObservedFs<'context> {
    pub fn new(
        inner: &'context dyn ExecutorFileSystem,
        expected_sandbox: Option<&'context FileSystemSandboxContext>,
    ) -> Self {
        Self {
            inner,
            expected_sandbox,
            events: Mutex::new(Vec::new()),
        }
    }

    fn events(&self) -> MutexGuard<'_, Vec<String>> {
        match self.events.lock() {
            Ok(events) => events,
            Err(poisoned) => poisoned.into_inner(),
        }
    }

    pub fn transcript(&self) -> Vec<String> {
        self.events().clone()
    }

    fn begin(
        &self,
        operation: &str,
        path: &PathUri,
        arguments: &str,
        sandbox: Option<&FileSystemSandboxContext>,
    ) -> usize {
        let same_reference = match (self.expected_sandbox, sandbox) {
            (None, None) => true,
            (Some(expected), Some(actual)) => std::ptr::eq(expected, actual),
            _ => false,
        };
        let mut events = self.events();
        // The start-event index is unique even if future callers overlap.
        let id = events.len();
        events.push(format!(
            "call_id={id};phase=begin;operation={operation};path_debug_hex={};native_path_hex={};sandbox_present={};sandbox_same_reference={same_reference};inner_is_local_fs={};{arguments}",
            hex(format!("{path:?}").as_bytes()),
            hex(path.inferred_native_path_string().as_bytes()),
            sandbox.is_some(),
            std::ptr::eq(self.inner, LOCAL_FS.as_ref()),
        ));
        id
    }

    fn finish<T>(&self, id: usize, result: &io::Result<T>, render: fn(&T) -> String) {
        let description = match result {
            Ok(value) => format!("status=ok;{}", render(value)),
            Err(error) => format!(
                "status=error;error_kind={:?};raw_os_error={:?};display_hex={};debug_hex={}",
                error.kind(),
                error.raw_os_error(),
                hex(error.to_string().as_bytes()),
                hex(format!("{error:?}").as_bytes()),
            ),
        };
        self.events()
            .push(format!("call_id={id};phase=end;{description}"));
    }

    fn observe<'a, T, F>(
        &'a self,
        operation: &'static str,
        path: &'a PathUri,
        arguments: String,
        sandbox: Option<&'a FileSystemSandboxContext>,
        call: F,
        render: fn(&T) -> String,
    ) -> ExecutorFileSystemFuture<'a, T>
    where
        T: Send + 'a,
        F: FnOnce() -> ExecutorFileSystemFuture<'a, T> + Send + 'a,
    {
        Box::pin(async move {
            let id = self.begin(operation, path, &arguments, sandbox);
            let result = call().await;
            self.finish(id, &result, render);
            // Return the actual value/error object unchanged.
            result
        })
    }
}

fn options(value: &impl Debug) -> String {
    format!("options_debug_hex={}", hex(format!("{value:?}").as_bytes()))
}

fn render_debug<T: Debug>(value: &T) -> String {
    format!("value_debug_hex={}", hex(format!("{value:?}").as_bytes()))
}

fn render_bytes<T: AsRef<[u8]>>(value: &T) -> String {
    format!("bytes_hex={}", hex(value.as_ref()))
}

fn render_unit(_: &()) -> String {
    "unit=true".to_string()
}

impl ExecutorFileSystem for ObservedFs<'_> {
    fn canonicalize<'a>(
        &'a self,
        path: &'a PathUri,
        sandbox: Option<&'a FileSystemSandboxContext>,
    ) -> ExecutorFileSystemFuture<'a, PathUri> {
        self.observe(
            "canonicalize",
            path,
            String::new(),
            sandbox,
            move || self.inner.canonicalize(path, sandbox),
            render_debug,
        )
    }

    fn read_file<'a>(
        &'a self,
        path: &'a PathUri,
        read_options: ReadFileOptions,
        sandbox: Option<&'a FileSystemSandboxContext>,
    ) -> ExecutorFileSystemFuture<'a, Vec<u8>> {
        self.observe(
            "read_file",
            path,
            options(&read_options),
            sandbox,
            move || self.inner.read_file(path, read_options, sandbox),
            render_bytes,
        )
    }

    fn read_file_stream<'a>(
        &'a self,
        path: &'a PathUri,
        sandbox: Option<&'a FileSystemSandboxContext>,
    ) -> ExecutorFileSystemFuture<'a, FileSystemReadStream> {
        self.observe(
            "read_file_stream",
            path,
            String::new(),
            sandbox,
            move || self.inner.read_file_stream(path, sandbox),
            |_| "stream_opened=true;stream_not_consumed_by_observer=true".to_string(),
        )
    }

    fn read_file_bounded_authorized<'a>(
        &'a self,
        path: &'a PathUri,
        sandbox: &'a FileSystemSandboxContext,
        max_bytes: usize,
    ) -> ExecutorFileSystemFuture<'a, Vec<u8>> {
        self.observe(
            "read_file_bounded_authorized",
            path,
            format!("max_bytes={max_bytes}"),
            Some(sandbox),
            move || {
                self.inner
                    .read_file_bounded_authorized(path, sandbox, max_bytes)
            },
            render_bytes,
        )
    }

    fn read_file_text<'a>(
        &'a self,
        path: &'a PathUri,
        read_options: ReadFileOptions,
        sandbox: Option<&'a FileSystemSandboxContext>,
    ) -> ExecutorFileSystemFuture<'a, String> {
        self.observe(
            "read_file_text",
            path,
            options(&read_options),
            sandbox,
            move || self.inner.read_file_text(path, read_options, sandbox),
            |value| format!("text_hex={}", hex(value.as_bytes())),
        )
    }

    fn write_file<'a>(
        &'a self,
        path: &'a PathUri,
        contents: Vec<u8>,
        write_options: WriteFileOptions,
        sandbox: Option<&'a FileSystemSandboxContext>,
    ) -> ExecutorFileSystemFuture<'a, ()> {
        let arguments = format!(
            "{};contents_hex={}",
            options(&write_options),
            hex(&contents),
        );
        self.observe(
            "write_file",
            path,
            arguments,
            sandbox,
            move || {
                self.inner
                    .write_file(path, contents, write_options, sandbox)
            },
            render_unit,
        )
    }

    fn create_directory<'a>(
        &'a self,
        path: &'a PathUri,
        create_options: CreateDirectoryOptions,
        sandbox: Option<&'a FileSystemSandboxContext>,
    ) -> ExecutorFileSystemFuture<'a, ()> {
        self.observe(
            "create_directory",
            path,
            options(&create_options),
            sandbox,
            move || self.inner.create_directory(path, create_options, sandbox),
            render_unit,
        )
    }

    fn get_metadata<'a>(
        &'a self,
        path: &'a PathUri,
        metadata_options: GetMetadataOptions,
        sandbox: Option<&'a FileSystemSandboxContext>,
    ) -> ExecutorFileSystemFuture<'a, FileMetadata> {
        self.observe(
            "get_metadata",
            path,
            options(&metadata_options),
            sandbox,
            move || self.inner.get_metadata(path, metadata_options, sandbox),
            // Preserve the complete returned object. Only its stable fields
            // are serialized; creation/modification timestamps are not read
            // by this effect owner and differ between fresh fixture roots.
            |value| {
                format!(
                    "is_file={};is_directory={};is_symlink={};size={}",
                    value.is_file, value.is_directory, value.is_symlink, value.size,
                )
            },
        )
    }

    fn read_directory<'a>(
        &'a self,
        path: &'a PathUri,
        sandbox: Option<&'a FileSystemSandboxContext>,
    ) -> ExecutorFileSystemFuture<'a, Vec<ReadDirectoryEntry>> {
        self.observe(
            "read_directory",
            path,
            String::new(),
            sandbox,
            move || self.inner.read_directory(path, sandbox),
            render_debug,
        )
    }

    fn walk<'a>(
        &'a self,
        path: &'a PathUri,
        walk_options: WalkOptions,
        sandbox: Option<&'a FileSystemSandboxContext>,
    ) -> ExecutorFileSystemFuture<'a, WalkOutcome> {
        self.observe(
            "walk",
            path,
            options(&walk_options),
            sandbox,
            move || self.inner.walk(path, walk_options, sandbox),
            render_debug,
        )
    }

    fn remove<'a>(
        &'a self,
        path: &'a PathUri,
        remove_options: RemoveOptions,
        sandbox: Option<&'a FileSystemSandboxContext>,
    ) -> ExecutorFileSystemFuture<'a, ()> {
        self.observe(
            "remove",
            path,
            options(&remove_options),
            sandbox,
            move || self.inner.remove(path, remove_options, sandbox),
            render_unit,
        )
    }

    fn copy<'a>(
        &'a self,
        source_path: &'a PathUri,
        destination_path: &'a PathUri,
        copy_options: CopyOptions,
        sandbox: Option<&'a FileSystemSandboxContext>,
    ) -> ExecutorFileSystemFuture<'a, ()> {
        let arguments = format!(
            "{};destination_debug_hex={};destination_native_path_hex={}",
            options(&copy_options),
            hex(format!("{destination_path:?}").as_bytes()),
            hex(destination_path.inferred_native_path_string().as_bytes()),
        );
        self.observe(
            "copy",
            source_path,
            arguments,
            sandbox,
            move || {
                self.inner
                    .copy(source_path, destination_path, copy_options, sandbox)
            },
            render_unit,
        )
    }
}
