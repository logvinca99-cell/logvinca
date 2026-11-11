# 온누리하우스 상세페이지 디자인 키트

## 결과물 (`output/`, 모두 PNG)
| 파일 | 용도 | 크기 | 용량 |
|---|---|---|---|
| `onnuri_top.png` | 상세 **상단** (바로 아래 옵션표) | 1000 × 735 | 약 17KB |
| `onnuri_bottom_01~04.png` | 상세 **하단** 4장, 위에서부터 순서대로 | 1000 × 1128~1992 | 장당 30~60KB |
| `onnuri_watermark.png` | **워터마크** (기본, 블루 + 흰 외곽선) | 496 × 128, 투명 | 약 5KB |
| `onnuri_watermark_white.png` | 워터마크 (어두운 사진용 흰색) | 496 × 128, 투명 | 약 4KB |
| `onnuri_profile.png` | 스토어 프로필 | 1000 × 1000 | |
| `onnuri_banner.png` | 스토어·이벤트 배너 | 1280 × 480 | |
| `onnuri_brand_guide.png` | 로고·컬러·글씨 크기 규칙 | 1200 × 1904 | |

- 상단·하단은 가로 1000px, 장당 세로 2000px 이하. 하단은 섹션 사이 여백에서만 잘리게 자동 분할됩니다.
- 글자·아이콘 위주 단색 디자인이라 PNG로 저장했고, 상단+하단 전체 약 220KB입니다.

## 문구 수정 후 다시 만들기
1. `src/*.html`에서 문구를 바꿉니다 (예: 운영시간은 `src/bottom.html` 맨 아래 고객센터).
2. `node render.js` 실행 (특정 파일만: `node render.js bottom`).

필요: Node.js + Playwright. pngquant가 있으면 자동으로 용량을 줄입니다.
글꼴은 `fonts/`의 Pretendard(OFL, 상업 이용 무료)를 사용합니다.
