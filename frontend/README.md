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

- 인증: 회원가입, JWT 로그인, 자동 토큰 갱신, 로그아웃
- Supervisor: 자연어 복합 요청을 검색·저장·추출·요약·번역 순서로 실행
- 검색: arXiv 논문 검색과 선택 저장
- 서재: 로그인 사용자가 저장한 논문 목록과 상세 조회
- 상세 탭: 본문 섹션, 요약 생성, 한국어 번역 생성, 근거 기반 질의응답

인증 상태는 `src/AuthContext.jsx`, 로그인·회원가입 화면은 `src/AuthPage.jsx`,
API 호출과 JWT 자동 갱신은 `src/api.js`, 질의응답 UI는 `src/PaperChat.jsx`에 분리되어 있어
디자인이나 상태 관리 라이브러리를 바꿀 때 개별 파일 단위로 교체할 수 있습니다.

논문 원본과 본문·요약·번역 결과는 서버에서 공용으로 재사용하되, 사용자별 서재 소유 관계가 분리됩니다. 로그인한 사용자는 본인 서재에 추가한 논문만 화면에서 조회할 수 있습니다.

Supervisor 화면은 별도 논문 기능을 구현하지 않습니다. `src/SupervisorChat.jsx`가 계획 API의 응답을 받아 `src/api.js`에 이미 연결된 기능 API를 순서대로 호출합니다. 따라서 각 기능 담당자는 기존 API 계약을 유지하면서 구현을 독립적으로 교체할 수 있습니다.

전체 API 계약은 `../docs/API_HANDOFF.md`를 참고합니다.

## 검증

```bash
npm run lint
npm run build
```
