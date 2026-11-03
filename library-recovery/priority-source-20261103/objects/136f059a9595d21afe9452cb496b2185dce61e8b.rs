pub fn preserve(error: std::io::Error) -> std::io::Result<()> {
    Err(error).inspect_err(|error| {
        if cfg!(debug_assertions) {
            eprintln!("fleet release publication failed at staged-directory rename: {error}");
        }
    })
}
