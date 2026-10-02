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
