# 온누리하우스 상세페이지 디자인 키트

## 결과물 (`output/`, 모두 PNG)
| 파일 | 용도 | 크기 | 용량 |
|---|---|---|---|
| `onnuri_top.png` | 상세 **상단** (로고 + 옵션 확인 안내, 바로 아래 옵션표) | 1000 × 488 | 약 10KB |
| `onnuri_bottom_01~08.png` | 상세 **하단** 8장, 위에서부터 순서대로 | 1000 × 891~1877 | 장당 25~55KB |
| `onnuri_watermark.png` | **워터마크** (기본, 블루 + 흰 외곽선) | 496 × 128, 투명 | 약 5KB |
| `onnuri_watermark_white.png` | 워터마크 (어두운 사진용 흰색) | 496 × 128, 투명 | 약 4KB |
| `onnuri_profile.png` | 스토어 프로필 | 1000 × 1000 | |
| `onnuri_banner.png` | 스토어·이벤트 배너 | 1280 × 480 | |
| `onnuri_brand_guide.png` | 로고·컬러·글씨 크기 규칙 | 1200 × 1904 | |

- 상단·하단은 가로 1000px, 장당 세로 2000px 이하. 하단은 섹션 사이 여백에서만 잘리게 자동 분할됩니다.
- 글자·아이콘 위주 단색 디자인이라 PNG로 저장했고, 상단+하단 전체 약 370KB입니다.

## 문구 수정 후 다시 만들기
1. `src/*.html`에서 문구를 바꿉니다 (예: 운영시간은 `src/bottom.html` 맨 아래 고객센터).
2. `node render.js` 실행 (특정 파일만: `node render.js bottom`).

필요: Node.js + Playwright. pngquant가 있으면 자동으로 용량을 줄입니다.
글꼴은 `fonts/`의 Pretendard(OFL, 상업 이용 무료)를 사용합니다.

## 스토어 꾸미기 (`output/store_*`)
에이바우트 스토어 꾸미기와 같은 구성, 온누리 색(차콜 + 골드)과 창문 얼굴 캐릭터(`src/mascot.js`, 시안 C)로 제작.
| 파일 | 용도 | 크기 | 바탕 |
|---|---|---|---|
| `store_profile_1300.png` | 스토어 대표 이미지(프로필) | 1300 × 1300 | 골드 |
| `store_logo_pc_260x80.png` / `store_logo_mobile_600x80.png` | 로고(GNB), 투명 | 260 × 80 / 600 × 80 | 투명 |
| `store_promo1_*` | 프로모션 1 브랜드 소개 + 손 흔드는 집 캐릭터 | PC 1920 × 400 / 모바일 750 × 600 | 크림 |
| `store_promo2_*` | 프로모션 2 최대 3,000원 혜택 + 쿠폰 든 캐릭터 | 〃 | 골드 |
| `store_promo3_*` | 프로모션 3 혜택 카드 3장 | 〃 | 차콜 |
| `store_promo4_*` | 프로모션 4 이달의 리뷰왕 (네이버페이 포인트 10,000원, 인원 비공개) | 〃 | 진한 황금색 |
| `store_free_*` | 자유배너: 문자 상담 | PC 1280 × 200 / 모바일 750 × 240 | 차콜 |
| `store_content_thumb_1200x675.png` | 이벤트 대표 이미지(팝업) | 1200 × 675 | 차콜 |
| `store_content_main_mobile_750x1200.png` / `_pc_2880x960.png` | 이벤트 메인 배너 | 750 × 1200 / 2880 × 960 | 차콜 + 흰 |

전달용: `onnuri_store_files.zip`(스토어 이미지 + 지침), `onnuri_store_kit.zip`(+ 업스타용), `GUIDE_넣는곳_지침.txt`
