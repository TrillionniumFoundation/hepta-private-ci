import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { loadControlConsole } from "./readiness.mjs";

test.beforeEach(async ({ request }) => { await request.get("/__test__/reset"); });

for (const width of [1440, 390]) {
  test(`chat-first hierarchy is accessible at ${width}px without fictional messaging`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 960 });
    await loadControlConsole(page, { openConsole: false });
    await expect(page.getByRole("heading", { name: "Conversations", exact: true })).toBeVisible();
    if (width > 760) await expect(page.locator("#chat-panel")).toBeVisible();
    await expect(page.locator("#console-panel")).toBeHidden();
    await expect(page.locator("#send-message")).toBeDisabled();
    await expect(page.locator("#composer-hint")).toContainText("Nothing will be sent");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const result = await new AxeBuilder({ page }).analyze();
    expect(result.violations).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath(`chat-${width}.png`), fullPage: true });
    await page.locator("#tab-console").focus();
    await page.keyboard.press("Enter");
    await expect(page.locator("#console-panel")).toBeVisible();
    await expect(page.getByRole("button", { name: "Request start" })).toBeEnabled();
    await page.locator("#tab-chat").click();
    await page.locator("#tab-chat").click();
    if (width > 760) await expect(page.locator("#chat-panel")).toBeVisible();
    await expect(page.locator("#tab-chat")).toHaveAttribute("aria-pressed", "true");
  });
}

test("observed conversation navigation retains drafts and sends once with literal text", async ({ page, request }, testInfo) => {
  await request.get("/__test__/chat-enable");
  await loadControlConsole(page, { openConsole: false });
  await expect(page.locator("#chat-connection")).toHaveText("Messaging connected");
  await page.getByRole("button", { name: /Engineering/ }).click();
  await expect(page.locator("#message-draft")).toBeEnabled();
  await page.locator("#message-draft").fill("Draft engineering");
  await page.getByRole("button", { name: /Research/ }).click();
  await page.locator("#message-draft").fill("Draft research");
  await page.getByRole("button", { name: /Engineering/ }).click();
  await expect(page.locator("#message-draft")).toHaveValue("Draft engineering");
  await page.locator("#message-draft").fill("<img src=x onerror=alert(1)> is literal text");
  await page.evaluate(() => { document.querySelector("#send-message").click(); document.querySelector("#send-message").click(); });
  await expect(page.locator("#message-timeline")).toContainText("<img src=x onerror=alert(1)> is literal text");
  await expect(page.locator("#message-timeline img")).toHaveCount(0);
  expect((await (await request.get("/__test__/chat-state")).json()).sendCount).toBe(1);
  await expect(page.locator("#message-draft")).toHaveValue("");
  await page.screenshot({ path: testInfo.outputPath("chat-observed-conversation.png"), fullPage: true });
  await page.locator("#cancel-message").click();
  await expect(page.locator("#composer-hint")).toContainText("Cancellation requested");
});

test("lost send response reconciles the original identity without a second message", async ({ page, request }) => {
  await request.get("/__test__/chat-enable");
  await loadControlConsole(page, { openConsole: false });
  await page.getByRole("button", { name: /Engineering/ }).click();
  await page.locator("#message-draft").fill("Exactly once even if response disappears");
  let lost = false;
  await page.route("**/chat/request", async route => {
    const body = route.request().postDataJSON();
    if (body.command.type === "send" && !lost) { lost = true; await route.fetch(); await route.abort("failed"); }
    else await route.continue();
  });
  await page.locator("#send-message").click();
  await expect(page.locator("#reconcile-message")).toBeVisible();
  await expect(page.locator("#composer-hint")).toContainText("outcome unknown");
  await expect(page.locator("#send-message")).toBeDisabled();
  await page.locator("#reconcile-message").click();
  await expect(page.locator("#reconcile-message")).toBeHidden();
  await expect(page.locator("#message-draft")).toHaveValue("");
  expect((await (await request.get("/__test__/chat-state")).json()).sendCount).toBe(1);
});

test("foreign session chat response is rejected without reflecting its private content", async ({ page, request }) => {
  await request.get("/__test__/chat-enable");
  await page.route("**/chat/request", async route => {
    const response = await route.fetch();
    const body = await response.json();
    body.sessionId = "foreign-session";
    body.result = {type:"conversations",data:[{id:"secret",title:"Private other account",preview:"Do not show"}],nextCursor:null};
    await route.fulfill({response,json:body});
  });
  await loadControlConsole(page, { openConsole: false });
  await expect(page.locator("#chat-connection")).toHaveText("Conversations could not be loaded");
  await expect(page.locator("body")).not.toContainText("Private other account");
  await expect(page.locator("#send-message")).toBeDisabled();
});

test("chat remains usable when authenticated session has no console read permission", async ({ page, request }) => {
  await request.get("/__test__/chat-enable");
  let consoleReads = 0;
  await page.route("**/session/connect", async route => {
    const response = await route.fetch(); const body = await response.json(); body.permissions = ["hepta://ui.control/runtime.request"];
    await route.fulfill({response,json:body});
  });
  await page.route("**/api/ui-control/v1/view", async route => { consoleReads++; await route.fulfill({status:403,json:{errorCode:"PERMISSION_DENIED"}}); });
  await loadControlConsole(page, {openConsole:false});
  await expect(page.locator("#chat-connection")).toHaveText("Messaging connected");
  await page.getByRole("button", {name:/Engineering/}).click();
  await page.locator("#message-draft").fill("Chat has its own server authorization");
  await expect(page.locator("#send-message")).toBeEnabled();
  await page.locator("#tab-console").click();
  await expect(page.locator("#refresh-view")).toBeDisabled();
  await expect(page.locator("#error-status")).toContainText("UI_CONTROL_PERMISSION_DENIED");
  expect(consoleReads).toBe(0);
});

test("authentication denial starts neither chat nor console reads", async ({ page }) => {
  let chatRequests = 0;
  await page.route("**/session/connect", route => route.fulfill({status:401,json:{errorCode:"SESSION_EXPIRED"}}));
  await page.route("**/chat/request", async route => { chatRequests++; await route.abort(); });
  await page.goto("/");
  await expect(page.locator("#startup-error")).toContainText("authenticated workspace session is required");
  await expect(page.locator("#send-message")).toBeDisabled();
  await expect(page.locator("#chat-connection")).not.toHaveText("Messaging connected");
  expect(chatRequests).toBe(0);
});

test("bounded older pages pause latest polling and compact Back retains selection", async ({ page, request }, testInfo) => {
  await request.get("/__test__/chat-history");
  await page.setViewportSize({width:390,height:960});
  await loadControlConsole(page,{openConsole:false});
  await page.getByRole("button",{name:/Engineering/}).click();
  await expect(page.locator("#message-timeline")).toContainText("Historical message 120");
  await page.getByRole("button",{name:"Older messages",exact:true}).click();
  await expect(page.locator("#message-timeline")).toContainText("Historical message 70");
  await expect(page.locator("#message-timeline")).not.toContainText("Historical message 120");
  await expect(page.locator("#history-note")).toContainText("live updates paused");
  // Allow a full regular 2s refresh interval: an older page must remain intact.
  await page.waitForTimeout(2200);
  await expect(page.locator("#message-timeline")).not.toContainText("Historical message 120");
  await page.screenshot({path:testInfo.outputPath("compact-conversation-history.png"),fullPage:true});
  await page.getByRole("button",{name:"Back to latest",exact:true}).click();
  await expect(page.locator("#message-timeline")).toContainText("Historical message 120");
  await page.locator("#message-draft").fill("Keep this draft while browsing rooms");
  await page.locator("#chat-back").click();
  await page.getByRole("button",{name:/Engineering/}).click();
  await expect(page.locator("#message-draft")).toHaveValue("Keep this draft while browsing rooms");
});

test("server-created empty-title conversation has a useful honest display label", async ({page,request}) => {
  await request.get("/__test__/chat-enable");
  await loadControlConsole(page,{openConsole:false});
  await expect(page.locator("#new-conversation")).toBeEnabled();
  await page.locator("#new-conversation").click();
  await expect(page.locator("#conversation-title")).toHaveText("New conversation");
  await expect(page.locator('[data-room="chat-new"]')).toContainText("Open conversation");
  await page.locator("#message-draft").fill("First message\nWith a second line");
  await page.locator("#send-message").click();
  await expect(page.locator("#message-timeline")).toContainText("First message\nWith a second line");
});

test("switching conversations removes the old cancellation target before the next observation", async ({page,request}) => {
  await request.get("/__test__/chat-enable");
  await loadControlConsole(page,{openConsole:false});
  await page.getByRole("button",{name:/Engineering/}).click();
  await page.locator("#message-draft").fill("Observe active turn");
  await page.locator("#send-message").click();
  await expect(page.locator("#cancel-message")).toBeVisible();
  let release;
  const held = new Promise(resolve => {release=resolve;});
  await page.route("**/chat/request", async route => {
    const command=route.request().postDataJSON().command;
    if (command.type === "timeline" && command.threadId === "chat-two") await held;
    await route.continue();
  });
  try {
    await page.getByRole("button",{name:/Research/}).click();
    await expect(page.locator("#conversation-title")).toHaveText("Research");
    await expect(page.locator("#cancel-message")).toBeHidden();
  } finally { release(); }
});

test("invalid unsent draft creates no pending identity and can be corrected", async ({page,request}) => {
  await request.get("/__test__/chat-enable");
  await loadControlConsole(page,{openConsole:false});
  await page.getByRole("button",{name:/Engineering/}).click();
  await page.evaluate(() => {
    const draft=document.querySelector("#message-draft"); draft.value="invalid\0draft";
    draft.dispatchEvent(new Event("input",{bubbles:true}));
  });
  await page.locator("#send-message").click();
  await expect(page.locator("#composer-hint")).toContainText("Message cannot be sent");
  await expect(page.locator("#reconcile-message")).toBeHidden();
  await page.locator("#message-draft").fill("Corrected message");
  await page.locator("#send-message").click();
  await expect(page.locator("#message-timeline")).toContainText("Corrected message");
  expect((await (await request.get("/__test__/chat-state")).json()).sendCount).toBe(1);
});

test("offline draft remains editable and reconnect never sends automatically", async ({page,context,request}) => {
  await request.get("/__test__/chat-enable");
  await loadControlConsole(page,{openConsole:false});
  await page.getByRole("button",{name:/Engineering/}).click();
  await page.locator("#message-draft").fill("Draft before offline");
  try {
    await context.setOffline(true);
    await expect(page.locator("#chat-connection")).toHaveText("Messaging is offline");
    await expect(page.locator("#send-message")).toBeDisabled();
    await page.locator("#message-draft").fill("Draft edited while offline");
  } finally { await context.setOffline(false); }
  await expect(page.locator("#chat-connection")).toHaveText("Messaging connected");
  await expect(page.locator("#message-draft")).toHaveValue("Draft edited while offline");
  expect((await (await request.get("/__test__/chat-state")).json()).sendCount).toBe(0);
});
