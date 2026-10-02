//! Rust-owned semantic app shell. All dynamic content uses text nodes.
use crate::dom::{dom_error, element};
use hepta_control_core::chat::ChatAvailability;
use hepta_control_core::{
    chat::{AppTab, ChatState},
    error::ControlError,
};
use wasm_bindgen::JsCast;
use web_sys::{Document, HtmlButtonElement, HtmlTextAreaElement};

pub fn mount(document: &Document) -> Result<(), ControlError> {
    document.set_title("Hepta — Conversations");
    document
        .body()
        .ok_or_else(ControlError::invalid)?
        .set_inner_html(SHELL);
    Ok(())
}

pub fn render(
    document: &Document,
    chat: &ChatState,
    previous: Option<&ChatState>,
    note: &str,
    show_list: bool,
) -> Result<(), ControlError> {
    let root = element(document, "chat-app")?;
    root.set_attribute(
        "data-list",
        if show_list || chat.selected.is_none() {
            "true"
        } else {
            "false"
        },
    )
    .map_err(dom_error)?;
    root.set_attribute(
        "data-console",
        if chat.tab == AppTab::Console {
            "true"
        } else {
            "false"
        },
    )
    .map_err(dom_error)?;
    for (tab, button, panel) in [
        (AppTab::Chat, "tab-chat", "chat-panel"),
        (AppTab::Console, "tab-console", "console-panel"),
    ] {
        let active = chat.tab == tab;
        element(document, button)?
            .set_attribute("aria-pressed", if active { "true" } else { "false" })
            .map_err(dom_error)?;
        let panel = element(document, panel)?;
        if active {
            panel.remove_attribute("hidden").map_err(dom_error)?;
        } else {
            panel.set_attribute("hidden", "").map_err(dom_error)?;
        }
    }
    element(document, "chat-connection")?.set_text_content(Some(chat.availability.label()));
    element(document, "chat-identity")?.set_text_content(Some(
        if chat.availability == ChatAvailability::Ready {
            "Authenticated messaging session"
        } else {
            chat.availability.label()
        },
    ));
    let title = chat
        .conversations
        .iter()
        .find(|r| Some(&r.id) == chat.selected.as_ref())
        .map(|r| r.title.as_str())
        .unwrap_or("A place to think together");
    element(document, "conversation-title")?.set_text_content(Some(title));
    let draft: HtmlTextAreaElement = crate::dom::cast(element(document, "message-draft")?)?;
    if draft.value() != chat.draft {
        draft.set_value(&chat.draft);
    }
    draft.set_disabled(chat.availability != ChatAvailability::Ready || chat.selected.is_none());
    let send: HtmlButtonElement = crate::dom::cast(element(document, "send-message")?)?;
    send.set_disabled(!chat.can_send());
    for id in ["chat-refresh", "new-conversation"] {
        let button: HtmlButtonElement = crate::dom::cast(element(document, id)?)?;
        button.set_disabled(
            chat.sending
                || (id == "new-conversation" && chat.availability != ChatAvailability::Ready),
        );
    }
    if !note.is_empty() {
        element(document, "composer-hint")?.set_text_content(Some(note));
    }
    if previous.is_none_or(|p| {
        p.conversations != chat.conversations
            || p.filter != chat.filter
            || p.selected != chat.selected
    }) {
        let list = element(document, "conversation-list")?;
        list.set_text_content(None);
        let mut count = 0;
        for room in chat.visible_conversations() {
            count += 1;
            list.set_attribute("role", "list").map_err(dom_error)?;
            let item = document.create_element("div").map_err(dom_error)?;
            item.set_attribute("role", "listitem").map_err(dom_error)?;
            let button = document.create_element("button").map_err(dom_error)?;
            button.set_class_name("room-item");
            button.set_attribute("type", "button").map_err(dom_error)?;
            button
                .set_attribute("data-room", &room.id)
                .map_err(dom_error)?;
            button
                .set_attribute(
                    "aria-current",
                    if Some(&room.id) == chat.selected.as_ref() {
                        "true"
                    } else {
                        "false"
                    },
                )
                .map_err(dom_error)?;
            for (tag, text) in [("strong", &room.title), ("span", &room.preview)] {
                let label = document.create_element(tag).map_err(dom_error)?;
                label.set_text_content(Some(text));
                button.append_child(&label).map_err(dom_error)?;
            }
            item.append_child(&button).map_err(dom_error)?;
            list.append_child(&item).map_err(dom_error)?;
        }
        if count == 0 {
            let empty = document.create_element("p").map_err(dom_error)?;
            empty.set_class_name("rooms-empty");
            list.remove_attribute("role").map_err(dom_error)?;
            empty.set_text_content(Some(if chat.filter.is_empty() {
                "No conversations loaded"
            } else {
                "No matching conversations"
            }));
            list.append_child(&empty).map_err(dom_error)?;
        }
    }
    if previous.is_some_and(|p| p.messages != chat.messages || p.selected != chat.selected) {
        let timeline = element(document, "message-timeline")?;
        let scroll = timeline
            .dyn_ref::<web_sys::HtmlElement>()
            .map(|e| e.scroll_top())
            .unwrap_or(0);
        timeline.set_text_content(None);
        if chat.messages.is_empty() {
            let empty = document.create_element("p").map_err(dom_error)?;
            empty.set_class_name("conversation-empty");
            empty.set_text_content(Some("No messages observed in this conversation yet."));
            timeline.append_child(&empty).map_err(dom_error)?;
        }
        for message in &chat.messages {
            let row = document.create_element("article").map_err(dom_error)?;
            row.set_class_name("message");
            for (tag, text) in [("strong", &message.sender), ("p", &message.body)] {
                let node = document.create_element(tag).map_err(dom_error)?;
                node.set_text_content(Some(text));
                row.append_child(&node).map_err(dom_error)?;
            }
            timeline.append_child(&row).map_err(dom_error)?;
        }
        if let Some(timeline) = timeline.dyn_ref::<web_sys::HtmlElement>() {
            timeline.set_scroll_top(scroll);
        }
    }
    Ok(())
}

const SHELL: &str = r###"<a class="skip-link" href="#chat-app">Skip to conversation</a>
<p id="startup-error" class="error" role="alert" hidden></p>
<p id="live-status" class="visually-hidden" role="status" aria-live="polite"></p>
<main id="chat-app" class="chat-app" tabindex="-1" aria-label="Hepta workspace">
<nav class="app-rail" aria-label="Workspace"><span class="brand-mark" role="img" aria-label="Hepta">H</span><button id="tab-chat" aria-controls="chat-panel" aria-pressed="true" title="Conversations">Chat</button><button id="tab-console" aria-controls="console-panel" aria-pressed="false" title="Runtime console">Console</button><span class="rail-caption">HEPTA</span></nav>
<aside class="rooms-pane" aria-label="Conversations"><header class="rooms-header"><p class="eyebrow">YOUR WORKSPACE</p><h1>Conversations</h1></header><label class="search-label" for="room-filter">Find a conversation</label><input id="room-filter" type="search" placeholder="Search conversations" autocomplete="off"><div class="chat-list-actions"><button id="new-conversation" type="button" disabled>New conversation</button><button id="chat-refresh" type="button">Refresh</button></div><div id="conversation-list" class="conversation-list"><p class="rooms-empty">No conversations loaded</p></div><footer class="workspace-identity"><span class="identity-avatar" aria-hidden="true">H</span><div><strong>Hepta workspace</strong><span id="chat-identity">No messaging session</span></div></footer></aside>
<div id="main-content" tabindex="-1"><div id="chat-panel"><header class="conversation-header"><button id="chat-back" type="button">Back</button><div><p class="eyebrow">CONVERSATION</p><h2 id="conversation-title">A place to think together</h2></div><span id="chat-connection" class="connection-label">Messaging is not connected</span></header><div id="message-timeline" class="message-timeline" role="log" aria-label="Messages" aria-live="polite"><div class="conversation-empty"><div class="empty-orbit" aria-hidden="true">H</div><p class="eyebrow">HEPTA / CONVERSATIONS</p><h2>Your next idea starts here</h2><p id="chat-empty-description">Select a conversation when messaging becomes available. Runtime tools are in the Console tab.</p></div></div><div class="composer"><label for="message-draft">Message</label><textarea id="message-draft" placeholder="Write a message…" maxlength="4096" disabled aria-describedby="composer-hint"></textarea><div class="composer-footer"><p id="composer-hint">Messaging transport is unavailable. Nothing will be sent.</p><button id="reconcile-message" type="button" disabled hidden>Check send</button><button id="cancel-message" type="button" disabled hidden>Stop reply</button><button id="send-message" type="button" disabled>Send message <span aria-hidden="true">↑</span></button></div></div></div>
<div id="console-panel" hidden><header class="console-header"><p class="eyebrow">WORKSPACE / CONSOLE</p><h2>Runtime console</h2><p>Authenticated runtime observations and confirmation-bound requests.</p></header>      <section aria-labelledby="connection-heading">
        <h2 id="connection-heading"><span class="section-index" aria-hidden="true">01</span> Connection</h2>
        <dl class="summary-grid">
          <div><dt>Status</dt><dd id="connection-state">Disconnected</dd></div>
          <div><dt>Session</dt><dd id="session-state">—</dd></div>
          <div><dt>Operator</dt><dd id="identity-state">—</dd></div>
          <div><dt>Generation</dt><dd id="generation-state">—</dd></div>
          <div><dt>Revision</dt><dd id="revision-state">—</dd></div>
        </dl>
        <p id="error-status" class="error" role="alert" hidden></p>
        <p id="stale-banner" class="warning" role="alert" hidden></p>
        
        
        <button id="refresh-view" type="button">Refresh runtime view</button>
      </section>

      <section aria-labelledby="runtime-heading">
        <h2 id="runtime-heading"><span class="section-index" aria-hidden="true">02</span> Runtime modules</h2>
        <div class="table-scroll" tabindex="0" aria-label="Scrollable runtime module table">
          <table>
            <thead>
              <tr><th scope="col">Module</th><th scope="col">Status</th><th scope="col">Revision</th><th scope="col">Semantic digest</th></tr>
            </thead>
            <tbody id="modules-body"></tbody>
          </table>
        </div>
      </section>

      <section aria-labelledby="operation-heading">
        <h2 id="operation-heading"><span class="section-index" aria-hidden="true">03</span> Control request</h2>
        <p>Every request is bound to the displayed generation, revision, semantic digest, operation ID, and audit trace.</p>
        <div class="field">
          <label for="target-id">Target module</label>
          <select id="target-id"></select>
        </div>
        <div class="field">
          <label for="operation-reason">Reason</label>
          <textarea id="operation-reason" maxlength="1024" required></textarea>
        </div>
        <div class="button-row">
          <button id="request-start" type="button" disabled>Request start</button>
          <button id="request-reconcile" type="button" disabled>Request reconcile</button>
          <button id="request-stop" class="danger" type="button" disabled>Request stop</button>
        </div>
      </section>

      <section aria-labelledby="pending-heading">
        <h2 id="pending-heading"><span class="section-index" aria-hidden="true">04</span> Pending and indeterminate operations</h2>
        <ul id="pending-list"></ul>
      </section>

      <section aria-labelledby="completed-heading">
        <h2 id="completed-heading"><span class="section-index" aria-hidden="true">05</span> Recent terminal operations</h2>
        <p>Terminal facts shown here come from authenticated backend observations, not local acknowledgements.</p>
        <ul id="completed-list"></ul>
      </section>
</div></div></main>    <dialog id="confirm-operation" aria-labelledby="confirm-title" aria-describedby="confirm-summary">
      <form method="dialog">
        <h2 id="confirm-title">Confirm control request</h2>
        <p id="confirm-summary"></p>
        <div class="button-row">
          <button id="confirm-cancel" type="button">Cancel</button>
          <button id="confirm-submit" class="danger" type="button">Submit request</button>
        </div>
      </form>
    </dialog>

"###;
