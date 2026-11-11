//! One isolated mechanism experiment, not a qualification or hosted-cause claim.
//! The external tracer delays exec entry; this crate keeps forbid(unsafe_code).

use super::*;
use pretty_assertions::assert_eq;
use std::os::unix::fs::MetadataExt;
use std::sync::Mutex;
use std::sync::mpsc;

#[derive(Debug, serde::Serialize)]
struct ObservedLockDescriptor {
    descriptor: String,
    device: u64,
    inode: u64,
    flags: u64,
}

fn matching_lock_descriptors(
    pid: u32,
    lock: &std::fs::Metadata,
) -> Vec<ObservedLockDescriptor> {
    let mut observed = Vec::new();
    for entry in std::fs::read_dir(format!("/proc/{pid}/fd")).unwrap() {
        let entry = entry.unwrap();
        let metadata = match std::fs::metadata(entry.path()) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => continue,
            Err(error) => panic!("cannot observe descriptor metadata: {error}"),
        };
        if metadata.dev() != lock.dev() || metadata.ino() != lock.ino() {
            continue;
        }
        let descriptor = entry.file_name().into_string().unwrap();
        let info = std::fs::read_to_string(format!("/proc/{pid}/fdinfo/{descriptor}")).unwrap();
        let flags = info
            .lines()
            .find_map(|line| line.strip_prefix("flags:\t"))
            .map(|value| u64::from_str_radix(value.trim(), 8).unwrap())
            .unwrap();
        observed.push(ObservedLockDescriptor {
            descriptor,
            device: metadata.dev(),
            inode: metadata.ino(),
            flags,
        });
    }
    observed
}

#[test]
fn controlled_pre_exec_inheritance_retains_the_publication_lock() {
    let began = Instant::now();
    let parent_pid = std::process::id();
    let executable = std::env::current_exe().unwrap();
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let (entered, observed) = mpsc::channel();
    let (resume, released) = mpsc::channel();
    let released = Mutex::new(released);
    *root.before_directory_sync.lock().unwrap() = Some(Arc::new(move || {
        entered.send(()).map_err(std::io::Error::other)?;
        released
            .lock()
            .unwrap()
            .recv_timeout(Duration::from_secs(10))
            .map_err(std::io::Error::other)
    }));
    let initializing_root = root.clone();
    let initializing = std::thread::spawn(move || {
        HostAuthorityFrontierStore::initialize(initializing_root, OWNER.into(), 1_u64)
    });
    observed.recv_timeout(Duration::from_secs(10)).unwrap();
    let locks: Vec<_> = std::fs::read_dir(directory.path())
        .unwrap()
        .map(Result::unwrap)
        .filter(|entry| entry.file_name().to_string_lossy().ends_with(".lock"))
        .map(|entry| entry.path())
        .collect();
    assert_eq!(locks.len(), 1);
    let lock = std::fs::metadata(&locks[0]).unwrap();
    let parent_before = matching_lock_descriptors(parent_pid, &lock);
    assert_eq!(parent_before.len(), 1);
    println!("INHERITANCE_OBSERVATION {}", serde_json::json!({
        "phase": "initialize_holds_lock", "elapsed_micros": began.elapsed().as_micros(),
        "parent_pid": parent_pid, "lock_path": locks[0], "descriptors": parent_before,
    }));

    // No pre_exec callback and no unsafe code. Only the external tracer pauses
    // this ordinary exec syscall before the kernel applies CLOEXEC.
    let child = std::thread::spawn(|| Command::new("/usr/bin/true").status().unwrap());
    let deadline = Instant::now() + Duration::from_secs(10);
    let child_pid = loop {
        let mut children = BTreeSet::new();
        for task in std::fs::read_dir("/proc/self/task").unwrap() {
            let task = task.unwrap();
            let children_file = task.path().join("children");
            match std::fs::read_to_string(children_file) {
                Ok(value) => children.extend(value.split_whitespace().map(|pid| pid.parse::<u32>().unwrap())),
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                Err(error) => panic!("cannot observe this process's children: {error}"),
            }
        }
        let inherited = children.into_iter().find(|pid| {
            std::fs::read_link(format!("/proc/{pid}/exe")).ok().as_ref() == Some(&executable)
                && !matching_lock_descriptors(*pid, &lock).is_empty()
        });
        if let Some(pid) = inherited {
            break pid;
        }
        assert!(Instant::now() < deadline, "no real pre-exec inherited lock was observed");
        std::thread::sleep(Duration::from_millis(1));
    };
    let inherited_before = matching_lock_descriptors(child_pid, &lock);
    assert_eq!(inherited_before.len(), 1);
    assert_ne!(inherited_before[0].flags & u64::from(OFlags::CLOEXEC.bits()), 0);
    *root.before_directory_sync.lock().unwrap() = None;
    resume.send(()).unwrap();
    let store = initializing.join().unwrap().unwrap();
    assert_eq!(std::fs::read_link(format!("/proc/{child_pid}/exe")).unwrap(), executable);
    let parent_after = matching_lock_descriptors(parent_pid, &lock);
    let inherited_after = matching_lock_descriptors(child_pid, &lock);
    assert!(parent_after.is_empty());
    assert_eq!(inherited_after.len(), 1);
    assert_ne!(inherited_after[0].flags & u64::from(OFlags::CLOEXEC.bits()), 0);
    let result = store.compare_and_set(OWNER, &1, &2);
    println!("INHERITANCE_OBSERVATION {}", serde_json::json!({
        "phase": "single_cas_while_child_retains_lock", "elapsed_micros": began.elapsed().as_micros(),
        "parent_pid": parent_pid, "child_pid": child_pid,
        "parent_descriptors": parent_after, "child_descriptors": inherited_after,
        "result": format!("{result:?}"),
    }));
    assert_eq!(result, Err(AuthorityTrustError::Conflict));
    assert_eq!(store.read(), Ok(1));
    assert!(child.join().unwrap().success());
    assert_eq!(store.load(OWNER), Ok(1));
    println!("INHERITANCE_OBSERVATION {}", serde_json::json!({
        "phase": "child_exited_original_value_readable", "elapsed_micros": began.elapsed().as_micros(),
        "child_pid": child_pid, "original_value": 1,
    }));

    // Independent no-inheritance fixture: its only CAS is never a retry of
    // the rejected operation above, whose original frontier remains one.
    let control_directory = tempfile::tempdir().unwrap();
    let control_root = test_directory(control_directory.path());
    let control = HostAuthorityFrontierStore::initialize(control_root, OWNER.into(), 1_u64).unwrap();
    let control_result = control.compare_and_set(OWNER, &1, &2);
    println!("INHERITANCE_OBSERVATION {}", serde_json::json!({
        "phase": "independent_no_inheritance_single_cas", "elapsed_micros": began.elapsed().as_micros(),
        "result": format!("{control_result:?}"),
    }));
    assert_eq!(control_result, Ok(()));
    assert_eq!(control.load(OWNER), Ok(2));
}
