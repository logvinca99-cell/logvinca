// 사용법: node render.js  →  output/ 폴더에 PNG 생성 (860px 원본 + @2x 고해상도)
const { chromium } = require('playwright');
const path = require('path');
const pages = [
  { file: 'top.html',     out: 'onnuri_top',     width: 860 },
  { file: 'bottom.html',  out: 'onnuri_bottom',  width: 860 },
  { file: 'profile.html', out: 'onnuri_profile', width: 1000, height: 1000 },
  { file: 'banner.html',  out: 'onnuri_banner',  width: 1280, height: 480 },
  { file: 'guide.html',   out: 'onnuri_brand_guide', width: 1200 },
];
const only = process.argv.slice(2);
(async () => {
  const browser = await chromium.launch();
  for (const p of pages) {
    if (only.length && !only.some(o => p.file.startsWith(o))) continue;
    for (const scale of [1, 2]) {
      const page = await browser.newPage({ viewport: { width: p.width, height: p.height || 800 }, deviceScaleFactor: scale });
      await page.goto('file://' + path.join(__dirname, 'src', p.file));
      await page.evaluate(() => document.fonts.ready);
      const suffix = scale === 1 ? '' : '@2x';
      await page.screenshot({ path: path.join(__dirname, 'output', `${p.out}${suffix}.png`), ...(p.height ? { clip: { x: 0, y: 0, width: p.width, height: p.height } } : { fullPage: true }) });
      await page.close();
    }
    console.log('rendered', p.file);
  }
  await browser.close();
})();
