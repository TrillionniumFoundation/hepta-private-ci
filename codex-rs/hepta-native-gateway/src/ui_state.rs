use std::collections::BTreeMap;
use std::fmt;

use codex_hepta_types::StableId;

use crate::shell::NativePresentationState;
use crate::shell::PlatformDecision;
use crate::shell::PlatformDecisionStatus;
use crate::shell::SessionOperationKey;

const MAX_FOCUS_TARGETS: usize = 512;
const MIN_SCALE_MILLI: u16 = 500;
const MAX_SCALE_MILLI: u16 = 4000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NavigationSection {
    Runtime,
    Operations,
    Updates,
    Settings,
}

impl NavigationSection {
    pub const fn accessibility_label(self, locale: NativeLocale) -> &'static str {
        match (locale, self) {
            (NativeLocale::English, Self::Runtime) => "Runtime",
            (NativeLocale::English, Self::Operations) => "Operations",
            (NativeLocale::English, Self::Updates) => "Updates",
            (NativeLocale::English, Self::Settings) => "Settings",
            (NativeLocale::ChineseSimplified, Self::Runtime) => "运行时",
            (NativeLocale::ChineseSimplified, Self::Operations) => "操作",
            (NativeLocale::ChineseSimplified, Self::Updates) => "更新",
            (NativeLocale::ChineseSimplified, Self::Settings) => "设置",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NativeLocale {
    English,
    ChineseSimplified,
}

impl NativeLocale {
    pub fn from_tag(tag: &str) -> Result<Self, UiStateError> {
        match tag.to_ascii_lowercase().as_str() {
            "en" | "en-us" | "en-gb" => Ok(Self::English),
            "zh" | "zh-cn" | "zh-hans" => Ok(Self::ChineseSimplified),
            _ => Err(UiStateError::UnsupportedLocale),
        }
    }

    pub const fn tag(self) -> &'static str {
        match self {
            Self::English => "en-US",
            Self::ChineseSimplified => "zh-CN",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ScaleFactorMilli(u16);

impl ScaleFactorMilli {
    pub fn new(value: u16) -> Self {
        Self(value.clamp(MIN_SCALE_MILLI, MAX_SCALE_MILLI))
    }

    pub const fn get(self) -> u16 {
        self.0
    }
}

impl Default for ScaleFactorMilli {
    fn default() -> Self {
        Self(1000)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum UiSeverity {
    Info,
    Warning,
    Error,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UiBanner {
    pub severity: UiSeverity,
    pub message: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AccessibilityRole {
    Application,
    Navigation,
    Tab,
    Status,
    Button,
    List,
    ListItem,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AccessibilityNode {
    pub id: StableId,
    pub role: AccessibilityRole,
    pub label: String,
    pub value: Option<String>,
    pub focusable: bool,
    pub focused: bool,
    pub disabled: bool,
    pub live_region: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperationRow {
    pub key: SessionOperationKey,
    pub action: String,
    pub status: PlatformDecisionStatus,
    pub terminal_observed: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum KeyCommand {
    TabForward,
    TabBackward,
    Escape,
    Activate,
    RuntimeShortcut,
    OperationsShortcut,
    UpdatesShortcut,
    SettingsShortcut,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum UiStateError {
    UnsupportedLocale,
    TooManyFocusTargets,
    FocusTargetMissing,
}

impl fmt::Display for UiStateError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for UiStateError {}

/// Renderer-independent native application view model.
///
/// The model owns navigation, focus order, locale, DPI scale and explicit
/// pending/indeterminate/error presentation. A concrete window renderer must
/// consume this model rather than inventing independent effect state.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeUiState {
    locale: NativeLocale,
    scale: ScaleFactorMilli,
    navigation: NavigationSection,
    runtime_view: Option<NativePresentationState>,
    operations: BTreeMap<SessionOperationKey, OperationRow>,
    focus_order: Vec<StableId>,
    focused: Option<StableId>,
    banner: Option<UiBanner>,
}

impl NativeUiState {
    pub fn new(locale: NativeLocale, scale: ScaleFactorMilli) -> Self {
        let focus_order = default_focus_order();
        let focused = focus_order.first().cloned();
        Self {
            locale,
            scale,
            navigation: NavigationSection::Runtime,
            runtime_view: None,
            operations: BTreeMap::new(),
            focus_order,
            focused,
            banner: None,
        }
    }

    pub const fn locale(&self) -> NativeLocale {
        self.locale
    }

    pub const fn scale(&self) -> ScaleFactorMilli {
        self.scale
    }

    pub const fn navigation(&self) -> NavigationSection {
        self.navigation
    }

    pub fn current_view(&self) -> Option<&NativePresentationState> {
        self.runtime_view.as_ref()
    }

    pub fn banner(&self) -> Option<&UiBanner> {
        self.banner.as_ref()
    }

    pub fn focused(&self) -> Option<&StableId> {
        self.focused.as_ref()
    }

    pub fn operation(&self, key: &SessionOperationKey) -> Option<&OperationRow> {
        self.operations.get(key)
    }

    pub fn set_locale(&mut self, locale: NativeLocale) {
        self.locale = locale;
    }

    pub fn set_scale(&mut self, scale: ScaleFactorMilli) {
        self.scale = scale;
    }

    pub fn present_runtime_view(&mut self, view: NativePresentationState) {
        self.runtime_view = Some(view);
        self.banner = None;
    }

    pub fn mark_runtime_unavailable(&mut self, detail: impl Into<String>) {
        self.banner = Some(UiBanner {
            severity: UiSeverity::Error,
            message: bounded_message(detail.into()),
        });
    }

    pub fn present_update_status(&mut self, succeeded: bool, quarantined: bool) {
        let (severity, english, chinese) = if succeeded {
            (
                UiSeverity::Info,
                "The signed native update completed and restart was observed.",
                "已完成签名原生更新，并观察到成功重启。",
            )
        } else if quarantined {
            (
                UiSeverity::Warning,
                "The native update was quarantined and rollback was requested.",
                "原生更新已被隔离，并已请求回滚。",
            )
        } else {
            (
                UiSeverity::Error,
                "The native update failed verification or execution.",
                "原生更新验证或执行失败。",
            )
        };
        self.banner = Some(UiBanner {
            severity,
            message: localized(self.locale, english, chinese).to_string(),
        });
    }

    pub fn present_operation(&mut self, decision: PlatformDecision) {
        let row = OperationRow {
            key: decision.key.clone(),
            action: decision.action.as_str().to_string(),
            status: decision.status.clone(),
            terminal_observed: decision.terminal_observed,
        };
        match row.status {
            PlatformDecisionStatus::Indeterminate => {
                self.banner = Some(UiBanner {
                    severity: UiSeverity::Warning,
                    message: localized(
                        self.locale,
                        "Operation outcome is unknown. Hepta will reconcile before any retry.",
                        "操作结果未知。Hepta 会先进行对账，绝不会直接重试外部效果。",
                    )
                    .to_string(),
                });
            }
            PlatformDecisionStatus::Failed | PlatformDecisionStatus::Rejected => {
                self.banner = Some(UiBanner {
                    severity: UiSeverity::Error,
                    message: localized(
                        self.locale,
                        "The platform operation did not succeed.",
                        "平台操作未成功。",
                    )
                    .to_string(),
                });
            }
            PlatformDecisionStatus::Succeeded => {
                self.banner = Some(UiBanner {
                    severity: UiSeverity::Info,
                    message: localized(
                        self.locale,
                        "The platform operation completed.",
                        "平台操作已完成。",
                    )
                    .to_string(),
                });
            }
        }
        self.operations.insert(decision.key, row);
    }

    pub fn replace_focus_order(&mut self, order: Vec<StableId>) -> Result<(), UiStateError> {
        if order.is_empty() || order.len() > MAX_FOCUS_TARGETS {
            return Err(UiStateError::TooManyFocusTargets);
        }
        self.focused = order.first().cloned();
        self.focus_order = order;
        Ok(())
    }

    pub fn focus(&mut self, id: StableId) -> Result<(), UiStateError> {
        if !self.focus_order.contains(&id) {
            return Err(UiStateError::FocusTargetMissing);
        }
        self.focused = Some(id);
        Ok(())
    }

    pub fn handle_key(&mut self, command: KeyCommand) {
        match command {
            KeyCommand::TabForward => self.move_focus(1),
            KeyCommand::TabBackward => self.move_focus(-1),
            KeyCommand::Escape => self.navigation = NavigationSection::Runtime,
            KeyCommand::Activate => {}
            KeyCommand::RuntimeShortcut => self.navigation = NavigationSection::Runtime,
            KeyCommand::OperationsShortcut => self.navigation = NavigationSection::Operations,
            KeyCommand::UpdatesShortcut => self.navigation = NavigationSection::Updates,
            KeyCommand::SettingsShortcut => self.navigation = NavigationSection::Settings,
        }
    }

    pub fn accessibility_snapshot(&self) -> Vec<AccessibilityNode> {
        let mut nodes = Vec::with_capacity(6 + self.operations.len());
        nodes.push(AccessibilityNode {
            id: stable_static("app"),
            role: AccessibilityRole::Application,
            label: localized(self.locale, "Hepta native", "Hepta 原生应用").to_string(),
            value: None,
            focusable: false,
            focused: false,
            disabled: false,
            live_region: false,
        });
        for section in [
            NavigationSection::Runtime,
            NavigationSection::Operations,
            NavigationSection::Updates,
            NavigationSection::Settings,
        ] {
            let id = navigation_id(section);
            nodes.push(AccessibilityNode {
                focused: self.focused.as_ref() == Some(&id),
                id,
                role: AccessibilityRole::Tab,
                label: section.accessibility_label(self.locale).to_string(),
                value: (section == self.navigation).then(|| "selected".to_string()),
                focusable: true,
                disabled: false,
                live_region: false,
            });
        }
        if let Some(banner) = &self.banner {
            nodes.push(AccessibilityNode {
                id: stable_static("status.banner"),
                role: AccessibilityRole::Status,
                label: banner.message.clone(),
                value: Some(format!("{:?}", banner.severity).to_ascii_lowercase()),
                focusable: false,
                focused: false,
                disabled: false,
                live_region: true,
            });
        }
        for row in self.operations.values() {
            nodes.push(AccessibilityNode {
                id: row.key.operation_id.clone(),
                role: AccessibilityRole::ListItem,
                label: format!("{}: {}", row.action, operation_status_label(&row.status)),
                value: Some(operation_status_label(&row.status).to_string()),
                focusable: false,
                focused: false,
                disabled: false,
                live_region: row.status == PlatformDecisionStatus::Indeterminate,
            });
        }
        nodes
    }

    fn move_focus(&mut self, delta: isize) {
        if self.focus_order.is_empty() {
            self.focused = None;
            return;
        }
        let current = self
            .focused
            .as_ref()
            .and_then(|focused| self.focus_order.iter().position(|value| value == focused))
            .unwrap_or(0);
        let len = self.focus_order.len() as isize;
        let next = (current as isize + delta).rem_euclid(len) as usize;
        self.focused = self.focus_order.get(next).cloned();
    }
}

impl Default for NativeUiState {
    fn default() -> Self {
        Self::new(NativeLocale::English, ScaleFactorMilli::default())
    }
}

fn default_focus_order() -> Vec<StableId> {
    vec![
        navigation_id(NavigationSection::Runtime),
        navigation_id(NavigationSection::Operations),
        navigation_id(NavigationSection::Updates),
        navigation_id(NavigationSection::Settings),
    ]
}

fn navigation_id(section: NavigationSection) -> StableId {
    match section {
        NavigationSection::Runtime => stable_static("nav.runtime"),
        NavigationSection::Operations => stable_static("nav.operations"),
        NavigationSection::Updates => stable_static("nav.updates"),
        NavigationSection::Settings => stable_static("nav.settings"),
    }
}

fn stable_static(value: &'static str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("static native UI id is invalid: {error}"))
}

fn bounded_message(mut message: String) -> String {
    const MAX_MESSAGE_BYTES: usize = 4096;
    if message.len() <= MAX_MESSAGE_BYTES {
        return message;
    }
    while message.len() > MAX_MESSAGE_BYTES {
        message.pop();
    }
    message
}

fn localized<'a>(locale: NativeLocale, english: &'a str, chinese: &'a str) -> &'a str {
    match locale {
        NativeLocale::English => english,
        NativeLocale::ChineseSimplified => chinese,
    }
}

fn operation_status_label(status: &PlatformDecisionStatus) -> &'static str {
    match status {
        PlatformDecisionStatus::Rejected => "rejected",
        PlatformDecisionStatus::Indeterminate => "indeterminate",
        PlatformDecisionStatus::Succeeded => "succeeded",
        PlatformDecisionStatus::Failed => "failed",
    }
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::Digest32;
    use codex_hepta_types::Generation;

    use crate::platform::PlatformAction;

    use super::*;

    fn stable(value: &str) -> StableId {
        StableId::new(value).unwrap_or_else(|error| panic!("fixture id: {error}"))
    }

    fn generation(value: u64) -> Generation {
        Generation::new(value).unwrap_or_else(|error| panic!("fixture generation: {error}"))
    }

    #[test]
    fn keyboard_focus_wraps_and_shortcuts_switch_sections() {
        let mut state = NativeUiState::default();
        assert_eq!(state.focused(), Some(&stable("nav.runtime")));
        state.handle_key(KeyCommand::TabBackward);
        assert_eq!(state.focused(), Some(&stable("nav.settings")));
        state.handle_key(KeyCommand::OperationsShortcut);
        assert_eq!(state.navigation(), NavigationSection::Operations);
        state.handle_key(KeyCommand::Escape);
        assert_eq!(state.navigation(), NavigationSection::Runtime);
    }

    #[test]
    fn dpi_scale_is_bounded() {
        assert_eq!(ScaleFactorMilli::new(100).get(), MIN_SCALE_MILLI);
        assert_eq!(ScaleFactorMilli::new(9000).get(), MAX_SCALE_MILLI);
        assert_eq!(ScaleFactorMilli::new(1500).get(), 1500);
    }

    #[test]
    fn indeterminate_operation_is_an_accessible_live_warning() {
        let mut state = NativeUiState::new(
            NativeLocale::ChineseSimplified,
            ScaleFactorMilli::default(),
        );
        let key = SessionOperationKey {
            session_id: stable("session.1"),
            session_generation: generation(1),
            operation_id: stable("operation.1"),
        };
        state.present_operation(PlatformDecision {
            key,
            action: PlatformAction::CopyText,
            payload_digest: Digest32::of_bytes(b"payload"),
            status: PlatformDecisionStatus::Indeterminate,
            terminal_observed: false,
            outcome_digest: None,
        });
        let nodes = state.accessibility_snapshot();
        assert!(nodes.iter().any(|node| node.live_region));
        assert!(state.banner().is_some_and(|banner| banner.message.contains("对账")));
    }
}
