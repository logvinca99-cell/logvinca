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
  { file: 'top.html',    out: 'cherry_top',    width: 860, scale: SCALE, split: true },
  { file: 'bottom.html', out: 'cherry_bottom', width: 860, scale: SCALE, split: true },
  { file: 'top2.html',    out: 'cherry2_top',    width: 860, scale: SCALE, split: true },
  { file: 'bottom2.html', out: 'cherry2_bottom', width: 860, scale: SCALE, split: true },
  { file: 'top3.html',    out: 'cherry3_top',    width: 860, scale: SCALE, split: true },
  { file: 'bottom3.html', out: 'cherry3_bottom', width: 860, scale: SCALE, split: true },
  { file: 'top4.html',    out: 'cherry4_top',    width: 860, scale: SCALE, split: true },
  { file: 'bottom4.html', out: 'cherry4_bottom', width: 860, scale: SCALE, split: true },
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
    // 이 작업의 이전 결과물 정리 (cherry_xxx.png, cherry_xxx_01.png, cherry_xxx@2x.png)
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
