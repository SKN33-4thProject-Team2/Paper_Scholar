# 검색 및 웹 Supervisor 실행 구조

## 수정 범위

- 한국어 검색 요청과 약어를 `src/services/search_intent.py`에서 공통 처리한다.
  일반 `/api/search/`, 웹 LangGraph, CLI 키워드 도구가 같은 변환을 사용한다.
- 대용량/대규모 언어 모델, LLM, RAG 등 알려진 용어는 외부 호출 없이 정규화한다.
  그 외 한국어 주제는 키워드 모델을 사용한다. 모델 장애/잘못된 응답을 원문 검색으로 숨기지 않는다.
- 요청 표현은 문장 끝에서만 제거한다. `반도체`, `GPT-4`, `검색 증강 생성`을 보존한다.
- 검색식은 영문 학술 용어의 제목/초록 검색이다. 변환 성공과 검색 결과 유무는 별개다.
- `/api/supervisor/runs/`는 작업을 접수하고, `runs/<id>/`는 상태를 조회한다.
  기존 `/supervisor/plan/`은 호환용으로 남아 있지만 새 웹 화면은 사용하지 않는다.
- 기존 `src/orchestration/graph.py`에 사용자 권한을 확인하는 Django 노드를 주입한다.
  웹 작업은 검색, 저장, 본문 추출, 요약, 번역을 지원한다.
- 사용자별 대화의 검색 후보와 선택 ID는 `SupervisorRun.context`에 저장한다.
  이전 요청이 실패하더라도 완료된 검색 단계의 문맥은 유지한다.
  번호가 없거나 범위를 벗어나면 확인 질문을 하고, 다른 사용자 문맥은 조회하지 않는다.

## 로컬 실행

Python 환경과 `.env`를 준비한 뒤 프로젝트 루트에서 실행한다.

```sh
python manage.py migrate
python manage.py runserver
```

별도 터미널에서 **반드시** 작업 실행기를 실행한다.

```sh
python manage.py run_jobs
```

이 실행기가 없으면 일반 추출/요약/번역과 Supervisor 요청은 `pending`에 머문다.
웹 프로세스에서 작업 스레드를 시작하지 않는다. DB의 대기 행이 작업 큐다.
기본 실행기는 오래된 작업부터 하나씩 처리한다. 여러 실행기를 쓰면 원자적 상태 변경으로
동일 작업의 중복 실행을 방지하지만, 모델 자원 및 공유 논문 저장소 용량을 고려해야 한다.

- 대기 작업은 프로세스 재시작 후 다시 읽는다.
- 실행 중 작업은 15초마다 생존 시각을 갱신한다.
- 2분 이상 생존 확인이 끊긴 작업은 실행기 다음 검사에서 실패로 전환한다.
- 중단된 유료 모델 호출을 자동 재실행하지 않는다. 사용자가 요청을 재전송할 수 있다.
- 한 사용자의 Supervisor 요청은 한 번에 하나만 접수한다.
- 브라우저 새로고침 후 가장 최근 대화와 진행 중 작업을 다시 조회한다.

## 배포

새 마이그레이션 `0004`, `0005` 적용이 필요하다. GitHub 배포와 `deploy.sh`는
`scripts/deploy_backend.sh`를 사용한다.

1. 회귀 검사 통과 후 이미지 빌드.
2. 기존 서비스가 실행 중인 상태에서 DB 마이그레이션 및 Django 설정 검사.
3. 기존 컨테이너를 `paper-scholar-previous`로 보관하고 새 컨테이너 실행.
4. `/api/ready/`로 DB 및 큐 스키마를 확인. 실패하면 이전 컨테이너 재시작.

컨테이너는 Gunicorn과 DB 작업 실행기를 함께 시작한다. 둘 중 하나가 종료되면
컨테이너가 종료되어 Docker 재시작 정책이 적용된다. 신규 데이터/논문 캐시는 named volume에 저장한다.
기존 배포가 볼륨을 쓰지 않았다면 해당 컨테이너의 로컬 캐시를 자동 이관하지는 않는다.
권위 있는 논문/본문/요약/번역 데이터는 기존 MySQL에 유지된다.

운영에서는 DEBUG=False를 강제한다. `DJANGO_SECRET_KEY`가 비어 있으면 시작하지 않는다.
허용 호스트는 `DJANGO_ALLOWED_HOSTS`, CSRF 출처는 `CSRF_TRUSTED_ORIGINS`로 설정한다.
포트 8000은 호스트 loopback에만 연결하므로 같은 호스트의 Nginx가 프록시해야 한다.
HTTP 프록시 외부에 백엔드를 직접 공개하는 구성을 사용하면 별도 조정이 필요하다.
모델은 `SUPERVISOR_MODEL`, `FAST_KEYWORD_MODEL`로 지정하며 기본은 `gpt-4o-mini`다.

이 배포의 마이그레이션은 필드 추가뿐이다. 향후 호환되지 않는 DB 변경에는
컨테이너 복구만으로 충분하지 않으므로 별도 DB 배포 절차가 필요하다.

## 검증

```sh
pip install -r requirements-test.txt
python manage.py test scholar --settings=django_config.test_settings
python manage.py makemigrations --check --dry-run --settings=django_config.test_settings
LANGSMITH_TRACING=false python -m unittest tests.test_search_intent tests.test_orchestration tests.test_deploy_backend
cd frontend
npm ci
npm run lint
node --test tests/*.test.js
npm run build
```

자동 테스트는 실제 LangGraph를 실행하되 외부 arXiv/모델 응답을 대체하고, DB는 메모리 SQLite를 사용한다.
배포 복구 테스트는 Docker와 HTTP를 대체해 실행 순서/실패 처리를 검사한다.
실제 모델의 의미 해석 품질, 운영 MySQL의 동시성 및 실제 Docker 이미지는 별도 환경 검증 대상이다.
