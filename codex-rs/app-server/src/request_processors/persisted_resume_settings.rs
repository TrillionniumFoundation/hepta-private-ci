use codex_core::config::Config;
use codex_protocol::config_types::ApprovalsReviewer;
use codex_protocol::models::ActivePermissionProfile;
use codex_protocol::protocol::AskForApproval;
use codex_protocol::protocol::EventMsg;
use codex_rollout::RolloutItem;
use codex_utils_absolute_path::AbsolutePathBuf;
use std::collections::HashSet;

pub(super) struct PersistedResumeEnvironment {
    pub(super) cwd: Option<AbsolutePathBuf>,
    pub(super) workspace_roots: Vec<AbsolutePathBuf>,
    pub(super) active_permission_profile: Option<ActivePermissionProfile>,
}

impl PersistedResumeEnvironment {
    pub(super) fn restore_workspace_roots(self, config: &mut Config) -> Option<AbsolutePathBuf> {
        // Rollouts contain effective roots, including roots derived from the old
        // profile. Resolve today's profile first so changing its identity or
        // inheritance cannot carry those roots into the new profile as explicit
        // runtime roots. Legacy records without an identity retain their roots.
        // Identity is not a versioned definition: edits within the same id and
        // extends are not distinguishable from these older rollout records.
        if self.active_permission_profile.is_none()
            || self.active_permission_profile == config.permissions.active_permission_profile()
        {
            let mut workspace_roots = self.workspace_roots;
            let mut seen = HashSet::new();
            workspace_roots.retain(|root| seen.insert(root.clone()));
            config.workspace_roots = workspace_roots.clone();
            config.workspace_roots_explicit = true;
            config.permissions.set_workspace_roots(workspace_roots);
        }
        // The persisted cwd is independent of the permission profile. The caller
        // only supplies it when no current cwd or root override was requested.
        self.cwd
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct PersistedResumeSettings {
    pub(super) approval_policy: AskForApproval,
    pub(super) approvals_reviewer: Option<ApprovalsReviewer>,
    pub(super) active_permission_profile: Option<ActivePermissionProfile>,
    pub(super) runtime_cwd: Option<AbsolutePathBuf>,
    pub(super) runtime_workspace_roots: Option<Vec<AbsolutePathBuf>>,
}

pub(super) fn latest_persisted_resume_settings(
    history: &[RolloutItem],
) -> Option<PersistedResumeSettings> {
    // ThreadSettingsApplied snapshots do not carry the primary runtime cwd or
    // workspace roots. Fold both from the same latest turn context so a later
    // settings-only update cannot erase or mix the environment that produced
    // the persisted model request. `None` roots on TurnContextItem means the
    // effective list was empty, which remains distinct from no turn context.
    let runtime_environment = history.iter().rev().find_map(|item| match item {
        RolloutItem::TurnContext(turn_context) => Some((
            turn_context.cwd.clone(),
            turn_context.workspace_roots.clone().unwrap_or_default(),
        )),
        _ => None,
    });
    let runtime_cwd = runtime_environment.as_ref().map(|(cwd, _)| cwd.clone());
    let runtime_workspace_roots = runtime_environment.map(|(_, roots)| roots);

    history
        .iter()
        .enumerate()
        .rev()
        .find_map(|(index, item)| match item {
            RolloutItem::TurnContext(turn_context) => Some(PersistedResumeSettings {
                approval_policy: turn_context.approval_policy,
                approvals_reviewer: turn_context.approvals_reviewer.or_else(|| {
                    history[..index].iter().rev().find_map(|item| match item {
                        RolloutItem::TurnContext(turn_context) => turn_context.approvals_reviewer,
                        RolloutItem::EventMsg(EventMsg::ThreadSettingsApplied(event)) => {
                            Some(event.thread_settings.approvals_reviewer)
                        }
                        _ => None,
                    })
                }),
                active_permission_profile: turn_context.active_permission_profile.clone(),
                runtime_cwd: runtime_cwd.clone(),
                runtime_workspace_roots: runtime_workspace_roots.clone(),
            }),
            RolloutItem::EventMsg(EventMsg::ThreadSettingsApplied(event)) => {
                Some(PersistedResumeSettings {
                    approval_policy: event.thread_settings.approval_policy,
                    approvals_reviewer: Some(event.thread_settings.approvals_reviewer),
                    active_permission_profile: event
                        .thread_settings
                        .active_permission_profile
                        .clone(),
                    runtime_cwd: runtime_cwd.clone(),
                    runtime_workspace_roots: runtime_workspace_roots.clone(),
                })
            }
            _ => None,
        })
}

#[cfg(test)]
#[path = "persisted_resume_settings_tests.rs"]
mod tests;
