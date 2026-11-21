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

## 스토어 꾸미기 (`output/store_*`)
사이즈는 네이버 공식 자료를 찾지 못해 디자인 업체들이 많이 쓰는 규격으로 만들었습니다. 업로드 화면 안내와 다르면 알려주세요.
| 파일 | 용도 | 크기 |
|---|---|---|
| `store_profile_1000.png` | 스토어 대표 이미지(프로필). 원으로 잘려도 대칭 | 1000 × 1000 |
| `store_logo.png` | 로고(상단바). 티켓 워터마크와 같은 모양, 투명 배경 | 642 × 180 |
| `store_promo1~3_pc_1920x400.png` | 프로모션 배너 PC (1 브랜드 / 2 알림받기 1,000원 + 어댑터 / 3 혜택) | 1920 × 400 |
| `store_promo1~3_mobile_750x600.png` | 프로모션 배너 모바일 | 750 × 600 |
| `store_free_pc_1280x200.png` / `store_free_mobile_750x240.png` | 자유배너: 문자 상담 안내 | 1280 × 200 / 750 × 240 |
| `store_content_thumb_1080.png` | 스토어 콘텐츠(이벤트) 대표 이미지 · 팝업 | 1080 × 1080 |
| `store_content_main.png` | 스토어 콘텐츠(이벤트) 메인 배너 | 1000 × 1260 |

## 전달용 묶음
`aboutt_store_kit.zip` — 스토어 꾸미기 이미지 + 업스타용 이미지 + 넣는 곳 지침(`GUIDE_넣는곳_지침.txt`). 프로모션 배너에는 '문자 상담 010-5934-5488'이 들어갑니다.
