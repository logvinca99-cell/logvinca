"""이미지 여백·무게중심 검사.
사용법: python3 tools/balance_check.py 이미지.png [아래에서 제외할 높이px]
바탕과 대비가 큰 픽셀(그림·글자)의 범위를 재서 좌/우/상/하 여백과 가로·세로 무게중심 치우침을 알려줍니다.
기준: 좌우·상하 여백 차이 20px 이내, 무게중심 치우침 폭의 3% 이내면 '균형'.
"""
import sys
import numpy as np
from PIL import Image

def check(path, skip_bottom=0):
    im = np.asarray(Image.open(path).convert('RGB')).astype(int)
    h, w, _ = im.shape
    area = im[:h - skip_bottom] if skip_bottom else im
    ah = area.shape[0]
    ink = ((area.max(2) - area.min(2)) > 90) | ((255 - area.mean(2)) > 110)
    ys, xs = np.nonzero(ink)
    if len(xs) == 0:
        return print(path, '그려진 부분 없음')
    L, R, T, B = xs.min(), w - 1 - xs.max(), ys.min(), ah - 1 - ys.max()
    cx, cy = xs.mean() - w / 2, ys.mean() - ah / 2
    ok = abs(L - R) <= 20 and abs(T - B) <= 20 and abs(cx) <= w * .03 and abs(cy) <= ah * .03
    print(f'{path}\n  여백 좌{L} 우{R} 상{T} 하{B} | 무게중심 x{cx:+.0f} y{cy:+.0f} → {"균형" if ok else "확인 필요"}')

if __name__ == '__main__':
    check(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 0)
