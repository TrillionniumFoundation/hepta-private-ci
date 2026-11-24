//! Real Windows qualification of the compiled bundled VFS, independent of SQLx.
//! A separate consumer qualification exercises SQLx's dedicated worker path.

#[path = "hepta_owner_test_support.rs"]
mod support;
#[path = "hepta_owner_thread_tests.rs"]
mod thread_token;

use crate::*;
use std::ffi::CString;
use std::os::windows::io::AsRawHandle;
use std::path::Path;
use support::*;
use windows_sys::Win32::Storage::FileSystem::GetFinalPathNameByHandleW;
use windows_sys::Win32::Storage::FileSystem::VOLUME_NAME_DOS;

const CREATE_RW: i32 = SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE;

#[test]
fn owner_registration_reuses_policy_without_changing_default_vfs() {
    let original = Vfs::Stock.pointer() as usize;
    let name = hepta_win32_owner_vfs_name().expect("compiled bundled Windows owner VFS");
    let private = Vfs::Private(name).pointer() as usize;
    assert_ne!(original, private);
    let threads: Vec<_> = (0..16)
        .map(|_| {
            std::thread::spawn(|| {
                let name = hepta_win32_owner_vfs_name().unwrap();
                (
                    name.to_bytes().to_vec(),
                    Vfs::Private(name).pointer() as usize,
                )
            })
        })
        .collect();
    for thread in threads {
        assert_eq!(thread.join().unwrap(), (name.to_bytes().to_vec(), private));
    }
    assert_eq!(Vfs::Stock.pointer() as usize, original);
}

#[test]
fn worker_creates_private_db_wal_and_shm_then_reopens() {
    let root = Root::new();
    let path = root.0.join("worker.sqlite3");
    let name = hepta_win32_owner_vfs_name().unwrap();
    let worker_path = path.clone();
    std::thread::spawn(move || {
        let db = Database::open(&worker_path, Vfs::Private(name), CREATE_RW).unwrap();
        db.execute(c"PRAGMA journal_mode=WAL; CREATE TABLE observed(value); INSERT INTO observed VALUES(7);");
        assert_private(db.handle());
        for suffix in ["-wal", "-shm"] {
            let file = std::fs::File::open(format!("{}{suffix}", worker_path.display())).unwrap();
            assert_private(file.as_raw_handle() as _);
        }
        let reader = Database::open(&worker_path, Vfs::Private(name), SQLITE_OPEN_READONLY).unwrap();
        reader.execute(c"SELECT value FROM observed;");
        assert_private(reader.handle());
    }).join().expect("native SQLite worker completes");
    let reopened = Database::open(&path, Vfs::Private(name), SQLITE_OPEN_READWRITE).unwrap();
    reopened.execute(c"INSERT INTO observed VALUES(8); SELECT count(*) FROM observed;");
    assert_private(reopened.handle());
}

#[test]
fn readonly_wal_reader_recreates_private_shm_without_writing_db() {
    let root = Root::new();
    let path = root.0.join("readonly.sqlite3");
    let name = hepta_win32_owner_vfs_name().unwrap();
    {
        let db = Database::open(&path, Vfs::Private(name), CREATE_RW).unwrap();
        let mut persist = 1;
        // SAFETY: PERSIST_WAL takes a live pointer to an int; connection is owned here.
        assert_eq!(
            unsafe {
                sqlite3_file_control(
                    db.0,
                    c"main".as_ptr(),
                    SQLITE_FCNTL_PERSIST_WAL,
                    (&mut persist as *mut i32).cast(),
                )
            },
            SQLITE_OK
        );
        db.execute(c"PRAGMA journal_mode=WAL; CREATE TABLE observed(value); INSERT INTO observed VALUES(1);");
    }
    let shm = root.0.join("readonly.sqlite3-shm");
    assert!(shm.is_file(), "persisted SHM control exists");
    std::fs::remove_file(&shm).unwrap();
    let before = std::fs::read(&path).unwrap();
    let db = Database::open(&path, Vfs::Private(name), SQLITE_OPEN_READONLY).unwrap();
    db.execute(c"SELECT value FROM observed;");
    assert_ne!(db.exec(c"INSERT INTO observed VALUES(2);"), SQLITE_OK);
    assert_private(db.handle());
    let file = std::fs::File::open(&shm).expect("actual readonly SHM recreation");
    assert_private(file.as_raw_handle() as _);
    assert_eq!(std::fs::read(&path).unwrap(), before);
}

#[test]
fn temporary_open_creates_private_noninheritable_handle_and_deletes_on_close() {
    let name = hepta_win32_owner_vfs_name().unwrap();
    let file = NativeFile::open(
        Vfs::Private(name),
        NativeName::Temporary,
        CREATE_RW | SQLITE_OPEN_EXCLUSIVE | SQLITE_OPEN_DELETEONCLOSE | SQLITE_OPEN_TEMP_DB,
    )
    .unwrap();
    let handle = file.handle();
    assert_private(handle);
    let mut text = vec![0u16; 32768];
    // SAFETY: The borrowed native handle stays open; output is a bounded UTF-16 buffer.
    let length = unsafe {
        GetFinalPathNameByHandleW(
            handle,
            text.as_mut_ptr(),
            text.len() as u32,
            VOLUME_NAME_DOS,
        )
    };
    assert!(length > 0 && (length as usize) < text.len());
    let path = std::path::PathBuf::from(String::from_utf16(&text[..length as usize]).unwrap());
    drop(file);
    assert!(
        !path.exists(),
        "private temporary file deleted by its own handle"
    );
}

fn assert_rejected_unchanged(path: &Path, private: Vfs<'_>) {
    let bytes = std::fs::read(path).unwrap();
    let security = path_security(path);
    // xOpen's MAIN_DB filename contract has two trailing NUL bytes.
    let mut filename = CString::new(path.to_str().unwrap())
        .unwrap()
        .into_bytes_with_nul();
    filename.push(0);
    let opened = NativeFile::open(
        private,
        NativeName::Named(path),
        SQLITE_OPEN_READWRITE | SQLITE_OPEN_MAIN_DB,
    );
    assert!(
        opened.is_err(),
        "actual private xOpen rejects fixture before database parsing"
    );
    let vfs = private.pointer();
    // SAFETY: Calls the actual registered private VFS xDelete with a live filename.
    let deleted = unsafe { (*vfs).xDelete.unwrap()(vfs, filename.as_ptr().cast(), 0) };
    assert_ne!(
        deleted, SQLITE_OK,
        "actual private xDelete rejects without deletion"
    );
    assert_eq!(std::fs::read(path).unwrap(), bytes);
    assert!(
        path_security(path) == security,
        "owner and complete DACL are unchanged"
    );
    // A successful stock xOpen controls for accidental sharing/access failures.
    let stock = NativeFile::open(
        Vfs::Stock,
        NativeName::Named(path),
        SQLITE_OPEN_READWRITE | SQLITE_OPEN_MAIN_DB,
    )
    .expect("stock VFS still opens the OS-authorized synthetic fixture");
    drop(stock);
}

#[test]
fn existing_wrong_owner_is_rejected_without_data_or_acl_changes() {
    let root = Root::new();
    let path = root.0.join("wrong-owner.sqlite3");
    std::fs::write(&path, b"preserve wrong-owner synthetic bytes").unwrap();
    require_wrong_owner_fixture(&path);
    // Isolate the owner defect: DACL itself is exactly the current user's private ACL.
    set_fixture_acl(&path, AttackAcl::OwnerOnly);
    assert!(
        path_security(&path).owner != user_sid(),
        "observed different-owner fixture"
    );
    assert_rejected_unchanged(&path, Vfs::Private(hepta_win32_owner_vfs_name().unwrap()));
}

#[test]
fn existing_broad_acl_is_rejected_without_data_or_acl_changes() {
    let root = Root::new();
    let path = root.0.join("broad-acl.sqlite3");
    let name = hepta_win32_owner_vfs_name().unwrap();
    let db = Database::open(&path, Vfs::Private(name), CREATE_RW).unwrap();
    db.execute(c"CREATE TABLE observed(value);");
    assert_private(db.handle());
    drop(db);
    set_fixture_acl(&path, AttackAcl::WorldReadable);
    assert!(
        path_security(&path).owner == user_sid(),
        "only DACL is unqualified"
    );
    assert_rejected_unchanged(&path, Vfs::Private(name));
}

#[test]
fn cached_private_shm_rejects_stock_policy_without_poisoning_private_readers() {
    let root = Root::new();
    let path = root.0.join("shared.sqlite3");
    let name = hepta_win32_owner_vfs_name().unwrap();
    let writer = Database::open(&path, Vfs::Private(name), CREATE_RW).unwrap();
    writer.execute(
        c"PRAGMA journal_mode=WAL; CREATE TABLE observed(value); INSERT INTO observed VALUES(4);",
    );
    let shm = root.0.join("shared.sqlite3-shm");
    let before = path_security(&shm);
    match Database::open(&path, Vfs::Stock, SQLITE_OPEN_READWRITE) {
        Ok(stock) => assert_eq!(
            stock.exec(c"SELECT value FROM observed;"),
            SQLITE_IOERR_SHMOPEN
        ),
        Err(status) => assert_eq!(status & 255, SQLITE_IOERR),
    }
    let reader = Database::open(&path, Vfs::Private(name), SQLITE_OPEN_READONLY).unwrap();
    reader.execute(c"SELECT value FROM observed;");
    writer.execute(c"INSERT INTO observed VALUES(5);");
    assert!(
        path_security(&shm) == before,
        "mixed policy did not change SHM security"
    );
    assert_private(reader.handle());
}
