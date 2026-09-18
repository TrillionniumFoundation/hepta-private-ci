#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NativePlatform {
    MacOs,
    Windows,
    Linux,
    Unsupported,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CapabilityMaturity {
    Implemented,
    DesktopSessionRequired,
    DependencyAdmissionPending,
    Unsupported,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NativePlatformProfile {
    pub platform: NativePlatform,
    pub window_framework: &'static str,
    pub window_renderer: CapabilityMaturity,
    pub open_path: CapabilityMaturity,
    pub reveal_path: CapabilityMaturity,
    pub clipboard: CapabilityMaturity,
    pub notification: CapabilityMaturity,
    pub keyring: CapabilityMaturity,
    pub signed_updates: CapabilityMaturity,
}

/// Selected all-Rust window stack. The source intentionally does not advertise
/// the renderer as implemented until `winit` + `egui` are admitted into the
/// pinned workspace lockfile and exercised by packaged OS tests.
pub const SELECTED_WINDOW_FRAMEWORK: &str = "winit+egui";

pub const PLATFORM_MATRIX: [NativePlatformProfile; 3] = [
    NativePlatformProfile {
        platform: NativePlatform::MacOs,
        window_framework: SELECTED_WINDOW_FRAMEWORK,
        window_renderer: CapabilityMaturity::DependencyAdmissionPending,
        open_path: CapabilityMaturity::Implemented,
        reveal_path: CapabilityMaturity::Implemented,
        clipboard: CapabilityMaturity::DesktopSessionRequired,
        notification: CapabilityMaturity::DesktopSessionRequired,
        keyring: CapabilityMaturity::Implemented,
        signed_updates: CapabilityMaturity::Implemented,
    },
    NativePlatformProfile {
        platform: NativePlatform::Windows,
        window_framework: SELECTED_WINDOW_FRAMEWORK,
        window_renderer: CapabilityMaturity::DependencyAdmissionPending,
        open_path: CapabilityMaturity::Implemented,
        reveal_path: CapabilityMaturity::Implemented,
        clipboard: CapabilityMaturity::DesktopSessionRequired,
        notification: CapabilityMaturity::DesktopSessionRequired,
        keyring: CapabilityMaturity::Implemented,
        signed_updates: CapabilityMaturity::Implemented,
    },
    NativePlatformProfile {
        platform: NativePlatform::Linux,
        window_framework: SELECTED_WINDOW_FRAMEWORK,
        window_renderer: CapabilityMaturity::DependencyAdmissionPending,
        open_path: CapabilityMaturity::DesktopSessionRequired,
        reveal_path: CapabilityMaturity::DesktopSessionRequired,
        clipboard: CapabilityMaturity::DesktopSessionRequired,
        notification: CapabilityMaturity::DesktopSessionRequired,
        keyring: CapabilityMaturity::DesktopSessionRequired,
        signed_updates: CapabilityMaturity::Implemented,
    },
];

pub const fn current_platform_profile() -> NativePlatformProfile {
    #[cfg(target_os = "macos")]
    {
        return PLATFORM_MATRIX[0];
    }
    #[cfg(target_os = "windows")]
    {
        return PLATFORM_MATRIX[1];
    }
    #[cfg(target_os = "linux")]
    {
        return PLATFORM_MATRIX[2];
    }
    #[allow(unreachable_code)]
    NativePlatformProfile {
        platform: NativePlatform::Unsupported,
        window_framework: SELECTED_WINDOW_FRAMEWORK,
        window_renderer: CapabilityMaturity::Unsupported,
        open_path: CapabilityMaturity::Unsupported,
        reveal_path: CapabilityMaturity::Unsupported,
        clipboard: CapabilityMaturity::Unsupported,
        notification: CapabilityMaturity::Unsupported,
        keyring: CapabilityMaturity::Unsupported,
        signed_updates: CapabilityMaturity::Unsupported,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn first_release_matrix_is_exactly_desktop_macos_windows_linux() {
        assert_eq!(PLATFORM_MATRIX.len(), 3);
        assert_eq!(PLATFORM_MATRIX[0].platform, NativePlatform::MacOs);
        assert_eq!(PLATFORM_MATRIX[1].platform, NativePlatform::Windows);
        assert_eq!(PLATFORM_MATRIX[2].platform, NativePlatform::Linux);
        assert!(PLATFORM_MATRIX.iter().all(|profile| {
            profile.window_framework == SELECTED_WINDOW_FRAMEWORK
                && profile.window_renderer == CapabilityMaturity::DependencyAdmissionPending
        }));
    }
}
