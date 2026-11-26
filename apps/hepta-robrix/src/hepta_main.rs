fn main() {
    #[cfg(target_os = "linux")]
    {
        use std::os::unix::fs::MetadataExt;
        if std::fs::metadata("/proc/self")
            .map(|value| value.uid() == 0)
            .unwrap_or(true)
        {
            eprintln!("Hepta must run as the enrolled desktop user.");
            std::process::exit(1);
        }
    }
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    if arguments == ["--help"] || arguments == ["-h"] {
        println!(
            "Hepta\nUsage: hepta-robrix [--config ABSOLUTE_JSON] [--check-connection]\nUses the original enrolled gateway and OS keyring. Configure chat separately before sending messages."
        );
        return;
    }
    #[cfg(not(target_arch = "wasm32"))]
    if arguments.iter().any(|value| value == "--check-connection") {
        let result = hepta_native::native_host::NativeHost::open(&arguments)
            .and_then(|mut host| host.refresh().map_err(Into::into));
        match result {
            Ok(observation) => {
                println!(
                    "Connected: {} agents; runtime ready: {}",
                    observation.agents.len(),
                    observation.ready
                );
                return;
            }
            Err(error) => {
                eprintln!("Hepta: {error}");
                std::process::exit(1);
            }
        }
    }
    // Packaged resources are relative to the executable, never the launcher's cwd.
    #[cfg(not(target_arch = "wasm32"))]
    if option_env!("MAKEPAD_PACKAGE_DIR").is_some() {
        let directory = std::env::current_exe()
            .ok()
            .and_then(|path| path.parent().map(std::path::Path::to_path_buf));
        if directory
            .as_ref()
            .is_none_or(|path| std::env::set_current_dir(path).is_err())
        {
            eprintln!("Hepta: packaged resources are unavailable.");
            std::process::exit(1);
        }
    }
    robrix::hepta_app::app_main();
}
