# 온누리하우스 상세페이지 디자인 키트

## 결과물 (`output/`)
| 파일 | 용도 | 크기 |
|---|---|---|
| `onnuri_top.png` | 상세페이지 **상단** (짧게, 바로 아래 옵션표) | 860 × 632 |
| `onnuri_bottom.png` | 상세페이지 **하단** (배송·통관·관부가세·취소·교환반품·고객센터) | 860 × 약 5350 |
| `onnuri_profile.png` | 스토어 프로필 사진 | 1000 × 1000 |
| `onnuri_banner.png` | 스토어 배너 / 이벤트 배너 기본형 | 1280 × 480 |
| `onnuri_brand_guide.png` | 로고·컬러·글꼴·규칙 정리 | 1200 × 1904 |

`@2x` 파일은 같은 이미지의 고해상도(2배) 버전입니다.

## 문구 수정 후 다시 만들기
1. `src/*.html`에서 문구를 바꿉니다 (예: 운영시간은 `src/bottom.html`의 `07 고객센터`).
2. `node render.js` 실행 (특정 파일만: `node render.js bottom`).

필요: Node.js + Playwright. 글꼴은 `fonts/`의 Pretendard(OFL, 상업 이용 무료)를 사용합니다.
