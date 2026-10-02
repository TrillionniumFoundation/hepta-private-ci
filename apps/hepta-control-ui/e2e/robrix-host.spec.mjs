// Real browser/Makepad host acceptance. Canvas screenshots are evidence for
// visual review; this suite does not claim a DOM axe pass or live-chat authority.
import {test,expect} from '@playwright/test';
for(const viewport of [{width:1280,height:800},{width:640,height:800}]) {
 test(`Robrix host starts under strict CSP ${viewport.width}`,async({page},testInfo)=>{
  const errors=[];const violations=[];const uploads=[];
  page.on('pageerror',error=>errors.push(error.message));
  page.on('console',message=>{if(message.type()==='error') errors.push(message.text());});
  page.on('request',request=>{if(/\/(?:api\/crash|\$report_error)/.test(request.url())) uploads.push(request.url());});
  await page.addInitScript(()=>{window.__cspViolations=[];document.addEventListener('securitypolicyviolation',event=>window.__cspViolations.push(`${event.violatedDirective}: ${event.blockedURI}`));});
  await page.setViewportSize(viewport);
  await page.goto('/');
  await expect(page.locator('canvas')).toBeVisible();
  await expect(page.locator('.canvas_loader')).toBeHidden({timeout:60000});
  await page.waitForTimeout(1000);
  expect(await page.locator('canvas').evaluate(canvas=>canvas.width>0&&canvas.height>0)).toBe(true);
  expect(await page.locator('meta[name=viewport]').getAttribute('content')).not.toContain('user-scalable=no');
  await page.screenshot({path:testInfo.outputPath(`robrix-${viewport.width}.png`),fullPage:true});
  violations.push(...await page.evaluate(()=>window.__cspViolations));
  expect(errors).toEqual([]);expect(violations).toEqual([]);expect(uploads).toEqual([]);
  // Resize the actual shared renderer and capture the returned state. Deep
  // keyboard/IME/scroll acceptance remains separate until visible geometry is reviewed.
  await page.setViewportSize({width:viewport.width===1280?640:1280,height:800});
  await page.waitForTimeout(500);
  await page.screenshot({path:testInfo.outputPath('robrix-after-resize.png'),fullPage:true});
  expect(errors).toEqual([]);
  expect(await page.evaluate(()=>window.__cspViolations)).toEqual([]);
  expect(uploads).toEqual([]);
 });
}
