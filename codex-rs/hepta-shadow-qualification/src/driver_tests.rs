use std::io;
use std::path::PathBuf;
use std::pin::Pin;
use std::task::Context;
use std::task::Poll;

use tokio::io::AsyncWrite;

use super::driver::QualificationDriverRun;
use crate::QualificationError;

#[tokio::test]
async fn app_and_mcp_fsm_persist_before_every_sample_write() -> Result<(), QualificationError> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("observer");
    let cwd = temp.path().join("work");
    std::fs::create_dir(&cwd)?;
    let mut run = QualificationDriverRun::create(&root, &cwd)?;
    let run_root = run.run_root().to_path_buf();

    let app_checks = vec![
        None,
        None,
        None,
        Some(run_root.join("app_server-01.pre-send.json")),
        Some(run_root.join("app_server-02.pre-send.json")),
    ];
    let mut app = run.app_server(ProbeWriter::new(app_checks, None))?;
    app.initialize().await?;
    app.initialized().await?;
    app.start_thread().await?;
    app.start_turn("thread-app").await?;
    app.start_turn("thread-app").await?;
    let app_writer = app.finish()?;
    assert_eq!(app_writer.write_count, 5);

    let mcp_checks = vec![
        None,
        None,
        Some(run_root.join("mcp-01.pre-send.json")),
        Some(run_root.join("mcp-02.pre-send.json")),
    ];
    let mut mcp = run.mcp(ProbeWriter::new(mcp_checks, None))?;
    mcp.initialize().await?;
    mcp.initialized().await?;
    mcp.start_thread().await?;
    mcp.continue_thread("thread-mcp").await?;
    let mcp_writer = mcp.finish()?;
    assert_eq!(mcp_writer.write_count, 4);

    let completed = run.finish()?;
    assert_eq!(completed.token_count(), 4);
    assert_eq!(std::fs::read_dir(run_root.join("protocol"))?.count(), 18);
    Ok(())
}

#[tokio::test]
async fn failed_pipe_write_keeps_durable_pre_send_and_poisoned_fsm()
-> Result<(), QualificationError> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("observer");
    let cwd = temp.path().join("work");
    std::fs::create_dir(&cwd)?;
    let mut run = QualificationDriverRun::create(&root, &cwd)?;
    let receipt = run.run_root().join("app_server-01.pre-send.json");
    let checks = vec![None, None, None, Some(receipt.clone())];
    let mut app = run.app_server(ProbeWriter::new(checks, Some(3)))?;
    app.initialize().await?;
    app.initialized().await?;
    app.start_thread().await?;
    assert!(app.start_turn("thread-app").await.is_err());
    drop(app);
    assert!(receipt.is_file());
    assert!(
        run.run_root()
            .join("protocol/app_server-outbound-004.receipt.json")
            .is_file()
    );
    assert!(run.finish().is_err());
    Ok(())
}

struct ProbeWriter {
    checks: Vec<Option<PathBuf>>,
    fail_at: Option<usize>,
    write_count: usize,
}

impl ProbeWriter {
    fn new(checks: Vec<Option<PathBuf>>, fail_at: Option<usize>) -> Self {
        Self {
            checks,
            fail_at,
            write_count: 0,
        }
    }
}

impl AsyncWrite for ProbeWriter {
    fn poll_write(
        mut self: Pin<&mut Self>,
        _context: &mut Context<'_>,
        buffer: &[u8],
    ) -> Poll<Result<usize, io::Error>> {
        let index = self.write_count;
        let expected = self
            .checks
            .get(index)
            .unwrap_or_else(|| panic!("unexpected write {index}"));
        if let Some(path) = expected {
            assert!(
                path.is_file(),
                "durable pre-send receipt must precede write"
            );
        }
        self.write_count += 1;
        if self.fail_at == Some(index) {
            return Poll::Ready(Err(io::Error::new(
                io::ErrorKind::BrokenPipe,
                "simulated pipe failure",
            )));
        }
        Poll::Ready(Ok(buffer.len()))
    }

    fn poll_flush(self: Pin<&mut Self>, _context: &mut Context<'_>) -> Poll<Result<(), io::Error>> {
        Poll::Ready(Ok(()))
    }

    fn poll_shutdown(
        self: Pin<&mut Self>,
        _context: &mut Context<'_>,
    ) -> Poll<Result<(), io::Error>> {
        Poll::Ready(Ok(()))
    }
}
