# 라벤더라 워터마크

로고(짙은 가지색 바탕 + 연보라 선 라벤더 + 자간 넓은 세리프 대문자)를 그대로 따른 썸네일 워터마크입니다.

## 컬러 (로고 이미지에서 추출)
| 이름 | HEX | RGB |
|---|---|---|
| 바탕 | #251D31 | 37, 29, 49 |
| 라벤더 | #C3B2D6 | 195, 178, 214 |
| 글자 | #F2EEF7 | 242, 238, 247 |

## 결과물 (`output/`, 배경 투명 PNG)
| 파일 | 모양 | 크기 | 권장 워터마크 크기 |
|---|---|---|---|
| `lavendera_wm_1_badge.png` | 둥근 배지: 라벤더 + LAVENDERA | 493 × 493 | 15% |
| `lavendera_wm_2_capsule.png` | 가로 캡슐(짙은 바탕) | 501 × 130 | 22% |
| **`lavendera_wm_3_arch_small.png`** | **아치형 태그 (사용용)**: 가로 500px 투명 캔버스 오른쪽 끝에 작게 붙임 | 500 × 255 | 기본 22% 그대로 |
| `lavendera_wm_3_arch.png` | 위가 둥근 아치형 태그 | 361 × 506 | 15% |
| `lavendera_wm_4_capsule_light.png` | 가로 캡슐(연보라 바탕) | 501 × 130 | 22% |
| `lavendera_wm_5_badge_icon.png` | 둥근 배지: 라벤더만, 안쪽 가는 테 | 471 × 471 | 15% |
| `lavendera_wm_preview.png` | 위 5종을 썸네일 우측 하단에 넣어 본 미리보기 | | |

## 다시 만들기
`node render.js` (글꼴: Noto Serif 영문 축소본, OFL 무료)

## 스토어 꾸미기 (`output/store_*`, 렌더: `node render_store.js`)
에이바우트·온누리와 같은 구성. 짙은 가지색 + 라벤더, 라벤더 봉오리 캐릭터(`src/mascot.js`).
| 파일 | 용도 | 크기 | 바탕 |
|---|---|---|---|
| `store_profile_1300.png` | 프로필 | 1300 × 1300 | 짙은 가지색 |
| `store_logo_pc_260x80.png` / `store_logo_mobile_600x80.png` | 로고(GNB), 투명 | 260 × 80 / 600 × 80 | 투명 |
| `store_promo1_*` | 브랜드 소개 | PC 1920 × 400 / 모바일 750 × 600 | 연보라 |
| `store_promo2_*` | 최대 3,000원 혜택 | 〃 | 라벤더 |
| `store_promo3_*` | 혜택 카드 | 〃 | 짙은 가지색 |
| `store_promo4_*` | 이달의 리뷰왕 | 〃 | 진보라 |
| `store_free_*` | 자유배너: 문자 상담 | PC 1280 × 200 / 모바일 750 × 240 | 짙은 가지색 |
| `store_content_thumb_1200x675.png` | 팝업 | 1200 × 675 | 짙은 가지색 |
| `store_content_main_*` | 이벤트 메인 | 750 × 1200 / 2880 × 960 | 짙은 가지색 + 흰 |

전달용: `lavendera_store_files.zip`(스토어 이미지 + 지침), `GUIDE_넣는곳_지침.txt`

## 최종 전달 묶음: `lavendera_final.zip` + `GUIDE_넣는곳_지침.txt`
- 1_store (16장): 프로필 · 로고 · 프로모션 1~4(리뷰왕 10,000원) · 자유배너 · 팝업 · 이벤트 메인
- 2_upsta (1장): 워터마크 `lavendera_wm_3_arch_small` (우측 하단, 22%)
스토어 꾸미기 2차 (`src/lav2_*.html`, 렌더: `node render_store2.js`): 고상하고 우아한 방향. 캐릭터 대신 선 라벤더, 아치 프레임, 가는 Pretendard + 세리프 영문, 아이보리·안개 보라·짙은 가지색.
배경 효과 3차: 은은한 메쉬 그라데이션·보케·종이 질감(옅게)·부드러운 그림자 (`lav2.css` 하단).
