# Paper Scholar Frontend

React와 Vite 기반의 Paper Scholar 웹 화면입니다.

## 로컬 실행

```bash
npm install
cp .env.example .env.local
npm run dev
```

기본 API 주소는 `http://localhost:8000/api`입니다. 다른 백엔드를 사용할 때는
`.env.local`의 `VITE_API_BASE_URL`을 변경합니다.

백엔드의 `http://localhost:8000/`은 화면 경로가 아니므로 404가 정상입니다.
연결 상태는 `http://localhost:8000/api/health/`에서 확인합니다.

## 화면 구성

- 검색: arXiv 논문 검색과 선택 저장
- 서재: MySQL에 저장된 논문 목록과 상세 조회
- 상세 탭: 본문 섹션, 요약 생성, 한국어 번역 생성, 근거 기반 질의응답

API 호출은 `src/api.js`, 질의응답 UI는 `src/PaperChat.jsx`에 분리되어 있어
디자인이나 상태 관리 라이브러리를 바꿀 때 개별 파일 단위로 교체할 수 있습니다.

전체 API 계약은 `../docs/API_HANDOFF.md`를 참고합니다.

## 검증

```bash
npm run lint
npm run build
```
