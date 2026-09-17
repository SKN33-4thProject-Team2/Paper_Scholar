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

## 검증

```bash
npm run lint
npm run build
```
