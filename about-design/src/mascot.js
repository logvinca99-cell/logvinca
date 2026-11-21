// 에이바우트 캐릭터 '점이' — 로고 a. 의 노란 점에서 나온 동글이
// 사용: <div class="mascot" data-pose="wave|coupon|plain"></div>
(function () {
  const INK = '#17141C';
  const base = `
    <ellipse cx="60" cy="112" rx="30" ry="5" fill="rgba(0,0,0,.12)"/>
    <ellipse cx="45" cy="104" rx="9" ry="6" fill="#FFE45C" stroke="${INK}" stroke-width="4"/>
    <ellipse cx="75" cy="104" rx="9" ry="6" fill="#FFE45C" stroke="${INK}" stroke-width="4"/>
    <circle cx="60" cy="62" r="42" fill="#FFE45C" stroke="${INK}" stroke-width="4"/>
    <ellipse cx="47" cy="58" rx="5" ry="7" fill="${INK}"/><ellipse cx="73" cy="58" rx="5" ry="7" fill="${INK}"/>
    <circle cx="49" cy="55" r="1.8" fill="#fff"/><circle cx="75" cy="55" r="1.8" fill="#fff"/>
    <ellipse cx="36" cy="72" rx="7" ry="4" fill="#FF9EB5" opacity=".8"/><ellipse cx="84" cy="72" rx="7" ry="4" fill="#FF9EB5" opacity=".8"/>
    <path d="M51 73 Q60 83 69 73" fill="none" stroke="${INK}" stroke-width="4" stroke-linecap="round"/>`;
  const armL = `<path d="M22 70 Q12 78 14 88" fill="none" stroke="${INK}" stroke-width="4" stroke-linecap="round"/>`;
  const armR = `<path d="M98 70 Q108 78 106 88" fill="none" stroke="${INK}" stroke-width="4" stroke-linecap="round"/>`;
  const wave = `<path d="M98 60 Q110 48 108 32" fill="none" stroke="${INK}" stroke-width="4" stroke-linecap="round"/>
    <path d="M114 26 l6 -4 M116 34 l7 0" stroke="${INK}" stroke-width="3" stroke-linecap="round"/>`;
  const coupon = `<g transform="rotate(-8 60 100)">
      <rect x="28" y="88" width="64" height="30" rx="6" fill="#fff" stroke="${INK}" stroke-width="4"/>
      <path d="M49 88 V118" stroke="#553C8B" stroke-width="3" stroke-dasharray="4 4"/>
      <text x="71" y="109" font-family="Anton" font-size="16" fill="#553C8B" text-anchor="middle">₩</text>
      <circle cx="38" cy="103" r="4.5" fill="#553C8B"/></g>
    <path d="M22 74 Q20 90 32 98" fill="none" stroke="${INK}" stroke-width="4" stroke-linecap="round"/>
    <path d="M98 74 Q100 90 88 98" fill="none" stroke="${INK}" stroke-width="4" stroke-linecap="round"/>`;
  const poses = { plain: armL + armR, wave: armL + wave, coupon: coupon };
  for (const el of document.querySelectorAll('.mascot')) {
    const p = el.dataset.pose || 'plain';
    el.innerHTML = `<svg viewBox="0 0 126 120" style="display:block;width:100%;height:100%;overflow:visible">${p === 'coupon' ? base + poses[p] : poses[p] + base}</svg>`;
  }
})();
