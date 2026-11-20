// 사용법: node render.js            → output/ 에 전부 생성
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
  { file: 'top.html',    out: 'about_top',    width: 860, scale: SCALE, split: true },
  { file: 'bottom.html', out: 'about_bottom', width: 860, scale: SCALE, split: true },
  { file: 'top_a.html', out: 'about_top_A', width: 860, scale: SCALE, split: true },
  { file: 'top_b.html', out: 'about_top_B', width: 860, scale: SCALE, split: true },
  { file: 'top_c.html', out: 'about_top_C', width: 860, scale: SCALE, split: true },
  { file: 'top_d.html', out: 'about_top_D', width: 860, scale: SCALE, split: true },
  { file: 'top_e.html', out: 'about_top_E', width: 860, scale: SCALE, split: true },
  { file: 'watermark.html', out: 'about_watermark',       width: 250, scale: 2.3, element: '#wm', transparent: true, vars: { __VARIANT__: '' } },
  { file: 'watermark.html', out: 'about_watermark_white', width: 250, scale: 2.3, element: '#wm', transparent: true, vars: { __VARIANT__: 'white' } },
  { file: 'watermark2.html', out: 'about_wm_1_bubble', width: 260, scale: 2.3, element: '#w1', transparent: true },
  { file: 'watermark2.html', out: 'about_wm_2_ticket', width: 260, scale: 2.3, element: '#w2', transparent: true },
  { file: 'watermark2.html', out: 'about_wm_3_tape', width: 260, scale: 2.3, element: '#w3', transparent: true },
  { file: 'watermark2.html', out: 'about_wm_4_capsule', width: 260, scale: 2.3, element: '#w4', transparent: true },
  { file: 'watermark2.html', out: 'about_wm_5_seal', width: 260, scale: 2.3, element: '#w5', transparent: true },
  { file: 'watermark3.html', out: 'about_wm_round_1_plum', width: 260, scale: 2.3, element: '#r1', transparent: true },
  { file: 'watermark3.html', out: 'about_wm_round_2_black', width: 260, scale: 2.3, element: '#r2', transparent: true },
  { file: 'watermark3.html', out: 'about_wm_round_3_yellow', width: 260, scale: 2.3, element: '#r3', transparent: true },
  { file: 'watermark3.html', out: 'about_wm_round_4_white', width: 260, scale: 2.3, element: '#r4', transparent: true },
  { file: 'watermark3.html', out: 'about_wm_round_5_split', width: 260, scale: 2.3, element: '#r5', transparent: true },
  { file: 'watermark3.html', out: 'about_wm_round_6_icon', width: 260, scale: 2.3, element: '#r6', transparent: true },
  { file: 'watermark4.html', out: 'about_wm_circle_1_arc_bottom', width: 260, scale: 2.3, element: '#c1', transparent: true },
  { file: 'watermark4.html', out: 'about_wm_circle_2_arc_top', width: 260, scale: 2.3, element: '#c2', transparent: true },
  { file: 'watermark4.html', out: 'about_wm_circle_3_ring', width: 260, scale: 2.3, element: '#c3', transparent: true },
  { file: 'watermark4.html', out: 'about_wm_circle_4_thin', width: 260, scale: 2.3, element: '#c4', transparent: true },
  { file: 'watermark4.html', out: 'about_wm_circle_5_badge', width: 260, scale: 2.3, element: '#c5', transparent: true },
  { file: 'watermark4.html', out: 'about_wm_circle_6_about', width: 260, scale: 2.3, element: '#c6', transparent: true },
  { file: 'watermark5.html', out: 'about_wm_dot_1_a', width: 260, scale: 2.3, element: '#s1', transparent: true },
  { file: 'watermark5.html', out: 'about_wm_dot_2_a_ring', width: 260, scale: 2.3, element: '#s2', transparent: true },
  { file: 'watermark5.html', out: 'about_wm_dot_3_mono', width: 260, scale: 2.3, element: '#s3', transparent: true },
  { file: 'watermark5.html', out: 'about_wm_dot_4_a_dot', width: 260, scale: 2.3, element: '#s4', transparent: true },
  { file: 'watermark5.html', out: 'about_wm_dot_5_about', width: 260, scale: 2.3, element: '#s5', transparent: true },
  { file: 'watermark5.html', out: 'about_wm_dot_6_both', width: 260, scale: 2.3, element: '#s6', transparent: true },
  { file: 'store_profile.html', out: 'store_profile_1000', width: 1000, height: 1000, scale: 1 },
  { file: 'store_logo.html', out: 'store_logo', width: 420, scale: 2, element: '#lg', transparent: true },
  { file: 'store_promo1.html', out: 'store_promo1_pc_1920x400', width: 1920, height: 400, scale: 1, vars: { __SIZE__: 'pc' } },
  { file: 'store_promo1.html', out: 'store_promo1_mobile_750x600', width: 750, height: 600, scale: 1, vars: { __SIZE__: 'm' } },
  { file: 'store_promo2.html', out: 'store_promo2_pc_1920x400', width: 1920, height: 400, scale: 1, vars: { __SIZE__: 'pc' } },
  { file: 'store_promo2.html', out: 'store_promo2_mobile_750x600', width: 750, height: 600, scale: 1, vars: { __SIZE__: 'm' } },
  { file: 'store_promo3.html', out: 'store_promo3_pc_1920x400', width: 1920, height: 400, scale: 1, vars: { __SIZE__: 'pc' } },
  { file: 'store_promo3.html', out: 'store_promo3_mobile_750x600', width: 750, height: 600, scale: 1, vars: { __SIZE__: 'm' } },
  { file: 'store_content_thumb.html', out: 'store_content_thumb_1080', width: 1080, height: 1080, scale: 1 },
  { file: 'store_content_main.html', out: 'store_content_main', width: 860, scale: 1000/860, split: true },
  { file: 'profile.html', out: 'about_profile', width: 1000, height: 1000, scale: 1 },
  { file: 'banner.html',  out: 'about_banner',  width: 1280, height: 480,  scale: 1 },
  { file: 'guide.html',   out: 'about_brand_guide', width: 1200, scale: 1 },
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
    await page.waitForTimeout(150); // 글자 중앙 맞춤 스크립트가 끝나길 기다림
    // 이 작업의 이전 결과물 정리 (about_xxx.png, about_xxx_01.png, about_xxx@2x.png)
    const mine = new RegExp(`^${j.out}(_\\d+|@2x)?\\.png$`);
    for (const f of fs.readdirSync(OUT)) if (mine.test(f)) fs.unlinkSync(path.join(OUT, f));

    const files = [];
    if (j.element) {
      const f = path.join(OUT, `${j.out}.png`);
      await page.locator(j.element).screenshot({ path: f, omitBackground: !!j.transparent });
      files.push(f);
    } else if (j.split) {
      // 분할 후보 1순위: 섹션 사이 흰 여백(.gap)의 가운데
      // 2순위(섹션이 한 장보다 길 때): 섹션 안 블록·목록 줄 사이 경계
      const { total, cuts, soft } = await page.evaluate(() => {
        const cuts = [], soft = [];
        for (const el of document.querySelectorAll('body > .gap')) {
          const r = el.getBoundingClientRect();
          cuts.push(r.top + r.height / 2);
        }
        for (const el of document.querySelectorAll('.page > *, .rows > li')) soft.push(el.getBoundingClientRect().top);
        return { total: document.documentElement.scrollHeight, cuts, soft };
      });
      const maxCss = MAX_H / j.scale;
      const parts = [];
      let start = 0;
      while (total - start > maxCss) {
        const fit = list => list.filter(c => c > start + 200 && c - start <= maxCss);
        const ok = fit(cuts), ok2 = fit(soft);
        const end = ok.length ? ok[ok.length - 1] : ok2.length ? Math.max(...ok2) : start + maxCss;
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
