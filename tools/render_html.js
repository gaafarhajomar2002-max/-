// يحوّل صفحة HTML إلى صورة PNG بمقاس A4 (يُستخدم لتوليد الغلاف).
// node tools/render_html.js input.html output.png
const { chromium } = require('playwright');
const path = require('path');

(async () => {
  const [, , inp, out] = process.argv;
  const browser = await chromium.launch();
  const page = await browser.newPage({
    viewport: { width: 794, height: 1123 }, // A4 @96dpi
    deviceScaleFactor: 2.5,
  });
  await page.goto('file://' + path.resolve(inp));
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(300);
  const jpg = /\.jpe?g$/i.test(out);
  await page.screenshot({ path: out, fullPage: false, ...(jpg ? { type: 'jpeg', quality: 90 } : {}) });
  await browser.close();
})();
