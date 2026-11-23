// 온누리하우스 캐릭터 — 로고의 골드 집에서 나온 집 모양 캐릭터
// 사용: <div class="mascot" data-pose="wave|coupon|plain"></div>
(function () {
  const INK = '#17141C';
  const base = `
    <ellipse cx="60" cy="114" rx="34" ry="5" fill="rgba(0,0,0,.14)"/>
    <ellipse cx="44" cy="108" rx="9" ry="6" fill="#EBAE1F" stroke="${INK}" stroke-width="4"/>
    <ellipse cx="76" cy="108" rx="9" ry="6" fill="#EBAE1F" stroke="${INK}" stroke-width="4"/>
    <path d="M60 12 L102 46 V98 Q102 105 95 105 H25 Q18 105 18 98 V46 Z" fill="#EBAE1F" stroke="${INK}" stroke-width="4" stroke-linejoin="round"/>
    <circle cx="60" cy="40" r="8" fill="#2B2620"/><ellipse cx="60" cy="40" rx="3.4" ry="8" fill="none" stroke="#EBAE1F" stroke-width="1.8"/><line x1="52" y1="40" x2="68" y2="40" stroke="#EBAE1F" stroke-width="1.8"/>
    <ellipse cx="47" cy="68" rx="5" ry="7" fill="${INK}"/><ellipse cx="73" cy="68" rx="5" ry="7" fill="${INK}"/>
    <circle cx="49" cy="65" r="1.8" fill="#fff"/><circle cx="75" cy="65" r="1.8" fill="#fff"/>
    <ellipse cx="35" cy="80" rx="7" ry="4" fill="#FF9EB5" opacity=".8"/><ellipse cx="85" cy="80" rx="7" ry="4" fill="#FF9EB5" opacity=".8"/>
    <path d="M51 82 Q60 92 69 82" fill="none" stroke="${INK}" stroke-width="4" stroke-linecap="round"/>`;
  const armL = `<path d="M18 74 Q8 82 10 92" fill="none" stroke="${INK}" stroke-width="4" stroke-linecap="round"/>`;
  const armR = `<path d="M102 74 Q112 82 110 92" fill="none" stroke="${INK}" stroke-width="4" stroke-linecap="round"/>`;
  const wave = `<path d="M102 66 Q114 54 112 38" fill="none" stroke="${INK}" stroke-width="4" stroke-linecap="round"/>
    <path d="M118 32 l6 -4 M120 40 l7 0" stroke="${INK}" stroke-width="3" stroke-linecap="round"/>`;
  const coupon = `<g transform="rotate(-8 60 100)">
      <rect x="28" y="88" width="64" height="30" rx="6" fill="#fff" stroke="${INK}" stroke-width="4"/>
      <path d="M49 88 V118" stroke="#2B2620" stroke-width="3" stroke-dasharray="4 4"/>
      <text x="71" y="109" font-family="Anton" font-size="16" fill="#2B2620" text-anchor="middle">₩</text>
      <circle cx="38" cy="103" r="4.5" fill="#2B2620"/></g>
    <path d="M22 74 Q20 90 32 98" fill="none" stroke="${INK}" stroke-width="4" stroke-linecap="round"/>
    <path d="M98 74 Q100 90 88 98" fill="none" stroke="${INK}" stroke-width="4" stroke-linecap="round"/>`;
  const crown = `<g transform="translate(60 0) scale(.8) translate(-60 -8)"><path d="M38 26 L44 8 L52 20 L60 2 L68 20 L76 8 L82 26 Z" fill="#FFD54A" stroke="${INK}" stroke-width="4" stroke-linejoin="round"/>
    <circle cx="44" cy="8" r="3.5" fill="#fff" stroke="${INK}" stroke-width="2.5"/><circle cx="60" cy="2" r="3.5" fill="#fff" stroke="${INK}" stroke-width="2.5"/><circle cx="76" cy="8" r="3.5" fill="#fff" stroke="${INK}" stroke-width="2.5"/></g>`;
  const cheer = `<path d="M18 70 Q2 64 -2 40" fill="none" stroke="${INK}" stroke-width="4" stroke-linecap="round"/><path d="M102 70 Q118 64 122 40" fill="none" stroke="${INK}" stroke-width="4" stroke-linecap="round"/><path d="M-8 26 l-5 -5 M2 22 l2 -7 M118 22 l-2 -7 M128 26 l5 -5" stroke="${INK}" stroke-width="3" stroke-linecap="round"/>`;
  const poses = { plain: armL + armR, wave: armL + wave, coupon: coupon, king: cheer, kingwave: armL + wave };
  for (const el of document.querySelectorAll('.mascot')) {
    const p = el.dataset.pose || 'plain';
    const top = p.startsWith('king') ? crown : '';
    el.innerHTML = `<svg viewBox="0 0 126 120" style="display:block;width:100%;height:100%;overflow:visible">${(p === 'coupon' || p === 'king') ? base + poses[p] : poses[p] + base}${top}</svg>`;
  }
})();
