use std::fs;

use super::runtime::FrozenProductBinary;
use super::runtime::QualificationRuntimeLayout;
use crate::QualificationError;

#[test]
fn creates_private_surface_layouts_and_strict_configs() -> Result<(), QualificationError> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("runtime");
    let layout = QualificationRuntimeLayout::create(&root)?;
    let address = "127.0.0.1:43123"
        .parse()
        .map_err(|error| QualificationError::Invalid(format!("invalid test address: {error}")))?;
    for surface in [layout.app_server(), layout.mcp()] {
        assert_eq!(surface.write_config(address)?.len(), 64);
        let parsed: toml::Value = toml::from_str(&fs::read_to_string(surface.config())?)
            .map_err(|error| QualificationError::Invalid(error.to_string()))?;
        assert_eq!(
            parsed["model_providers"]["hepta-shadow-loopback-v1"]["base_url"].as_str(),
            Some("http://127.0.0.1:43123/v1")
        );
        assert_eq!(
            surface.environment().get("HOME"),
            Some(&surface.home().display().to_string())
        );
        assert!(surface.sqlite().is_dir());
        assert_eq!(surface.work(), layout.work());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;

        assert_eq!(fs::metadata(layout.root())?.permissions().mode() & 0o077, 0);
        for surface in [layout.app_server(), layout.mcp()] {
            let path = surface.home().join("installation_id");
            fs::write(&path, "11111111-1111-4111-8111-111111111111")?;
            fs::set_permissions(&path, fs::Permissions::from_mode(0o644))?;
        }
        layout.harden_known_product_permissions()?;
        super::durable::verify_private_tree(layout.root())?;
    }
    Ok(())
}

#[test]
fn rejects_an_unpinned_product_binary() -> Result<(), QualificationError> {
    let temp = tempfile::tempdir()?;
    let candidate = temp.path().join("hepta");
    fs::write(&candidate, b"not the frozen product")?;
    assert!(FrozenProductBinary::verify(&candidate).is_err());
    Ok(())
}
