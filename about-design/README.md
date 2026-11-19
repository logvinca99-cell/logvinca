# 에이바우트 상세페이지 디자인 키트 (초안)

이름 뜻: about(~에 대하여). 상세 하단을 잡지 한 권 같은 **구매 안내서**로 꾸미고,
섹션마다 `about delivery`, `about returns`처럼 이름을 붙였습니다.

## 디자인 규칙
- 왼쪽 정렬. 둥근 박스 없이 굵은 선(8px)·가는 선(1px)으로 지면을 나눔
- 섹션 머리 = 테두리만 있는 큰 숫자 + 영문 라벨 + 명조 제목
- 강조는 형광펜 밑줄 하나로만
- 배송은 ‘주문 후 발주해 준비되는 상품’, ‘약 2주’로만 표현 (통관·관부가세·구매대행 문구 없음)

## 글꼴 (역할별로 섞어 씀, 모두 OFL 무료)
| 역할 | 글꼴 | 크기 |
|---|---|---|
| 제목 | Noto Serif KR Black | 76px / 46px |
| 본문 | IBM Plex Sans KR | 29px / 보조 23px |
| 숫자 | Anton | |
| 영문 | Instrument Serif Italic | |

## 컬러
| 이름 | HEX | RGB |
|---|---|---|
| 플럼 | #553C8B | 85, 60, 139 |
| 먹색 | #17141C | 23, 20, 28 |
| 형광펜 노랑 | #FFE45C | 255, 228, 92 |
| 연보라 면 | #F3F0F8 | 243, 240, 248 |

## 결과물 (`output/`, 모두 PNG, 가로 1000px)
| 파일 | 내용 |
|---|---|
| `about_top.png` | 상단: 로고 + 옵션 확인 + 약 2주 띠 (1000 × 627) |
| `about_bottom_01.png` | 표지 + 목차 |
| `about_bottom_02.png` | 01 배송 (달력 14칸, 진행 순서) |
| `about_bottom_03.png` | 02 착불 배송비 |
| `about_bottom_04.png` | 03 상품 안내 |
| `about_bottom_05.png` | 04 교환·반품 |
| `about_bottom_06.png` | 05 주문 취소 |
| `about_bottom_07.png` | 06 개인정보 제3자 제공 동의 |
| `about_bottom_08.png` | 문의 (문자 말풍선 + 번호) |
| `about_watermark.png` / `about_watermark_white.png` | 워터마크 (투명) |
| `about_profile.png`, `about_banner.png`, `about_brand_guide.png` | 프로필, 배너, 브랜드 가이드 |

## 다시 만들기
`src/*.html` 문구 수정 후 `node render.js`
