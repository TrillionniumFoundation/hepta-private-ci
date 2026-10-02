import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { loadControlConsole } from "./readiness.mjs";

test.beforeEach(async ({ request }) => { await request.get("/__test__/reset"); });

for (const width of [1440, 390]) {
  test(`chat-first hierarchy is accessible at ${width}px without fictional messaging`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 960 });
    await loadControlConsole(page, { openConsole: false });
    await expect(page.getByRole("heading", { name: "Conversations", exact: true })).toBeVisible();
    await expect(page.locator("#chat-panel")).toBeVisible();
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
    await expect(page.locator("#chat-panel")).toBeVisible();
    await expect(page.locator("#tab-chat")).toHaveAttribute("aria-pressed", "true");
  });
}
