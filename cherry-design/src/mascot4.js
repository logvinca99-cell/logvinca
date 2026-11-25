// 미스터 체리 캐릭터 (4차) — 검은 테두리 없는 매끈한 체리 두 알
// 사용: <div class="mascot" data-pose="plain|wave|love"></div>
(function () {
  const R = '#E0344B', RD = '#B71E35', HL = '#FF8A98', LF = '#5BB46B', LFD = '#3D8F4F', EYE = '#3A1418', PK = '#FFB3C0';
  const berry = (cx, cy, r, wink) => `
    <circle cx="${cx}" cy="${cy}" r="${r}" fill="${R}"/>
    <path d="M${cx - r} ${cy} A${r} ${r} 0 0 0 ${cx + r} ${cy} A${r} ${r * .72} 0 0 1 ${cx - r} ${cy} Z" fill="${RD}" opacity=".35"/>
    <ellipse cx="${cx - r * .45}" cy="${cy - r * .5}" rx="${r * .2}" ry="${r * .12}" fill="#fff" opacity=".85" transform="rotate(-35 ${cx - r * .45} ${cy - r * .5})"/>
    ${wink ? `<path d="M${cx - r * .42} ${cy + r * .02} q${r * .14} ${-r * .14} ${r * .28} 0" fill="none" stroke="${EYE}" stroke-width="3.2" stroke-linecap="round"/>`
           : `<circle cx="${cx - r * .28}" cy="${cy}" r="${r * .1}" fill="${EYE}"/>`}
    <circle cx="${cx + r * .28}" cy="${cy}" r="${r * .1}" fill="${EYE}"/>
    <ellipse cx="${cx - r * .52}" cy="${cy + r * .26}" rx="${r * .16}" ry="${r * .1}" fill="${PK}"/>
    <ellipse cx="${cx + r * .52}" cy="${cy + r * .26}" rx="${r * .16}" ry="${r * .1}" fill="${PK}"/>
    <path d="M${cx - r * .12} ${cy + r * .2} q${r * .12} ${r * .14} ${r * .24} 0" fill="none" stroke="${EYE}" stroke-width="3" stroke-linecap="round"/>`;
  const stems = `
    <path d="M44 72 Q50 38 80 14" fill="none" stroke="${LFD}" stroke-width="4.5" stroke-linecap="round"/>
    <path d="M100 74 Q100 42 80 14" fill="none" stroke="${LFD}" stroke-width="4.5" stroke-linecap="round"/>
    <path d="M80 14 Q98 0 116 9 Q100 24 80 14 Z" fill="${LF}"/>
    <path d="M84 13 Q98 9 110 10" fill="none" stroke="${LFD}" stroke-width="2" stroke-linecap="round"/>`;
  const limb = (d) => `<path d="${d}" fill="none" stroke="${RD}" stroke-width="5" stroke-linecap="round"/>`;
  const shadow = `<ellipse cx="72" cy="134" rx="56" ry="5" fill="rgba(0,0,0,.08)"/>`;
  const body = (wink) => shadow + stems + berry(42, 100, 32, false) + berry(104, 102, 30, wink);
  const outL = limb('M11 108 Q4 114 7 122'), outR = limb('M134 108 Q141 114 138 122');
  const waveR = limb('M133 98 Q145 86 141 70');
  const heart = `<path d="M128 44 c-6 -8 -17 -2 -11 8 l11 11 l11 -11 c6 -10 -5 -16 -11 -8 z" fill="${HL}"/>`;
  const poses = { plain: body(false) + outL + outR, wave: body(false) + outL + waveR, love: body(true) + outL + outR + heart };
  for (const el of document.querySelectorAll('.mascot')) {
    const p = poses[el.dataset.pose] ? el.dataset.pose : 'plain';
    el.innerHTML = `<svg viewBox="-4 -4 156 144" style="display:block;width:100%;height:100%;overflow:visible">${poses[p]}</svg>`;
  }
})();
