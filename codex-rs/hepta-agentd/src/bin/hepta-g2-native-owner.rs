//! Actual bounded G2 owner entry. The kernel, original Root and original
//! Supervisor assign roles and generations; argv and JSON never assign them.

#[cfg(target_os = "linux")]
#[path = "../native_g2_entry/mod.rs"]
mod native;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    #[cfg(target_os = "linux")]
    return native::run();
    #[cfg(not(target_os = "linux"))]
    Err("the original G2 kernel entry requires Linux ABI".into())
}
