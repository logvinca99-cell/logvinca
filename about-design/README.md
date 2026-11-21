# 에이바우트 상세페이지 디자인 키트 (초안)

이름 뜻: about(~에 대하여). 안내를 **문자 대화**처럼 풀었습니다.
섹션마다 [손님 질문 말풍선] → [가게 답 말풍선] → 짧은 줄 목록 순서입니다.

## 디자인 규칙
- 강조는 답 말풍선 안의 노란 글씨 한 군데만. 목록에는 굵은 글씨·밑줄 없음
- 본문은 한 가지 크기(27px)로만 쓰고, 작은 회색 보조 글씨를 덧붙이지 않음
- 표지·문의는 어두운 면, 착불 배송비는 플럼 면, 나머지는 흰 바탕
- 배송은 ‘주문 후 준비되는 상품’, ‘약 2주’로만 표현 (통관·관부가세·구매대행 문구 없음)

## 글꼴 (모두 OFL 무료)
| 역할 | 글꼴 |
|---|---|
| 한글 제목·본문 | Wanted Sans (ExtraBlack 40px / Medium 27px) |
| 숫자 | Anton |
| 영문 | Instrument Serif Italic |

## 컬러
| 이름 | HEX | RGB |
|---|---|---|
| 플럼 | #553C8B | 85, 60, 139 |
| 먹색 | #17141C | 23, 20, 28 |
| 노랑 | #FFE45C | 255, 228, 92 |
| 연보라 | #F1EEF5 | 241, 238, 245 |

## 결과물 (`output/`, 모두 PNG, 가로 1000px)
| 파일 | 내용 |
|---|---|
| `about_top.png` | 상단: 티켓형 (시안 C 확정) — 옵션 확인 문구 + 약 2주 (1000 × 467) |
| `about_top_A~E.png` | 상단 시안 5종 (A 체크 카드 / B 사진 비교 / C 티켓 / D 미니멀 표 / E 옐로 스티커) |
| `about_bottom_01.png` | 표지 + 배송 |
| `about_bottom_02.png` | 착불 배송비 + 상품 안내 |
| `about_bottom_03.png` | 교환·반품 |
| `about_bottom_04.png` | 주문 취소 + 개인정보 제3자 제공 동의 |
| `about_bottom_05.png` | 문의 (문자 말풍선 + 번호) |
| `about_watermark.png` / `about_watermark_white.png` | 워터마크 (투명) |
| `about_wm_1_bubble` ~ `about_wm_5_seal` | 딱지형 워터마크 시안 5종 (말풍선 / 티켓 / 노란 테이프 / 먹색 캡슐 / 둥근 도장), 투명 PNG 약 500px |
| `about_wm_preview.png` | 위 5종을 썸네일 우측 하단에 넣어 본 미리보기 |
| `about_wm_round_1_plum` ~ `about_wm_round_6_icon` | 원형 워터마크 시안 6종 (보라 / 검정 / 노랑 / 흰 바탕 / 위아래 나눔 / a.만), 투명 PNG 497px |
| `about_wm_round_preview.png` | 원형 6종을 썸네일 우측 하단에 15% 크기로 넣어 본 미리보기 |
| `about_wm_circle_1_arc_bottom` ~ `about_wm_circle_6_about` | 보라 원형 워터마크, 글자 정리판 6종 (아래 둥근 글자 / 위 둥근 글자 / 위 한글+아래 영문 / 가는 글씨 / 흰 테 배지 / about.) |
| `about_wm_circle_preview.png` | 위 6종 미리보기 |
| `about_wm_dot_1_a` ~ `about_wm_dot_6_both` | 대칭 원형 워터마크 6종: 원 자체가 마침표, 글자는 실제 잉크 기준 정중앙 (a / a+안쪽 테 / 도형 a / a+아래 점 / about / 위아래 글자) |
| `about_wm_dot_preview.png` | 위 6종 미리보기 |
| `about_profile.png`, `about_banner.png`, `about_brand_guide.png` | 프로필, 배너, 브랜드 가이드 |

## 다시 만들기
`src/*.html` 문구 수정 후 `node render.js`

## 스토어 꾸미기 (`output/store_*`) — 2차 수정 (최대 3,000원 혜택 강조, 자리별 색·캐릭터 변화)
캐릭터 '점이': 로고 a. 의 노란 점에서 나온 동글이 (`src/mascot.js`, 자세: wave / coupon / plain)
| 파일 | 용도 | 크기 | 바탕 |
|---|---|---|---|
| `store_profile_1300.png` | 스토어 대표 이미지(프로필) | 1300 × 1300 | 보라 |
| `store_logo_pc_260x80.png` / `store_logo_mobile_600x80.png` | 로고(GNB), 투명 | 260 × 80 / 600 × 80 | 투명 |
| `store_promo1_*` | 프로모션 1 브랜드 소개 + 손 흔드는 캐릭터 | PC 1920 × 400 / 모바일 750 × 600 | 연보라 |
| `store_promo2_*` | 프로모션 2 최대 3,000원 혜택 + 쿠폰 든 캐릭터 | 〃 | 노랑 |
| `store_promo3_*` | 프로모션 3 혜택 카드 3장 | 〃 | 먹색 |
| `store_promo4_*` | 프로모션 4 이달의 리뷰왕 (네이버페이 포인트 10,000원, 인원 비공개) + 왕관 캐릭터 | 〃 | 보라 |
| `store_free_*` | 자유배너: 문자 상담 | PC 1280 × 200 / 모바일 750 × 240 | 먹색 |
| `store_content_thumb_1200x675.png` | 이벤트 대표 이미지(팝업) | 1200 × 675 | 보라 |
| `store_content_main_mobile_750x1200.png` / `_pc_2880x960.png` | 이벤트 메인 배너 | 750 × 1200 / 2880 × 960 | 보라 + 흰 |

## 전달용 묶음
`aboutt_store_kit.zip` — 스토어 꾸미기 이미지 + 업스타용 이미지 + 넣는 곳 지침(`GUIDE_넣는곳_지침.txt`). 프로모션 배너에는 '문자 상담 010-5934-5488'이 들어갑니다.
