# 원제: Translating Natural Language Instructions for Behavioral Robot Navigation with a Multi-Head Attention Mechanism

[본문 전체 마크다운 번역 결과]

# 다중 헤드 어텐션 메커니즘을 활용한 행동 기반 로봇 내비게이션을 위한 자연어 지시문 번역

Patricio Cerda-Mardini, Vladimir Araujo, Alvaro Soto  
칠레 가톨릭대학교  
데이터 기초연구 밀레니엄 연구소  
{pcerdam, vgaraujo}@uc.cl, asoto@ing.puc.cl

## 초록

본 연구에서는 실내 로봇 내비게이션을 위해 자연어를 고수준 행동 언어로 변환하는 신경망 모델의 융합 계층으로 다중 헤드 어텐션 메커니즘을 제안한다. 이를 위해 내비게이션 그래프를 해당 과제의 지식 기반으로 활용하는 Zang et al.(2018a)의 프레임워크를 따른다. 실험 결과, 학습 과정에서 관찰하지 못한 환경에서 지시문을 번역할 때 성능이 크게 향상되었으며, 이를 통해 모델의 일반화 능력이 개선됨을 확인했다.

## 배경

자연어 지시를 따를 수 있는 로봇 에이전트를 개발하는 일은 여전히 해결되지 않은 과제이다. 이상적으로 로봇은 사용자의 자연어 지시를 바탕으로 실행 가능한 내비게이션 계획을 정확하게 생성할 수 있어야 한다. 목표는 복잡하지만 알려진 실내 환경(그림 1(a))에서 출발지로부터 목적지에 도달하는 것이다. 이러한 환경은 그래프로 표현할 수 있으며(Sepulveda et al., 2018), 노드는 장소(예: 사무실, 침실)를, 간선은 로봇이 인접한 노드 사이를 이동할 수 있도록 하는 고수준 행동(예: 복도 따라가기, 사무실 나가기)을 나타낸다(그림 1(b)). 본 연구에서는 로봇이 Sepulveda et al.(2018)과 같이 모든 고수준 행동을 안정적으로 수행할 수 있다고 가정한다.

기존 연구에서는 이 문제를 지시문을 순차적으로 실행되는 고수준 행동 계획으로 변환하는 문제로 정식화했으며(Zang et al., 2018b), 그래프 표현을 통해 환경의 위상 정보를 활용했다(Zang et al., 2018a). 구체적으로 지도학습 모델은 사용자의 텍스트 지시문, 로봇의 초기 위치, 그리고 $(n_{1}, b, n_{2})$ 형태의 삼중항으로 인코딩된 환경의 행동 그래프를 입력으로 받는다. 여기서 $n_{1}$과 $n_{2}$는 장소이고 $b$는 두 장소를 연결하는 행동이다. 이후 일반적인 시퀀스-투-시퀀스 모델과 그래프 및 지시문 정보를 융합하는 단일 소프트 어텐션 계층을 사용하여, 지시된 목적지에 도달하기 위한 행동 시퀀스를 예측한다.

그러나 추론 시점에 이 접근법은 학습 중 관찰하지 못한 환경에서 성능이 크게 저하되는 문제를 보인다. 본 연구에서는 어텐션 계층을 다중 헤드 구조로 수정하여 모델의 일반화 능력을 향상하고, 이에 따라 미관측 환경에서의 성능을 높이고자 한다.

> **그림 1: (a) 환경 지도. (b) 행동 내비게이션 그래프. (c) 제안 모델.** (c)의 자연어 지시문은 순차적인 행동 계획으로 변환된다. (a)에서 빨간색으로 강조된 경로와 (b)에서 빨간색으로 표시된 노드 및 간선은 모델 (c)가 예측한 행동에 해당한다.  
> 자연어 지시문: “방에서 나와 오른쪽으로 돌아서, 꽃병을 지날 때까지 복도를 따라간 다음, 왼쪽에 있는 다음 방으로 들어가세요.”

## 방법론

## 접근법

Transformer 모델이 다중 모달 데이터의 다양한 관계를 인코딩하는 데 성공한 점에 착안하여(Vaswani et al., 2017; Tan and Bansal, 2019; Zhou et al., 2020), 자연어 지시문과 내비게이션 그래프라는 두 표현 공간의 정보를 보다 유용한 방식으로 융합하기 위해 Transformer의 다중 헤드 어텐션 메커니즘을 활용한다. 즉, 각 헤드는 두 정보원 사이의 서로 다른 패턴을 융합하는 데 특화된다. 이러한 능력이 디코더가 테스트 시점의 새로운 환경에서 발생하는 성능 저하를 완화하는 데 도움이 될 것이라고 가정한다.

## 제안 모델

제안하는 구조(그림 1(c))는 초기 인코딩 계층으로 구성된다. 이 계층에서는 사전 학습된 GloVe 표현(Pennington et al., 2014)을 사용하여 지시문의 각 단어를 인코딩하고, 각 삼중항 집합은 $B$개의 행동과 $N$개의 노드 중 어떤 항목이 해당 삼중항을 구성하는지를 나타내도록 원-핫 인코딩한다. 이후 양방향 게이트 순환 유닛(bi-directional Gated Recurrent Unit, GRU)(Chung et al., 2014)을 사용하여 이러한 인코딩을 임베딩한다.

그다음 새롭게 추가된 다중 헤드 어텐션 메커니즘을 통해 다중 모달 표현을 융합한다. 이후 연결된 완전연결 계층은 융합된 정보의 차원을 축소하며, 이렇게 얻은 정보는 순환 GRU 디코더가 사용하는 문맥 $C$가 된다. 디코더는 초기 위치를 입력으로 받고 지시문을 순차적인 행동 계획으로 변환하며, 각 시간 단계에서 문맥 $C$에 소프트 어텐션을 적용한다. 손실 함수는 정답 번역에 대한 교차 엔트로피로 정의한다.

## 실험 설정

Zang et al.(2018a)이 소개한 데이터셋과 기존의 학습 및 테스트 분할을 사용한다. 여기서 Test-Repeated 분할에는 학습 시 에이전트가 이미 관찰한 환경이 포함되어 있으며, Test-New 분할에는 이전에 관찰하지 못한 지도가 포함되어 있다. 전체적으로 100개의 지도에 걸쳐 10,040개의 지시문을 사용하며, 이 중 8,066개는 학습에 사용된다. 각 지도에는 6~65개의 방이 포함되어 있다.

또한 기존 연구와 동일한 성능 지표를 사용한다. 구체적으로 F1 점수, 정답과의 편집 거리(edit distance, ED), 그리고 M@k 지표를 사용한다. M@k에서는 번역 결과가 정답으로부터 $k$회의 이동 이내에 있으면 일치로 간주하며¹, M@0은 완전 일치를 의미한다.

모델은 배치 크기 256으로 200 에포크 동안 학습했다. 다중 헤드 어텐션 계층은 4개의 헤드로 설정했다. 그 외의 모델 매개변수는 Zang et al.(2018a)에서 사용한 설정과 동일하게 유지했다.

## 결과 및 논의

## 결과

표 1은 본 연구의 접근법과 Zang et al.(2018a)이 보고한 기준 모델, 그리고 해당 기준 모델을 자체 구현한 결과의 성능을 보여준다. 자체 구현한 기준 모델은 Test-Repeated 집합에서 기대한 수준의 성능을 보이지 못했다는 점에 주목할 필요가 있다.

다중 헤드 접근법을 사용한 결과, Test-New 집합의 완전 일치 성능이 23.2% 향상되었다. 이는 본 연구의 번역 모델이 더 우수한 일반화 능력을 갖는다는 점을 뒷받침한다. 그러나 Test-Repeated 집합에서는 기존 접근법에 비해 완전 일치 성능이 8.5% 감소했다. 다만 이 집합에서는 자체 구현한 기준 모델보다 25.9%, Test-New 집합에서는 18.4% 높은 성능을 기록했다.

| 구조 | Test-Repeated |  |  |  |  | Test-New |  |  |  |  |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 구조 | F1 ↑ | M@0 ↑ | M@1 ↑ | M@2 ↑ | ED ↓ | F1 | M@0 | M@1 | M@2 | ED |
| 기준 모델(Zang) | **93.54** | **61.17** | **83.30** | **92.19** | **0.75** | 90.22 | 41.71 | 69.82 | 82.08 | 1.22 |
| 기준 모델(자체 구현) | 91.67 | 44.43 | 76.93 | 89.16 | 1.01 | 90.89 | 43.41 | 72.64 | 87.25 | 1.09 |
| 본 연구 | 93.07 | 55.96 | 81.31 | 90.16 | 0.84 | **92.57** | **51.40** | **79.06** | **89.43** | **0.91** |

> **표 1: 결과.** 기호 ↑는 해당 열에서 값이 클수록 더 우수함을 의미하며, 기호 ↓는 값이 작을수록 더 우수함을 의미한다.

## 결론

본 연구에서는 지식 기반을 활용하여 자연어를 로봇이 이해하고 실행할 수 있는 고수준 행동 언어로 변환하는 데 유용한 메커니즘으로 다중 헤드 어텐션을 도입했다. 그 결과, 이전 연구에 비해 한 번도 관찰하지 못한 환경에서 더 우수한 성능을 보였다. 향후 연구에서는 이미 관찰한 지도에서의 성능 저하를 최소화하고, 생성된 어텐션 가중치에 대한 정성적 분석을 수행할 예정이다.

## 감사의 글

본 연구는 데이터 기초연구 밀레니엄 연구소와 Fondecyt 보조금 1181739의 부분적인 지원을 받아 수행되었다.

¹ 이동 1회는 계획 내 행동을 추가, 삭제 또는 교체하는 연산이다.

## 참고문헌

Junyoung Chung, Çaglar Gülçehre, Kyunghyun Cho, and Yoshua Bengio. 2014. 게이트 순환 신경망의 시퀀스 모델링에 대한 실증적 평가. *arXiv*, abs/1412.3555.

Jeffrey Pennington, Richard Socher, and Christopher D. Manning. 2014. GloVe: 단어 표현을 위한 전역 벡터. *EMNLP*.

Gabriel Sepulveda, Juan Carlos Niebles, and Alvaro Soto. 2018. 심층학습 기반 행동 접근법을 활용한 실내 자율 내비게이션. *2018 IEEE International Conference on Robotics and Automation (ICRA)*, 4646–4653쪽. IEEE.

Hao Tan and Mohit Bansal. 2019. LXMERT: Transformer를 활용한 교차 모달 인코더 표현 학습. *Proceedings of the 2019 Conference on Empirical Methods in Natural Language Processing and the 9th International Joint Conference on Natural Language Processing (EMNLP-IJCNLP)*, 5103–5114쪽.

Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit, Llion Jones, Aidan N. Gomez, Lukasz Kaiser, and Illia Polosukhin. 2017. Attention is all you need. *31st Conference on Neural Information Processing Systems*, NIPS ’17.

Xiaoxue Zang, Ashwini Pokle, Marynel Vázquez, Kevin Chen, Juan Carlos Niebles, Alvaro Soto, and Silvio Savarese. 2018a. 자연어 내비게이션 지시문을 행동 기반 로봇 내비게이션을 위한 고수준 계획으로 변환하기. *Proceedings of the 2018 Conference on Empirical Methods in Natural Language Processing*, 2657–2666쪽, 브뤼셀, 벨기에, 10–11월. Association for Computational Linguistics.

Xiaoxue Zang, Marynel Vázquez, Juan Carlos Niebles, Alvaro Soto, and Silvio Savarese. 2018b. 자연어 방향 지시를 활용한 행동 기반 실내 내비게이션. *Companion of the 2018 ACM/IEEE International Conference on Human-Robot Interaction*.

Yichao Zhou, Shaunak Mishra, Manisha Verma, Narayan Bhamidipati, and Wei Wang. 2020. 시각-언어 표현을 활용한 광고 크리에이티브 디자인 테마 추천.