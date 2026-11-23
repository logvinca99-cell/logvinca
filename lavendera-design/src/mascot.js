// 라벤더라 캐릭터 — 동글동글한 라벤더 꽃봉오리 (머리에 새싹 잎)
// 사용: <div class="mascot" data-pose="plain|wave|coupon|king"></div>
(function () {
  const INK = '#251D31', G = '#C3B2D6', GD = '#A28CC4', LF = '#8FB98A', PK = '#FF9EB5';
  const face = (cx, cy, s) => `
    <ellipse cx="${cx - 14 * s}" cy="${cy}" rx="${5.5 * s}" ry="${7.5 * s}" fill="${INK}"/><ellipse cx="${cx + 14 * s}" cy="${cy}" rx="${5.5 * s}" ry="${7.5 * s}" fill="${INK}"/>
    <circle cx="${cx - 12 * s}" cy="${cy - 3 * s}" r="${2.2 * s}" fill="#fff"/><circle cx="${cx + 16 * s}" cy="${cy - 3 * s}" r="${2.2 * s}" fill="#fff"/>
    <ellipse cx="${cx - 25 * s}" cy="${cy + 10 * s}" rx="${7 * s}" ry="${4.2 * s}" fill="${PK}" opacity=".85"/><ellipse cx="${cx + 25 * s}" cy="${cy + 10 * s}" rx="${7 * s}" ry="${4.2 * s}" fill="${PK}" opacity=".85"/>
    <path d="M${cx - 6 * s} ${cy + 9 * s} Q${cx} ${cy + 15 * s} ${cx + 6 * s} ${cy + 9 * s}" fill="none" stroke="${INK}" stroke-width="${3.6 * s}" stroke-linecap="round"/>`;
  const arm = (x1, y1, x2, y2, x3, y3) => `<path d="M${x1} ${y1} Q${x2} ${y2} ${x3} ${y3}" fill="none" stroke="${INK}" stroke-width="5" stroke-linecap="round"/>`;
  const body = `
    <ellipse cx="70" cy="132" rx="40" ry="5" fill="rgba(0,0,0,.12)"/>
    <ellipse cx="54" cy="124" rx="10" ry="6.5" fill="${G}" stroke="${INK}" stroke-width="4.5"/><ellipse cx="86" cy="124" rx="10" ry="6.5" fill="${G}" stroke="${INK}" stroke-width="4.5"/>
    <path d="M70 46 V30" stroke="${INK}" stroke-width="4.5" stroke-linecap="round"/>
    <path d="M70 34 Q56 18 44 24 Q52 38 70 34 Z" fill="${LF}" stroke="${INK}" stroke-width="4" stroke-linejoin="round"/>
    <path d="M70 32 Q84 14 98 20 Q90 36 70 32 Z" fill="${LF}" stroke="${INK}" stroke-width="4" stroke-linejoin="round"/>
    <path d="M70 42 C 104 42 118 70 118 92 C 118 114 98 124 70 124 C 42 124 22 114 22 92 C 22 70 36 42 70 42 Z" fill="${G}" stroke="${INK}" stroke-width="5" stroke-linejoin="round"/>
    ${face(70, 90, 0.9)}`;
  const sparkle = (x, y) => `<path d="M${x} ${y} l4 -6 M${x + 4} ${y + 10} l8 -1" stroke="${INK}" stroke-width="3.5" stroke-linecap="round"/>`;
  const armDownL = arm(20, 92, 8, 100, 12, 112), armDownR = arm(120, 92, 132, 100, 128, 112);
  const armUpR = arm(120, 88, 134, 74, 130, 56) + sparkle(134, 46);
  const armUpL = arm(20, 88, 6, 74, 10, 56) + `<path d="M6 46 l-4 -6 M-2 56 l-8 -1" stroke="${INK}" stroke-width="3.5" stroke-linecap="round"/>`;
  const coupon = `
    <g transform="rotate(-7 70 120)">
      <rect x="34" y="106" width="72" height="30" rx="6" fill="#fff" stroke="${INK}" stroke-width="4.5"/>
      <path d="M57 106 V136" stroke="${INK}" stroke-width="3" stroke-dasharray="4 4"/>
      <circle cx="45" cy="121" r="5" fill="${GD}" stroke="${INK}" stroke-width="2.5"/>
      <text x="82" y="128" font-family="Anton" font-size="18" fill="${INK}" text-anchor="middle">₩</text>
    </g>` + arm(22, 96, 18, 112, 34, 118) + arm(118, 96, 122, 112, 106, 116);
  const crown = `
    <g transform="translate(70 0) scale(.72) translate(-60 -12)">
      <path d="M38 26 L44 8 L52 20 L60 2 L68 20 L76 8 L82 26 Z" fill="#FFD54A" stroke="${INK}" stroke-width="4" stroke-linejoin="round"/>
      <circle cx="44" cy="8" r="3.5" fill="#fff" stroke="${INK}" stroke-width="2.5"/><circle cx="60" cy="2" r="3.5" fill="#fff" stroke="${INK}" stroke-width="2.5"/><circle cx="76" cy="8" r="3.5" fill="#fff" stroke="${INK}" stroke-width="2.5"/>
    </g>`;
  const poses = {
    plain:  body + armDownL + armDownR,
    wave:   body + armDownL + armUpR,
    coupon: body + coupon,
    king:   body + armUpL + armUpR + crown,
  };
  poses.kingwave = poses.king;
  for (const el of document.querySelectorAll('.mascot')) {
    const p = poses[el.dataset.pose] ? el.dataset.pose : 'plain';
    el.innerHTML = `<svg viewBox="0 -4 140 144" style="display:block;width:100%;height:100%;overflow:visible">${poses[p]}</svg>`;
  }
})();
