# Paper Scholar Brand Assets

브랜드마크는 **종이 한 장의 모서리가 접힌 형태의 “P”** 와 **별빛 하나**로 구성됩니다.
P는 Paper, 접힌 모서리는 논문 페이지, 별빛은 논문에서 얻는 통찰(Scholar)을 뜻합니다.

## 파일

| 용도 | SVG | PNG (투명 배경) |
|---|---|---|
| 심볼 (밝은 배경) | `symbol.svg` | `png/symbol.png` (512) |
| 심볼 (어두운 배경) | `symbol-dark.svg` | `png/symbol-dark.png` |
| 심볼 (브랜드 블루 배경 위) | `symbol-white.svg` | `png/symbol-white.png` |
| 워드마크 (밝은 배경) | `wordmark.svg` | `png/wordmark.png` (1200 폭) |
| 워드마크 (어두운 배경) | `wordmark-dark.svg` | `png/wordmark-dark.png` |
| 가로형 콤비네이션 (밝은 배경) | `logo-horizontal.svg` | `png/logo-horizontal.png` (1600 폭) |
| 가로형 콤비네이션 (어두운 배경) | `logo-horizontal-dark.svg` | `png/logo-horizontal-dark.png` |
| 앱 아이콘 (둥근 모서리) | `app-icon.svg` | `png/app-icon-1024.png`, `-512`, `-192` |
| 앱 아이콘 (전체 채움) | `app-icon-square.svg` | `png/apple-touch-icon.png` (180) |
| favicon | `favicon.svg` | `png/favicon-16/32/48.png`, `favicon.ico` |

- 심볼과 워드마크는 별도 파일이며, 워드마크 글자는 **윤곽선(패스)으로 변환**되어 있어 폰트가 없어도 깨지지 않습니다.
- 워드마크 서체: Inter Display SemiBold (SIL Open Font License 1.1, 상업적 사용 가능), 자간 -1.2%.
- `symbol*.svg`는 64×64 격자이고 사방에 여백이 포함되어 있습니다. `logo-horizontal*.svg`와 `wordmark*.svg`는 여백 없이 꼭 맞게 잘려 있으므로 배치할 때 아래 여백 규칙을 적용하세요.

## 색상

| 이름 | HEX | 사용처 |
|---|---|---|
| Scholar Blue | `#2D64D8` | 심볼 본체(밝은 배경), 앱 아이콘 배경, UI 강조색 |
| Paper Tint | `#B3CCF6` | 접힌 모서리 |
| Star Yellow | `#F0B93A` | 별빛 (심볼 외에는 상태·작은 강조에만) |
| Ink Navy | `#12213D` | 워드마크 (밝은 배경) |
| Sky Blue (다크용) | `#6CA0F5` | 심볼 본체(어두운 배경) |
| Sky Tint (다크용) | `#BFD5F8` | 접힌 모서리(어두운 배경) |
| Snow | `#F1F5FC` | 워드마크 (어두운 배경) |
| White | `#FFFFFF` | 앱 아이콘 위의 P |

대안 팔레트 후보(확정안 아님): `#3570E0` 선명한 블루, `#2456B8` 차분한 코발트, `#3B7BF0` 가장 밝은 블루. 교체할 때는 본체와 접힌 모서리(본체보다 밝은 틴트)를 함께 바꾸세요.

## 여백 규칙

- **최소 여백(clear space)**: 심볼 본체 P의 폭 `x`(약 38 격자 단위) 기준으로 **0.25x** 를 사방에 확보합니다. 가로형은 P 폭의 1/4입니다.
- **심볼과 워드마크 간격**: 가로형에서 심볼과 글자 사이는 P 폭의 약 42%(16/38)입니다. 가로형 파일을 쓰면 이미 맞춰져 있으니 임의로 벌리거나 좁히지 마세요.
- **워드마크 정렬**: 글자의 대문자 높이 중심이 심볼의 세로 중심과 맞도록 되어 있습니다.
- **최소 크기**: 가로형 높이 24px(폭 약 120px), 심볼 단독 16px 이상. 16px 이하는 `favicon.svg` 또는 `app-icon`을 쓰세요.
- **앱 아이콘**: 타일 대비 심볼 높이 56%. 아이콘 바깥으로 그림자나 테두리를 추가하지 마세요.

## 사용 규칙

- 밝은 배경에는 `*.svg`, 어두운 배경에는 `*-dark.svg`, 브랜드 블루 배경 위에는 `symbol-white.svg`를 씁니다.
- 별의 노란색은 바꾸지 마세요. 심볼에 그림자, 외곽선, 그라데이션, 3D 효과를 넣지 마세요.
- 심볼을 회전하거나 늘려서 비율을 바꾸지 마세요. 심볼과 글자의 색을 임의로 섞지 마세요.
- 사진처럼 복잡한 배경 위에서는 흰색 또는 짙은 네이비 단색 영역 위에 올리세요.
