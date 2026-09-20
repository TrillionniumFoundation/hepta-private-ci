use std::path::Path;

use anyhow::Result;
use pretty_assertions::assert_eq;

use crate::HeptaFleetRoot;
use crate::HeptaStateRoot;

#[test]
fn accepted_runtime_roots_remain_absolute_on_the_executing_host() -> Result<()> {
    #[cfg(unix)]
    let paths = ["/srv/hepta/state", "/tmp/hepta root"];
    #[cfg(windows)]
    let paths = [
        r"C:\srv\hepta\state",
        r"\\server\share\hepta",
        r"\\?\C:\srv\hepta\state",
        r"\\?\UNC\server\share\hepta",
    ];

    for path in paths {
        let expected = Path::new(path);
        let state = HeptaStateRoot::parse(path)?;
        let fleet = HeptaFleetRoot::parse(path)?;
        assert_eq!(state.as_path(), expected);
        assert_eq!(fleet.as_path(), expected);
        assert!(state.as_path().is_absolute());
        assert!(fleet.as_path().is_absolute());
        assert!(state.layout().runtime_root().is_absolute());
        assert!(fleet.layout().state_root().is_absolute());
    }
    Ok(())
}

#[test]
fn foreign_or_drive_relative_roots_cannot_select_local_state() {
    #[cfg(unix)]
    let paths = [
        r"C:\srv\hepta\state",
        r"\\server\share\hepta",
        "C:/srv/hepta",
    ];
    #[cfg(windows)]
    let paths = ["/srv/hepta/state", r"\srv\hepta\state", "C:srv/hepta"];

    for path in paths {
        assert!(!Path::new(path).is_absolute());
        assert!(HeptaStateRoot::parse(path).is_err(), "accepted {path:?}");
        assert!(HeptaFleetRoot::parse(path).is_err(), "accepted {path:?}");
        assert!(HeptaStateRoot::production_default(Path::new(path)).is_err());
        assert!(HeptaFleetRoot::production_default(Path::new(path)).is_err());
    }
}

#[test]
fn native_filesystem_roots_and_traversal_are_rejected() {
    #[cfg(unix)]
    let paths = ["/", "/srv/../hepta", "/srv/./hepta", "/srv/hepta/."];
    #[cfg(windows)]
    let paths = [
        r"C:\",
        r"\\server\share",
        r"\\?\C:\",
        r"C:\srv\..\hepta",
        r"C:\srv\.\hepta",
        r"C:\srv\hepta\.",
        r"\\server\share\..\hepta",
    ];

    for path in paths {
        assert!(HeptaStateRoot::parse(path).is_err(), "accepted {path:?}");
        assert!(HeptaFleetRoot::parse(path).is_err(), "accepted {path:?}");
    }
}
