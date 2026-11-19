use super::stage_helper;
use pretty_assertions::assert_eq;
use std::fs;
use std::io;
use std::sync::Arc;
use std::sync::Barrier;
use tempfile::TempDir;

#[test]
fn helper_publication_accepts_only_complete_identical_files() -> io::Result<()> {
    let directory = TempDir::new()?;
    let source = directory.path().join("source.exe");
    let destination = directory.path().join("destination.exe");
    let bytes = vec![0x5a; 65_537];
    fs::write(&source, &bytes)?;
    stage_helper(&source, &destination)?;
    let open_destination = fs::File::open(&destination)?;
    stage_helper(&source, &destination)?;
    assert_eq!(fs::read(&destination)?, bytes);
    drop(open_destination);

    for wrong in [
        vec![0x5b; bytes.len()],
        bytes[..bytes.len() - 1].to_vec(),
        [bytes.as_slice(), &[0x5a]].concat(),
    ] {
        fs::write(&destination, &wrong)?;
        let result = stage_helper(&source, &destination);
        assert_eq!(
            result.map_err(|error| error.kind()),
            Err(io::ErrorKind::InvalidData)
        );
        assert_eq!(fs::read(&destination)?, wrong);
    }
    assert_eq!(fs::read_dir(directory.path())?.count(), 2);
    Ok(())
}

#[test]
fn concurrent_helper_publication_never_replaces_another_complete_copy() -> io::Result<()> {
    let directory = TempDir::new()?;
    let source = directory.path().join("source.exe");
    let destination = directory.path().join("destination.exe");
    let bytes = vec![0x71; 131_073];
    fs::write(&source, &bytes)?;
    let barrier = Arc::new(Barrier::new(/*n*/ 8));
    std::thread::scope(|scope| -> io::Result<()> {
        let mut workers = Vec::new();
        for _ in 0..8 {
            let source = &source;
            let destination = &destination;
            let barrier = Arc::clone(&barrier);
            workers.push(scope.spawn(move || {
                barrier.wait();
                stage_helper(source, destination)
            }));
        }
        for worker in workers {
            worker
                .join()
                .map_err(|_| io::Error::other("staging worker panicked"))??;
        }
        Ok(())
    })?;
    assert_eq!(fs::read(&destination)?, bytes);
    assert_eq!(fs::read_dir(directory.path())?.count(), 2);
    Ok(())
}

#[test]
fn helper_publication_preserves_an_existing_directory() -> io::Result<()> {
    let directory = TempDir::new()?;
    let source = directory.path().join("source.exe");
    let destination = directory.path().join("destination.exe");
    fs::write(&source, b"helper")?;
    fs::create_dir(&destination)?;
    assert!(stage_helper(&source, &destination).is_err());
    assert!(destination.is_dir());
    assert_eq!(fs::read_dir(directory.path())?.count(), 2);
    Ok(())
}
