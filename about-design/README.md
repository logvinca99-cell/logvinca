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
| `about_top.png` | 상단: 로고 + 옵션 확인 + 약 2주 띠 (1000 × 602) |
| `about_bottom_01.png` | 표지 + 배송 |
| `about_bottom_02.png` | 착불 배송비 + 상품 안내 |
| `about_bottom_03.png` | 교환·반품 |
| `about_bottom_04.png` | 주문 취소 + 개인정보 제3자 제공 동의 |
| `about_bottom_05.png` | 문의 (문자 말풍선 + 번호) |
| `about_watermark.png` / `about_watermark_white.png` | 워터마크 (투명) |
| `about_profile.png`, `about_banner.png`, `about_brand_guide.png` | 프로필, 배너, 브랜드 가이드 |

## 다시 만들기
`src/*.html` 문구 수정 후 `node render.js`
