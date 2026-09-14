# 원제: Improving Sample Quality of Diffusion Models Using Self-Attention Guidance

[본문 전체 마크다운 번역 결과]

# 확산 모델의 자기 어텐션 가이던스를 이용한 샘플 품질 향상

수성 홍, 규성 이, 우석 장, 승룡 김  
고려대학교, 서울, 대한민국  
{susung1999, jpl358, jws1997, seungryong_kim}@korea.ac.kr

(a) SAG가 없는 ADM [7](위)와 SAG를 적용한 ADM [7](아래)  
(b) SAG가 없는 Stable Diffusion [31](위)과 SAG를 적용한 Stable Diffusion [31](아래)

> **그림 1: 가이던스가 적용되지 않은 샘플(위)과 자기 어텐션 가이던스가 적용된 샘플(아래)의 정성적 비교.** 분류기 가이던스(CG) [7]나 분류기 없는 가이던스(CFG) [16]와 달리, 자기 어텐션 가이던스(SAG)는 클래스 레이블이나 텍스트 프롬프트와 같은 외부 조건이나 추가 학습을 반드시 요구하지 않는다. 또한 사전 학습된 확산 모델인 (a) 비조건부 ADM [7]과 (b) 빈 프롬프트를 사용한 Stable Diffusion [31]이 생성하는 이미지의 세부 정보를 향상한다.

## 초록

잡음 제거 확산 모델(DDM)은 탁월한 생성 품질과 다양성으로 주목받고 있다. 이러한 성공은 분류기 가이던스 및 분류기 없는 가이던스와 같은 클래스 또는 텍스트 조건부 확산 가이던스 방법의 도입에 크게 기인한다. 본 논문에서는 기존의 전통적인 가이던스 방법을 넘어서는 보다 포괄적인 관점을 제시한다. 이 일반화된 관점에서 외부 조건과 추가 학습이 필요 없는 새로운 전략을 도입하여 생성 이미지의 품질을 향상한다.

간단한 방법으로서 블러 가이던스는 중간 샘플이 세밀한 정보와 구조를 표현하는 데 더 적합하도록 만들어, 확산 모델이 적절한 가이던스 강도로 더 높은 품질의 샘플을 생성할 수 있게 한다. 이를 발전시킨 자기 어텐션 가이던스(Self-Attention Guidance, SAG)는 확산 모델의 중간 자기 어텐션 맵을 활용하여 가이던스의 안정성과 효과를 높인다. 구체적으로 SAG는 각 반복 단계에서 확산 모델이 주목하는 영역만 적대적으로 블러 처리하고, 그에 따라 모델을 가이던스한다.

실험 결과, SAG는 ADM, IDDPM, Stable Diffusion, DiT를 포함한 다양한 확산 모델의 성능을 향상한다. 또한 SAG를 기존의 가이던스 방법과 결합하면 성능이 추가로 향상된다.

## 1 서론

최근 잡음 제거 확산 모델(DDM) [35, 37, 14, 7, 15, 31]은 반복적인 잡음 제거 과정을 통해 잡음으로부터 이미지를 합성하며, 고품질·고다양성 이미지 생성에서 뛰어난 성능을 보여 활발히 연구되고 있다. 이러한 성과의 핵심에는 확산 가이던스 방법 [7, 23, 16]이 있다. 여러 연구는 확산 모델이 생성하는 이미지 샘플의 품질을 향상하기 위해 클래스 레이블 [7, 16]이나 캡션 [23]을 사용하는 가이던스 기법이 필수적임을 보였다.

그러나 이러한 가이던스 방법은 큰 폭의 성능 향상에도 불구하고 외부 조건을 사용해야 한다는 한계가 있다. 예를 들어 분류기 가이던스(CG) [7]는 별도의 분류기를 추가로 학습해야 하며, 분류기 없는 가이던스(CFG) [16]는 학습 과정에 레이블 제거를 도입하여 복잡성을 높인다. 또한 두 방법 모두 획득하기 어려운 외부 조건에 의존하므로 조건부 설정에 국한된다.

이러한 한계를 고려하여 본 연구에서는 확산 모델의 중간 샘플에 포함된 정보를 활용할 수 있는 보다 일반적인 확산 가이던스의 수식을 제시한다. 이 수식은 기존 접근법 [16, 7, 23]에서 요구하는 외부 정보라는 필수 조건을 확산 가이던스와 분리하여, 확산 모델을 유연하고 조건 없이 가이던스할 수 있게 한다. 이에 따라 외부 조건이 있는 경우와 없는 경우 모두에 확산 가이던스를 적용할 수 있다.

또한 본 연구에서는 중간 샘플에 포함된 모든 내부 정보가 가이던스로 사용될 수 있다는 직관을 바탕으로, 샘플 품질을 향상하기 위한 간단한 방법으로 블러 가이던스를 먼저 제안한다. 블러 가이던스는 가우시안 블러로 제거된 정보를 활용하여 중간 샘플을 가이던스한다. 가우시안 블러는 세밀한 수준의 디테일을 자연스럽게 제거한다는 장점이 있다 [17, 20, 30]. 실험 결과 블러 가이던스는 중간 정도의 가이던스 강도에서 샘플 품질을 향상하지만, 강도가 커지면 전체 영역에 구조적 모호성을 유발한다. 이로 인해 열화된 입력에 대한 예측과 원본 입력에 대한 예측을 정렬하기 어려워진다.

큰 가이던스 강도에서도 블러 가이던스의 효과와 안정성을 높이기 위해, 확산 모델의 자기 어텐션 메커니즘을 탐구한다. 일반적으로 최근의 확산 모델 [14, 7, 24, 31, 15, 27]은 구조 내부에 자기 어텐션 모듈 [40, 8]을 포함한다. 자기 어텐션이 생성 과정에서 중요한 정보를 포착하는 핵심 요소라는 점 [18, 45, 46, 12]에 착안하여, 본 연구에서는 자기 어텐션 가이던스(SAG)를 제안한다. SAG는 확산 모델의 자기 어텐션 맵을 사용하여 중요한 정보를 포함하는 영역을 적대적으로 블러 처리하고, 잔여 정보를 이용해 확산 모델을 가이던스한다.

확산 모델의 역과정에서 어텐션 맵을 활용함으로써, 외부 정보나 추가 학습 없이 자기 조건화를 통해 이미지 품질을 향상하고 아티팩트를 줄일 수 있다. 제안 방법의 의사코드와 파이프라인은 알고리즘 1과 그림 2(b)에 제시되어 있다.

실험에서는 ADM [7], IDDPM [24], Stable Diffusion [31], DiT [27]에 제안 방법을 적용하여 효과를 평가한다. 이를 통해 제안 방법이 폭넓게 적용될 수 있음을 보인다. 또한 SAG를 단독으로 사용했을 때 샘플 품질이 향상될 뿐 아니라, 분류기 가이던스 [7]나 분류기 없는 가이던스 [16]와 같은 기존 가이던스 방법 위에 SAG를 추가하면 성능이 더욱 향상됨을 보인다. 이는 SAG가 기존 방법과 직교적인 특성을 가짐을 의미한다. 마지막으로 다양한 절제 실험을 통해 설계 선택을 검증한다.

본 연구의 기여는 다음과 같다.

- 조건부 가이던스 방법 [7, 16, 23]을 일반화하여 외부 조건 없이 모든 확산 모델에 적용할 수 있는 조건 없는 방법을 제시하고, 가이던스의 적용 범위를 확장한다.
- 확산 모델의 내부 자기 어텐션 맵을 활용하는 새로운 가이던스 방법인 자기 어텐션 가이던스(SAG)를 제안한다. SAG는 외부 조건이나 추가 미세 조정 없이 샘플 품질을 향상한다.
- SAG가 기존 조건부 모델 및 방법과 직교적임을 보이고, 다른 방법과 유연하게 결합하여 더 높은 성능을 달성할 수 있음을 보인다.
- 설계 선택의 타당성과 제안 방법의 효과를 입증하기 위한 광범위한 절제 실험을 수행한다.

프로젝트 페이지와 코드는 다음에서 확인할 수 있다: https://ku-cvlab.github.io/Self-Attention-Guidance/

## 2 관련 연구

### 잡음 제거 확산 모델

확산 모델 [35]은 점수 기반 모델 [37, 38]과 밀접한 관련이 있으며, 우수한 샘플링 품질과 다양성으로 큰 주목을 받았다. 선구적인 연구인 DDPM [14]은 점진적으로 잡음을 제거하여 이미지를 복원하는 반복 과정을 통해 이미지를 생성한다. 이후 샘플링 과정의 품질과 속도를 향상하기 위한 여러 접근법이 제안되었다 [36, 24, 31, 15, 7].

특히 IDDPM [24]은 확산 모델의 역과정에서 분산을 추가로 예측한다. DDIM [36]은 비마르코프 확산 과정을 도입하여 샘플링 속도를 높인다. LDM [31]은 잠재 공간에서 확산 과정을 처리함으로써 계산 비용을 줄인다.

최근의 확산 모델 [14, 7, 24, 31, 15, 27]은 일반적으로 U-Net 구조 내부의 일부 중간 계층에 자기 어텐션을 사용한다 [40, 8]. DDPM [14]은 U-Net [32]의 저해상도 계층에 자기 어텐션 층을 도입했다. 이를 바탕으로 Dhariwal과 Nichol [7]은 자기 어텐션 헤드 수와 해상도에 따른 성능 향상을 측정했다. 한편 DiT [27]은 Transformer 기반 백본을 활용하여 높은 성능을 달성했다.

### 확산 모델을 위한 샘플링 가이던스

최근 연구들은 더 높은 품질의 이미지를 생성하기 위해 클래스 레이블에 기반한 확산 가이던스 방법을 제안했다 [7, 16]. 분류기 가이던스(CG) [7]는 학습된 분류기를 사용하여 역과정을 특정 클래스 분포 방향으로 유도한다. 이에 대한 대안으로 Ho와 Salimans [16]은 추가 분류기 없이 유사한 효과를 달성하는 분류기 없는 가이던스(CFG)를 제안했다.

구현이 간단하고 효과적이기 때문에 CFG는 다양한 고품질 확산 모델에 사용되었다 [29, 31, 39, 41, 23, 33]. 이러한 가이던스 방법의 개념을 차용하여 Nichol 등 [23]은 CLIP [28] 가이던스와 CFG를 사용하는 텍스트-이미지 생성 방법을 제안했다. 그러나 이들 접근법은 레이블이 없는 데이터셋에 적용하기 어렵고 추가 학습 절차가 필요하다는 한계가 있다 [7, 16]. 또한 클래스나 텍스트와 같은 외부 조건을 요구하므로 조건부 확산 모델에 국한된다.

### 생성 모델의 자기 어텐션

자기 어텐션 메커니즘은 Transformer 기반 모델 [40]의 핵심 요소이다. 자기 어텐션은 표현력이 뛰어나고 전역 문맥을 인코딩할 수 있기 때문에 자연어 처리 [40]에서 사실상의 표준 방법이 되었으며, 이러한 특성은 컴퓨터 비전 분야에서도 자기 어텐션을 도입하는 연구를 촉진했다 [8, 18, 45, 46].

Jiang 등 [18]과 Zhang 등 [45, 46]은 더 나은 이미지 품질을 위해 생성적 적대 신경망(GAN)에 자기 어텐션을 도입했다. 이후 확산 모델 역시 자기 어텐션을 모델 구조에 포함했다. DDPM [14]은 U-Net의 저해상도 계층에 자기 어텐션 층을 도입하며 이러한 흐름을 시작했다. DiT [27]은 Transformer [40]를 백본으로 사용하는 확산 모델을 제안했다.

### 확산 모델의 내부 표현

확산 모델이 생성 작업에서 성공을 거두면서, 일부 연구는 확산 모델의 표현을 의미론적 분할과 같은 다른 작업에 활용하려 했다. Brempong 등 [2]은 잡음 제거 사전 학습이 의미론적 분할 성능을 높인다는 것을 보였고, Baranchuk 등 [1]은 확산 모델의 U-Net [32] 표현을 이용한 레이블 효율적 의미론적 분할 방법을 제안했다.

교차 어텐션을 사용하는 텍스트 기반 이미지 조작과 같은 특정 과제 [12]가 동시에 연구되어 왔지만, 이는 내부 자기 어텐션 맵을 활용하여 일반 확산 모델을 조건 없이 개선하고 자기 조건화하는 본 연구와 본질적으로 다르다.

## 3 사전 지식

### 잡음 제거 확률 모델

DDPM [14]은 반복적인 잡음 제거 과정을 통해 백색 잡음으로부터 이미지를 복원하는 모델이다. 이미지 $\mathbf{x}_0$와 시점 $t \in \{T,T-1,\ldots,1\}$에서의 분산 스케줄 $\beta_t$가 주어지면, 정방향 과정은 마르코프 과정으로 정의된다. 또한 $\epsilon_\theta(\mathbf{x}_t,t)$와 $\Sigma_\theta(\mathbf{x}_t,t)$로 매개변수화된 학습된 확산 모델이 주어지면 역과정을 정의할 수 있다. 여기서는 분산을 예측할 수도 있지만 [24, 7], $\Sigma_\theta(\mathbf{x}_t,t)=\sigma_t^2=\beta_t$로 설정한다 [14].

구체적으로 $\mathbf{x}_T\sim\mathcal{N}(0,\mathbf{I})$와 $\Sigma_\theta(\mathbf{x}_t,t)$가 주어졌을 때 DDPM은 다음을 계산하여 $\mathbf{x}_{T-1},\mathbf{x}_{T-2},\ldots,\mathbf{x}_0$을 샘플링한다.

$$\mathbf{x}_{t-1}=\frac{1}{\sqrt{\bar{\alpha}_t}}\left(\mathbf{x}_t-\frac{\beta_t}{\sqrt{1-\bar{\alpha}_t}}\epsilon_\theta(\mathbf{x}_t,t)\right)+\sigma_t\mathbf{z},\tag{1}$$

여기서 $\alpha_t=1-\beta_t$, $\bar{\alpha}_t=\prod_{i=1}^{t}\alpha_i$, $\mathbf{z}\sim\mathcal{N}(0,\mathbf{I})$이며 $\epsilon_\theta$는 매개변수 $\theta$로 표현되는 신경망이다. 이하에서는 간결성을 위해 $\epsilon_\theta(\mathbf{x}_t):=\epsilon_\theta(\mathbf{x}_t,t)$로 표기한다.

재매개변수화 기법을 이용하면 다음 식으로 시점 $t$에서 $\mathbf{x}_0$를 중간 복원한 $\hat{\mathbf{x}}_0$을 얻을 수 있다.

$$\hat{\mathbf{x}}_0=\frac{\mathbf{x}_t-\sqrt{1-\bar{\alpha}_t}\epsilon_\theta(\mathbf{x}_t,t)}{\sqrt{\bar{\alpha}_t}}.\tag{2}$$

### 분류기 가이던스와 분류기 없는 가이던스

GAN이 다양성과 충실도 사이의 절충을 수행하는 능력을 확산 모델에 도입하기 위해 Dhariwal과 Nichol [7]은 추가 분류기 $p(c|\mathbf{x}_t)$를 사용하는 분류기 가이던스를 제안했다. 여기서 $c$는 클래스 레이블이며, 가이던스 강도 $s>0$에 대해 다음과 같이 표현된다.

$$\tilde{\epsilon}(\mathbf{x}_t,c)=\epsilon_\theta(\mathbf{x}_t,c)-s\sigma_t\nabla_{\mathbf{x}_t}\log p(c|\mathbf{x}_t).\tag{3}$$

여기서 $\epsilon_\theta(\mathbf{x}_t,c)$는 조건부 확산 모델의 출력이고, $\tilde{\epsilon}(\mathbf{x}_t,c)$는 분류기에 의해 가이던스된 출력이다.

Ho와 Salimans [16]은 추가 분류기 없이 분류기 가이던스와 유사한 효과를 달성하는 분류기 없는 가이던스를 제안했다.

$$\tilde{\epsilon}(\mathbf{x}_t,c)=\epsilon_\theta(\mathbf{x}_t,c)+s(\epsilon_\theta(\mathbf{x}_t,c)-\epsilon_\theta(\mathbf{x}_t))=\epsilon_\theta(\mathbf{x}_t)+(1+s)(\epsilon_\theta(\mathbf{x}_t,c)-\epsilon_\theta(\mathbf{x}_t)).\tag{5}$$

### 확산 모델의 자기 어텐션

확산 모델의 백본에 사용되는 자기 어텐션은 생성 과정에서 입력의 중요한 부분에 주목할 수 있게 한다 [18, 45, 46, 12]. 높이 $H$, 너비 $W$에 대해 시점 $t$의 특성 맵 $\mathbf{X}_t\in\mathbb{R}^{(HW)\times C}$가 주어졌을 때, $N$개 헤드를 갖는 자기 어텐션은 다음과 같이 정의된다.

$$Q_t^h=\mathbf{X}_tW_Q^h,\quad K_t^h=\mathbf{X}_tW_K^h,\tag{6}$$

$$A_t^h=\operatorname{softmax}\left(Q_t^h(K_t^h)^T/\sqrt{d}\right),\tag{7}$$

여기서 $W_Q^h,W_K^h,W_V^h\in\mathbb{R}^{C\times d}$이며 $h=0,1,\ldots,N-1$이다. 각 $A_t^h$는 $V_t^h=\mathbf{X}_tW_V^h$와 곱해진다.

## 4 확산 가이던스의 일반화

분류기 가이던스와 분류기 없는 가이던스는 조건부 확산 모델의 생성에 크게 기여했지만 [7, 16, 23], 외부 입력에 의존한다. 본 연구에서는 관점을 확장하여 외부 입력이 있는 경우와 없는 경우를 모두 다룬다. 또한 이 절의 마지막에서 CFG [16]를 본 프레임워크에 통합하는 방법을 보인다.

시점 $t$에서 확산 모델의 전체 입력은 일반화된 조건 $h_t$와, $h_t$가 제거된 섭동 샘플 $\bar{\mathbf{x}}_t$로 구성된다. 조건 $h_t$는 $\mathbf{x}_t$ 내부의 정보, 외부 조건 또는 두 가지 모두를 포함할 수 있다. 이 정의에 따라 $\bar{\mathbf{x}}_t$가 주어졌을 때 $h_t$를 예측한다고 가정하는 가상의 회귀기 $p_{\mathrm{im}}(h_t|\bar{\mathbf{x}}_t)$를 이용하여 가이던스를 다음과 같이 정의한다.

$$\tilde{\epsilon}(\bar{\mathbf{x}}_t,h_t)=\epsilon_\theta(\bar{\mathbf{x}}_t,h_t)-s\sigma_t\nabla_{\bar{\mathbf{x}}_t}\log p_{\mathrm{im}}(h_t|\bar{\mathbf{x}}_t).\tag{8}$$

베이즈 규칙 $p_{\mathrm{im}}(h|\bar{\mathbf{x}}_t)\propto p(\bar{\mathbf{x}}_t|h)/p(\bar{\mathbf{x}}_t)$를 사용하면 가상의 회귀기 점수는 다음과 같이 유도된다.

$$\nabla_{\bar{\mathbf{x}}_t}\log p_{\mathrm{im}}(h_t|\bar{\mathbf{x}}_t)=-\frac{1}{\sigma_t}\left(\epsilon^*(\bar{\mathbf{x}}_t,h_t)-\epsilon^*(\bar{\mathbf{x}}_t)\right),\tag{9}$$

여기서 $\epsilon^*$는 해당 회귀기의 참 점수를 의미한다. 이를 식 (8)에 대입하면 다음을 얻는다.

$$\tilde{\epsilon}(\bar{\mathbf{x}}_t,h_t)=\epsilon_\theta(\bar{\mathbf{x}}_t,h_t)+s(\epsilon_\theta(\bar{\mathbf{x}}_t,h_t)-\epsilon_\theta(\bar{\mathbf{x}}_t))=\epsilon_\theta(\bar{\mathbf{x}}_t)+(1+s)(\epsilon_\theta(\bar{\mathbf{x}}_t,h_t)-\epsilon_\theta(\bar{\mathbf{x}}_t)).\tag{12}$$

식 (11)은 $\bar{\mathbf{x}}_t$가 확산 모델 $\epsilon_\theta$가 정의하는 데이터 다양체에 속해야 한다는 제약을 부과한다. CFG [16]는 $\bar{\mathbf{x}}_t=\mathbf{x}_t$, $h_t=c$로 설정하고 가상의 회귀기 $p_{\mathrm{im}}(h_t|\bar{\mathbf{x}}_t)$를 [16]의 암시적 분류기로 환원한 식 (12)의 특수한 경우이다.

이러한 수식을 이용하면 입력으로 잡음 이미지 $\mathbf{x}_t$만을 사용하고 외부 레이블이 없는 비조건부 모델에도 확산 가이던스를 정의할 수 있다. 즉, 역과정의 중간 샘플에 포함된 시각 정보로 자기 조건화를 수행한다. 이를 바탕으로 비조건부 모델에 적절한 $h_t$와 그에 대응하는 $\bar{\mathbf{x}}_t$를 찾는 방법을 논의하고, 다음 절에서 구체적인 가이던스를 제안한다.

## 5 샘플 품질 향상을 위한 자기 어텐션 맵 활용

4절의 유도는 $\mathbf{x}_t$에 포함된 중요한 정보 $h_t$를 추출하면 확산 모델의 역과정을 가이던스할 수 있음을 의미한다. 이에 착안하여, 사전 학습된 확산 모델에서 $\bar{\mathbf{x}}_t$가 분포 밖으로 벗어날 위험을 줄이면서 역과정에 중요한 정보를 효과적으로 제공하는 자기 어텐션 가이던스(SAG)를 제안한다.

먼저 SAG의 기초적인 형태인 블러 가이던스를 설명한 뒤, 자기 어텐션 맵을 이용하는 SAG를 소개한다.

### 5.1 확산 모델을 위한 블러 가이던스

가우시안 블러는 입력 신호 $\hat{\mathbf{x}}_0$를 가우시안 필터 $G_\sigma$와 컨볼루션하여 출력 $\tilde{\mathbf{x}}_0$을 생성하는 선형 필터링 기법이다.

$$\tilde{\mathbf{x}}_0=\hat{\mathbf{x}}_0*G_\sigma,$$

여기서 $*$는 컨볼루션 연산을 의미한다. 표준편차 $\sigma$가 증가하면 가우시안 블러는 입력 신호의 미세한 세부 정보를 줄이고 이를 일정한 값에 가까운 형태로 평활화한다 [30].

먼저 식 (2)의 중간 복원 $\hat{\mathbf{x}}_0$을 가우시안 필터 $G_\sigma$로 블러 처리한다. 이후 $\epsilon_\theta(\mathbf{x}_t)$를 사용하여 다시 확산함으로써 $\tilde{\mathbf{x}}_t$를 생성한다. 이 과정은 블러가 가우시안 잡음을 감소시키는 부작용을 우회하며, 가이던스가 무작위 잡음이 아니라 중간 콘텐츠에 의존하도록 한다. 이하에서는 잠재 확산 모델 [31]을 포함하기 위해 $\mathbf{x}_t$를 잡음 이미지 또는 공간적 잠재 변수로 모두 표기한다.

$\tilde{\mathbf{x}}_0$과 $\hat{\mathbf{x}}_0$ 사이에는 정보 불균형이 존재한다. $\hat{\mathbf{x}}_0$이 더 많은 세밀한 정보를 포함하기 때문이다. 블러 가이던스는 중간 복원에서 일부 정보를 의도적으로 제거하고, 제거된 정보를 이용해 예측을 해당 정보에 더 적합한 방향으로 유도한다. 식 (12)에서 $\bar{\mathbf{x}}_t=\tilde{\mathbf{x}}_t$, $h_t=\mathbf{x}_t-\tilde{\mathbf{x}}_t$로 설정하면 블러 가이던스를 얻는다.

실제로 결합 입력 $(\tilde{\mathbf{x}}_t,h_t)$는 단순히 $\mathbf{x}_t=\tilde{\mathbf{x}}_t+h_t$로 계산된다. $\mathbf{x}_t-\tilde{\mathbf{x}}_t$는 블러 처리 이전의 정보를 보존하므로, 확산 모델이 이미지 생성에 필요한 세부 정보를 복원하도록 확산 과정을 유도한다.

블러 가이던스를 적용하면 중간 정도의 가이던스 강도에서 품질 지표가 향상된다. 그러나 큰 가이던스 강도($s>5.0$)에서는 그림 3의 위쪽 행과 같이 잡음이 많은 결과가 생성된다. 이는 전역 블러가 전체 영역에 구조적 모호성을 도입하기 때문인 것으로 보인다. 열화된 입력에 대한 예측과 원본 입력에 대한 예측을 정렬하기 어려워지고, 이러한 오차가 시간 단계에 걸쳐 누적되어 잡음이 발생한다.

### 5.2 확산 모델을 위한 자기 어텐션 가이던스

자기 어텐션 메커니즘 [8, 40]은 확산 모델의 핵심 구성 요소로 알려져 있다 [7, 14]. 확산 모델의 백본에 구현된 자기 어텐션은 생성 과정에서 입력의 중요한 부분에 주목하게 한다 [18, 45, 46, 12]. 그림 4는 ADM [7]의 자기 어텐션 마스크 영역이 이미지의 고주파 세부 정보와 겹치는 예를 보여준다.

확산 모델의 자기 어텐션 맵에서 집계된 어텐션 맵을 얻기 위해, 먼저 쌓인 자기 어텐션 맵 $A_t^S\in\mathbb{R}^{N\times(HW)\times(HW)}$에 전역 평균 풀링(GAP)을 적용하여 $\mathbb{R}^{HW}$로 집계한다. 이후 이를 $\mathbb{R}^{H\times W}$로 변형하고, 최근접 이웃 업샘플링을 적용하여 $\mathbf{x}_t$의 해상도에 맞춘다.

$$A_t=\operatorname{Upsample}\left(\operatorname{Reshape}\left(\operatorname{GAP}(A_t^S)\right)\right).\tag{13}$$

마스킹 임계값 $\psi$가 주어졌을 때, SAG는 자기 어텐션 맵에 따라 $\mathbf{x}_t$에서 마스크된 패치만 블러 처리한다. 실험에서는 $\psi$를 $A_t$의 평균값으로 설정한다.

$$M_t=\mathbf{1}(A_t>\psi),$$

$$\hat{\mathbf{x}}_t=(1-M_t)\odot\mathbf{x}_t+M_t\odot\tilde{\mathbf{x}}_t,\tag{15}$$

여기서 $\odot$는 아다마르 곱을 의미하며 $\tilde{\mathbf{x}}_t$는 5.1절과 동일한 방식으로 얻는다. 최종적으로 가이던스된 잡음 예측은 다음과 같다.

$$\tilde{\epsilon}(\mathbf{x}_t)=\epsilon_\theta(\hat{\mathbf{x}}_t)+(1+s)(\epsilon_\theta(\mathbf{x}_t)-\epsilon_\theta(\hat{\mathbf{x}}_t)).\tag{16}$$

식 (16)은 $h_t=M_t\odot\mathbf{x}_t-M_t\odot\tilde{\mathbf{x}}_t$, $\bar{\mathbf{x}}_t=\hat{\mathbf{x}}_t$로 설정한 식 (12)의 특수한 경우이다.

블러 가이던스와 달리 $\hat{\mathbf{x}}_t$는 $\mathbf{x}_t$의 손상되지 않은 패치를 명시적으로 포함한다. 따라서 큰 가이던스 강도에서도 $\epsilon_\theta(\hat{\mathbf{x}}_t)$가 원래 예측에서 지나치게 벗어나지 않으며, 역과정에 중요한 정보를 적대적으로 은닉할 수 있다.

### 알고리즘 1 자기 어텐션 가이던스(SAG) 샘플링

- `Model(x_t)`: 입력 $x_t$를 받아 예측 잡음 $\epsilon_t$, 분산 $\Sigma_t$, 자기 어텐션 맵 $A_t$를 출력하는 확산 모델
- `Gaussian-Blur(\hat{x}_0)`: 가우시안 블러 함수

1. $x_T\sim\mathcal{N}(0,I)$
2. $t=T,T-1,\ldots,1$에 대해 반복:
   - $\epsilon_t,\Sigma_t,A_t\leftarrow\operatorname{Model}(x_t)$
   - $M_t\leftarrow\mathbf{1}(A_t>\psi)$
   - $\hat{x}_0\leftarrow(x_t-\sqrt{1-\bar{\alpha}_t}\epsilon_t)/\sqrt{\bar{\alpha}_t}$
   - $\tilde{x}_0\leftarrow\operatorname{Gaussian\text{-}Blur}(\hat{x}_0)$
   - $\tilde{x}_t\leftarrow\sqrt{\bar{\alpha}_t}\tilde{x}_0+\sqrt{1-\bar{\alpha}_t}\epsilon_t$
   - $\hat{x}_t\leftarrow(1-M_t)\odot x_t+M_t\odot\tilde{x}_t$
   - $\hat{\epsilon}_t\leftarrow\operatorname{Model}(\hat{x}_t)$
   - $\tilde{\epsilon}_t\leftarrow\hat{\epsilon}_t+(1+s)(\epsilon_t-\hat{\epsilon}_t)$
   - $x_{t-1}\sim\mathcal{N}\left(\frac{1}{\sqrt{\bar{\alpha}_t}}\left(x_t-\frac{\beta_t}{\sqrt{1-\bar{\alpha}_t}}\tilde{\epsilon}_t\right),\Sigma_t\right)$
3. $x_0$ 반환

> **그림 2: 분류기 없는 가이던스 [16]와 자기 어텐션 가이던스(SAG)의 비교.** 분류기 없는 가이던스가 외부 클래스 정보를 사용하는 것과 달리, SAG는 자기 어텐션을 통해 내부 정보를 추출하여 모델을 가이던스하므로 학습과 조건이 필요 없다.

## 6 실험

### 6.1 실험 설정

실험을 위해 NVIDIA GeForce RTX 3090 GPU 8개로 구성된 서버 두 대를 사용하여 샘플을 생성했다. ADM [7], IDDPM [24], Stable Diffusion [31], DiT [27]의 사전 학습 모델을 기반으로 하였으며, 공개 저장소에서 모든 가중치를 가져왔다. [7]과 동일한 평가 지표인 FID [13], sFID [22], IS [34], 개선된 정밀도 및 재현율 [19]을 사용했다.

### 6.2 실험 결과

#### SAG를 이용한 비조건부 생성

CG와 CFG가 갖지 못한 조건 없는 특성을 보이기 위해 비조건부 모델에서 SAG의 효과를 평가했다. ImageNet [6] 256×256, LSUN Cat [44], LSUN Horse [44]로 학습한 ADM [7]을 평가했다.

| 데이터셋 | 입력 | SAG | FID (↓) | sFID (↓) | IS (↑) | 정밀도 (↑) | 재현율 (↑) |
|---|---|---:|---:|---:|---:|---:|---:|
| ImageNet 256×256 | 비조건부 | ✗ | 26.21 | 6.35 | 39.70 | 0.61 | 0.63 |
| ImageNet 256×256 | 비조건부 | ✓ | **20.08** | **5.77** | **45.56** | **0.68** | 0.59 |
| ImageNet 256×256 | 조건부 | ✗ | 10.94 | 6.02 | 100.98 | 0.69 | 0.63 |
| ImageNet 256×256 | 조건부 | ✓ | **9.41** | **5.28** | **104.79** | **0.70** | 0.62 |
| LSUN Cat 256×256 | 비조건부 | ✗ | 7.03 | 8.24 | - | 0.60 | 0.53 |
| LSUN Cat 256×256 | 비조건부 | ✓ | **6.87** | **8.21** | - | 0.60 | 0.50 |
| LSUN Horse 256×256 | 비조건부 | ✗ | 3.45 | 7.55 | - | 0.68 | 0.56 |
| LSUN Horse 256×256 | 비조건부 | ✓ | **3.43** | **7.51** | - | 0.68 | 0.55 |

> **표 1: 256×256 이미지로 사전 학습된 ADM [7]에서 SAG를 적용한 50K 샘플 결과.** 최상의 값은 굵게 표시했다.

SAG는 비조건부 모델의 FID, sFID, IS를 일관되게 향상했지만 재현율은 낮췄다. 최근 연구 [7, 16]에서 설명한 것처럼 샘플 충실도와 다양성 사이에는 절충 관계가 존재하기 때문으로 보인다. 그럼에도 그림 6의 비교에서 확인할 수 있듯이, 내부 조건을 자기 조건화하는 효과로 인해 정성적 품질은 향상되었다.

IDDPM [24]의 비조건부 모델에도 SAG를 적용했다. ImageNet 64×64로 학습된 모델에서 FID가 향상되었다.

| 스케줄 | 목적 함수 | 입력 | SAG | FID (↓) |
|---|---|---|---:|---:|
| cosine | $L_{\mathrm{hybrid}}$ | 비조건부 | ✗ | 19.2 |
| cosine | $L_{\mathrm{hybrid}}$ | 비조건부 | ✓ | **18.0** |

> **표 2: ImageNet 64×64로 사전 학습된 IDDPM [24]에서 SAG를 적용한 50K 샘플 결과.**

#### SAG를 이용한 조건부 생성

SAG는 비조건부 모델에서 효과적일 뿐 아니라 조건부 모델에도 적용할 수 있다. 이를 평가하기 위해 ImageNet 256×256으로 조건부 학습된 ADM [7]을 실험했다. 표 1은 비조건부 모델과 유사하게 조건부 모델에서도 SAG가 효과적임을 보여준다.

Stable Diffusion [31]에 SAG를 적용하고, 500쌍의 이미지에 대해 인간 평가를 수행했다. Stable Diffusion에는 빈 프롬프트를 사용하고 각 쌍에 동일한 무작위 시드를 적용했다. 결과적으로 SAG를 적용한 샘플이 사람들에게 시각적으로 더 선호되거나 현실적으로 평가되었다.

또한 Stable Diffusion에서 CFG와 SAG를 결합하여 텍스트-이미지 생성으로 적용 범위를 확장했다. SAG를 적용한 이미지는 자기 조건화 효과로 인해 더 높은 품질과 더 적은 아티팩트를 보였다. 빈 프롬프트를 사용한 경우에도 품질이 뚜렷하게 향상되었으며, 이는 SAG가 외부 조건과 독립적임을 뒷받침한다.

#### CFG와의 직교성

| CG [7] | SAG | FID (↓) | sFID (↓) | 정밀도 (↑) | 재현율 (↑) |
|---:|---:|---:|---:|---:|---:|
| ✗ | ✗ | 5.91 | 5.09 | 0.70 | 0.65 |
| ✓ | ✗ | 2.97 | 5.09 | 0.78 | 0.59 |
| ✗ | ✓ | 5.11 | **4.09** | 0.72 | 0.65 |
| ✓ | ✓ | **2.58** | 4.35 | **0.79** | 0.59 |

> **표 3: SAG와 CG [7]의 호환성.** ImageNet 128×128으로 학습된 ADM의 결과이다.

CG와 SAG를 함께 사용하면 FID와 정밀도가 추가로 향상되었다. 반면 sFID에서는 SAG만 사용하는 경우가 가장 좋았다. 이는 SAG가 기존 가이던스와 직교적인 요소를 가지며 동시에 사용될 수 있음을 의미한다.

| 모델 | CFG [16] | SAG | FID (↓) |
|---|---:|---:|---:|
| DiT-XL/2 [27] | ✓ | ✗ | 2.27 |
| DiT-XL/2 [27] | ✓ | ✓ | **2.16** |

> **표 4: SAG와 CFG [16]의 호환성.** ImageNet 256×256으로 학습된 DiT-XL/2의 결과이다.

CFG와 SAG를 함께 사용한 샘플은 자기 조건화 효과로 추가적인 품질 향상을 보였다. 이러한 결과는 그림 8의 텍스트-이미지 샘플에서도 확인된다.

### 6.3 절제 실험 및 분석

#### 마스킹 전략

ADM [7]에서 10K 샘플을 사용하여 다양한 마스킹 전략을 비교했다. 다른 마스킹 방식에서는 공정한 비교를 위해 이미지 픽셀의 40%를 마스크했다. 이는 자기 어텐션 마스킹의 임계값을 1.0으로 설정했을 때 마스크되는 영역과 동일하다.

| 마스킹 전략 | FID (↓) | IS (↑) |
|---|---:|---:|
| 기준선 | 5.98 | 141.72 |
| 전역(5.1절의 블러 가이던스) | 5.82 | 143.15 |
| 고주파 | 5.74 | 148.87 |
| 무작위 | 5.68 | 148.99 |
| 정사각형 | 5.68 | 146.50 |
| 자기 어텐션(SAG) | **5.47** | **151.12** |
| DINO [3] 어텐션 | 5.63 | 146.18 |

> **표 5: 마스킹 전략에 대한 절제 실험.** ImageNet 128×128으로 학습된 ADM의 결과이다.

자기 어텐션 마스킹이 다른 전략보다 우수했다. 특히 전역 마스킹, 즉 블러 가이던스는 가장 낮은 성능을 보여 SAG의 동기를 뒷받침했다. $\hat{x}_0$에 FFT를 사용한 고주파 마스크와 DINO [3]의 자기 어텐션 마스크도 적용했지만, FID와 IS에서 제안 방법보다 낮은 성능을 보였다.

#### 가이던스 강도

ADM [7]에서 10K 샘플을 사용하여 가이던스 강도 변화를 평가했다. 강도 $s=-0.1,0.1,0.2,0.3,0.4$를 테스트한 결과, FID, sFID, Inception Score는 $s=0.1$에서 가장 좋았다. 정밀도는 $s=0.3$에서 가장 높았다. 음의 강도($s=-0.1$)나 지나치게 큰 강도($s\geq0.4$)는 샘플 품질을 저하시켰다.

#### 가우시안 블러

$\sigma\in\{1,3,9,27\}$ 및 극단적인 경우를 10K 샘플로 평가했다. $\sigma\to\infty$이면 필터가 신호 콘텐츠를 점진적으로 블러 처리하여 모든 픽셀이 평균값에 가까워진다. 반대로 $\sigma\to0$이면 신호가 변하지 않는다. SAG는 $\sigma$의 선형적 변화에 강건하지만, 최상의 성능을 내는 최적의 $\sigma$가 존재한다. 최적값은 입력 해상도에도 의존하며, 일반적으로 입력 해상도가 높을수록 더 큰 $\sigma$가 필요하다.

| $\sigma$ | 기준선($\sigma\to0$) | $\sigma=1$ | $\sigma=3$ | $\sigma=9$ | $\sigma=27$ | 평균 픽셀($\sigma\to\infty$) |
|---|---:|---:|---:|---:|---:|---:|
| FID (↓) | 5.98 | 5.58 | **5.47** | 5.70 | 5.80 | 5.84 |
| IS (↑) | 141.72 | 145.85 | **151.12** | 148.70 | 147.83 | 147.52 |

> **표 6: 가우시안 블러의 $\sigma$에 대한 절제 실험.** ImageNet 128×128으로 학습된 ADM의 결과이다.

#### 계산 비용

| 방법 | GPU 메모리 | 실행 시간 |
|---|---:|---:|
| 가이던스 없음 | 12,167MB | 108.27초 |
| SAG | 12,209MB | 186.60초 |
| CFG [16] | 12,218MB | 190.27초 |

> **표 7: 계산 비용.**

SAG의 메모리와 시간 소비량은 CFG와 거의 동일하다. 이는 블러와 마스킹 등의 SAG 연산에 따른 추가 비용이 무시할 수 있는 수준임을 의미한다. 다만 추가적인 순전파 단계가 필요하므로 가이던스를 사용하지 않는 경우보다 비용이 높다.

## 7 결론

본 연구에서는 확산 모델 내부의 정보를 활용하여 고품질 이미지를 합성하는 새롭고 일반적인 가이던스 수식을 제시했다. 제안한 자기 어텐션 가이던스는 조건과 학습이 필요 없으며 ADM, ID-DPM, Stable Diffusion, DiT 등 다양한 확산 모델에 적용할 수 있다. 또한 자기 조건화를 통해 이미지 품질을 향상하고 아티팩트를 줄인다.

실험 결과는 제안 방법의 효과와 자기 어텐션 가이던스가 기존 가이던스 방법과 직교적이라는 점을 입증한다. 이러한 발견과 가이던스의 일반화를 바탕으로, 본 연구가 잡음 제거 확산 모델과 그 가이던스에 관한 후속 연구를 촉진하는 계기가 되기를 기대한다.

## 감사의 글

본 연구는 대한민국 과학기술정보통신부의 지원을 받았다(IITP-2022-2020-0-01819, ICT Creative Consilience 프로그램, 한국연구재단 NRF-2021R1C1C1006897). 또한 삼성전자 모바일익스피리언스 사업부의 지원을 받았다.

## 부록

본 부록에서는 DDPM [7]의 추가 세부 사항, 제안 방법의 구현 세부 사항, 추가 분석 및 결과, 인간 평가 절차를 제시한다. 마지막으로 한계와 향후 연구 방향을 논의한다.

### A. 잡음 제거 확률 모델

DDPM [14]은 반복적인 잡음 제거 단계를 통해 백색 잡음으로부터 이미지를 생성하는 생성 모델이다. 이미지 $\mathbf{x}_0$와 임의의 시점 $t\in\{1,2,\ldots,T\}$에 대한 분산 스케줄 $\beta_t$가 주어지면 DDPM의 정방향 과정은 다음과 같은 마르코프 과정으로 정의된다.

$$q(\mathbf{x}_{t+1}|\mathbf{x}_t)=\mathcal{N}(\mathbf{x}_{t+1};\sqrt{1-\beta_t}\mathbf{x}_t,\beta_t\mathbf{I}).\tag{17}$$

다음의 폐쇄형 식을 사용하면 $\mathbf{x}_0$에서 직접 $\mathbf{x}_t$를 얻을 수 있다.

$$q(\mathbf{x}_t|\mathbf{x}_0)=\mathcal{N}(\mathbf{x}_t;\sqrt{\bar{\alpha}_t}\mathbf{x}_0,(1-\bar{\alpha}_t)\mathbf{I}),\tag{18}$$

여기서 $\alpha_t=1-\beta_t$, $\bar{\alpha}_t=\prod_{i=1}^{t}\alpha_i$이다.

역과정은 다음과 같이 정의된다.

$$p_\theta(\mathbf{x}_{t-1}|\mathbf{x}_t)=\mathcal{N}(\mathbf{x}_{t-1};\mu_\theta(\mathbf{x}_t,t),\Sigma_\theta(\mathbf{x}_t,t)\mathbf{I}),\tag{19}$$

여기서 $\mu_\theta$와 $\Sigma_\theta$는 매개변수 $\theta$를 갖는 신경망이다. DDPM과 같이 $\Sigma_\theta$를 상수 $\sigma_t^2=\beta_t$로 고정하면, $p_\theta(\mathbf{x}_{t-1}|\mathbf{x}_t)$는 다음의 정방향 사후분포와 비교된다.

$$q(\mathbf{x}_{t-1}|\mathbf{x}_0,\mathbf{x}_t)=\mathcal{N}(\mathbf{x}_{t-1};\tilde{\mu}_t(\mathbf{x}_0,\mathbf{x}_t),\tilde{\beta}_t\mathbf{I}).\tag{20}$$

Ho 등 [14]은 $\mu_\theta$와 $\tilde{\mu}_t$를 직접 비교하는 대신 재매개변수화 후 다음의 단순화된 목적 함수를 최적화하는 것이 유리하다는 것을 발견했다.

$$\mathbf{x}_t=\sqrt{\bar{\alpha}_t}\mathbf{x}_0+\sqrt{1-\bar{\alpha}_t}\boldsymbol{\epsilon},\quad\text{where}\quad\boldsymbol{\epsilon}\sim\mathcal{N}(0,\mathbf{I}),\tag{21}$$

$$L_{\mathrm{simple}}=\mathbb{E}_{\mathbf{x}_0,t,\boldsymbol{\epsilon}}\left[\|\boldsymbol{\epsilon}-\epsilon_\theta(\sqrt{\bar{\alpha}_t}\mathbf{x}_0+\sqrt{1-\bar{\alpha}_t}\boldsymbol{\epsilon},t)\|^2\right].\tag{22}$$

샘플링 과정에서는 $\mathbf{x}_T$에서 $\mathbf{x}_0$까지 다음을 계산한다.

$$\mathbf{x}_{t-1}=\frac{1}{\sqrt{\bar{\alpha}_t}}\left(\mathbf{x}_t-\frac{\beta_t}{\sqrt{1-\bar{\alpha}_t}}\epsilon_\theta(\mathbf{x}_t,t)\right)+\sigma_t\mathbf{z},\tag{23}$$

여기서 $\mathbf{z}\sim\mathcal{N}(0,\mathbf{I})$이다. 식 (21)을 다시 쓰면 각 시점에서 $\mathbf{x}_0$의 예측값 $\hat{\mathbf{x}}_0$을 다음과 같이 얻을 수 있다.

$$\hat{\mathbf{x}}_0=\frac{\mathbf{x}_t-\sqrt{1-\bar{\alpha}_t}\epsilon_\theta(\mathbf{x}_t,t)}{\sqrt{\bar{\alpha}_t}}.\tag{24}$$

### B. 추가 구현 세부 사항

#### B.1 환경 설정

사전 학습된 ADM [7], IDDPM [24], Stable Diffusion v1.4 [31], DiT [27]에서 샘플을 생성하기 위해 NVIDIA GeForce RTX 3090 GPU 8개로 구성된 서버 두 대를 사용했다. 각 모델의 PyTorch [26] 구현을 기반으로 하였으며, 공개 저장소에서 모든 가중치를 가져왔다.

#### B.2 선택적 블러

5.2절의 선택적 블러는 효율적으로 구현할 수 있다. 먼저 $\mathbf{x}_t$의 중간 복원 $\hat{\mathbf{x}}_0$을 블러 처리한다 [14]. 그런 다음 $\hat{\mathbf{x}}_0$과 블러 처리된 $\hat{\mathbf{x}}_0$에 각각 $1-M_t$와 $M_t$를 적용한다. 출력들을 합산한 뒤, 위에서 $\hat{\mathbf{x}}_0$ 계산에 사용한 예측 잡음 $\epsilon_\theta(\mathbf{x}_t)$를 이용해 다시 잡음을 추가한다. 이 과정은 본문의 식 (15)와 동일한 $\hat{\mathbf{x}}_t$를 생성한다.

#### B.3 SAG와 CFG의 결합

Stable Diffusion [31]과 DiT [27]에서 SAG를 CFG [16]와 결합하려면 조건부 모델과 비조건부 모델에 대해 SAG를 각각 계산해야 하므로 네 번의 순전파가 필요하다. 실제로는 다음과 같이 가이던스된 잡음 예측을 효율적으로 계산할 수 있다.

$$\tilde{\epsilon}(\mathbf{x}_t)=\epsilon_\theta(\mathbf{x}_t,c)+s_c(\epsilon_\theta(\mathbf{x}_t,c)-\epsilon_\theta(\mathbf{x}_t))+s_s(\epsilon_\theta(\mathbf{x}_t)-\epsilon_\theta(\bar{\mathbf{x}}_t)),\tag{25}$$

여기서 $s_c$와 $s_s$는 각각 CFG와 SAG의 강도이며, $c$는 텍스트 프롬프트이다.

#### B.4 하이퍼파라미터 설정

| 모델 및 데이터셋 | 가이던스 강도 | 임계값 | 계층 | $\sigma$ |
|---|---:|---:|---|---:|
| ADM, ImageNet 256×256 비조건부 | 0.5, 0.8 | 1.0 | 출력 2 | 9 |
| ADM, ImageNet 256×256 조건부 | 0.2 | 1.0 | 출력 2 | 9 |
| ADM, LSUN Cat 256×256 | 0.05 | 1.0 | 출력 2 | 9 |
| ADM, LSUN Horse 256×256 | 0.01 | 1.0 | 출력 2 | 9 |
| ADM, ImageNet 128×128 | 0.1 | 1.0 | 출력 8 | 3 |
| IDDPM, ImageNet 64×64 비조건부 | 0.05 | 1.0 | 출력 7 | - |
| Stable Diffusion | 0.75, 1.0 | 1.0 | 중간 | - |
| DiT | 0.005 | 1.0 | 13번째 블록 | - |

> **표 8: 하이퍼파라미터 설정.**

### C. 추가 분석 및 결과

#### C.1 확산 모델의 자기 어텐션 탐구

ADM [7]의 U-Net [32]에서 8×8, 16×16, 32×32 해상도의 자기 어텐션 맵을 시각화했다. 중간 시점의 어텐션 맵은 생성 이미지의 구조를 포착했다. 또한 U-Net의 다양한 헤드와 계층에서 자기 어텐션 마스크를 추출하여 시각화했다. ‘평균’은 네 개 헤드의 어텐션 맵을 평균한 뒤 얻은 마스크를 의미한다.

ADM의 자기 어텐션 마스크와 DINO [3]의 자기 어텐션 마스크를 비교했다. DINO의 어텐션 마스크와 비교할 때 ADM의 마스크는 여러 객체와 확산 모델이 정교하게 표현해야 하는 이미지의 고주파 세부 정보에 더 많이 주목했다.

이 관찰을 바탕으로 확산 모델의 자기 어텐션이 주목하는 두 가지 요소, 즉 샘플의 주파수와 의미 정보를 조사했다. 먼저 높은 어텐션 점수를 갖는 패치와 전체 패치의 주파수 스펙트럼을 비교하여 자기 어텐션 맵과 주파수의 상관관계를 분석했다. 높은 어텐션을 갖는 패치가 더 많은 고주파 세부 정보를 포함한다는 것을 확인했다. 또한 자기 어텐션 맵이 전경 객체와 얼마나 일치하는지 평가했으며, 모든 해상도에서 일부 의미 정보를 포착한다는 것을 발견했다.

| 패치 크기 | $\psi$ | 무작위 | 자기 어텐션 | 차이 |
|---|---:|---:|---:|---:|
| 8×8 | 1.0 | 0.16 | 0.23 | +44% |
| 8×8 | 1.3 | 0.09 | 0.14 | +56% |
| 16×16 | 1.0 | 0.18 | 0.25 | +39% |
| 16×16 | 1.3 | 0.05 | 0.11 | +120% |
| 32×32 | 1.0 | 0.18 | 0.26 | +44% |
| 32×32 | 1.3 | 0.04 | 0.10 | +150% |

> **표 9: 자기 어텐션 마스크의 의미론적 분석.** $\psi$는 마스킹 임계값이며, 차이는 무작위 기준과 비교한 IoU의 백분율 차이이다.

#### C.2 추가 절제 실험

자기 어텐션 마스킹의 임계값이 블러 처리 영역의 비율에 미치는 영향을 10K 샘플로 평가했다. 임계값 0.7, 1.0, 1.3을 테스트한 결과 임계값 1.0에서 가장 높은 성능을 얻었다.

| $\psi$ | 기준선 | $\psi=0.7$ | $\psi=1.0$ | $\psi=1.3$ |
|---|---:|---:|---:|---:|
| FID (↓) | 5.98 | 5.67 | **5.47** | 5.66 |
| IS (↑) | 141.72 | 148.60 | **151.12** | 145.58 |

> **표 10: 마스킹 임계값 $\psi$에 대한 절제 실험.** ImageNet 128×128으로 학습된 ADM의 결과이다.

어텐션 맵을 추출하는 계층에 대한 평가도 수행했다. 각 해상도의 인코더와 디코더에서 마지막 자기 어텐션 계층을 선택했으며, 인코더와 디코더를 나누는 병목 계층도 포함했다.

| 계층 | 기준선 | 입력 11 | 입력 8 | 중간 | 출력 2 | 출력 5 | 출력 8 |
|---|---:|---:|---:|---:|---:|---:|---:|
| FID (↓) | 5.98 | 5.54 | 5.61 | 5.63 | 5.59 | 5.57 | **5.47** |
| IS (↑) | 141.72 | 150.07 | 148.20 | 143.44 | 150.62 | 141.73 | **151.12** |

> **표 11: 어텐션 맵을 추출하는 계층에 대한 절제 실험.** 중간 블록은 ‘중간’으로 표기했으며, 입력 및 출력 블록의 $n$번째 계층은 각각 ‘입력 $n$’, ‘출력 $n$’으로 표기했다.

추출 계층과 관계없이 기준선보다 성능이 일관되게 향상되었다. 특히 최종 계층의 자기 어텐션을 사용하는 경우 FID와 IS가 가장 우수했다.

#### C.3 정성적 결과

본문의 샘플 외에도 ImageNet 128×128으로 사전 학습된 ADM, LSUN Cats, LSUN Horse에서 SAG를 적용해 무작위 샘플을 생성했다.

## D. 인간 평가 절차

Stable Diffusion [31] 샘플을 사용하여 빈 프롬프트와 SAG 적용 여부를 달리한 500쌍의 이미지를 생성했다. SAG를 적용한 샘플의 SAG 강도는 1.0으로 설정했으며, 각 쌍에는 동일한 시드를 사용했다.

50명의 참가자에게 두 그룹으로 구성된 4개 샘플을 제시했다. 한 그룹은 SAG를 적용한 샘플이고 다른 그룹은 적용하지 않은 샘플이었다. 참가자들은 이미지 품질이 더 높은 그룹을 선택했다. 질문 예시는 그림 13에 제시되어 있다. 이미지 쌍은 임의로 선별하거나 필터링하지 않았으며, 응답에 대한 후처리도 수행하지 않았다.

> **그림 13: 평가 질문의 예시.** 참가자에게 어느 행이 제안 방법으로 샘플링되었는지는 알리지 않았다.

## E. 한계와 향후 연구

자기 조건화가 강화되면 일반적으로 사람에게 더 시각적으로 매력적인 결과를 얻을 수 있지만, 생성 이미지의 다양성과 참신성이 감소할 가능성도 고려해야 한다. 이는 추가적인 논의가 필요한 문제이다. 다만 현재 단계에서는 가이던스 강도를 조절하여 SAG의 영향을 효과적으로 제어할 수 있으므로 유용한 응용이 가능하다.

또한 SAG는 순전파 단계를 두 배로 요구한다. 이는 CFG [16]에도 공통적인 문제이며 해결이 필요하다. 가능한 해결책으로는 가이던스를 확산 모델에 증류하는 방법 [21]이 있다. 이를 통해 품질을 유지하면서 SAG와 CFG의 계산 비용을 줄일 수 있을 것이다.

자기 어텐션 기반 가이던스는 연속값으로 토큰 확률을 근사하는 대신 토큰 확률을 직접 모델링하는 이산 확산 모델 [39, 10]에 더 적합할 수도 있다. 이러한 모델과 본 방법의 통합은 흥미로운 향후 연구 주제이다.

## 참고문헌

참고문헌의 저자명, 학술대회명, 저널명 및 서지 정보는 원문 표기를 따른다.

[1] Dmitry Baranchuk, Andrey Voynov, Ivan Rubachev, Valentin Khrulkov, and Artem Babenko. 확산 모델을 이용한 레이블 효율적 의미론적 분할. ICLR, 2021.

[2] Emmanuel Asiedu Brempong, Simon Kornblith, Ting Chen, et al. 의미론적 분할을 위한 잡음 제거 사전 학습. CVPR, 2022.

[3] Mathilde Caron, Hugo Touvron, Ishan Misra, et al. 자기 지도 비전 Transformer의 새로운 특성. ICCV, 2021.

[4] Yuanqi Chen, Ge Li, Cece Jin, Shan Liu, and Thomas Li. SSD-GAN: 공간 및 스펙트럼 영역에서 현실성 측정. AAAI, 2021.

[5] Kanjar De and V. Masilamani. 주파수 영역에서 흐릿한 이미지의 이미지 선명도 측정. Procedia Engineering, 2013.

[6] Jia Deng, Wei Dong, Richard Socher, et al. ImageNet: 대규모 계층적 이미지 데이터베이스. CVPR, 2009.

[7] Prafulla Dhariwal and Alexander Nichol. 확산 모델이 이미지 합성에서 GAN을 능가하다. NeurIPS, 2021.

[8] Alexey Dosovitskiy, Lucas Beyer, Alexander Kolesnikov, et al. 이미지 하나는 16×16 단어의 가치가 있다: 대규모 이미지 인식을 위한 Transformer. ICLR, 2020.

[9] Patrick Esser, Robin Rombach, and Bjorn Ommer. 고해상도 이미지 합성을 위한 Transformer 길들이기. CVPR, 2021.

[10] Shuyang Gu, Dong Chen, Jianmin Bao, et al. 텍스트-이미지 합성을 위한 벡터 양자화 확산 모델. CVPR, 2022.

[11] Kaiming He, Georgia Gkioxari, Piotr Dollár, and Ross Girshick. Mask R-CNN. ICCV, 2017.

[12] Amir Hertz, Ron Mokady, Jay Tenenbaum, et al. 교차 어텐션 제어를 이용한 프롬프트-투-프롬프트 이미지 편집. arXiv, 2022.

[13] Martin Heusel, Hubert Ramsauer, Thomas Unterthiner, et al. 두 시간 척도 업데이트 규칙으로 학습된 GAN은 국소 내시 균형으로 수렴한다. NeurIPS, 2017.

[14] Jonathan Ho, Ajay Jain, and Pieter Abbeel. 잡음 제거 확률적 생성 모델. NeurIPS, 2020.

[15] Jonathan Ho, Chitwan Saharia, William Chan, et al. 고충실도 이미지 생성을 위한 계층형 확산 모델. JMLR, 2022.

[16] Jonathan Ho and Tim Salimans. 분류기 없는 확산 가이던스. NeurIPS 워크숍, 2021.

[17] Emiel Hoogeboom and Tim Salimans. 블러 확산 모델. arXiv, 2022.

[18] Yifan Jiang, Shiyu Chang, and Zhangyang Wang. TransGAN: 두 개의 순수 Transformer로 강력한 GAN 만들기 및 확장. NeurIPS, 2021.

[19] Tuomas Kynkäänniemi, Tero Karras, Samuli Laine, et al. 생성 모델 평가를 위한 개선된 정밀도 및 재현율 지표. NeurIPS, 2019.

[20] Sangyun Lee, Hyungjin Chung, Jaehyeon Kim, and Jong Chul Ye. 거친 단계에서 세밀한 단계로의 이미지 합성을 위한 확산 모델의 점진적 디블러링. NeurIPS 워크숍, 2022.

[21] Chenlin Meng, Ruiqi Gao, Diederik P. Kingma, et al. 가이던스된 확산 모델의 증류에 관하여. arXiv, 2022.

[22] Charlie Nash, Jacob Menick, Sander Dieleman, and Peter Battaglia. 희소 표현을 이용한 이미지 생성. ICML, 2021.

[23] Alex Nichol, Prafulla Dhariwal, Aditya Ramesh, et al. GLIDE: 텍스트 가이던스 확산 모델을 이용한 사실적 이미지 생성 및 편집을 향하여. arXiv, 2021.

[24] Alexander Quinn Nichol and Prafulla Dhariwal. 개선된 잡음 제거 확률적 생성 모델. ICML, 2021.

[25] Bjorn Ommer and Joachim M. Buhmann. 시각 객체의 구성적 본질 학습. CVPR, 2007.

[26] Adam Paszke, Sam Gross, Francisco Massa, et al. PyTorch: 명령형 방식의 고성능 딥러닝 라이브러리. NeurIPS, 2019.

[27] William Peebles and Saining Xie. Transformer를 이용한 확장 가능한 확산 모델. arXiv, 2022.

[28] Alec Radford, Jong Wook Kim, Chris Hallacy, et al. 자연어 감독을 이용한 전이 가능한 시각 모델 학습. ICML, 2021.

[29] Aditya Ramesh, Prafulla Dhariwal, Alex Nichol, et al. CLIP 잠재 변수를 이용한 계층적 텍스트 조건부 이미지 생성. arXiv, 2022.

[30] Severi Rissanen, Markus Heinonen, and Arno Solin. 역열 확산을 이용한 생성 모델링. arXiv, 2022.

[31] Robin Rombach, Andreas Blattmann, Dominik Lorenz, et al. 잠재 확산 모델을 이용한 고해상도 이미지 합성. CVPR, 2022.

[32] Olaf Ronneberger, Philipp Fischer, and Thomas Brox. U-Net: 생의학 이미지 분할을 위한 컨볼루션 네트워크. MICCAI, 2015.

[33] Chitwan Saharia, William Chan, Saurabh Saxena, et al. 심층 언어 이해를 갖춘 사실적 텍스트-이미지 확산 모델. arXiv, 2022.

[34] Tim Salimans, Ian Goodfellow, Wojciech Zaremba, et al. GAN 학습을 위한 개선된 기법. NeurIPS, 2016.

[35] Jascha Sohl-Dickstein, Eric Weiss, Niru Maheswaranathan, and Surya Ganguli. 비평형 열역학을 이용한 비지도 학습. ICML, 2015.

[36] Jiaming Song, Chenlin Meng, and Stefano Ermon. 잡음 제거 확산 암시 모델. ICLR, 2021.

[37] Yang Song and Stefano Ermon. 데이터 분포의 그래디언트를 추정하는 생성 모델링. NeurIPS, 2019.

[38] Yang Song, Jascha Sohl-Dickstein, Diederik P. Kingma, et al. 확률 미분방정식을 통한 점수 기반 생성 모델링. ICLR, 2020.

[39] Zhicong Tang, Shuyang Gu, Jianmin Bao, et al. 개선된 벡터 양자화 확산 모델. arXiv, 2022.

[40] Ashish Vaswani, Noam Shazeer, Niki Parmar, et al. Attention is all you need. NeurIPS, 2017.

[41] Tengfei Wang, Ting Zhang, Bo Zhang, et al. 이미지-이미지 변환을 위해 필요한 것은 사전 학습뿐이다. arXiv, 2022.

[42] Yiwen Xu, Maurice Pagnucco, and Yang Song. DHG-GAN: 결합된 고주파 의미론을 통한 다양한 이미지 외삽. ACCV, 2022.

[43] Mengping Yang, Zhe Wang, Ziqiu Chi, and Wenyi Feng. WaveGAN: 고충실도 소수샷 이미지 생성을 위한 주파수 인식 GAN. ECCV, 2022.

[44] Fisher Yu, Ari Seff, Yinda Zhang, et al. LSUN: 인간이 참여한 딥러닝을 이용한 대규모 이미지 데이터셋 구축. arXiv, 2015.

[45] Bowen Zhang, Shuyang Gu, Bo Zhang, et al. StyleSwin: 고해상도 이미지 생성을 위한 Transformer 기반 GAN. CVPR, 2022.

[46] Han Zhang, Ian Goodfellow, Dimitris Metaxas, and Augustus Odena. 자기 어텐션 생성적 적대 신경망. ICML, 2019.