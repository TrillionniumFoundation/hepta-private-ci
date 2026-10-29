//! Controlled process regression fixture; never installed by product startup.
#[cfg(unix)]
#[path = "../paired_process_fixture.rs"]
mod fixture;

fn main() -> std::process::ExitCode {
    #[cfg(unix)]
    {
        match fixture::run() {
            Ok(()) => std::process::ExitCode::SUCCESS,
            Err(error) => {
                eprintln!("paired test fixture failed: {error:#}");
                std::process::ExitCode::FAILURE
            }
        }
    }
    #[cfg(not(unix))]
    {
        eprintln!("paired test fixture requires the Unix control profile");
        std::process::ExitCode::FAILURE
    }
}
