//! Native adapter for the shared, authority-free conversation projection.
use super::*;
use chat_model::ChatAvailability;
use chat_model::design;

impl chat_app::ChatShell {
    fn chat_status_text(&self) -> &'static str {
        match self.chat.availability {
            ChatAvailability::Unavailable => self
                .locale
                .text("Messaging is not connected", "消息服务尚未连接"),
            ChatAvailability::Loading => {
                self.locale.text("Loading conversations…", "正在加载对话…")
            }
            ChatAvailability::Ready => self.locale.text("Messaging connected", "消息服务已连接"),
            ChatAvailability::Offline => self.locale.text("Messaging is offline", "消息服务离线"),
            ChatAvailability::Failed => self
                .locale
                .text("Conversations could not be loaded", "无法加载对话"),
        }
    }

    pub(super) fn chat_view(&mut self, ui: &mut egui::Ui) {
        let compact = ui.available_width() < design::COMPACT_WIDTH;
        if self.chat_bridge.error.is_some() {
            egui::Panel::top("chat-error").show(ui, |ui| {
                egui::ScrollArea::vertical()
                    .max_height(56.0)
                    .show(ui, |ui| {
                        if let Some(error) = &self.chat_bridge.error {
                            ui.label(egui::RichText::new(error).color(theme::ERROR));
                        }
                    });
                if matches!(
                    self.chat.availability,
                    ChatAvailability::Offline | ChatAvailability::Failed
                ) && ui
                    .button(self.locale.text("Reconnect", "重新连接"))
                    .clicked()
                {
                    self.retry_chat();
                }
            });
        }
        // A narrow viewport presents one navigable pane rather than squeezing
        // a timeline and room list into unreadable columns.
        if !compact {
            egui::Panel::left("chat-conversations")
                .resizable(true)
                .default_size(design::ROOMS_WIDTH)
                .size_range(220.0..=360.0)
                .frame(theme::card())
                .show(ui, |ui| self.conversation_list(ui));
        }
        egui::CentralPanel::default()
            .frame(egui::Frame::new().fill(theme::BACKGROUND).inner_margin(20))
            .show(ui, |ui| {
                if compact && (self.chat.selected.is_none() || self.chat_show_list) {
                    self.conversation_list(ui);
                } else {
                    if compact
                        && ui
                            .button(self.locale.text("Back to conversations", "返回对话列表"))
                            .clicked()
                    {
                        self.chat_show_list = true;
                    }
                    self.conversation_timeline(ui);
                }
            });
    }

    fn conversation_list(&mut self, ui: &mut egui::Ui) {
        ui.heading(self.locale.text("Conversations", "对话"));
        ui.label(
            egui::RichText::new(
                self.locale
                    .text("A place to think together", "一起思考的空间"),
            )
            .color(theme::MUTED),
        );
        ui.add_space(12.0);
        ui.horizontal(|ui| {
            if ui
                .add_enabled(
                    self.chat_transport_ready(),
                    egui::Button::new(self.locale.text("New conversation", "新建对话")),
                )
                .clicked()
            {
                self.create_chat();
            }
            if ui
                .add_enabled(
                    self.chat_transport_ready(),
                    egui::Button::new(self.locale.text("Refresh", "刷新")),
                )
                .on_hover_text(self.locale.text("Refresh conversations", "刷新对话"))
                .clicked()
            {
                self.refresh_chats(None);
            }
        });
        if self.chat_bridge.list_cursor.is_some() {
            if ui
                .add_enabled(
                    self.chat_transport_ready() && self.chat.conversations.len() < 200,
                    egui::Button::new(self.locale.text("More conversations", "更多对话")),
                )
                .clicked()
            {
                self.refresh_chats(self.chat_bridge.list_cursor.clone());
            }
            if self.chat.conversations.len() >= 200 {
                ui.label(self.locale.text(
                    "Showing 200 conversations. Refresh to return to the newest page.",
                    "已显示 200 个对话。刷新可返回最新页面。",
                ));
            }
        }
        let label = ui.label(self.locale.text("Search conversations", "搜索对话"));
        ui.add(
            egui::TextEdit::singleline(&mut self.chat.filter)
                .id(egui::Id::new("chat-search"))
                .desired_width(f32::INFINITY)
                .char_limit(256),
        )
        .labelled_by(label.id);
        ui.add_space(16.0);
        let rooms: Vec<_> = self.chat.visible_conversations().cloned().collect();
        if rooms.is_empty() {
            ui.label(
                self.locale
                    .text("No conversations to show", "暂无可显示的对话"),
            );
            ui.label(egui::RichText::new(self.chat_status_text()).color(theme::MUTED));
            if self.chat.availability == ChatAvailability::Unavailable {
                ui.label(self.locale.text("Messaging needs an operator-provided chat configuration. Start Hepta with --chat-config and its absolute path.", "消息服务需要操作员提供聊天配置。启动 Hepta 时请指定 --chat-config 和配置的绝对路径。"));
            }
        }
        egui::ScrollArea::vertical()
            .id_salt("chat-room-list")
            .show(ui, |ui| {
                for room in rooms {
                    let title = if self.locale == Locale::Chinese && room.title.trim().is_empty() {
                        "新建对话"
                    } else {
                        room.display_title()
                    };
                    let preview =
                        if self.locale == Locale::Chinese && room.preview.trim().is_empty() {
                            "打开对话"
                        } else {
                            room.display_preview()
                        };
                    let label = if room.unread > 0 {
                        format!("{title} ({})\n{preview}", room.unread)
                    } else {
                        format!("{title}\n{preview}")
                    };
                    ui.horizontal(|ui| {
                        theme::identity_mark(ui, &room.title);
                        if ui
                            .add(
                                egui::Button::new(label)
                                    .selected(
                                        self.chat.selected.as_deref() == Some(room.id.as_str()),
                                    )
                                    .min_size(egui::vec2(
                                        ui.available_width(),
                                        design::CONTROL_HEIGHT,
                                    )),
                            )
                            .clicked()
                        {
                            self.select_chat(&room.id);
                        }
                    });
                }
            });
    }

    fn conversation_timeline(&mut self, ui: &mut egui::Ui) {
        egui::Panel::bottom("chat-composer-panel")
            .frame(egui::Frame::new())
            .show(ui, |ui| self.chat_composer(ui));
        let title = self
            .chat
            .conversations
            .iter()
            .find(|room| Some(&room.id) == self.chat.selected.as_ref())
            .map(|room| {
                if self.locale == Locale::Chinese && room.title.trim().is_empty() {
                    "新建对话"
                } else {
                    room.display_title()
                }
            })
            .unwrap_or(if self.chat.selected.is_some() {
                self.locale.text("New conversation", "新建对话")
            } else {
                self.locale.text("Your next conversation", "开启下一段对话")
            });
        ui.heading(title);
        ui.label(egui::RichText::new(self.chat_status_text()).color(theme::MUTED));
        if self.chat.page.cursor.is_some() || self.chat.page.next_cursor.is_some() {
            ui.horizontal_wrapped(|ui| {
                if self.chat.page.next_cursor.is_some()
                    && ui
                        .add_enabled(
                            self.chat_transport_ready() && !self.chat.page.loading,
                            egui::Button::new(self.locale.text("Older messages", "更早的消息")),
                        )
                        .clicked()
                {
                    self.timeline_page(self.chat.page.next_cursor.clone());
                }
                if self.chat.page.cursor.is_some()
                    && ui
                        .add_enabled(
                            self.chat_transport_ready() && !self.chat.page.loading,
                            egui::Button::new(self.locale.text("Back to latest", "返回最新消息")),
                        )
                        .clicked()
                {
                    self.timeline_page(None);
                }
                if self.chat.page.loading && ui.available_width() >= 24.0 {
                    ui.spinner();
                }
            });
        }
        ui.separator();
        // Reserve composer space so long timelines cannot push it off-screen.
        let timeline_height = ui.available_height().max(0.0);
        egui::ScrollArea::vertical()
            .id_salt(("chat-timeline", &self.chat.selected, &self.chat.page.cursor))
            .max_height(timeline_height)
            .min_scrolled_height(timeline_height)
            .stick_to_bottom(true)
            .show(ui, |ui| {
                ui.set_min_width(ui.available_width());
                if self.chat.messages.is_empty() && self.chat.page.loading {
                    ui.spinner();
                    ui.label(self.locale.text("Loading messages…", "正在加载消息…"));
                }
                if self.chat.messages.is_empty() && !self.chat.page.loading {
                    ui.add_space(24.0);
                    theme::brand_mark(ui);
                    ui.heading(self.locale.text("Space for your ideas", "让想法自由生长"));
                    ui.label(if self.chat.selected.is_some() {
                        self.locale.text("No messages in this conversation yet.", "此对话还没有消息。")
                    } else {
                        self.locale.text("Choose a conversation to read its messages.", "选择对话以查看消息。")
                    });
                    if self.chat.availability == ChatAvailability::Unavailable {
                        ui.label(self.locale.text("This runtime does not provide an authenticated messaging connection yet.", "此运行时尚未提供已验证的消息连接。"));
                    }
                }
                for message in &self.chat.messages {
                    theme::card().corner_radius(design::BUBBLE_RADIUS).show(ui, |ui| {
                        ui.horizontal_wrapped(|ui| {
                            theme::identity_mark(ui, &message.sender);
                            ui.strong(&message.sender);
                            ui.label(egui::RichText::new(&message.timestamp).small().color(theme::MUTED));
                        });
                        ui.label(&message.body);
                    });
                    ui.add_space(design::MESSAGE_SPACING);
                }
            });
    }

    fn chat_composer(&mut self, ui: &mut egui::Ui) {
        ui.separator();
        let label = ui.label(self.locale.text("Message", "消息"));
        egui::Frame::new()
            .fill(theme::SURFACE)
            .stroke(egui::Stroke::new(1.0, theme::BORDER))
            .corner_radius(design::COMPOSER_RADIUS)
            .inner_margin(10)
            .show(ui, |ui| {
                ui.add(
                    egui::TextEdit::multiline(&mut self.chat.draft)
                        .id(egui::Id::new("chat-composer"))
                        .frame(egui::Frame::NONE)
                        .desired_width(f32::INFINITY)
                        .desired_rows(2)
                        .char_limit(4096)
                        .hint_text(self.locale.text("Write a message…", "输入消息…")),
                )
                .labelled_by(label.id);
            });
        ui.horizontal_wrapped(|ui| {
            ui.label(
                egui::RichText::new(self.locale.text(
                    "Draft stays here until you send",
                    "点击发送前，草稿仅保留在此处",
                ))
                .small()
                .color(theme::MUTED),
            );
            if ui
                .add_enabled(
                    self.chat_transport_ready() && self.chat.can_send(),
                    egui::Button::new(self.locale.text("Send", "发送")),
                )
                .on_disabled_hover_text(self.locale.text(
                    "Select a connected conversation and enter a message",
                    "请选择已连接的对话并输入消息",
                ))
                .clicked()
            {
                self.send_chat();
            }
            if self.chat_bridge.active_turn.is_some()
                && ui
                    .add_enabled(
                        self.chat_transport_ready(),
                        egui::Button::new(self.locale.text("Stop reply", "停止回复")),
                    )
                    .clicked()
            {
                self.stop_chat();
            }
            if self.chat.sending {
                ui.spinner();
                ui.label(
                    self.locale
                        .text("Awaiting server confirmation", "等待服务器确认"),
                );
            }
        });
    }
}
