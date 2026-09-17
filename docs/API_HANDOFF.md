# Paper Scholar API 인계 문서

이 문서는 Django 백엔드와 React 화면 사이의 현재 API 계약을 정리합니다. 프론트엔드 담당자는 `frontend/src/api.js`만 교체하거나 확장해 화면 구조와 API 호출을 분리해서 수정할 수 있습니다.

## 로컬 주소

- Django API: `http://127.0.0.1:8000/api`
- React 개발 서버: `http://127.0.0.1:5173`
- 프론트 API 환경변수: `VITE_API_BASE_URL`

백엔드의 `/` 경로는 화면이 아니므로 404가 정상입니다. 연결 확인에는 `GET /api/health/`를 사용합니다.

## 조회 및 검색

| Method | Path | 설명 |
| --- | --- | --- |
| GET | `/api/health/` | API 상태 확인 |
| POST | `/api/search/` | arXiv 제목 검색 |
| GET | `/api/papers/` | MySQL 논문 목록 |
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
