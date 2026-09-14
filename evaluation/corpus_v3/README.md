# Evaluation Corpus v3

운영용 `data/`와 완전히 분리된 학술 논문 평가 코퍼스입니다. 이 폴더의 생성물은
애플리케이션, Streamlit, LangGraph 및 팀원이 사용하는 운영 DB에 연결되지 않습니다.

## 구성

- `manifest.jsonl`: 평가 논문 40편의 고정 ID, 제목, 분야 및 데이터 분할
- `source_pdfs/`: 평가 전용 PDF 40편
- `generated/saved_papers_eval.db`: 평가용 PDF 메타데이터
- `generated/extracted_papers.db`: 평가용 본문
- `generated/extracted_papers_ref.db`: 평가용 참고문헌
- `generated/extracted_papers.json`: `DeepSearch` 호환 평가용 카탈로그
- `dataset_v3.jsonl`: 총 650개의 평가 사례
- `generated/build_report.json`: 파일 해시와 생성 결과 검증 보고서

## 문항 은행과 실행 규모

| Suite | 건수 |
|---|---:|
| artifacts | 40 |
| retrieval | 400 |
| deep_research | 80 |
| pipeline | 80 |
| refusal | 50 |
| 합계 | 650 |

650건은 향후 표본을 교체하거나 확장할 수 있도록 보존하는 후보 문항 은행입니다.
현재 실제 실행 예산은 400건이며, `artifacts 40 / retrieval 240 /
deep_research 40 / pipeline 40 / refusal 40`으로 논문 40편을 균형 있게 포함합니다.

논문 단위 분할은 `dev 8편 / regression 12편 / final 20편`이며, 동일 논문이
서로 다른 분할에 섞이지 않습니다. 거절 사례까지 포함한 문항 분할은
`dev 130건 / regression 195건 / final 325건`입니다.

## 생성 방법

프로젝트의 `academic-paper-rag` conda 환경에서 실행합니다.

```powershell
conda run -n academic-paper-rag python evaluation/corpus_v3/build_corpus.py
```

다시 내려받으려면 `--force-download`, 다시 추출하려면 `--force-extract`를
추가합니다. 네트워크 없이 데이터셋만 다시 생성할 때는 다음을 사용합니다.

```powershell
conda run -n academic-paper-rag python evaluation/corpus_v3/build_corpus.py --skip-download --skip-extract
```

## 격리 원칙

빌더는 이 `corpus_v3` 폴더 안에서만 파일을 생성하거나 갱신합니다. 기존
`data/paper_extract`, `data/paper_save`, `data/paper_list`는 읽기만 하며,
원본 프로젝트의 Python 파일은 수정하지 않습니다. 평가 실행기는 평가 전용 DB와
경로만 의존성 주입으로 연결합니다.
