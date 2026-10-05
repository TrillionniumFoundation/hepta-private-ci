//! Product overview prepared by the refresh worker from authenticated data.

use eframe::egui;

use super::Locale;
use crate::error::ShellError;
use crate::fleet_observation::AgentLifecycle;
use crate::fleet_observation::FleetObservation;

#[derive(Debug)]
pub(super) enum RuntimeOverview {
    Fleet(FleetObservation),
    Legacy,
}

impl RuntimeOverview {
    pub fn prepare(value: &serde_json::Value) -> Result<Self, ShellError> {
        Ok(match FleetObservation::parse(value)? {
            Some(fleet) => Self::Fleet(fleet),
            None => Self::Legacy,
        })
    }

    #[cfg(test)]
    pub fn render(&self, ui: &mut egui::Ui, locale: Locale) {
        self.render_controls(ui, locale, false);
    }

    pub fn render_controls(
        &self,
        ui: &mut egui::Ui,
        locale: Locale,
        enabled: bool,
    ) -> Option<(String, crate::fleet_lifecycle::FleetLifecycleOperation)> {
        let mut action = None;
        match self {
            Self::Legacy => {
                ui.label(locale.text("Connected to the legacy runtime", "已连接旧版运行时"));
                ui.label(locale.text(
                    "Agent information is unavailable from this source.",
                    "此数据源未提供代理信息。",
                ));
            }
            Self::Fleet(fleet) => {
                ui.label(
                    egui::RichText::new(if fleet.health.ready {
                        locale.text("Service online", "服务在线")
                    } else {
                        locale.text("Service is recovering", "服务正在恢复")
                    })
                    .strong(),
                );
                let healthy = fleet.agents.iter().filter(|agent| agent.healthy).count();
                let attention = fleet
                    .agents
                    .iter()
                    .filter(|agent| {
                        agent.lifecycle == AgentLifecycle::Failed || agent.matrix.degraded
                    })
                    .count();
                ui.horizontal_wrapped(|ui| {
                    ui.label(format!(
                        "{}: {}",
                        locale.text("Agents", "代理"),
                        fleet.agents.len()
                    ));
                    ui.label(format!("{}: {healthy}", locale.text("Healthy", "健康")));
                    ui.label(format!(
                        "{}: {attention}",
                        locale.text("Need attention", "需要关注")
                    ));
                });
                if fleet.health.observed_faults != 0 {
                    ui.label(format!(
                        "{}: {}",
                        locale.text("Recorded faults", "已记录故障"),
                        fleet.health.observed_faults
                    ));
                }
                ui.separator();
                ui.heading(locale.text("Agents", "代理"));
                if !enabled {
                    ui.label(locale.text(
                        "Agent control is unavailable or waiting for a previous action.",
                        "代理控制尚未启用，或正在等待上次操作。",
                    ));
                }
                ui.label(locale.text("Agent version updates and module changes are not available in this desktop yet.", "此桌面暂不支持代理版本升级和模块变更。"));
                if fleet.agents.is_empty() {
                    ui.label(locale.text("No agents are registered yet.", "尚未登记代理。"));
                }
                for (index, agent) in fleet.agents.iter().enumerate() {
                    ui.group(|ui| {
                        ui.horizontal_wrapped(|ui| {
                            ui.strong(format!(
                                "{} {} · {}",
                                locale.text("Agent", "代理"),
                                index + 1,
                                &agent.agent_id[..8]
                            ))
                            .on_hover_text(format!(
                                "{} · {} {}",
                                agent.agent_id,
                                locale.text("State revision", "状态修订"),
                                agent.lifecycle_generation
                            ));
                            ui.label(agent_label(agent.lifecycle, agent.healthy, locale));
                        });
                        if let Some(release) = &agent.current_release {
                            ui.label(format!("{}: {release}", locale.text("Version", "版本")));
                        }
                        if agent.lifecycle == AgentLifecycle::Failed {
                            ui.label(locale.text(
                                "Recovery requires attention. See the current diagnostics below.",
                                "恢复需要关注，请查看下方当前诊断信息。",
                            ));
                        }
                        if agent.matrix.configured {
                            ui.label(if agent.matrix.healthy {
                                locale.text("Companion service healthy", "附属服务健康")
                            } else {
                                locale.text("Companion service is recovering", "附属服务正在恢复")
                            });
                        }
                        ui.horizontal(|ui| {
                            use crate::fleet_lifecycle::FleetLifecycleOperation::Restart;
                            use crate::fleet_lifecycle::FleetLifecycleOperation::Start;
                            use crate::fleet_lifecycle::FleetLifecycleOperation::Stop;
                            for (operation, label, allowed) in [
                                (
                                    Start,
                                    locale.text("Start", "启动"),
                                    !agent.active && agent.current_release.is_some(),
                                ),
                                (Stop, locale.text("Stop", "停止"), agent.active),
                                (
                                    Restart,
                                    locale.text("Restart", "重启"),
                                    agent.active && agent.lifecycle == AgentLifecycle::Running,
                                ),
                            ] {
                                if ui
                                    .add_enabled(enabled && allowed, egui::Button::new(label))
                                    .clicked()
                                {
                                    action = Some((agent.agent_id.clone(), operation));
                                }
                            }
                        });
                        if let Some(error) = &agent.matrix.last_error {
                            ui.label(error);
                        }
                    });
                }
            }
        }
        action
    }
}

fn agent_label(lifecycle: AgentLifecycle, healthy: bool, locale: Locale) -> &'static str {
    match lifecycle {
        AgentLifecycle::Stopped => locale.text("Stopped", "已停止"),
        AgentLifecycle::Starting => locale.text("Starting", "正在启动"),
        AgentLifecycle::Running if healthy => locale.text("Running · healthy", "运行中 · 健康"),
        AgentLifecycle::Running => {
            locale.text("Running · checking health", "运行中 · 正在检查健康状态")
        }
        AgentLifecycle::Draining => locale.text("Stopping safely", "正在安全停止"),
        AgentLifecycle::Failed => locale.text("Recovery blocked", "恢复受阻"),
    }
}

#[cfg(test)]
#[path = "fleet_overview_tests.rs"]
mod tests;
