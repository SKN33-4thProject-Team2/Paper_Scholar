"""로그 코드별 레벨, 이벤트 이름, 사용자 메시지 정의."""

from __future__ import annotations

from .log_codes import LogCode


LOG_MESSAGES: dict[LogCode, dict[str, str]] = {
    LogCode.OLLAMA_CONNECTION_CHECKED: {
        "level": "INFO",
        "event": "ollama_connection_checked",
        "message": "Ollama 서버 연결 및 모델 설치 상태를 확인했습니다.",
    },
    LogCode.OLLAMA_GENERATION_SUCCEEDED: {
        "level": "INFO",
        "event": "ollama_generation_succeeded",
        "message": "Ollama가 응답 생성을 완료했습니다.",
    },
    LogCode.OLLAMA_CONNECTION_FAILED: {
        "level": "ERROR",
        "event": "ollama_connection_failed",
        "message": "Ollama 서버에 연결하지 못했습니다.",
    },
    LogCode.OLLAMA_GENERATION_FAILED: {
        "level": "ERROR",
        "event": "ollama_generation_failed",
        "message": "Ollama 응답 생성 요청에 실패했습니다.",
    },
    LogCode.OLLAMA_CONFIG_LOAD_FAILED: {
        "level": "ERROR",
        "event": "ollama_config_load_failed",
        "message": "Ollama 설정 파일을 불러오지 못했습니다.",
    },
    LogCode.KEYWORD_GENERATION_STARTED: {
        "level": "INFO",
        "event": "keyword_generation_started",
        "message": "학술 검색 키워드 생성을 시작합니다.",
    },
    LogCode.KEYWORD_GENERATION_SUCCEEDED: {
        "level": "INFO",
        "event": "keyword_generation_succeeded",
        "message": "학술 검색 키워드 6개를 생성했습니다.",
    },
    LogCode.KEYWORD_GENERATION_FALLBACK: {
        "level": "WARNING",
        "event": "keyword_generation_fallback",
        "message": "키워드 생성 또는 응답 처리 문제로 기본 키워드를 사용합니다.",
    },
    LogCode.KEYWORD_GENERATION_REJECTED: {
        "level": "WARNING",
        "event": "keyword_generation_rejected",
        "message": "검색어가 비어 있어 키워드 생성을 시작하지 않았습니다.",
    },
    LogCode.KEYWORD_GENERATION_FAILED: {
        "level": "ERROR",
        "event": "keyword_generation_failed",
        "message": "Ollama가 중복 없는 유효한 학술 검색 키워드 6개를 반환하지 않았습니다.",
    },
    LogCode.PAPER_EXTRACTION_STARTED: {
        "level": "INFO",
        "event": "paper_extraction_started",
        "message": "논문 PDF 본문 추출을 시작합니다.",
    },
    LogCode.PAPER_EXTRACTION_SKIPPED: {
        "level": "INFO",
        "event": "paper_extraction_skipped",
        "message": "이미 추출된 논문이라 건너뜁니다.",
    },
    LogCode.PAPER_EXTRACTION_SUCCEEDED: {
        "level": "INFO",
        "event": "paper_extraction_succeeded",
        "message": "논문 본문을 가공해 저장했습니다.",
    },
    LogCode.PAPER_EXTRACTION_REJECTED: {
        "level": "WARNING",
        "event": "paper_extraction_rejected",
        "message": "요청한 논문의 PDF를 찾지 못해 추출하지 않았습니다.",
    },
    LogCode.PAPER_EXTRACTION_FAILED: {
        "level": "ERROR",
        "event": "paper_extraction_failed",
        "message": "논문 PDF 본문 추출에 실패했습니다.",
    },
    LogCode.PAGE_VISION_FALLBACK: {
        "level": "WARNING",
        "event": "page_vision_fallback",
        "message": "해당 쪽의 비전 판독에 실패해 로컬 추출 결과로 대체했습니다.",
    },
    LogCode.PAGE_VISION_UNAVAILABLE: {
        "level": "WARNING",
        "event": "page_vision_unavailable",
        "message": "NVIDIA API 키가 없어 로컬 추출만 사용합니다.",
    },
    LogCode.SECTION_CLASSIFY_FALLBACK: {
        "level": "WARNING",
        "event": "section_classify_fallback",
        "message": "대단원 분류를 모델로 하지 못해 낱말 규칙으로 대체했습니다.",
    },
    LogCode.PAPER_SEARCH_STARTED: {
        "level": "INFO",
        "event": "paper_search_started",
        "message": "arXiv 외부 학술 논문 검색을 시작합니다.",
    },
    LogCode.PAPER_SEARCH_SUCCEEDED: {
        "level": "INFO",
        "event": "paper_search_succeeded",
        "message": "arXiv 외부 학술 논문 검색을 성공적으로 완료했습니다.",
    },
    LogCode.PAPER_SEARCH_REJECTED: {
        "level": "WARNING",
        "event": "paper_search_rejected",
        "message": "검색 조건이 비어 있거나 취소되어 외부 논문 검색을 수행하지 않았습니다.",
    },
    LogCode.PAPER_SEARCH_FAILED: {
        "level": "ERROR",
        "event": "paper_search_failed",
        "message": "arXiv 외부 학술 논문 검색 처리 중 오류가 발생했습니다.",
    },
    LogCode.PAPER_SAVE_STARTED: {
        "level": "INFO",
        "event": "paper_save_started",
        "message": "검색된 논문 메타데이터 저장을 시작합니다.",
    },
    LogCode.PAPER_SAVE_SUCCEEDED: {
        "level": "INFO",
        "event": "paper_save_succeeded",
        "message": "선택한 논문 메타데이터를 서재 DB 및 JSON에 성공적으로 저장했습니다.",
    },
    LogCode.PAPER_SAVE_REJECTED: {
        "level": "WARNING",
        "event": "paper_save_rejected",
        "message": "저장할 논문이 선택되지 않아 저장을 건너뜁니다.",
    },
    LogCode.PAPER_SAVE_FAILED: {
        "level": "ERROR",
        "event": "paper_save_failed",
        "message": "논문 메타데이터를 저장하는 중 오류가 발생했습니다.",
    },
    LogCode.TRANSLATION_STARTED: {
        "level": "INFO",
        "event": "translation_started",
        "message": "논문 번역을 시작합니다."
    },
    LogCode.TRANSLATION_CHUNK_STARTED: {
        "level": "INFO",
        "event": "translation_chunk_started",
        "message": "논문 청크 번역을 시작합니다."
    },
    LogCode.TRANSLATION_RESUMED: {
        "level": "INFO",
        "event": "translation_resumed",
        "message": "임시 체크포인트에서 논문 번역을 재개합니다."
    },
    LogCode.TRANSLATION_RETRYING: {
        "level": "WARNING",
        "event": "translation_retrying",
        "message": "복구 가능한 오류로 논문 청크 번역을 재시도합니다."
    },
    LogCode.TRANSLATION_CHUNK_SPLIT: {
        "level": "WARNING",
        "event": "translation_chunk_split",
        "message": "출력 토큰 한도를 초과한 번역 청크를 더 작게 분할합니다."
    },
    LogCode.TRANSLATION_TABLE_PRESERVED: {
        "level": "WARNING",
        "event": "translation_table_preserved",
        "message": "표 번역 구조를 검증하지 못해 원문 표를 그대로 보존합니다."
    },
    LogCode.TRANSLATION_SUCCEEDED: {
        "level": "INFO",
        "event": "translation_succeeded",
        "message": "논문 번역을 완료했습니다."
    },
    LogCode.TRANSLATION_CHECKPOINT_SAVED: {
        "level": "INFO",
        "event": "translation_checkpoint_saved",
        "message": "번역 재개용 임시 체크포인트를 저장했습니다."
    },
    LogCode.TRANSLATION_CHECKPOINT_DELETED: {
        "level": "INFO",
        "event": "translation_checkpoint_deleted",
        "message": "번역 완료 후 임시 체크포인트를 삭제했습니다."
    },
    LogCode.TRANSLATION_MARKDOWN_SAVED: {
        "level": "INFO",
        "event": "translation_markdown_saved",
        "message": "논문 번역 마크다운 산출물을 저장했습니다.",
    },
    LogCode.TRANSLATION_REJECTED: {
        "level": "WARNING",
        "event": "translation_rejected",
        "message": "번역 조건을 충족하지 못해 논문 번역을 시작하지 않았습니다.",
    },
    LogCode.TRANSLATION_CHECKPOINT_INVALID: {
        "level": "WARNING",
        "event": "translation_checkpoint_invalid",
        "message": "임시 체크포인트를 재사용할 수 없어 처음부터 번역합니다.",
    },
    LogCode.TRANSLATION_FAILED: {
        "level": "ERROR",
        "event": "translation_failed",
        "message": "논문 번역에 실패했습니다. 잠시 후 다시 시도해 주세요.",
    },
    LogCode.TRANSLATION_CHECKPOINT_FAILED: {
        "level": "ERROR",
        "event": "translation_checkpoint_failed",
        "message": "번역 재개용 임시 체크포인트 처리에 실패했습니다.",
    },
    LogCode.TRANSLATION_MARKDOWN_SAVE_FAILED: {
        "level": "ERROR",
        "event": "translation_markdown_save_failed",
        "message": "논문 번역 마크다운 산출물을 저장하지 못했습니다.",
    },
    LogCode.SUMMARY_STARTED: {
        "level": "INFO",
        "event": "summary_started",
        "message": "번역된 논문의 구조화 요약을 시작합니다.",
    },
    LogCode.SUMMARY_CHUNK_STARTED: {
        "level": "INFO",
        "event": "summary_chunk_started",
        "message": "논문 청크에서 요약 근거 추출을 시작합니다.",
    },
    LogCode.SUMMARY_RESUMED: {
        "level": "INFO",
        "event": "summary_resumed",
        "message": "임시 체크포인트에서 논문 요약을 재개합니다.",
    },
    LogCode.SUMMARY_RETRYING: {
        "level": "WARNING",
        "event": "summary_retrying",
        "message": "일시적인 오류로 논문 요약 생성을 재시도합니다.",
    },
    LogCode.SUMMARY_REDUCE_STARTED: {
        "level": "INFO",
        "event": "summary_reduce_started",
        "message": "청크별 근거를 논문의 최종 4단 요약으로 통합합니다.",
    },
    LogCode.SUMMARY_SUCCEEDED: {
        "level": "INFO",
        "event": "summary_succeeded",
        "message": "논문의 4단 구조 요약을 완료했습니다.",
    },
    LogCode.SUMMARY_MARKDOWN_SAVED: {
        "level": "INFO",
        "event": "summary_markdown_saved",
        "message": "논문 요약 마크다운 산출물을 저장했습니다.",
    },
    LogCode.SUMMARY_CHECKPOINT_SAVED: {
        "level": "INFO",
        "event": "summary_checkpoint_saved",
        "message": "요약 재개용 청크 체크포인트를 저장했습니다.",
    },
    LogCode.SUMMARY_CHECKPOINT_DELETED: {
        "level": "INFO",
        "event": "summary_checkpoint_deleted",
        "message": "요약 완료 후 임시 체크포인트를 삭제했습니다.",
    },
    LogCode.SUMMARY_REJECTED: {
        "level": "WARNING",
        "event": "summary_rejected",
        "message": "요약 조건을 충족하지 못해 논문 요약을 시작하지 않았습니다.",
    },
    LogCode.SUMMARY_CHECKPOINT_INVALID: {
        "level": "WARNING",
        "event": "summary_checkpoint_invalid",
        "message": "임시 체크포인트를 재사용할 수 없어 처음부터 요약합니다.",
    },
    LogCode.SUMMARY_FAILED: {
        "level": "ERROR",
        "event": "summary_failed",
        "message": "논문 요약 생성에 실패했습니다.",
    },
    LogCode.SUMMARY_MARKDOWN_SAVE_FAILED: {
        "level": "ERROR",
        "event": "summary_markdown_save_failed",
        "message": "논문 요약 마크다운 산출물을 저장하지 못했습니다.",
    },
    LogCode.SUMMARY_CHECKPOINT_FAILED: {
        "level": "ERROR",
        "event": "summary_checkpoint_failed",
        "message": "요약 재개용 임시 체크포인트 처리에 실패했습니다.",
    },
    LogCode.SUMMARY_STORAGE_STARTED: {
        "level": "INFO",
        "event": "summary_storage_started",
        "message": "논문 요약의 Vector DB 저장을 시작합니다.",
    },
    LogCode.SUMMARY_STORAGE_SUCCEEDED: {
        "level": "INFO",
        "event": "summary_storage_succeeded",
        "message": "논문 요약을 Vector DB에 저장했습니다.",
    },
    LogCode.SUMMARY_STORAGE_FAILED: {
        "level": "ERROR",
        "event": "summary_storage_failed",
        "message": "논문 요약을 Vector DB에 저장하지 못했습니다.",
    },
    LogCode.DEEP_RESEARCH_LIST_STARTED: {
        "level": "INFO",
        "event": "deep_research_list_started",
        "message": "Deep Research 대상 논문 목록을 조회합니다.",
    },
    LogCode.DEEP_RESEARCH_ANSWER_STARTED: {
        "level": "INFO",
        "event": "deep_research_answer_started",
        "message": "선택한 논문을 근거로 Deep Research 답변을 생성합니다.",
    },
    LogCode.DEEP_RESEARCH_RELATED_SEARCH_STARTED: {
        "level": "INFO",
        "event": "deep_research_related_search_started",
        "message": "선택한 논문의 참고문헌 기반 관련 논문 검색을 시작합니다.",
    },
    LogCode.DEEP_RESEARCH_LIST_SUCCEEDED: {
        "level": "INFO",
        "event": "deep_research_list_succeeded",
        "message": "Deep Research 대상 논문 목록을 불러왔습니다.",
    },
    LogCode.DEEP_RESEARCH_PAPER_SELECTED: {
        "level": "INFO",
        "event": "deep_research_paper_selected",
        "message": "Deep Research 대상 논문을 선택했습니다.",
    },
    LogCode.DEEP_RESEARCH_ANSWER_SUCCEEDED: {
        "level": "INFO",
        "event": "deep_research_answer_succeeded",
        "message": "선택한 논문을 근거로 Deep Research 답변을 생성했습니다.",
    },
    LogCode.DEEP_RESEARCH_RELATED_SEARCH_SUCCEEDED: {
        "level": "INFO",
        "event": "deep_research_related_search_succeeded",
        "message": "참고문헌 기반 관련 논문 검색을 완료했습니다.",
    },
    LogCode.DEEP_RESEARCH_REQUEST_REJECTED: {
        "level": "WARNING",
        "event": "deep_research_request_rejected",
        "message": "Deep Research 요청을 처리할 수 없어 사용자 입력을 다시 요청합니다.",
    },
    LogCode.DEEP_RESEARCH_ANSWER_FAILED: {
        "level": "ERROR",
        "event": "deep_research_answer_failed",
        "message": "Deep Research 답변 생성에 실패했습니다.",
    },
    LogCode.DEEP_RESEARCH_RELATED_SEARCH_FAILED: {
        "level": "ERROR",
        "event": "deep_research_related_search_failed",
        "message": "참고문헌 기반 관련 논문 검색에 실패했습니다.",
    },
}
