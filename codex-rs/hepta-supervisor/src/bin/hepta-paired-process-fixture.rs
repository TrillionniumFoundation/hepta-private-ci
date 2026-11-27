// The paired product tests install this executable into the release catalog.
// Keep the child protocol independent of the parent libtest harness.
#[cfg(unix)]
#[path = "../paired_process_fixture.rs"]
mod paired_process_fixture;

#[cfg(unix)]
fn main() {
    paired_process_fixture::run();
}

#[cfg(not(unix))]
fn main() {
    panic!("paired process fixture requires Unix");
}
