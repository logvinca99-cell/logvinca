// 사용법: node render.js  → output/ 에 워터마크 PNG 생성 (투명 배경, 가로 약 500px)
const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const path = require('path');
const jobs = [
  ['#v1', 'lavendera_wm_1_badge', 2.2],
  ['#v2', 'lavendera_wm_2_capsule', 1.58],
  ['#v3', 'lavendera_wm_3_arch', 2.2],
  ['#v4', 'lavendera_wm_4_capsule_light', 1.58],
  ['#v5', 'lavendera_wm_5_badge_icon', 2.2],
];
(async () => {
  const browser = await chromium.launch();
  for (const [sel, out, scale] of jobs) {
    const page = await browser.newPage({ viewport: { width: 280, height: 100 }, deviceScaleFactor: scale });
    await page.goto('file://' + path.join(__dirname, 'src', 'watermark.html'));
    await page.evaluate(() => document.fonts.ready);
    const f = path.join(__dirname, 'output', out + '.png');
    await page.locator(sel).screenshot({ path: f, omitBackground: true });
    try { execFileSync('pngquant', ['--quality=80-95', '--force', '--ext', '.png', f]); } catch (e) {}
    console.log(out);
    await page.close();
  }
  await browser.close();
})();
