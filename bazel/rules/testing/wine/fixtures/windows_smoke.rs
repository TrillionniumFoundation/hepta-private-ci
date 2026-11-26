use std::io::Write;

fn main() {
    if let Some(home) = std::env::var_os("WINE_SMOKE_HOME") {
        let marker = std::path::PathBuf::from(home).join("marker.txt");
        assert_eq!(
            std::fs::read(&marker).expect("read prelaunch marker"),
            b"created before launch"
        );
    }
    println!("WINE_TEST_READY");
    std::io::stdout().flush().expect("flush readiness marker");

    if std::env::args().any(|arg| arg == "--fail") {
        std::process::exit(9);
    }
    if std::env::args().any(|arg| arg == "--wait") {
        loop {
            std::thread::park();
        }
    }
}
