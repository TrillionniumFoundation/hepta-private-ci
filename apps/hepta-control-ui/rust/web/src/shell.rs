//! Rust-owned semantic app shell. All dynamic content uses text nodes.
use crate::dom::{dom_error, element};
use hepta_control_core::{
    chat::{AppTab, ChatState},
    error::ControlError,
};
use web_sys::Document;

pub fn mount(document: &Document) -> Result<(), ControlError> {
    document.set_title("Hepta — Conversations");
    document
        .body()
        .ok_or_else(ControlError::invalid)?
        .set_inner_html(SHELL);
    Ok(())
}

pub fn render(document: &Document, chat: &ChatState) -> Result<(), ControlError> {
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
    Ok(())
}

const SHELL: &str = r###"<a class="skip-link" href="#main-content">Skip to conversation</a>
<div class="chat-app">
<nav class="app-rail" aria-label="Workspace"><span class="brand-mark" aria-label="Hepta">H</span><button id="tab-chat" aria-controls="chat-panel" aria-pressed="true" title="Conversations">Chat</button><button id="tab-console" aria-controls="console-panel" aria-pressed="false" title="Runtime console">Console</button><span class="rail-caption">HEPTA</span></nav>
<aside class="rooms-pane" aria-label="Conversations"><header class="rooms-header"><p class="eyebrow">YOUR WORKSPACE</p><h1>Conversations</h1></header><label class="search-label" for="room-filter">Find a conversation</label><input id="room-filter" type="search" placeholder="Search conversations" autocomplete="off"><div id="conversation-list" class="conversation-list" role="list"><p class="rooms-empty">No conversations loaded</p></div><footer class="workspace-identity"><span class="identity-avatar" aria-hidden="true">H</span><div><strong>Hepta workspace</strong><span id="chat-identity">No messaging session</span></div></footer></aside>
<main id="main-content" tabindex="-1"><div id="chat-panel"><header class="conversation-header"><div><p class="eyebrow">CONVERSATION</p><h2 id="conversation-title">A place to think together</h2></div><span id="chat-connection" class="connection-label">Messaging is not connected</span></header><div id="message-timeline" class="message-timeline" role="log" aria-label="Messages" aria-live="polite"><div class="conversation-empty"><div class="empty-orbit" aria-hidden="true">H</div><p class="eyebrow">HEPTA / CONVERSATIONS</p><h2>Your next idea starts here</h2><p id="chat-empty-description">Select a conversation when messaging becomes available. Runtime tools are in the Console tab.</p></div></div><div class="composer"><label for="message-draft">Message</label><textarea id="message-draft" placeholder="Write a message…" maxlength="4096" disabled aria-describedby="composer-hint"></textarea><div class="composer-footer"><p id="composer-hint">Messaging transport is unavailable. Nothing will be sent.</p><button id="send-message" type="button" disabled>Send message <span aria-hidden="true">↑</span></button></div></div></div>
<div id="console-panel" hidden><header class="console-header"><p class="eyebrow">WORKSPACE / CONSOLE</p><h2>Runtime console</h2><p>Authenticated runtime observations and confirmation-bound requests.</p></header>      <section aria-labelledby="connection-heading">
        <h2 id="connection-heading"><span class="section-index" aria-hidden="true">01</span> Connection</h2>
        <dl class="summary-grid">
          <div><dt>Status</dt><dd id="connection-state">Disconnected</dd></div>
          <div><dt>Session</dt><dd id="session-state">—</dd></div>
          <div><dt>Operator</dt><dd id="identity-state">—</dd></div>
          <div><dt>Generation</dt><dd id="generation-state">—</dd></div>
          <div><dt>Revision</dt><dd id="revision-state">—</dd></div>
        </dl>
        <p id="stale-banner" class="warning" role="alert" hidden></p>
        <p id="error-status" class="error" role="alert" hidden></p>
        <p id="live-status" class="visually-hidden" role="status" aria-live="polite"></p>
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
</div></main></div>    <dialog id="confirm-operation" aria-labelledby="confirm-title" aria-describedby="confirm-summary">
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
