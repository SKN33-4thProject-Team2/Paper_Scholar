# 웹 통합 점검 결과

점검일: 2026-09-17

## 이번 작업 범위

다음 흐름을 Django API와 React 화면 기준으로 점검했습니다.

1. 회원가입, JWT 로그인·갱신, 현재 사용자 조회
2. 사용자별 서재 격리와 공용 논문 산출물 재사용
3. arXiv 검색
4. 선택 논문 저장 및 본문 추출 작업 등록
5. 본문 섹션 조회
6. 요약 생성 및 상태 조회
7. 한국어 번역 생성 및 상태 조회
8. 선택 논문 기반 RAG 질의응답과 근거 반환
9. Supervisor 복합 명령 계획과 기존 기능 순차 실행

## 통과한 점검

- Django 시스템 검사: 통과
- Django `scholar` 테스트: 54개 통과
- MySQL 저장소·요약/번역 동기화·오케스트레이션 관련 기존 테스트: 31개 통과
- React 정적 검사: 통과
- React 프로덕션 빌드: 통과
- Git whitespace 검사: 통과

인증 점검에는 실제 `Authorization: Bearer` 헤더를 사용한 사용자 조회와 토큰 갱신, 미인증 요청 차단, 사용자 A/B의 서재·산출물 접근 격리 검증이 포함됩니다.

Supervisor 점검에는 인증 요구, 모호한 주제의 실행 차단, 유사 논문 수 계산, 검색→저장→추출→요약→번역 계획 검증이 포함됩니다. 기존 기능 구현은 변경하지 않았으며 React가 현재 API를 조합해 실행합니다.

동일한 검증은 프로젝트 루트에서 아래 명령으로 재실행할 수 있습니다.

```bash
PAPER_SCHOLAR_PYTHON=/path/to/python scripts/check_web_integration.sh
```

## 전체 레거시 테스트에서 확인된 별도 문제

`python -m unittest discover -s tests -p 'test_*.py'` 실행 결과, 이번 웹/DB 변경과 직접 관련 없는 기존 테스트 불일치가 남아 있습니다.

- `tests/test_deep_research.py`: 제거된 `SQLitePaperRepository`를 여전히 import함
- `tests/test_paper_extractor.py`: 현재 `paper_sections` 저장 구조와 과거 `extracted` 테이블 테스트가 불일치함
- `tests/test_quality_evaluation.py`: 체크인된 평가 산출물의 제목 보존 기대값과 실제 데이터가 불일치함
- 실제 Ollama 호출 테스트 3개는 `RUN_MODEL_INTEGRATION_TESTS=1`이 없어 정상적으로 건너뜀

이 항목들은 PDF 추출기·평가 데이터·과거 CLI 저장소 호환성 범위이므로 이번 Django/React 통합 커밋에서는 동작 코드를 임의로 변경하지 않았습니다.

## 로컬 환경 의존성 경고

`python -m pip check`에서 현재 가상환경의 다음 충돌을 확인했습니다.

```text
langchain-mcp-adapters 0.3.2 requires mcp>=1.24.0,<2.0.0,
but mcp 2.0.0 is installed.
```

현재 프로젝트 코드에서는 MCP 패키지를 직접 import하지 않아 이번 웹 기능 실행에는 영향이 없지만, 환경 정리 시 `mcp` 버전을 호환 범위로 맞춰야 합니다.

## 배포 담당자 참고

- JWT 액세스 토큰 유효기간은 30분, 리프레시 토큰은 7일입니다.
- 브라우저는 현재 토큰을 `localStorage`에 저장하므로 운영 환경에서는 HTTPS와 XSS 방어 헤더를 반드시 적용해야 합니다.
- 현재 비동기 작업 실행기는 개발용 프로세스 내부 스레드입니다.
- Docker/AWS 구성과 운영 작업 큐 교체는 별도 담당 범위입니다.
- 작업 큐를 교체하더라도 `ProcessingJob` 상태와 API 응답 계약은 유지하는 편이 프론트 수정 범위를 줄입니다.
