// 라벤더라 스토어 꾸미기 렌더. 사용법: node render_store.js            → output/ 에 전부 생성
//        node render.js bottom     → 특정 파일만
//
// 출력 규격 (스토어 업로드 프로그램 권장값 기준)
//  - 상단·하단: 가로 1000px, 장당 세로 2000px 이하 PNG. 길면 섹션 경계에서 자동 분할
//  - 워터마크: 가로 약 500px, 투명 배경 PNG
// pngquant 가 설치되어 있으면 자동으로 용량을 줄입니다 (없으면 생략).
const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const OUT = path.join(__dirname, 'output');
const MAX_H = 2000;           // 장당 최대 세로(px, 출력 기준)
const SCALE = 1000 / 860;     // 860px 디자인 → 가로 1000px 출력

const jobs = [
  { file: 'store_profile.html', out: 'store_profile_1300', width: 1000, height: 1000, scale: 1.3 },
  { file: 'store_logo.html', out: 'store_logo_src', width: 640, scale: 4, element: '#lg', transparent: true },
  { file: 'store_promo1.html', out: 'store_promo1_pc_1920x400', width: 1920, height: 400, scale: 1, vars: { __SIZE__: 'pc' } },
  { file: 'store_promo1.html', out: 'store_promo1_mobile_750x600', width: 750, height: 600, scale: 1, vars: { __SIZE__: 'm' } },
  { file: 'store_promo2.html', out: 'store_promo2_pc_1920x400', width: 1920, height: 400, scale: 1, vars: { __SIZE__: 'pc' } },
  { file: 'store_promo2.html', out: 'store_promo2_mobile_750x600', width: 750, height: 600, scale: 1, vars: { __SIZE__: 'm' } },
  { file: 'store_promo3.html', out: 'store_promo3_pc_1920x400', width: 1920, height: 400, scale: 1, vars: { __SIZE__: 'pc' } },
  { file: 'store_promo3.html', out: 'store_promo3_mobile_750x600', width: 750, height: 600, scale: 1, vars: { __SIZE__: 'm' } },
  { file: 'store_promo4.html', out: 'store_promo4_pc_1920x400', width: 1920, height: 400, scale: 1, vars: { __SIZE__: 'pc' } },
  { file: 'store_promo4.html', out: 'store_promo4_mobile_750x600', width: 750, height: 600, scale: 1, vars: { __SIZE__: 'm' } },
  { file: 'store_free.html', out: 'store_free_pc_1280x200', width: 1280, height: 200, scale: 1, vars: { __SIZE__: 'pc' } },
  { file: 'store_free.html', out: 'store_free_mobile_750x240', width: 750, height: 240, scale: 1, vars: { __SIZE__: 'm' } },
  { file: 'store_content_thumb.html', out: 'store_content_thumb_1200x675', width: 1200, height: 675, scale: 1 },
  { file: 'store_content_main.html', out: 'store_content_main_mobile_750x1200', width: 750, height: 1200, scale: 1, vars: { __SIZE__: 'm' } },
  { file: 'store_content_main.html', out: 'store_content_main_pc_2880x960', width: 1440, height: 480, scale: 2, vars: { __SIZE__: 'pc' } },
];

function compress(file) {
  try { execFileSync('pngquant', ['--quality=80-95', '--speed', '1', '--force', '--ext', '.png', file]); } catch (e) { /* pngquant 없음 → 원본 유지 */ }
}

(async () => {
  const only = process.argv.slice(2);
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  for (const j of jobs) {
    if (only.length && !only.some(o => j.file.startsWith(o))) continue;
    const page = await browser.newPage({ viewport: { width: j.width, height: j.height || 100 }, deviceScaleFactor: j.scale });
    let src = path.join(__dirname, 'src', j.file);
    if (j.vars) { // 변형용 임시 HTML
      let html = fs.readFileSync(src, 'utf8');
      for (const [k, v] of Object.entries(j.vars)) html = html.split(k).join(v);
      src = path.join(__dirname, 'src', `.tmp_${j.out}.html`);
      fs.writeFileSync(src, html);
    }
    await page.goto('file://' + src);
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(150);
    // 이 작업의 이전 결과물 정리 (onnuri_xxx.png, onnuri_xxx_01.png, onnuri_xxx@2x.png)
    const mine = new RegExp(`^${j.out}(_\\d+|@2x)?\\.png$`);
    for (const f of fs.readdirSync(OUT)) if (mine.test(f)) fs.unlinkSync(path.join(OUT, f));

    const files = [];
    if (j.element) {
      const f = path.join(OUT, `${j.out}.png`);
      await page.locator(j.element).screenshot({ path: f, omitBackground: !!j.transparent });
      files.push(f);
    } else if (j.split) {
      // 분할 후보: 섹션 사이 흰 여백(.gap)의 가운데 → 섹션 중간이 잘리지 않음
      const { total, cuts } = await page.evaluate(() => {
        const cuts = [];
        for (const el of document.querySelectorAll('body > .gap')) {
          const r = el.getBoundingClientRect();
          cuts.push(r.top + r.height / 2);
        }
        return { total: document.documentElement.scrollHeight, cuts };
      });
      const maxCss = MAX_H / j.scale;
      const parts = [];
      let start = 0;
      while (total - start > maxCss) {
        const ok = cuts.filter(c => c > start + 200 && c - start <= maxCss);
        const end = ok.length ? ok[ok.length - 1] : start + maxCss;
        parts.push([start, end]); start = end;
      }
      parts.push([start, total]);
      await page.setViewportSize({ width: j.width, height: Math.ceil(total) + 200 });
      for (let i = 0; i < parts.length; i++) {
        // 1000px 출력 기준으로 픽셀이 딱 떨어지게 잘라 마지막 줄이 흐려지지 않게 함
        const px = v => Math.floor(v * j.scale) / j.scale;
        const a = px(parts[i][0]), b = px(parts[i][1]);
        const f = path.join(OUT, parts.length === 1 ? `${j.out}.png` : `${j.out}_${String(i + 1).padStart(2, '0')}.png`);
        await page.screenshot({ path: f, clip: { x: 0, y: a, width: j.width, height: b - a } });
        files.push(f);
      }
    } else {
      const f = path.join(OUT, `${j.out}.png`);
      await page.screenshot(j.height ? { path: f, clip: { x: 0, y: 0, width: j.width, height: j.height } } : { path: f, fullPage: true });
      files.push(f);
    }
    await page.close();
    if (j.vars) fs.unlinkSync(src);
    for (const f of files) { compress(f); console.log(path.basename(f), Math.round(fs.statSync(f).size / 1024) + 'KB'); }
  }
  await browser.close();
})();
