# 평가 실행 안내

평가 코퍼스 v3는 논문 40편과 후보 문항 650건을 보관합니다. 실제 평가는 비용을
제어하면서 모든 논문과 기능을 고르게 포함하도록 고정된 400건만 실행합니다.

| Suite | 후보 문항 | 400건 실행 배분 |
|---|---:|---:|
| artifacts | 40 | 40 |
| retrieval | 400 | 240 |
| deep_research | 80 | 40 |
| pipeline | 80 | 40 |
| refusal | 50 | 40 |
| 합계 | 650 | 400 |

평가 코드는 `evaluation/`과 `evaluation/corpus_v3/`만 사용합니다. 운영용
`data/`, 앱, Streamlit 및 프로젝트 LangGraph의 파일과 DB는 수정하지 않습니다.

## 400건 로컬 평가

아래 명령은 중단 후 다시 실행해도 성공 결과를 재사용합니다. 현재 결과는
`evaluation/corpus_v3/generated/execution_results_v3.jsonl`과
`evaluation_summary_v3.json`에 저장됩니다.

```powershell
conda run -n academic-paper-rag python -m evaluation.run_v3_evaluation `
  --suite all --answer-mode openai --budget 400
```

핵심 결정적 지표는 논문 추출 정확도, 논문 단위 Recall/MRR, 실제 정답 구간
Recall@5/Section MRR, 인용 정밀도, 거절 정확도, 필수 용어 재현율 및 LangGraph
노드 경로 정확도입니다. 1.0인 논문 단위 검색 점수는 선택 논문 ID 안에서
검색하는 구조의 정상 결과이므로, 검색 품질 판단에는 구간 단위 지표를 함께 봅니다.

## LangSmith

`.env`에 `LANGSMITH_API_KEY`가 설정되어 있으면 다음 명령으로 400건의 캐시된
결과를 데이터셋과 실험에 기록합니다. `cached`는 OpenAI 모델을 다시 호출하지
않습니다.

```powershell
conda run -n academic-paper-rag python -m evaluation.evaluate_langsmith `
  --suite all --source cached --budget 400
```

## RAGAS, DeepEval, Promptfoo

| 도구 | 역할 | 기본 입력 |
|---|---|---|
| RAGAS | Faithfulness, Answer Relevancy, Context Precision/Recall | 저장된 v3 결과 |
| DeepEval | 답변 품질과 에이전트 경로 평가 | 저장된 v3 결과 |
| Promptfoo | regression 분할 회귀 테스트 | 400건 중 저장된 사례 |

RAGAS와 DeepEval은 의존성 충돌을 막기 위해 별도 환경에서 실행합니다. 두 도구의
LLM judge는 별도 토큰을 사용하므로 필요한 표본 수를 정한 뒤 실행합니다.

```powershell
conda create -n evaluation_env python=3.12 -y
conda run -n evaluation_env pip install -r evaluation/requirements.txt
conda run -n evaluation_env python -m evaluation.ragas_evaluation --max-cases 2
conda run -n evaluation_env python -m evaluation.deepeval_evaluation --suite retrieval --max-cases 2
```

Promptfoo provider는 기본적으로 400건 실행 캐시를 읽으므로 모델을 재호출하지
않습니다. Node.js와 `npx`가 준비된 환경에서 실행합니다.

```powershell
Set-Location evaluation/promptfoo
$env:PROMPTFOO_PYTHON=(Get-Command python).Source
npx promptfoo@latest eval
```
