# 원제: Primal-Attention: Self-attention through Asymmetric Kernel SVD in Primal Representation

[본문 전체 마크다운 번역 결과]

# Primal-Attention: 원초 표현에서 비대칭 커널 SVD를 통한 자기 어텐션

Yingyi Chen${}^{*}$, Qinghua Tao${}^{*}$, Francesco Tonin, Johan A. K. Suykens  
ESAT-STADIUS, KU Leuven, Belgium  
${}^{*}$공동 제1저자  
${}^{2}$구현 코드는 https://github.com/yingyichen-cyy/PrimalAttention 에서 제공된다.  
NeurIPS 2023

## 초록

최근 트랜스포머의 자기 어텐션을 커널 머신으로 해석하여 이해하고 개선하려는 연구가 활발히 이루어지고 있다. 그러나 기존 연구는 비대칭 자기 어텐션에 대칭 커널을 위한 방법을 적용하므로, 이론적 분석과 수치적 구현 사이에 무시하기 어려운 간극이 존재한다. 본 논문에서는 비대칭 커널 특이값 분해(Kernel Singular Value Decomposition, KSVD)를 통해 자기 어텐션을 표현하고 최적화하는 새로운 관점을 제시한다. 이는 심층 층에서 자기 어텐션이 일반적으로 보이는 저랭크 특성에도 동기를 얻는다.

비대칭 KSVD를 통해 다음을 수행한다. i) 자기 어텐션의 원초-쌍대 표현을 정식화하고, 최적화 목적을 어텐션 출력에서의 투영 분산을 최대화하는 문제로 변환한다. ii) KSVD의 원초 표현을 이용한 새로운 어텐션 메커니즘인 Primal-Attention을 제안하여 쌍대 표현의 커널 행렬을 명시적으로 계산하지 않는다. iii) KKT 조건을 이용해 Primal-Attention에서 KSVD 최적화의 정상해가 목적 함수값 0을 갖는다는 것을 증명한다.

이에 따라 KSVD 최적화는 별도의 분해 없이 정규화 손실을 단순히 최소화하는 방식으로 구현할 수 있으며, 이를 통해 저랭크 특성을 촉진한다. 수치 실험에서 제안한 Primal-Attention은 향상된 효율성과 함께 최신 수준의 성능을 보인다. 또한 KSVD 최적화가 적용된 Primal-Attention은 표준 자기 어텐션보다 더 가파른 특이값 감소를 보이며, 본 방법의 가능성을 추가로 확인하였다. 우리가 아는 한, 본 연구는 자기 어텐션의 비대칭 커널에 대해 원초-쌍대 표현을 제시하고 이를 모델링과 최적화에 성공적으로 적용한 최초의 연구이다.

## 1. 서론

트랜스포머[1]는 자연어 처리[2, 3, 4], 컴퓨터 비전[5, 6, 7, 8], 강화학습[9, 10, 11] 등 다양한 과제에서 최신 수준의 성능을 달성하며 널리 사용되고 있다. 이러한 성공에서 자기 어텐션 블록은 핵심적인 역할을 한다. 자기 어텐션은 쿼리, 키, 밸류를 이용하여 데이터 시퀀스 내 개체들 사이의 복잡한 의존성을 표현한다. 그러나 트랜스포머의 이론적 이해는 뛰어난 경험적 성능에 비해 여전히 뒤처져 있다.

> **그림 1: ImageNet-1K[23]에서 자기 어텐션 행렬의 스펙트럼 분석.** (a)–(c)는 사전 학습된 DeiT-Small/16[7]과 Primal.+DeiT-Small/16(본 연구)의 선택된 층에서 어텐션 행렬 특이값에 대한 누적 설명 분산의 평균과 표준편차를 나타낸다. 깊은 층으로 갈수록 어텐션 행렬의 특이값 감소가 더 가파르게 나타나며, 이는 (d)에서도 확인된다. (c)에서는 두 모델의 마지막 층, 즉 “L[11]”로 표시한 11번째 층의 자기 어텐션 행렬에 대한 누적 설명 분산 곡선도 도시하였다. 제안 방법은 기준 모델보다 향상된 저랭크 특성을 보인다.

최근에는 내적 어텐션 연산을 커널 행렬로 볼 수 있다는 커널 기반 관점이 제안되었다[12]. 이는 오랫동안 연구되어 해석 가능성이 높은 커널 방법[13]과 트랜스포머를 연결한다는 점에서 고무적이다. 이러한 관점을 따라 자기 어텐션을 개선하기 위한 다양한 연구가 제안되었다[14, 15, 16, 17, 18, 19]. 그러나 이들 연구에서 사용하는 커널 기법은 대칭성을 요구하는 Mercer 커널[20]에 기반하며, 이는 본질적으로 비대칭적인 자기 어텐션의 설정과 일치하지 않는다.

[21]은 재생 커널 바나흐 공간(Reproducing Kernel Banach Spaces, RKBS)[22]에 기반한 비대칭 커널을 이용해 어텐션을 분석적으로 특성화하였다. 그러나 비대칭성이나 관련 최적화는 개선에 활용되지 않았다. [19]는 서포트 벡터 회귀로부터 원초-쌍대 표현을 이용해 자기 어텐션을 유도하지만, 여전히 Mercer 커널을 위한 기법을 사용한다. 또한 지도학습 과제에서 가정하는 자기 어텐션의 정답 출력은 실제로 존재하지 않는 경우가 많아 최적화에 적용하기 어렵다.

본 연구에서는 비대칭 KSVD에 기반한 원초-쌍대 표현으로 자기 어텐션을 해석하는 새로운 관점을 제시한다. 이를 통해 이론과 구현에서 비대칭성을 무시해 발생하던 간극을 해소한다. 구체적으로 비지도 설정에서 자기 어텐션을 원초 표현, 즉 Primal-Attention으로 재구성하고 그에 맞게 최적화한다.

본 방법은 두 가지 주요 동기에 기반한다. 첫째, 그림 1(d)에서 보이듯 트랜스포머의 어텐션 행렬은 저랭크일 수 있으며, 이 특성은 네트워크의 깊은 층으로 갈수록 더욱 뚜렷해진다. 둘째, 자기 어텐션 행렬은 본질적으로 비대칭 커널 행렬이다[12, 21]. 이에 따라 저랭크성과 비대칭성을 모두 고려하는 자기 어텐션용 KSVD를 제안한다.

본 연구의 기여는 다음과 같다.

- 비대칭 커널을 사용하는 KSVD로 자기 어텐션을 특성화한다. 대칭 커널 기반 방법을 사용하는 기존 연구와 달리, 자기 어텐션의 실제 설정에 더욱 부합하도록 비대칭성을 고려한다. (2절)
- KSVD를 통해 자기 어텐션의 원초-쌍대 표현을 유도하고, 쌍대 표현에서 발생하는 비용이 큰 커널 계산을 피하는 원초 기반의 새로운 어텐션인 Primal-Attention을 제안한다. KSVD에서 밸류는 특성의 분산을 최대로 만드는 투영 가중치로 해석되며, 투영 방향 수를 제한함으로써 저랭크 특성을 추구할 수 있다. (3절, 4절)
- 유도된 KSVD의 정상해가 제약 없는 원초 문제에서 목적 함수값 0을 만든다는 것을 증명한다. 따라서 Primal-Attention의 KSVD 최적화는 추가적인 분해 연산 없이 손실 함수에 정규화 항을 더해 효율적으로 수행할 수 있다. (4절)
- 수치 실험에서 Primal-Attention은 다양한 데이터셋에서 최신 수준의 성능과 표준 자기 어텐션보다 우수한 효율성을 보인다. 또한 KSVD에서 유도된 최적화가 더 가파른 특이값 감소를 갖는 어텐션을 학습하도록 정규화하여, 보다 저랭크인 특성을 학습하게 함을 확인한다. (5절)

## 2. 문제 설정: 비대칭 커널을 이용한 자기 어텐션

입력 데이터 시퀀스를 $\{x_i\in\mathbb{R}^d\}_{i=1}^N$이라 하자. 자기 어텐션[1]에서 쿼리, 키, 밸류는 입력 시퀀스의 선형 투영으로 출력된다.

$q(x_i)=W_qx_i,\quad k(x_i)=W_kx_i,\quad v(x_i)=W_vx_i,$

여기서 $W_q\in\mathbb{R}^{d_q\times d}$, $W_k\in\mathbb{R}^{d_k\times d}$, $W_v\in\mathbb{R}^{d_v\times d}$이며 일반적으로 $d_q=d_k$로 설정한다. 어텐션 점수는 다음과 같다.

$a(x_i,x_j)=\frac{\langle q(x_i),k(x_j)\rangle}{\sqrt{d_k}}=\frac{\langle W_qx_i,W_kx_j\rangle}{\sqrt{d_k}}.$

표준 자기 어텐션에서는 비선형성과 양의 값을 도입하기 위해 소프트맥스 활성화를 적용하여 어텐션 가중치를 얻는다.

$\kappa(x_i,x_j)=\operatorname{softmax}\left(\frac{\langle W_qx_i,W_kx_j\rangle}{\sqrt{d_k}}\right),\quad i,j=1,\ldots,N.$

[12]와 유사하게 어텐션 행렬 $K:=[\kappa(x_i,x_j)]\in\mathbb{R}^{N\times N}$은 원소가 $\kappa(x_i,x_j)$인 커널 행렬로 해석할 수 있다. 여기서 $\kappa(\cdot,\cdot):\mathbb{R}^d\times\mathbb{R}^d\to\mathbb{R}$는 커널 함수이다. 일반적으로 $\langle W_qx_i,W_kx_j\rangle\neq\langle W_qx_j,W_kx_i\rangle$이므로 비대칭 커널이 되며, 이에 따라 $K_{ij}\neq K_{ji}$이다.

각 헤드에서 자기 어텐션의 출력 $o_i\in\mathbb{R}^{d_v}$는 다음과 같이 주어진다.

$o_i=\sum_{j=1}^Nv(x_j)\kappa(x_i,x_j)=\sum_{j=1}^Nv(x_j)K_{ij},\quad i=1,\ldots,N.$

트랜스포머에서는 일반적으로 여러 헤드를 연결하여 사용한다[1].

### 비대칭 어텐션 행렬

커널 방법에서는 재생 커널 힐베르트 공간(RKHS)[13]의 커널 트릭을 통해 대칭 및 양의 준정부호인 Mercer 커널[20]을 다룬다. 반면 트랜스포머[1]의 어텐션 커널 행렬은 식 (2)에서 보인 것처럼 비대칭이다.

자기 어텐션 개선을 위해 커널 해석을 활용한 기존 연구[14, 17, 18, 19]는 모두 Mercer 커널에 기반하므로 자기 어텐션의 비대칭적 본질과 일치하지 않는다. 이와 달리 재생 커널 바나흐 공간(RKBS)[22]의 커널 트릭에서는 비대칭성을 허용한다.

**정의 2.1** ([21]의 정의 2, [24]의 정리 2.1, [25]). 비대칭 커널의 경우, $\kappa(\cdot,\cdot):\mathcal{X}\times\mathcal{Z}\to\mathbb{R}$인 RKBS의 커널 트릭은 각각 $\mathcal{X}$와 $\mathcal{Z}$ 위의 바나흐 공간 $\mathcal{B}_{\mathcal{X}},\mathcal{B}_{\mathcal{Z}}$에서 정의된 두 실수 가측 특성 사상의 내적으로 다음과 같이 정의된다.

$\kappa(x,z)=\langle\phi_x(x),\phi_z(z)\rangle,\quad \forall x\in\mathcal{X},\ \phi_x\in\mathcal{B}_{\mathcal{X}},\ z\in\mathcal{Z},\ \phi_z\in\mathcal{B}_{\mathcal{Z}}.$

정의 2.1에 따라 자기 어텐션의 커널 행렬은 RKBS의 커널 트릭으로 특성화할 수 있으며, 이는 커널 표현 정리의 관점에서 분석 도구를 제공한다.

### SVD와 이동 고유값 문제

SVD는 주어진 $r$-랭크 행렬 $A\in\mathbb{R}^{N\times M}$을 두 집합의 직교정규 고유기저로 분해한다.

$A=U\Sigma V^\top,\quad \Sigma=\operatorname{diag}\{\sigma_1,\ldots,\sigma_r\},$

여기서 양의 특이값은 $\sigma_i$이고, $U\in\mathbb{R}^{N\times r}$와 $V\in\mathbb{R}^{M\times r}$의 열은 각각 좌특이벡터와 우특이벡터이다[26]. $U$와 $V$는 식 (5)에 나타난 것처럼 열과 행에 관한 부분공간 투영을 나타내며, 비대칭성으로 인해 $A$에 존재하는 서로 다른 정보를 담는다. $A$가 정사각 대칭 행렬이면 SVD는 $U=V$인 고유값 분해로 환원된다.

[27]은 최소제곱 서포트 벡터 머신(LSSVM)[28]을 이용한 SVD의 새로운 변분 원리를 제안하였다. 이때 쌍대 문제는 SVD에 관한 Lanczos[29]의 분해 정리에 대응하는 이동 고유값 문제로 이어진다.

**정리 2.2 (Lanczos[29]).** 임의의 영이 아닌 행렬 $A\in\mathbb{R}^{N\times M}$은 다음과 같이 쓸 수 있다.

$A=\widetilde U\widetilde\Sigma\widetilde V^\top,$

여기서 $\widetilde U,\widetilde\Sigma,\widetilde V$는 다음의 이동 고유값 문제로 정의된다.

$A\widetilde V=\widetilde U\widetilde\Sigma,\quad A^\top\widetilde U=\widetilde V\widetilde\Sigma.$

$\widetilde U\in\mathbb{R}^{N\times r}$와 $\widetilde V\in\mathbb{R}^{M\times r}$는 $\widetilde U^\top\widetilde U=I_r$, $\widetilde V^\top\widetilde V=I_r$를 만족하며, $\widetilde\Sigma\in\mathbb{R}^{r\times r}$는 양의 원소를 갖는 대각 행렬이다.

## 3. 커널 SVD에 기반한 자기 어텐션의 원초-쌍대 표현

이 절에서는 RKBS의 커널 트릭을 비대칭 어텐션 커널에 적용하고, KSVD에 기반한 원초-쌍대 표현으로 자기 어텐션을 유도한다. 이 학습 체계에서는 쌍대 표현의 커널 행렬을 명시적으로 계산하지 않고 원초 표현에서 어텐션 출력을 재구성하여 새로운 자기 어텐션 메커니즘을 제안한다. 또한 정상성 조건을 이용해 KSVD 최적화를 추가 손실 항으로 구현함으로써 별도의 분해 없이 모델의 저랭크 특성을 정규화한다.

### 원초 및 쌍대에서의 KSVD 최적화 문제

정의 2.1에 따라 자기 어텐션의 비대칭 커널 $K$에 대한 쌍대 커널 함수는 다음과 같이 쓸 수 있다.

$K_{ij}=\kappa(x_i,x_j):=\langle\phi_q(x_i),\phi_k(x_j)\rangle,$

여기서 $\phi_q,\phi_k$는 쿼리와 키에 관련된 두 특성 사상이다. 식 (3)의 자기 어텐션 출력에서 $\{v(x_j)\}_{j=1}^N$은 커널 방법의 쌍대 표현에서 커널 행렬을 투영하는 쌍대 변수와 유사하며, 이때 커널은 비대칭이다.

이에 따라 LSSVM 체계에서의 SVD 비선형 확장[27]은 자기 어텐션 설정에 적합하다. 본 연구에서는 [27]의 행렬 SVD 설정을 쿼리와 키라는 두 입력 데이터 원천을 갖는 비대칭 어텐션 행렬로 확장한다. 또한 자기 어텐션에서 밸류가 입력 데이터에 의존한다는 점을 고려하여 데이터 의존적 투영 가중치를 도입한다.

주어진 시퀀스 $\{x_i\in\mathbb{R}^d\}_{i=1}^N$에 대해 KSVD의 원초 최적화 문제를 다음과 같이 정의한다.

$\max_{W_e,W_r,\{e_i\},\{r_j\}}J=\frac{1}{2}\sum_{i=1}^Ne_i^\top\Lambda e_i+\frac{1}{2}\sum_{j=1}^Nr_j^\top\Lambda r_j-\operatorname{Tr}(W_e^\top W_r)$

$\text{s.t. }e_i=(f(X)^\top W_e)^\top\phi_q(x_i),\quad i=1,\ldots,N,$

$r_j=(f(X)^\top W_r)^\top\phi_k(x_j),\quad j=1,\ldots,N.$

여기서 데이터 의존적 투영 가중치는 $f(X)^\top W_e=:W_{e|X}\in\mathbb{R}^{p\times s}$ 및 $f(X)^\top W_r=:W_{r|X}\in\mathbb{R}^{p\times s}$로 정의되며, $W_e,W_r\in\mathbb{R}^{N\times s}$에 의존한다. $\phi_q(\cdot),\phi_k(\cdot):\mathbb{R}^d\to\mathbb{R}^p$는 특성 사상이고, $e_i,r_j\in\mathbb{R}^s$는 투영 점수이다. $\Lambda\in\mathbb{R}^{s\times s}$는 양의 대각 정규화 행렬이다.

원초 최적화의 목적 함수 $J$는 쿼리와 키에 대해 $W_{e|X}^\top\phi_q(x_i)$와 $W_{r|X}^\top\phi_k(x_j)$의 투영 분산을 최대화하며, 두 투영을 결합하는 정규화 항도 포함한다. 쌍대에서의 해는 최대 투영 분산을 갖는 방향을 나타내는 좌특이벡터와 우특이벡터로 표현된다. 따라서 식 (6)의 원초 최적화를 통해 자기 어텐션의 학습은 어텐션 행렬에 대한 SVD 문제로 해석된다.

원초 최적화 문제의 주요 요소는 다음과 같다.

1. 투영 가중치는 데이터 의존적이다. $f(X)=:F_X\in\mathbb{R}^{N\times p}$는 시퀀스 데이터 $X=[x_1,\ldots,x_N]^\top\in\mathbb{R}^{N\times d}$의 정보를 포함하는 변환 행렬이다. $X$가 주어지면 $F_X$는 상수 행렬이며, 실험에서는 이를 $X$에 선형적으로 의존하도록 설정한다. $F_X$를 항등 행렬로 설정하면 원초 커널 방법의 일반적인 설정으로 환원된다.
2. 쿼리와 키에 관련된 특성 사상은 각각 $\phi_q(x_i):=g_q(q(x_i))$, $\phi_k(x_i):=g_k(k(x_i))$로 정의한다. 여기서 $g_q:\mathbb{R}^{d_q}\to\mathbb{R}^p$와 $g_k:\mathbb{R}^{d_k}\to\mathbb{R}^p$는 식 (1)의 선형 투영 위에 구성된 사상이다.
3. $\phi_q(x_i),\phi_k(x_j)\in\mathbb{R}^p$를 $W_{e|X},W_{r|X}\in\mathbb{R}^{p\times s}$로 투영하면 $s$개 방향의 투영 점수 $e_i,r_j\in\mathbb{R}^s$를 얻는다. 일반적으로 $s<p$이며, 이는 쌍대 최적화에서 유도되는 커널 행렬의 특이값 개수에 대응한다.

**비고 3.1 (분산 최대화 목적).** KSVD 문제의 원초 목적 함수는 특성 공간에서 $W_{e|X},W_{r|X}$ 방향으로 이루어진 두 투영 $e_i,r_j$의 분산을 공동으로 최대화한다. 따라서 $e_i,r_j$는 쿼리와 키에 관해 $\phi_q$와 $\phi_k$에 공통으로 존재하는 최대 정보를 포착하도록 학습된다.

라그랑주 쌍대성과 KKT 조건을 이용하면 식 (6)의 쌍대 최적화 문제가 비대칭 어텐션 커널 $K$의 SVD에 대응하는 이동 고유값 문제로 이어짐을 보일 수 있다.

**정리 3.2 (자기 어텐션에서 KSVD의 쌍대 최적화 문제).** 라그랑주 쌍대성과 KKT 조건에 따라 식 (6)의 쌍대 최적화는 다음을 만족한다.

$KH_r=H_e\Sigma,\quad K^\top H_e=H_r\Sigma,$

여기서 $\Sigma\in\mathbb{R}^{s\times s}$는 양의 대각 행렬이며, $H_e=[h_{e1},\ldots,h_{eN}]^\top\in\mathbb{R}^{N\times s}$와 $H_r=[h_{r1},\ldots,h_{rN}]^\top\in\mathbb{R}^{N\times s}$는 각각 좌특이벡터와 우특이벡터 역할을 하는 쌍대 변수이다.

비대칭 커널 행렬에 대한 커널 트릭은 다음과 같이 해석된다.

$K_{ij}=\langle f(X)g_q(q(x_i)),f(X)g_k(k(x_j))\rangle=:\langle\phi'_q(x_i),\phi'_k(x_j)\rangle.$

정리 3.2에서 $\Sigma=\Lambda^{-1}$이며, 이는 식 (6)의 0이 아닌 $\Lambda$에 대응한다. Lanczos 분해 정리에 따라 $\Sigma$는 어텐션 커널 $K$의 특이값, $H_e$와 $H_r$는 각각 좌특이벡터와 우특이벡터에 대응한다. 따라서 $K=H_e\Sigma H_r^\top$이다.

### KSVD의 쌍대 표현으로서의 자기 어텐션

KSVD 문제의 원초-쌍대 모델 표현을 제시하면 다음과 같다.

$\text{원초: }\ e(x)=W_{e|X}^\top\phi_q(x),\quad r(x)=W_{r|X}^\top\phi_k(x),$

$\text{쌍대: }\ e(x)=\sum_{j=1}^Nh_{rj}\kappa(x,x_j),\quad r(x)=\sum_{i=1}^Nh_{ei}\kappa(x_i,x).$

표준 자기 어텐션의 출력 $o_i$는 식 (8)의 쌍대 표현에 나타난 투영 점수 $e(x)$에 대응한다. 즉, 표준 자기 어텐션에서 밸류 $\{v(x_j)\}_{j=1}^N$를 쌍대 변수 $\{h_{rj}\}_{j=1}^N$로 선택하면 밸류는 $K$의 우특이벡터 역할을 한다.

이 관점에서 자기 어텐션의 최적화 목표는 식 (6)과 같이 $e_i,r_j$의 최대 분산을 공동으로 포착하는 것으로 해석할 수 있다. 그러나 표준 자기 어텐션은 $e_i$ 점수만 출력한다. 따라서 비대칭 어텐션 커널의 우특이벡터와 관련된 투영 점수만 고려한다.

## 4. Primal-Attention

### 모델링

커널 표현을 사용하지 않고도 어텐션 출력을 동등하게 표현할 수 있다는 점은 중요하다. 이는 커널 행렬 계산을 피할 수 있게 한다. KSVD의 관점에서는 식 (8)의 $h_{ei}$에 포함된 좌특이벡터와 관련된 또 다른 투영 $r_j$가 존재하며, 이는 비대칭 커널 행렬에 포함된 추가 정보를 제공한다.

본 연구에서는 KSVD의 원초 표현을 활용한 새로운 어텐션 메커니즘인 Primal-Attention을 제안한다. 이를 위해 두 개의 명시적 특성 사상 $\phi_q,\phi_k$를 사용한다. 자기 어텐션 커널 행렬의 비대칭성을 충분히 활용하기 위해 좌특이벡터와 우특이벡터를 이용한 두 투영을 연결하여 어텐션 출력을 다음과 같이 정의한다.

$o_i:=[e_i;r_i]=[W_{e|X}^\top\phi_q(x_i);W_{r|X}^\top\phi_k(x_i)]=[W_e^\top f(X)g_q(q(x_i));W_r^\top f(X)g_k(k(x_i))].$

Primal-Attention에서 원초의 투영 가중치 $W_{e|X},W_{r|X}$는 쌍대의 밸류에 대응한다. $f(X)=F_X$를 항등 행렬로 설정하면 식 (6)의 KSVD 문제는 [27]의 데이터 비의존적 투영 가중치 경우로 환원된다. 이때 비대칭 어텐션 커널의 커널 트릭은 다음과 같다.

$K_{ij}=\langle g_q(q(x_i)),g_k(k(x_j))\rangle=\langle\phi_q(x_i),\phi_k(x_j)\rangle.$

### 비선형성을 위한 특성 사상의 선택

표준 자기 어텐션은 어텐션 점수 행렬에 비선형성을 도입하기 위해 소프트맥스를 사용한다. 본 연구의 설정과 커널 트릭 관점에서 이는 다음과 같이 표현할 수 있다.

$\kappa(x_i,x_j)=\widehat D^{-1}\langle\phi_q(x_i),\phi_k(x_j)\rangle,$

$\phi_q(x):=g(q(x)),\quad \phi_k(x):=g(k(x)),$

$g(z):=\exp(-\|z\|^2/2)(\exp(w_1^\top z),\ldots,\exp(w_p^\top z)),$

여기서 $w_i\sim\mathcal{N}(0,I_{d_q})$, $d_q=d_k$이며 $\widehat D:=\operatorname{diag}(\phi_q(X)(\phi_k(X)^\top\mathbf{1}_N))$이다. 투영 점수는 다음과 같이 대응한다.

$e(x)=\widehat D^{-1/2}W_{e|X}^\top\phi_q(x),\quad r(x)=\widehat D^{-1/2}W_{r|X}^\top\phi_k(x).$

그러나 이 경우 두 개의 지수 특성 사상을 구성하고 모든 표본에 대한 정규화 인자 $\widehat D$를 계산해야 한다. 본 연구에서는 모든 실험에서 쿼리와 키에 대한 코사인 유사도 커널과 관련된 특성 사상을 사용한다.

$\phi_q(x)=g_q(q(x)):=\frac{q(x)}{\|q(x)\|_2},\quad \phi_k(x)=g_k(k(x)):=\frac{k(x)}{\|k(x)\|_2}.$

이는 구현이 간단하면서 특성 사상에 비선형성과 정규화를 모두 제공한다.

### 최적화

KSVD 문제는 원초에서 제약 최적화 문제로, 또는 쌍대에서 커널 행렬 $K$에 대한 이동 고유값 문제(SVD)로 최적화할 수 있다. Primal-Attention에서는 원초에서 최적화한다.

**보조정리 4.2 (정상해에서의 목적 함수값 0).** 쌍대 최적화의 이동 고유값 문제를 만족하는 $H_e,H_r,\Sigma$의 해는 원초 최적화 문제의 목적 함수 $J$를 0으로 만든다.

이 성질에 따라 쌍대에서 커널 행렬 $K$의 SVD를 직접 계산하는 대신, Primal-Attention의 최적화는 원초 목적 함수를 0으로 만드는 방식으로 수행한다.

$\min\ \mathcal{L}+\eta\sum_lJ_l^2,$

여기서 $\mathcal{L}$은 과제 관련 손실이며, 예를 들어 분류 과제에서는 교차 엔트로피 손실이다. 합산 항의 $J_l$은 제안한 Primal-Attention을 사용하는 모든 어텐션 블록의 목적 함수이며, 각 $J_l$은 모든 헤드에 대한 평균으로 구현된다. $\eta>0$는 정규화 계수이다.

각 Primal-Attention 헤드에 대해 목적 함수는 다음과 같다.

$J(W_e,W_r,\Lambda)=\frac{1}{2}\sum_{i=1}^Ne_i^\top\Lambda e_i+\frac{1}{2}\sum_{j=1}^Nr_j^\top\Lambda r_j-\operatorname{Tr}(W_e^\top W_r).$

이를 원초 변수로 다시 쓰면 다음과 같다.

$J=\frac{1}{2}\sum_{i=1}^N\|(W_{e|X}\Lambda_e^{1/2})^\top\phi_q(x_i)\|_2^2+\frac{1}{2}\sum_{j=1}^N\|(W_{r|X}\Lambda_r^{1/2})^\top\phi_k(x_j)\|_2^2-\operatorname{Tr}(W_e^\top W_r).$

여기서 $\Lambda$는 최적화 과정에서 자동으로 결정된다. 따라서 Primal-Attention의 KSVD 최적화는 정규화 손실을 추가하여 쉽게 구현할 수 있다. Primal-Attention은 KSVD의 원초 표현으로 자기 어텐션을 표현할 뿐 아니라, KSVD의 최적화를 어텐션 정규화에 활용한다. 목적 함수가 0에 도달하면 KSVD의 정상성 조건을 만족하게 된다.

## 5. 수치 실험

본 절에서는 시계열, 장거리 시퀀스 모델링, 강화학습, 이미지 분류, 언어 모델링의 다섯 가지 벤치마크에서 트랜스포머에 적용한 Primal-Attention의 효과를 검증한다.

두 종류의 트랜스포머를 고려한다.

1. **PrimalFormer(Primal.)**: 모든 어텐션 층에 Primal-Attention을 적용하고 KSVD 손실로 정규화한다.
2. **Primal.+**: 트랜스포머 계열 기준 모델의 마지막 층을 Primal-Attention으로 대체한다. 이는 대규모 데이터와 복잡한 과제에서 정보 압축을 줄여야 하는 경우에 적합하다.

두 가지 주요 하이퍼파라미터는 식 (10)의 계수 $\eta$와 식 (6)의 KSVD 투영 방향 수 $s$이다. 데이터 의존적 설정에서는 효율성을 위해 $X$에서 $n=\min\{10s,N\}$개의 점을 균일하게 표본 추출한다. 존슨–린덴스트라우스 보조정리에 따르면 무작위 선형 투영으로 행렬의 주요 패턴을 보존할 수 있다.

### 5.1 UEA 시계열 분류

UEA 시계열 분류 아카이브[31]는 시간적 시퀀스를 평가하기 위한 벤치마크이다. [11]을 따라 전처리된 다변량 데이터셋 10개를 선택하고, 은닉 차원 512, 8개 헤드, 자기 어텐션 임베딩 차원 64인 2층 트랜스포머를 백본으로 사용하였다. 하이퍼파라미터는 $\eta\in\{0.1,0.2,0.5\}$, $s\in\{20,30,40\}$에서 탐색하였다.

**표 1. UEA 시계열 분류 벤치마크의 테스트 정확도(%).**

| 데이터셋 | Trans. | Linear. | Re. | Long. | Per. | YOSO-E | Cos. | SOFT | Flow. | Primal. | Primal.+Trans. |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| EthanolConcentration | 32.7 | 31.9 | 31.9 | 32.3 | 31.2 | 31.2 | 32.3 | 33.5 | 33.8 | 33.1 | **35.4** |
| FaceDetection | 67.3 | 67.0 | 68.6 | 62.6 | 67.0 | 67.3 | 64.8 | 67.1 | 67.6 | 67.1 | 63.8 |
| HandWriting | 32.0 | 34.7 | 27.4 | 39.6 | 32.1 | 30.9 | 28.9 | 34.7 | 33.8 | 29.6 | 28.7 |
| HeartBeat | 76.1 | 76.6 | 77.1 | 78.0 | 75.6 | 76.5 | 77.1 | 75.6 | 77.6 | 76.1 | 77.1 |
| JapaneseVowels | 98.7 | 99.2 | 97.8 | 98.9 | 98.1 | 98.6 | 98.3 | 99.2 | 98.9 | 98.4 | 98.9 |
| PEMS-SF | 82.1 | 82.1 | 82.7 | 83.8 | 80.9 | 85.2 | 83.2 | 80.9 | 83.8 | 89.6 | **90.2** |
| SelfRegulationSCP1 | 92.2 | 92.5 | 90.4 | 90.1 | 91.5 | 91.1 | 91.1 | 91.8 | 92.5 | 92.5 | 92.5 |
| SelfRegulationSCP2 | 53.9 | 56.7 | 56.7 | 55.6 | 56.7 | 53.9 | 55.0 | 55.6 | 56.1 | **57.2** | 56.1 |
| SpokenArabicDigits | 98.4 | 98.0 | 97.0 | 94.4 | 98.4 | 98.9 | 98.4 | 98.8 | 98.8 | — | — |
| UWaveGestureLibrary | 85.6 | 85.0 | 85.6 | 87.5 | 85.3 | 88.4 | 85.6 | 85.0 | 86.6 | 86.3 | **88.4** |
| 평균 정확도 | 71.9 | 72.4 | 71.5 | 72.0 | 71.9 | 72.2 | 71.5 | 72.2 | 73.0 | 73.0 | **73.1** |

PrimalFormer와 Primal.+는 Flowformer[11]와 비교해 대등하거나 더 우수한 성능을 보인다. 특히 Primal.+는 마지막 층의 소프트맥스 자기 어텐션만 Primal-Attention으로 대체하여 표준 트랜스포머보다 전체적으로 1.2% 향상된 최고 정확도를 달성했다. 이는 표준 소프트맥스 자기 어텐션에 비해 Primal-Attention이 시간적 모델링 능력을 향상시킬 가능성을 보여준다.

**표 2. UEA 벤치마크의 실행 시간과 메모리 사용량.**

| 모델 | 평균 시간(초/에폭) | 평균 메모리(GB) |
|---|---:|---:|
| Trans. | 2.5 (1×) | 10.9 (1×) |
| Flow. | 2.2 (1.1×) | 2.8 (3.9×) |
| Primal.+Trans. | 1.9 (1.3×) | 6.5 (1.7×) |
| Primal. | **1.9 (1.3×)** | **2.7 (4.0×)** |

두 Primal. 모델은 표준 트랜스포머보다 지속적으로 높은 효율을 보였다. Primal.은 대부분의 경우 Flowformer보다도 실행 시간과 메모리 측면에서 우수하다.

### 5.2 Long-Range Arena 벤치마크

Long-Range Arena(LRA)[39]는 수식 계산(ListOps), 리뷰 분류(Text), 문서 검색(Retrieval), 이미지 분류(Image), 이미지 공간 의존성(Pathfinder)을 포함하는 장거리 시퀀스 벤치마크이다. 2층 트랜스포머를 백본으로 사용했으며, 은닉 차원은 128, 헤드 수는 2, 임베딩 차원은 64이다.

**표 3. LRA 벤치마크의 테스트 정확도(%).**

| 데이터셋 | Trans. | Re. | Per. | Lin. | Nyström. | Long. | YOSO-E | Primal. | Primal.+Trans. |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ListOps | 37.1 | 19.1 | 18.8 | 37.3 | 37.2 | 37.2 | 37.3 | 37.3 | 37.3 |
| Text | 65.0 | 64.9 | 63.8 | 55.9 | 65.5 | 64.6 | 64.7 | 61.2 | 65.4 |
| Retrieval | 79.4 | 78.6 | 78.6 | 79.4 | 79.6 | 81.0 | 81.2 | 77.8 | 81.0 |
| Image | 38.2 | 43.3 | 37.1 | 37.8 | 41.6 | 39.1 | 39.8 | 43.0 | **43.9** |
| Pathfinder | 74.2 | 69.4 | 69.9 | 67.6 | 70.9 | 73.0 | 72.9 | 68.3 | **74.3** |
| 평균 정확도 | 58.8 | 55.1 | 53.6 | 55.6 | 59.0 | 59.0 | 59.2 | 57.5 | **60.4** |

PrimalFormer는 Reformer, Performer, Linformer보다 높은 정확도와 우수한 효율성을 보였다. Primal.+Trans.는 60.4%의 최신 수준 정확도를 달성했으며, 이는 트랜스포머보다 1.6%, YOSO-E보다 1.2% 높다.

**표 4. LRA에서의 효율성 비교.**

| 모델 | 평균 시간(초/1K steps) | 평균 메모리(GB) |
|---|---:|---:|
| Trans. | 592.6 (1×) | 11.45 (1×) |
| Nyström. | 155.8 (약 3.8×) | 1.95 (약 7.5×) |
| Lin. | 153.3 (약 3.9×) | 3.68 (약 3.1×) |
| Per. | 210.2 (약 2.8×) | 3.59 (약 3.3×) |
| Re. | 221.2 (약 2.7×) | 3.52 (약 3.4×) |
| Primal.+Trans. | 300.6 (약 2.0×) | 11.05 (약 1.1×) |
| Primal. | **131.7 (약 4.5×)** | **1.59 (약 7.2×)** |

### 5.3 강화학습

연속 제어 과제를 위해 설계된 D4RL 벤치마크[47]에서 오프라인 강화학습 성능을 평가하였다. HalfCheetah, Hopper, Walker 환경과 Medium-Expert, Medium, Medium-Replay 데이터셋을 사용하였다.

오프라인 강화학습은 자기회귀 과제이므로 Primal-Attention을 인과적 버전으로 확장하였다. 3층 구조, 은닉 차원 256, 헤드 4개, 임베딩 차원 64를 사용했으며, $\eta=0.05$, $s\in\{32,64,96\}$로 설정하였다.

**표 5. D4RL 데이터셋의 보상.**

| 데이터셋 | 환경 | DT | Linear. | Re. | Per. | Cos. | Flow. | Primal.+DT |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Medium-Expert | HalfCheetah | 83.8±3.3 | 78.2±3.2 | 81.5±1.6 | 85.1±2.1 | 85.5±2.9 | 90.8±0.4 | 77.8±22.1 |
|  | Hopper | 104.0±2.5 | 107.2±0.9 | 104.2±9.8 | 93.5±13.9 | 98.1±7.4 | 109.9±1.0 | **111.5±0.2** |
|  | Walker | 107.7±0.6 | 67.2±27.3 | 71.4±1.8 | 72.6±2.4 | 100.5±14.5 | 108.0±0.4 | **108.9±0.1** |
| Medium | HalfCheetah | 34.6±0.6 | 32.1±1.5 | 33.6±0.7 | 31.7±0.9 | 32.8±3.6 | 34.7±1.5 | **38.9±0.4** |
|  | Hopper | 79.7±7.4 | 74.3±7.0 | 66.1±2.6 | 64.6±24.2 | 59.3±16.5 | 75.5±14.5 | **88.5±12.5** |
|  | Walker | 62.9±5.0 | 62.1±7.4 | 50.1±3.5 | 61.3±6.7 | 60.5±9.9 | 62.0±3.1 | **76.8±10.3** |
| 평균 보상 |  | 72.2±2.6 | 64.4±6.5 | 63.9±2.9 | 63.8±7.6 | 67.8±7.6 | 73.5±2.9 | **77.5±6.0** |

Primal.+DT는 모든 비교 방법보다 높은 평균 보상을 달성했으며, Flowformer보다 4.0점, Decision Transformer보다 5.3점 높았다. Primal.+DT는 표준 Decision Transformer의 최상위 층 자기 어텐션만 대체하면서도 성능을 향상시켰다.

**표 6. D4RL에서의 효율성 비교.**

| 모델 | 시간(초/1K steps) | 메모리(GB) |
|---|---:|---:|
| DT | 20.8 | 0.3 |
| Flow. | 54.4 | 1.5 |
| Primal.+DT | 23.4 | 0.3 |

Primal.+DT는 가장 효율적인 기준 모델인 DT와 비슷한 시간 및 메모리 효율성을 유지하면서도 더 높은 보상을 달성하였다.

### 5.4 대규모 실험

이미지 분류에서는 DeiT-Small/16[7]을 백본으로 사용하여 ImageNet-100[48]과 ImageNet-1K[23]를 평가하였다. 언어 모델링에서는 WikiText-103[49]을 사용하였다.

**표 7. 대규모 실험 결과.**

| 모델 | ImageNet-100 정확도 | ImageNet-1K 정확도 | 시간(초/1K steps) | 메모리(GB) |
|---|---:|---:|---:|---:|
| DeiT-Small/16 | 74.2 | 79.8 | 2425.5 | 14.2 |
| Primal.+DeiT-Small/16 | **75.7** | 79.8 | **2330.2** | **14.0** |

WikiText-103 결과는 다음과 같다.

| 모델 | 혼란도 | 시간(초/1K steps) | 메모리(GB) |
|---|---:|---:|---:|
| Trans. | 33.0 | 3108.4 | 9.0 |
| Flow. | 30.8 | 3998.4 | 10.5 |
| Primal.+Trans. | **31.0** | **3104.0** | **8.9** |

Primal-Attention을 마지막 층에 적용하면 전체 성능이 향상된다. 기본 설정의 제안 방법은 트랜스포머보다 혼란도를 2.0 낮추면서 효율성을 유지하였다.

### 5.5 두 투영 $e(x),r(x)$의 절제 연구

비대칭 어텐션 커널의 좌특이벡터를 반영하는 $r$ 점수를 사용하는 경우와 사용하지 않는 경우를 LRA에서 비교하였다.

**표 8. 좌특이벡터 관련 $r$ 점수에 대한 절제 실험.**

| 모델 | $r$ 점수 | ListOps | Text | Retrieval | Image | Pathfinder | 평균 |
|---|---|---:|---:|---:|---:|---:|---:|
| Primal. | 사용 안 함 | 36.8 | 52.4 | 58.2 | 30.5 | 50.2 | 45.6 |
| Primal. | 사용 | 37.3 | 61.2 | 77.8 | 43.0 | 68.3 | 57.5 |
| Primal.+Trans. | 사용 안 함 | 37.1 | 65.1 | 79.2 | 42.8 | 72.8 | 59.4 |
| Primal.+Trans. | 사용 | **37.3** | **65.4** | **81.0** | **43.9** | **74.3** | **60.4** |

두 투영을 모두 사용하는 것이 성능을 향상시키며, 이는 비대칭 어텐션 커널의 양쪽 특이벡터를 학습하는 것이 효과적임을 보여준다.

## 6. 관련 연구

[12]의 선구적 연구 이후 트랜스포머에서 커널 기반 접근법이 활발히 연구되었으며, 어텐션 행렬에 대한 커널 해석이 제시되었다. FourierFormer[17]는 표준 자기 어텐션을 대칭 커널 방법을 이용한 비모수 회귀로 다룬다. [18]은 조건부 양의 정부호 커널을 이용해 상대적 위치 임베딩을 고려한다. [19]는 자기 어텐션을 서포트 벡터 회귀로 해석하지만 사용된 커널의 비대칭성을 고려하지 않으며, 지도 회귀를 실제 어텐션 최적화에도 적용하지 않는다.

Skyformer[51]는 비대칭성 문제를 다루지만, 소프트맥스 어텐션을 근사 대칭 어텐션으로 대체하는 대칭화를 사용하므로 여전히 비대칭성을 무시한다. 이들 연구는 본래 대칭 커널을 위해 설계된 커널 기법을 사용하며 Mercer 조건을 요구한다. 따라서 자기 어텐션의 비대칭적 본질과 이론적 분석 및 수치적 구현 사이에 간극이 발생한다.

[21]은 비대칭성을 허용하는 RKBS[22]의 커널 트릭을 활용하여 경험적 위험 최소화를 통해 어텐션을 이진 커널 학습 문제로 정식화한다. 그러나 트랜스포머 구현에 직접 적용할 수 있는 명시적 최적화를 찾기 어렵다.

한편 어텐션 계산의 효율성을 높이기 위한 다양한 근사 기법도 연구되었다. Reformer[34]는 국소 민감 해싱으로 희소 근사를 수행하고, Performer[14]는 무작위 특성으로 자기 어텐션 행렬을 근사한다. Linformer[46]는 무작위 투영을 이용한 저랭크 근사를 수행하며, Nyströmformer[45]는 어텐션 행렬의 쿼리와 키를 다운샘플링하여 Nyström 방법을 사용한다. [52]는 어텐션에 희소성 사전확률을 도입한다.

이들 연구는 표준 자기 어텐션에서 커널 행렬의 계산량을 줄이는 데 초점을 둔다. 따라서 모두 커널 행렬을 포함하는 쌍대 형식의 문제를 해결한다. 반면 본 연구는 원초 형식에서 문제를 해결한다는 점에서 본질적으로 다르다.

## 7. 결론

본 논문에서는 비대칭 커널과 LSSVM 체계에서의 비대칭 커널 SVD(KSVD)를 이용해 트랜스포머의 자기 어텐션을 해석하였다. KSVD의 관점에서 자기 어텐션에 대한 원초-쌍대 모델 표현을 정식화하고, 원초 표현을 활용한 새로운 어텐션 메커니즘인 Primal-Attention을 제안하였다.

Primal-Attention은 쌍대의 어텐션 커널 행렬 계산을 피할 뿐 아니라, 비지도 KSVD 최적화를 추가 정규화 손실로 학습 과정에 효율적으로 통합한다. 이를 통해 더욱 정보가 풍부한 저랭크 특성을 학습할 수 있다.

분석적 유도와 수치 평가를 통해 명시적 모델 해석 가능성과 최신 수준의 성능을 연결하는 본 방법의 가능성을 확인하였다. 향후 연구로는 강건한 트랜스포머와 같이 저랭크 특성을 활용하는 다양한 변형을 개발하고, 더 일반적인 아키텍처와 과제에 Primal-Attention을 적용하는 방향을 고려할 수 있다.

## 감사의 글

본 연구는 유럽연합 Horizon 2020 연구·혁신 프로그램의 유럽연구위원회 ERC Advanced Grant E-DUALITY(787960), iBOF 프로젝트 Tensor Tools for Taming the Curse(3E221427), KU Leuven 연구위원회 프로젝트 Optimization framework for deep kernel machines(C14/18/068), KU Leuven Grant CoE PFV/10/002, FWO 프로젝트 GOA4917N(Deep Restricted kernel Machines: Methods and Foundations), 박사과정 및 박사후 연구비, 플랑드르 정부 AI Research Program, EU H2020 ICT-48 Network TAILOR, Leuven.AI Institute의 지원을 받았다.

## 참고문헌

[1] Vaswani et al. Attention is all you need. *NeurIPS*, 2017.  
[2] Devlin et al. BERT: Pre-training of deep bidirectional transformers for language understanding. *NAACL-HLT*, 2019.  
[3] Brown et al. Language models are few-shot learners. *NeurIPS*, 2020.  
[4] Raffel et al. Exploring the limits of transfer learning with a unified text-to-text transformer. *JMLR*, 2020.  
[5] Fan et al. Multiscale vision transformers. *ICCV*, 2021.  
[6] Liu et al. Swin transformer: Hierarchical vision transformer using shifted windows. *ICCV*, 2021.  
[7] Touvron et al. Training data-efficient image transformers & distillation through attention. *ICML*, 2021.  
[8] Chen et al. Jigsaw-ViT: Learning jigsaw puzzles in vision transformer. *Pattern Recognition Letters*, 2023.  
[9] Janner et al. Offline reinforcement learning as one big sequence modeling problem. *NeurIPS*, 2021.  
[10] Chen et al. Decision transformer: Reinforcement learning via sequence modeling. *NeurIPS*, 2021.  
[11] Wu et al. Flowformer: Linearizing transformers with conservation flows. *ICML*, 2022.  
[12] Tsai et al. Transformer dissection: An unified understanding for transformer’s attention via the lens of kernel. *EMNLP-IJCNLP*, 2019.  
[13] Vapnik. An overview of statistical learning theory. *IEEE Transactions on Neural Networks*, 1999.  
[14] Choromanski et al. Rethinking attention with performers. *ICLR*, 2021.  
[15] Ali et al. XCiT: Cross-covariance image transformers. *NeurIPS*, 2021.  
[16] Nguyen et al. Improving transformers with probabilistic attention keys. *ICML*, 2022.  
[17] Nguyen et al. Fourierformer: Transformer meets generalized Fourier integral theorem. *NeurIPS*, 2022.  
[18] Chi et al. Kerple: Kernelized relative positional embedding for length extrapolation. *NeurIPS*, 2022.  
[19] Nguyen et al. A primal-dual framework for transformers and neural networks. *ICLR*, 2023.  
[20] Mercer. Functions of positive and negative type, and their connection with the theory of integral equations. *Philosophical Transactions of the Royal Society A*, 1909.  
[21] Wright and Gonzalez. Transformers are deep infinite-dimensional non-Mercer binary kernel machines. arXiv, 2021.  
[22] Zhang et al. Reproducing kernel Banach spaces for machine learning. *JMLR*, 2009.  
[23] Deng et al. ImageNet: A large-scale hierarchical image database. *CVPR*, 2009.  
[24] Lin et al. On reproducing kernel Banach spaces: Generic definitions and unified framework of constructions. *Acta Mathematica Sinica*, 2022.  
[25] Georgiev et al. Construction of pairs of reproducing kernel Banach spaces. Springer, 2013.  
[26] Strang. *Linear Algebra and Its Applications*. 2006.  
[27] Suykens. SVD revisited: A new variational principle, compatible feature maps and nonlinear extensions. *Applied and Computational Harmonic Analysis*, 2016.  
[28] Suykens et al. *Least Squares Support Vector Machines*. 2002.  
[29] Lanczos. Linear systems in self-adjoint form. *The American Mathematical Monthly*, 1958.  
[30] Lindenstrauss and Johnson. Extensions of Lipschitz maps into a Hilbert space. 1984.  
[31] Bagnall et al. The UEA multivariate time series classification archive. arXiv, 2018.  
[32] Zerveas et al. A transformer-based framework for multivariate time series representation learning. *KDD*, 2021.  
[33] Katharopoulos et al. Transformers are RNNs: Fast autoregressive transformers with linear attention. *ICML*, 2020.  
[34] Kitaev et al. Reformer: The efficient transformer. *ICLR*, 2020.  
[35] Beltagy et al. Longformer: The long-document transformer. arXiv, 2020.  
[36] Zeng et al. You only sample (almost) once: Linear cost self-attention via Bernoulli sampling. *ICML*, 2021.  
[37] Qin et al. Cosformer: Rethinking softmax in attention. *ICLR*, 2022.  
[38] Lu et al. SOFT: Softmax-free transformer with linear complexity. *NeurIPS*, 2021.  
[39] Tay et al. Long range arena: A benchmark for efficient transformers. *ICLR*, 2021.  
[40] Nangia and Bowman. ListOps: A diagnostic dataset for latent tree learning. *NAACL*, 2018.  
[41] Maas et al. Learning word vectors for sentiment analysis. *ACL*, 2011.  
[42] Radev et al. The ACL anthology network corpus. *Language Resources and Evaluation*, 2013.  
[43] Krizhevsky et al. Learning multiple layers of features from tiny images. 2009.  
[44] Linsley et al. Learning long-range spatial dependencies with horizontal gated recurrent units. *NeurIPS*, 2018.  
[45] Xiong et al. Nyströmformer: A Nyström-based algorithm for approximating self-attention. *AAAI*, 2021.  
[46] Wang et al. Linformer: Self-attention with linear complexity. arXiv, 2020.  
[47] Fu et al. D4RL: Datasets for deep data-driven reinforcement learning. arXiv, 2020.  
[48] Russakovsky et al. ImageNet large scale visual recognition challenge. *IJCV*, 2015.  
[49] Merity et al. Pointer sentinel mixture models. *ICLR*, 2016.  
[50] Peng et al. Random feature attention. *ICLR*, 2021.  
[51] Chen et al. Skyformer: Remodel self-attention with Gaussian kernel and Nyström method. *NeurIPS*, 2021.  
[52] Child et al. Generating long sequences with sparse transformers. arXiv, 2019.

# 부록

## A. 이론적 증명

본 절에서는 논문에 제시된 모든 분석 결과, 즉 정리 3.2, 비고 3.3, 보조정리 4.2를 증명한다.

### A.1 정리 3.2의 증명

시퀀스 데이터 $\{x_i\in\mathbb{R}^d\}_{i=1}^N$로 구성된 $X\in\mathbb{R}^{N\times d}$에 대해 KSVD의 원초 최적화 문제는 다음과 같다.

$\max_{W_e,W_r,\{e_i\},\{r_j\}}J=\frac{1}{2}\sum_{i=1}^Ne_i^\top\Lambda e_i+\frac{1}{2}\sum_{j=1}^Nr_j^\top\Lambda r_j-\operatorname{Tr}(W_e^\top W_r)$

$\text{s.t. }e_i=(f(X)^\top W_e)^\top\phi_q(x_i),\quad r_j=(f(X)^\top W_r)^\top\phi_k(x_j).$

라그랑주 함수에 쿼리와 키 투영 점수에 대한 쌍대 변수 $h_{ei},h_{rj}\in\mathbb{R}^s$를 도입한다. KKT 조건을 적용하면 다음을 얻는다.

$\sum_{i=1}^Nf(X)\phi_q(x_i)h_{ei}^\top=W_r,\quad \sum_{j=1}^Nf(X)\phi_k(x_j)h_{rj}^\top=W_e,$

$\Lambda e_i=h_{ei},\quad \Lambda r_j=h_{rj},$

$W_e^\top f(X)\phi_q(x_i)=e_i,\quad W_r^\top f(X)\phi_k(x_j)=r_j.$

원초 변수들을 제거하면 다음과 같다.

$\sum_{j=1}^Nh_{rj}\phi_k(x_j)^\top f(X)^\top f(X)\phi_q(x_i)=\Lambda^{-1}h_{ei},$

$\sum_{i=1}^Nh_{ei}\phi_q(x_i)^\top f(X)^\top f(X)\phi_k(x_j)=\Lambda^{-1}h_{rj}.$

커널 행렬을 $K_{ij}:=\langle f(X)\phi_q(x_i),f(X)\phi_k(x_j)\rangle$로 정의하고, $\Sigma:=\Lambda^{-1}$로 두면 위 식은 다음의 행렬 형태가 된다.

$KH_r=H_e\Sigma,\quad K^\top H_e=H_r\Sigma.$

Lanczos 분해 정리에 따라 $H_e,H_r$는 각각 $K$의 좌특이벡터와 우특이벡터이며, $\Sigma$는 대응하는 특이값이다. 따라서 정리가 증명된다.

#### 정리 3.2에 대한 논평

[27]은 주어진 데이터 행렬의 선형 SVD에 대해 LSSVM 기반의 원초-쌍대 변분 원리를 제안하였다. 본 연구의 KSVD는 [27]의 커널 학습 체계를 활용하지만 다음과 같은 차이점이 있다.

1. [27]이 임의의 데이터 행렬에 대한 원래 SVD를 다루는 반면, 본 연구는 쿼리와 키에 관련된 비선형 특성 사상으로 비대칭 어텐션 행렬을 유도한다. 또한 단일 투영 방향을 다루는 [27]의 설정을 여러 투영 방향으로 확장하였다.
2. 두 비선형 특성 사상의 데이터 원천은 주어진 행렬의 행과 열이 아니라 쿼리와 키에 관련된다. 따라서 본 연구의 KSVD는 더욱 일반적인 데이터 설정을 갖는다.
3. [27]의 데이터 비의존적 투영 가중치와 달리, 본 연구는 시퀀스 데이터에 의존하는 변환 행렬을 허용한다. 이는 표준 자기 어텐션의 밸류가 입력 시퀀스에 따라 변하고 쌍대 변수 역할을 한다는 점에 동기를 얻는다. 데이터 의존적 투영 가중치는 모델의 표현력을 높이며, 이동 고유값 문제의 유도에는 영향을 주지 않는다.

### A.2 비고 3.3의 증명

원초 모델 표현은 다음과 같다.

$e(x)=(f(X)^\top W_e)^\top\phi_q(x),\quad r(x)=(f(X)^\top W_r)^\top\phi_k(x).$

KKT 조건에서 원초 변수를 제거하면 쌍대 표현을 얻는다.

$e(x)=\sum_{j=1}^Nh_{rj}\langle f(X)\phi_k(x_j),f(X)\phi_q(x)\rangle,$

$r(x)=\sum_{i=1}^Nh_{ei}\langle f(X)\phi_q(x_i),f(X)\phi_k(x)\rangle.$

커널 트릭을 적용하면 다음의 원초-쌍대 표현이 된다.

$\text{원초: }e(x)=W_{e|X}^\top\phi_q(x),\quad r(x)=W_{r|X}^\top\phi_k(x),$

$\text{쌍대: }e(x)=\sum_{j=1}^Nh_{rj}\kappa(x,x_j),\quad r(x)=\sum_{i=1}^Nh_{ei}\kappa(x_i,x).$

따라서 투영 점수는 명시적 특성 사상을 사용하는 원초 또는 커널 행렬을 사용하는 쌍대에서 동등하게 표현할 수 있다. 원초 표현은 커널 행렬 계산을 피할 수 있으며, $r(x)$는 비대칭성에서 발생하는 추가 정보를 반영한다.

### A.3 보조정리 4.2의 증명

KKT 조건을 이용해 원초 변수들을 제거하면 목적 함수는 다음과 같이 쓸 수 있다.

$J=\frac{1}{2}\sum_{i=1}^Nh_{ei}^\top\Sigma h_{ei}+\frac{1}{2}\sum_{j=1}^Nh_{rj}^\top\Sigma h_{rj}-\operatorname{Tr}(H_e^\top KH_r\Sigma).$

$\Sigma=\operatorname{diag}(\sigma_1,\ldots,\sigma_s)$이고, $h_{e,l},h_{r,l}$을 각각 $l$번째 투영 방향에 해당하는 쌍대 변수라고 하자. 이동 고유값 문제로부터 다음을 얻는다.

$K^\top Kh_{r,l}=\sigma_l^2h_{r,l},\quad KK^\top h_{e,l}=\sigma_l^2h_{e,l}.$

또한 $Kh_{r,l}=\sigma_lh_{e,l}$, $K^\top h_{e,l}=\sigma_lh_{r,l}$이므로,

$h_{e,l}^\top h_{e,l}=h_{r,l}^\top h_{r,l}.$

따라서 목적 함수는 다음과 같이 정리된다.

$J=\frac{1}{2}\sum_{l=1}^s\sigma_lh_{e,l}^\top h_{e,l}+\frac{1}{2}\sum_{l=1}^s\sigma_lh_{r,l}^\top h_{r,l}-\sum_{l=1}^s\sigma_lh_{e,l}^\top h_{e,l}=0.$

그러므로 정상성 조건을 만족하는 경우 원초 목적 함수값은 0이다.

## B. 추가 실험 결과

### B.1 구현 세부사항

다음은 Primal-Attention의 주요 알고리즘이다.

#### 알고리즘 1. Primal-Attention을 이용한 학습

입력 시퀀스를 $X=[x_1,\ldots,x_N]^\top\in\mathbb{R}^{N\times d}$라 하고, $g_q:\mathbb{R}^{d_q}\to\mathbb{R}^p$, $g_k:\mathbb{R}^{d_k}\to\mathbb{R}^p$, 투영 방향 수 $s$, 정규화 계수 $\eta$를 입력으로 한다.

- 데이터 의존적 투영 가중치의 경우 $q(x_i)=W_qx_i$, $k(x_i)=W_kx_i$를 계산한다.
- $e(x_i)=(f(X)^\top W_e)^\top g_q(q(x_i))$를 계산한다.
- $r(x_i)=(f(X)^\top W_r)^\top g_k(k(x_i))$를 계산한다.
- $o_i=W_o[e(x_i);r(x_i)]$를 계산한다.
- 데이터 비의존적 투영 가중치의 경우 $e(x_i)=W_e^\top g_q(q(x_i))$, $r(x_i)=W_r^\top g_k(k(x_i))$로 계산한다.
- 마지막으로 동일하게 $o_i=W_o[e(x_i);r(x_i)]$를 계산한다.

#### UEA 시계열

UEA 벤치마크는 30개 데이터셋으로 구성되며, [11]을 따라 10개를 선택하였다. PrimalFormer와 Primal.+Trans. 모두 데이터 의존적 투영 가중치를 사용하였다. 긴 시퀀스의 경우 효율성을 위해 $f(X):=X'$로 설정하였으며, $X'$는 $X$에서 균일하게 표본 추출한 $n=\min\{s\cdot\text{rank\_multi},N\}$개의 행으로 구성된다. 대부분의 경우 $\text{rank\_multi}=10$을 사용하고, 짧은 시퀀스 데이터셋에서는 5를 사용하였다.

#### Long-Range Arena

LRA의 시퀀스 길이는 ListOps 2K, Text 4K, Retrieval 4K, Image 1K, Pathfinder 1K이다. 모든 실험에서 $n=\min\{10s,N\}$을 사용하였다.

#### 강화학습

D4RL은 오프라인 강화학습의 성능을 평가하기 위한 연속 제어 과제 및 데이터셋 모음이다. Decision Transformer의 세 번째 층 자기 어텐션을 Primal-Attention으로 대체하였다. 자기회귀적 인과 마스크와 정렬하기 위해 인과적 Primal-Attention을 사용하였다. 이 과제에서는 과적합을 방지하기 위해 데이터 비의존적 투영 가중치 $W_e,W_r\in\mathbb{R}^{p\times s}$를 사용하였다.

#### 이미지 분류

ImageNet-100은 ImageNet-1K의 100개 클래스로 구성된다. 두 데이터셋에서 표준 DeiT-Small/16을 백본으로 사용하고 마지막 층의 자기 어텐션을 데이터 의존적 Primal-Attention으로 대체하였다.

#### 언어 모델링

WikiText-103에서는 이전 토큰이 주어졌을 때 다음 토큰의 확률 분포를 추정한다. 트랜스포머의 마지막 층 자기 어텐션을 데이터 의존적 투영 가중치를 사용하는 인과적 Primal-Attention으로 대체하였다.

### B.2 추가 절제 연구

#### $\eta$와 $s$에 대한 절제

Primal-Attention의 주요 하이퍼파라미터인 KSVD 정규화 손실 계수 $\eta$와 투영 방향 수 $s$를 평가하였다. 대부분의 데이터셋에서 $\eta>0$는 $\eta=0$보다 성능을 향상시켰다. 이는 정규화 손실을 통한 KSVD 최적화가 비정규화 모델보다 성능 향상을 제공함을 보여준다.

정규화가 없는 경우에도 Primal-Attention은 우수한 성능을 보였다. 이는 새로운 원초 표현 자체가 자기 어텐션을 효과적으로 표현하고 어텐션 출력의 학습을 수행할 수 있음을 의미한다. 각 헤드의 임베딩 차원은 64이지만 실험에서는 $s\in\{20,30,40\}$를 사용하였다. 적절한 KSVD 기반 압축은 저랭크 특성이 요구되는 경우 성능 향상으로 이어질 수 있다.

#### 투영 가중치

데이터 의존적 투영 가중치와 데이터 비의존적 투영 가중치를 비교하였다. UEA와 LRA 모두에서 데이터 의존적 투영 가중치가 더 높은 성능을 보였다. 이는 긴 시퀀스에서 데이터 의존적 가중치가 모델의 표현력을 높이고 더 많은 정보를 포착하기 때문으로 해석된다.

그러나 데이터 의존적 투영 가중치가 항상 유리한 것은 아니다. 강화학습에서는 보상 학습에 과적합할 수 있으므로 데이터 비의존적 설정을 사용하였다. 일반화된 투영 가중치 형식은 다양한 과제와 데이터셋에 맞춰 모델의 표현력을 조정할 수 있게 한다.

### B.3 효율성에 관한 추가 논의

Primal-Attention을 사용하는 트랜스포머의 효율성 향상은 두 요인의 영향을 받는다.

1. Primal-Attention을 사용하는 층의 수: 대체하는 층이 많을수록 효율성이 향상된다.
2. 시퀀스 길이: 시퀀스가 길수록 $N\times N$ 커널 행렬 계산을 피하는 효과가 커진다.

깊은 구조에서는 더 많은 층을 Primal-Attention으로 대체하여 효율성을 높일 수 있다. 그러나 매우 깊은 트랜스포머에서 모든 층에 적용하는 것이 항상 성능 면에서 우수한 것은 아니다. 얕은 층은 데이터 패턴을 표현하기 위해 더 큰 모델 용량이 필요할 수 있기 때문이다.

Primal.+의 구조는 다음과 같다.

| 데이터셋 | 표준 층 + Primal 층 |
|---|---|
| UEA | 1+[1] |
| LRA | 1+[1] |
| D4RL | 2+[1] |
| WikiText-103 | 5+[1] |
| ImageNet | 11+[1] |

Primal.+의 효율성 향상은 UEA와 LRA에서 특히 두드러진다. 이들 백본은 2층으로 구성되어 한 층을 교체하는 효과가 크며, 시퀀스 길이도 상대적으로 길다. 반면 D4RL, WikiText-103, ImageNet은 더 많은 층을 가지므로 Primal.+에서도 표준 자기 어텐션 층이 대부분을 차지한다. 또한 이들 데이터셋의 시퀀스 길이가 상대적으로 짧아 효율성 향상이 제한된다.

## C. 광범위한 영향

### 사회적 영향

본 연구는 LSSVM 체계에서 비대칭 커널을 사용하는 KSVD 문제를 통해 자기 어텐션을 해석하는 새로운 관점을 제시한다. 표준 트랜스포머와 비교하여 제안 방법은 커널 행렬 계산을 피하고 저랭크 특성을 정규화하므로 긴 시퀀스 데이터셋에서 더욱 효율적이다. 이에 따라 학습 과정의 전력 소비를 줄여 에너지 효율성을 높일 수 있다.

### 가능한 향후 연구

본 연구에서는 커널 대신 특성 사상을 사용하는 KSVD의 원초 관점에서 새로운 자기 어텐션 메커니즘을 제안하였다. 현재는 코사인 유사도 커널에 대응하는 특성 사상을 사용하여 평가한 벤치마크에서 최신 수준의 성능을 달성하였다. 보다 일반적인 설정과 응용을 위해서는 다양한 특성 사상과 백본 아키텍처를 연구할 필요가 있다. 이를 통해 더 넓은 과제에 방법을 확장하고 실제 환경에서 성능을 향상시킬 수 있을 것이다.