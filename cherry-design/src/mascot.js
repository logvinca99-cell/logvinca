// 미스터 체리 캐릭터 — 꼭지가 이어진 체리 두 알 (왼쪽이 형, 오른쪽이 동생)
// 사용: <div class="mascot" data-pose="plain|wave|love"></div>
(function () {
  const INK = '#2A1A1E', R = '#E23D55', RD = '#C42A43', LF = '#5DB26B', LFD = '#3E8E4A', PK = '#FF9EB5';
  const face = (cx, cy, s, wink) => `
    ${wink ? `<path d="M${cx - 18 * s} ${cy} q5 -5 10 0" fill="none" stroke="${INK}" stroke-width="${3.4 * s}" stroke-linecap="round"/>`
           : `<ellipse cx="${cx - 13 * s}" cy="${cy}" rx="${4.6 * s}" ry="${6.2 * s}" fill="${INK}"/><circle cx="${cx - 11.5 * s}" cy="${cy - 2.5 * s}" r="${1.8 * s}" fill="#fff"/>`}
    <ellipse cx="${cx + 13 * s}" cy="${cy}" rx="${4.6 * s}" ry="${6.2 * s}" fill="${INK}"/><circle cx="${cx + 14.5 * s}" cy="${cy - 2.5 * s}" r="${1.8 * s}" fill="#fff"/>
    <ellipse cx="${cx - 22 * s}" cy="${cy + 9 * s}" rx="${6 * s}" ry="${3.6 * s}" fill="${PK}" opacity=".9"/><ellipse cx="${cx + 22 * s}" cy="${cy + 9 * s}" rx="${6 * s}" ry="${3.6 * s}" fill="${PK}" opacity=".9"/>
    <path d="M${cx - 5 * s} ${cy + 8 * s} Q${cx} ${cy + 13 * s} ${cx + 5 * s} ${cy + 8 * s}" fill="none" stroke="${INK}" stroke-width="${3.2 * s}" stroke-linecap="round"/>`;
  const berry = (cx, cy, r) => `
    <circle cx="${cx}" cy="${cy}" r="${r}" fill="${R}" stroke="${INK}" stroke-width="4.5"/>
    <path d="M${cx - r * .62} ${cy - r * .35} q${r * .18} ${-r * .3} ${r * .45} ${-r * .38}" fill="none" stroke="#fff" stroke-width="4.5" stroke-linecap="round" opacity=".75"/>`;
  const stems = `
    <path d="M44 74 Q50 36 82 14" fill="none" stroke="${LFD}" stroke-width="5" stroke-linecap="round"/>
    <path d="M100 76 Q100 42 82 14" fill="none" stroke="${LFD}" stroke-width="5" stroke-linecap="round"/>
    <path d="M82 14 Q100 0 118 10 Q102 26 82 14 Z" fill="${LF}" stroke="${INK}" stroke-width="3.5" stroke-linejoin="round"/>
    <path d="M86 14 Q100 10 112 11" fill="none" stroke="${LFD}" stroke-width="2.5" stroke-linecap="round"/>`;
  const arm = (d) => `<path d="${d}" fill="none" stroke="${INK}" stroke-width="4.5" stroke-linecap="round"/>`;
  const shadow = `<ellipse cx="72" cy="134" rx="58" ry="5" fill="rgba(0,0,0,.10)"/>`;
  const body = (wink) => shadow + stems + berry(42, 100, 32) + berry(104, 102, 30) + face(42, 100, .82, false) + face(104, 102, .78, wink);
  const hold = arm('M70 108 Q73 114 76 108');                       // 둘이 손잡기
  const outL = arm('M11 104 Q2 110 4 120'), outR = arm('M134 104 Q143 110 141 120');
  const waveR = arm('M133 96 Q146 84 142 66') + `<path d="M146 58 l5 -5 M150 68 l7 0" stroke="${INK}" stroke-width="3" stroke-linecap="round"/>`;
  const heart = `<path d="M128 40 c-6 -8 -18 -2 -12 8 l12 12 l12 -12 c6 -10 -6 -16 -12 -8 z" fill="${PK}" stroke="${INK}" stroke-width="3.5" stroke-linejoin="round"/>`;
  const poses = {
    plain: body(false) + hold + outL + outR,
    wave:  body(false) + hold + outL + waveR,
    love:  body(true)  + hold + outL + outR + heart,
  };
  for (const el of document.querySelectorAll('.mascot')) {
    const p = poses[el.dataset.pose] ? el.dataset.pose : 'plain';
    el.innerHTML = `<svg viewBox="-4 -4 156 144" style="display:block;width:100%;height:100%;overflow:visible">${poses[p]}</svg>`;
  }
})();
