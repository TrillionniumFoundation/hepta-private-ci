// Cargo tree headings are structural rows, never dependency marker names.
fn hepta_dependency_heading(line: &str) -> bool {
    matches!(line.trim_start_matches(|c: char| c.is_whitespace() || matches!(c, '│' | '├' | '└' | '─')),
        "[build-dependencies]" | "[dev-dependencies]")
}

// Tool-only compatibility helper injected into the exact pinned cargo-makepad.
fn hepta_dependency_dir(
    build_dir: &std::path::Path,
    name: &str,
    resource_root: &std::path::Path,
) -> Result<Option<std::path::PathBuf>, String> {
    if name.is_empty() || name.len() > 128 || !name.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'-' || c == b'_') {
        return Err(format!("invalid dependency marker name (first 128 chars): {:?}", name.chars().take(128).collect::<String>()));
    }
    let build_root = build_dir.canonicalize().map_err(|e| e.to_string())?;
    let allowed = resource_root.canonicalize().map_err(|e| e.to_string())?;
    let mut selected = None;
    for marker in [build_dir.join(format!("{name}.path")), build_dir.join("build").join(format!("{name}.path"))] {
        if !marker.exists() { continue; }
        let marker = marker.canonicalize().map_err(|e| e.to_string())?;
        if !marker.starts_with(&build_root) { return Err("dependency marker escapes build directory".into()); }
        let raw = std::fs::read_to_string(&marker).map_err(|e| e.to_string())?;
        let candidate = std::path::Path::new(raw.trim());
        if !candidate.is_absolute() { return Err("dependency marker must contain an absolute path".into()); }
        let candidate = candidate.canonicalize().map_err(|e| e.to_string())?;
        if !candidate.is_dir() || !candidate.starts_with(&allowed) {
            return Err("dependency resource path escapes exact Makepad source".into());
        }
        if selected.as_ref().is_some_and(|existing| existing != &candidate) {
            return Err("ambiguous legacy and current dependency markers".into());
        }
        selected = Some(candidate);
    }
    Ok(selected)
}

#[cfg(test)]
mod hepta_marker_tests {
    use super::*;
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicUsize, Ordering};
    static NEXT: AtomicUsize = AtomicUsize::new(0);
    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            let root = std::env::temp_dir().join(format!("robrix-marker-{}-{}", std::process::id(), NEXT.fetch_add(1, Ordering::Relaxed)));
            for path in ["target/release/build", "source/platform", "source/widgets", "outside"] {
                std::fs::create_dir_all(root.join(path)).unwrap();
            }
            Self(root)
        }
        fn build(&self) -> PathBuf { self.0.join("target/release") }
        fn source(&self) -> PathBuf { self.0.join("source") }
        fn write(&self, modern: bool, destination: &str) {
            let name = if modern { "build/makepad-platform.path" } else { "makepad-platform.path" };
            std::fs::write(self.build().join(name), self.0.join(destination).to_str().unwrap()).unwrap();
        }
        fn resolve(&self) -> Result<Option<PathBuf>, String> { hepta_dependency_dir(&self.build(), "makepad-platform", &self.source()) }
    }
    impl Drop for Fixture { fn drop(&mut self) { let _ = std::fs::remove_dir_all(&self.0); } }
    #[test] fn actual_cargo_tree_headings_are_not_marker_names() {
        for line in ["│   │       [build-dependencies]", "[build-dependencies]", "[dev-dependencies]"] {
            assert!(hepta_dependency_heading(line));
        }
        for line in ["├── makepad-platform v1.0.0", "[build-dependencies]/../", "[unknown]"] {
            assert!(!hepta_dependency_heading(line));
        }
    }
    #[test] fn malformed_marker_names_still_fail_with_bounded_diagnostics() {
        let f = Fixture::new();
        for name in ["build-dependencies]", "../makepad-platform", "makepad-platform.path", ""] {
            assert!(hepta_dependency_dir(&f.build(), name, &f.source()).unwrap_err().contains("invalid dependency marker name"));
        }
        assert!(hepta_dependency_dir(&f.build(), &"x".repeat(1000), &f.source()).unwrap_err().len() < 200);
    }
    #[test] fn absent_marker_is_not_a_resolved_resource() { let f = Fixture::new(); assert_eq!(f.resolve().unwrap(), None); }
    #[test] fn legacy_and_current_layouts_resolve_same_source() {
        let f = Fixture::new(); f.write(false, "source/platform"); assert_eq!(f.resolve().unwrap(), Some(f.source().join("platform")));
        f.write(true, "source/platform"); assert_eq!(f.resolve().unwrap(), Some(f.source().join("platform")));
        std::fs::remove_file(f.build().join("makepad-platform.path")).unwrap(); assert_eq!(f.resolve().unwrap(), Some(f.source().join("platform")));
    }
    #[test] fn ambiguous_markers_fail() { let f = Fixture::new(); f.write(false, "source/platform"); f.write(true, "source/widgets"); assert!(f.resolve().is_err()); }
    #[test] fn escaping_resource_path_fails() { let f = Fixture::new(); f.write(true, "outside"); assert!(f.resolve().is_err()); }
    #[test] fn escaping_marker_symlink_fails() {
        let f = Fixture::new(); let outside = f.0.join("outside/marker"); std::fs::write(&outside, f.source().join("platform").to_str().unwrap()).unwrap();
        #[cfg(unix)] std::os::unix::fs::symlink(outside, f.build().join("build/makepad-platform.path")).unwrap();
        #[cfg(unix)] assert!(f.resolve().is_err());
    }
    #[test] fn relative_resource_path_fails() {
        let f = Fixture::new(); std::fs::write(f.build().join("build/makepad-platform.path"), "../../source/platform").unwrap(); assert!(f.resolve().is_err());
    }
}
