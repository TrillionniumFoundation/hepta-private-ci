//! Actual file operations in the launcher's disposable boundary fixture.
//! This supplements the unchanged PowerShell owner test; it needs no CLR/CNG.
use core::ffi::c_void;

use super::number;
use super::windows_probe_memory::BoundedMemory;
use super::write;
use super::ExitProcess;
use super::GetLastError;

#[link(name = "kernel32")]
unsafe extern "system" {
    fn GetEnvironmentVariableW(name: *const u16, buffer: *mut u16, capacity: u32) -> u32;
    fn CreateFileW(
        path: *const u16,
        access: u32,
        share: u32,
        security: *const c_void,
        disposition: u32,
        flags: u32,
        template: isize,
    ) -> isize;
    fn ReadFile(
        file: isize,
        data: *mut u8,
        len: u32,
        read: *mut u32,
        overlapped: *mut c_void,
    ) -> i32;
    fn WriteFile(
        file: isize,
        data: *const u8,
        len: u32,
        written: *mut u32,
        overlapped: *mut c_void,
    ) -> i32;
    fn CloseHandle(handle: isize) -> i32;
    fn DeleteFileW(path: *const u16) -> i32;
    fn RemoveDirectoryW(path: *const u16) -> i32;
}

const CAPACITY: usize = 2048;
const WRITE_MASKS: [u32; 13] = [
    0x2, 0x4, 0x10, 0x100, 0x40, 0x10000, 0x40000, 0x80000, 0x3, 0x100100, 0x130089, 0x50000,
    0x1A0089,
];

pub(super) fn requested() -> bool {
    let name = wide_name(b"BOUNDARY_DIAGNOSTIC");
    let mut value = [0_u16; 2];
    unsafe { GetEnvironmentVariableW(name.as_ptr(), value.as_mut_ptr(), 2) == 1 && value[0] == 49 }
}

fn wide_name(name: &[u8]) -> [u16; 64] {
    assert!(name.len() < 64);
    let mut result = [0_u16; 64];
    for (to, from) in result.iter_mut().zip(name) {
        *to = *from as u16;
    }
    result
}

struct NativePath(BoundedMemory);

impl NativePath {
    fn read(name: &[u8], suffix: &[u8]) -> Result<Self, u32> {
        let name = wide_name(name);
        let memory = BoundedMemory::new(CAPACITY * 2).ok_or(8_u32)?;
        let pointer = memory.as_ptr().cast::<u16>();
        let len =
            unsafe { GetEnvironmentVariableW(name.as_ptr(), pointer, CAPACITY as u32) } as usize;
        if len == 0 {
            return Err(unsafe { GetLastError() });
        }
        if len >= CAPACITY || len + suffix.len() + 1 >= CAPACITY {
            return Err(206); // ERROR_FILENAME_EXCED_RANGE; never truncate a path.
        }
        if !suffix.is_empty() {
            unsafe { pointer.add(len).write(92) };
            for (index, value) in suffix.iter().enumerate() {
                unsafe { pointer.add(len + 1 + index).write(*value as u16) };
            }
            unsafe { pointer.add(len + 1 + suffix.len()).write(0) };
        }
        Ok(Self(memory))
    }

    fn as_ptr(&self) -> *const u16 {
        self.0.as_ptr().cast()
    }
}

struct FileHandle(isize);

impl FileHandle {
    fn open(path: &NativePath, access: u32, disposition: u32, flags: u32) -> Result<Self, u32> {
        let handle = unsafe {
            CreateFileW(
                path.as_ptr(),
                access,
                /*share*/ 7,
                core::ptr::null(),
                disposition,
                flags,
                0,
            )
        };
        if handle == -1 {
            Err(unsafe { GetLastError() })
        } else {
            Ok(Self(handle))
        }
    }
}

impl Drop for FileHandle {
    fn drop(&mut self) {
        if unsafe { CloseHandle(self.0) } == 0 {
            number(b"file_probe_close_error", unsafe { GetLastError() });
            unsafe { ExitProcess(93) }
        }
    }
}

fn write_bytes(file: &FileHandle, bytes: &[u8]) -> u32 {
    let mut written = 0;
    if unsafe {
        WriteFile(
            file.0,
            bytes.as_ptr(),
            bytes.len() as u32,
            &mut written,
            core::ptr::null_mut(),
        )
    } == 0
    {
        return unsafe { GetLastError() };
    }
    if written as usize != bytes.len() {
        29
    } else {
        0
    }
}

fn overwrite(path: &NativePath, bytes: &[u8]) -> u32 {
    match FileHandle::open(
        path, /*GENERIC_WRITE*/ 0x40000000, /*CREATE_ALWAYS*/ 2, 0,
    ) {
        Ok(file) => write_bytes(&file, bytes),
        Err(error) => error,
    }
}

fn delete_file(path: &NativePath) -> u32 {
    if unsafe { DeleteFileW(path.as_ptr()) } == 0 {
        unsafe { GetLastError() }
    } else {
        0
    }
}

fn delete_directory(path: &NativePath) -> u32 {
    if unsafe { RemoveDirectoryW(path.as_ptr()) } == 0 {
        unsafe { GetLastError() }
    } else {
        0
    }
}

fn observe() -> Result<(), u32> {
    write(b"file_probe_entry=1\n");
    for (index, root) in [b"BOUNDARY_WORKSPACE".as_slice(), b"BOUNDARY_TEMP"]
        .iter()
        .enumerate()
    {
        number(b"allowed_index", index as u32);
        number(
            b"allowed_create_error",
            overwrite(&NativePath::read(root, b"created.txt")?, b"allowed"),
        );
        number(
            b"allowed_delete_file_error",
            delete_file(&NativePath::read(root, b"delete.txt")?),
        );
        number(
            b"allowed_delete_directory_error",
            delete_directory(&NativePath::read(root, b"delete-dir")?),
        );
    }
    let outside_file = NativePath::read(b"BOUNDARY_OUTSIDE", b"keep.txt")?;
    match FileHandle::open(
        &outside_file,
        /*GENERIC_READ*/ 0x80000000,
        /*OPEN_EXISTING*/ 3,
        0,
    ) {
        Ok(file) => {
            let mut bytes = [0_u8; 8];
            let mut read = 0;
            let ok = unsafe {
                ReadFile(
                    file.0,
                    bytes.as_mut_ptr(),
                    bytes.len() as u32,
                    &mut read,
                    core::ptr::null_mut(),
                )
            };
            number(
                b"outside_read_error",
                if ok == 0 {
                    unsafe { GetLastError() }
                } else {
                    0
                },
            );
            number(
                b"outside_read_exact",
                (ok != 0 && read == 7 && &bytes[..7] == b"outside") as u32,
            );
        }
        Err(error) => {
            number(b"outside_read_error", error);
            number(b"outside_read_exact", 0);
        }
    }
    let paths: [(&[u8], &[u8]); 5] = [
        (b"BOUNDARY_OUTSIDE", b"keep.txt"),
        (b"BOUNDARY_OUTSIDE", b""),
        (b"BOUNDARY_ALIAS", b"keep.txt"),
        (b"BOUNDARY_ALIAS", b""),
        (b"BOUNDARY_HARDLINK", b""),
    ];
    for (path_index, (root, suffix)) in paths.into_iter().enumerate() {
        let path = NativePath::read(root, suffix)?;
        for (mask_index, mask) in WRITE_MASKS.into_iter().enumerate() {
            number(
                b"file_open_index",
                (path_index * WRITE_MASKS.len() + mask_index) as u32,
            );
            number(b"file_open_mask", mask);
            let error = match FileHandle::open(
                &path, mask, /*OPEN_EXISTING*/ 3, /*BACKUP_SEMANTICS*/ 0x02000000,
            ) {
                Ok(_handle) => 0,
                Err(error) => error,
            };
            number(b"file_open_error", error);
        }
    }
    let maximum_error =
        match FileHandle::open(&outside_file, /*MAXIMUM_ALLOWED*/ 0x02000000, 3, 0) {
            Ok(file) => write_bytes(&file, b"x"),
            Err(error) => error,
        };
    number(b"maximum_write_error", maximum_error);
    number(
        b"outside_overwrite_error",
        overwrite(&outside_file, b"overwritten"),
    );
    number(
        b"outside_create_error",
        overwrite(
            &NativePath::read(b"BOUNDARY_OUTSIDE", b"created.txt")?,
            b"outside",
        ),
    );
    number(b"outside_delete_file_error", delete_file(&outside_file));
    number(
        b"outside_delete_directory_error",
        delete_directory(&NativePath::read(b"BOUNDARY_OUTSIDE", b"keep-dir")?),
    );
    write(b"file_probe_complete=1\n");
    Ok(())
}

pub(super) fn run() -> ! {
    // All path allocations and file handles are dropped before the final exit.
    let code = match observe() {
        Ok(()) => 0,
        Err(error) => {
            number(b"file_probe_incomplete_error", error);
            94
        }
    };
    unsafe { ExitProcess(code) }
}
