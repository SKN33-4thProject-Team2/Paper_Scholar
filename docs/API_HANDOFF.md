# Paper Scholar API 인계 문서

이 문서는 Django 백엔드와 React 화면 사이의 현재 API 계약을 정리합니다. 프론트엔드 담당자는 `frontend/src/api.js`만 교체하거나 확장해 화면 구조와 API 호출을 분리해서 수정할 수 있습니다.

## 로컬 주소

- Django API: `http://127.0.0.1:8000/api`
- React 개발 서버: `http://127.0.0.1:5173`
- 프론트 API 환경변수: `VITE_API_BASE_URL`

백엔드의 `/` 경로는 화면이 아니므로 404가 정상입니다. 연결 확인에는 `GET /api/health/`를 사용합니다.

## 인증과 개인 서재

상태 확인과 회원가입·토큰 발급·토큰 갱신을 제외한 API는 JWT 인증이 필요합니다.

| Method | Path | 설명 |
| --- | --- | --- |
| POST | `/api/auth/register/` | 회원가입 |
| POST | `/api/auth/token/` | 액세스·리프레시 토큰 발급 |
| POST | `/api/auth/token/refresh/` | 액세스 토큰 갱신 |
| GET | `/api/auth/me/` | 현재 로그인 사용자 조회 |

회원가입 요청:

```json
{
  "username": "paper-reader",
  "email": "reader@example.com",
  "password": "StrongPass!2468",
  "password_confirm": "StrongPass!2468"
}
```

로그인 요청은 `username`과 `password`를 보내며, 응답의 `access`와 `refresh` 토큰을 보관합니다. 인증 API 호출에는 다음 헤더를 사용합니다.

```http
Authorization: Bearer <access-token>
```

액세스 토큰은 30분, 리프레시 토큰은 7일 동안 유효합니다. React 클라이언트는 401 응답을 받으면 리프레시 토큰으로 액세스 토큰을 한 번 갱신한 뒤 원래 요청을 재시도합니다.

`Paper`, 본문 섹션, 요약, 번역은 같은 arXiv 논문을 중복 처리하지 않도록 공용 데이터로 저장합니다. 사용자의 소유 관계는 `LibraryEntry(user, paper)`로 별도 관리합니다. 따라서 각 사용자는 본인이 저장한 논문만 목록·상세·본문·요약·번역·RAG 화면에서 볼 수 있고, 같은 논문을 저장한 사용자끼리는 이미 생성된 산출물을 재사용합니다.

## 조회 및 검색

| Method | Path | 설명 |
| --- | --- | --- |
| GET | `/api/health/` | API 상태 확인 |
| POST | `/api/search/` | arXiv 제목 검색 |
| GET | `/api/papers/` | 로그인 사용자의 서재 논문 목록 |
| GET | `/api/papers/{arxiv_id}/` | 논문 상세와 산출물 개수 |
| GET | `/api/papers/{arxiv_id}/sections/` | 본문 섹션 목록 |
| GET | `/api/papers/{arxiv_id}/summary/` | 최종 요약 조회 |
| GET | `/api/papers/{arxiv_id}/translations/` | 번역 목록 조회 |
| GET | `/api/jobs/{job_id}/` | 비동기 작업 상태 조회 |

검색 요청 예시:

```json
{
  "query": "retrieval augmented generation",
  "max_results": 10,
  "sort_by": "r"
}
```

## 저장과 산출물 생성

### 논문 저장

`POST /api/papers/save/`

```json
{
  "papers": [
    {
      "arxiv_id": "1706.03762",
      "title": "Attention Is All You Need",
      "authors": ["Ashish Vaswani"],
      "abstract": "...",
      "pdf_url": "https://arxiv.org/pdf/1706.03762"
    }
  ],
  "extract_content": true
}
```

본문 추출을 요청하면 HTTP 202와 `jobs` 배열을 반환합니다.

### 요약 생성

`POST /api/papers/{arxiv_id}/summarize/`

```json
{ "force": false }
```

### 요약 번역

`POST /api/papers/{arxiv_id}/translate/`

```json
{
  "target_language": "ko",
  "force": false
}
```

요약과 번역 요청은 HTTP 202로 `job`을 반환할 수 있습니다. 프론트는 `GET /api/jobs/{job_id}/`를 폴링하고 `completed`가 되면 해당 조회 API를 다시 호출합니다. 상태 값은 `pending`, `running`, `completed`, `failed`입니다.

현재 작업 실행기는 로컬 개발용 스레드 방식입니다. 운영 배포 시 작업 큐 교체는 배포 담당 범위이며 API 계약은 유지하면 됩니다.

## 논문 질의응답

`POST /api/papers/{arxiv_id}/ask/`

```json
{ "question": "이 논문의 핵심 방법과 결과는 무엇인가요?" }
```

응답 예시:

```json
{
  "arxiv_id": "1706.03762",
  "question": "이 논문의 핵심 방법과 결과는 무엇인가요?",
  "answer": "...",
  "sources": [
    { "index": 1, "text": "논문에서 검색된 근거 문장" }
  ],
  "model": "configured-model"
}
```

RAG는 선택한 논문의 Chroma 본문 청크를 우선 검색하고, 사용할 수 없으면 MySQL에 저장된 본문·요약·번역 내용으로 검색을 대체합니다. 본문 섹션이 없으면 HTTP 409를 반환합니다.

## 오류 응답

일반 오류는 다음 형식을 사용합니다.

```json
{ "detail": "사용자에게 표시할 오류 메시지" }
```

- 400: 요청값 검증 실패
- 401: 인증 정보가 없거나 토큰이 만료됨
- 404: 논문 또는 산출물 없음
- 409: 선행 산출물이 없어 작업 불가
- 500/502: 내부 처리 또는 외부 서비스 실패

## 로컬 검증

```bash
python backend/manage.py test scholar --settings=django_config.test_settings
python backend/manage.py check --settings=django_config.test_settings
cd frontend
npm run lint
npm run build
```

한 번에 검사하려면 `scripts/check_web_integration.sh`를 사용합니다. 현재 점검 결과와
기존 레거시 테스트의 별도 이슈는 `docs/INTEGRATION_STATUS.md`에 기록되어 있습니다.
