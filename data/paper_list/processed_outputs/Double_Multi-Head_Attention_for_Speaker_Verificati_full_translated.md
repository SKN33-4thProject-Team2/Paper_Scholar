# 원제: Double Multi-Head Attention for Speaker Verification

[본문 전체 마크다운 번역 결과]

# 화자 검증을 위한 이중 다중 헤드 어텐션

Miquel India, Pooyan Safari, Javier Hernando  
TALP 연구센터, 신호 이론 및 통신학과, 카탈루냐 공과대학교, 바르셀로나, 스페인  
{miquel.angel.india, javier.hernando}@upc.edu, pooyan.safari@tsc.upc.edu

## 초록

화자 검증을 위한 최신 딥러닝 시스템 대부분은 화자 임베딩 추출기를 기반으로 한다. 이러한 구조는 일반적으로 특징 추출 프런트엔드와 가변 길이 발화를 고정 길이 화자 벡터로 변환하는 풀링 층으로 구성된다. 본 논문에서는 기존의 Self Multi-Head Attention 기반 접근법을 확장한 Double Multi-Head Attention 풀링을 제안한다. 제안 방법은 풀링 층에 추가적인 셀프 어텐션 층을 도입하여 Multi-Head Attention이 생성한 컨텍스트 벡터들을 하나의 화자 표현으로 요약한다. 이 방법은 각 헤드가 포착한 정보에 가중치를 부여함으로써 풀링 메커니즘을 강화하며, 더욱 판별력 있는 화자 임베딩을 생성한다.

제안 방법은 VoxCeleb2 데이터셋을 사용하여 평가하였다. 그 결과 Self Attention 풀링 및 Self Multi-Head Attention과 비교하여 EER 기준 각각 6.09%와 5.23%의 상대적 개선을 확인하였다. 이러한 결과는 Double Multi-Head Attention이 음성 신호로부터 CNN 기반 프런트엔드가 포착한 가장 관련성 높은 특징을 효율적으로 선택하는 데 매우 효과적인 방법임을 보여준다.

입력 신호로부터 프런트엔드가 인코딩한 시퀀스가 주어지면, 풀링 층을 사용하여 발화 수준 표현을 얻는다. 최근 몇 년 동안 다양한 풀링 전략을 다룬 여러 연구가 수행되었다 [19, 20, 21]. X-vector는 본래 통계적 풀링을 사용한다 [6]. Self Attention 메커니즘은 통계적 풀링을 개선하기 위해 사용되어 왔으며, 그 예로 [22]가 있다. [23]과 같은 연구에서는 어텐션을 사용하여 순서 정보를 포함한 더 나은 특징 통계를 추출한다. 또한 기본적인 Self Attention 메커니즘을 개선한 다양한 Self Attention 기반 풀링 층이 제안되었다. [22]에서는 동일한 인코딩 시퀀스에 여러 어텐션을 적용하여 복수의 컨텍스트 벡터를 생성한다. 우리의 이전 연구 [11]에서는 인코딩된 시퀀스를 여러 헤드로 분할하고 각 헤드의 부분 시퀀스에 서로 다른 어텐션 모델을 적용한다. [24]와 같이 비(非)셀프 어텐션 메커니즘도 제안되었는데, 여기서는 비교하려는 두 발화를 입력으로 상호 어텐션 네트워크를 구성한다.

**색인어—** Self Multi-Head Attention, 이중 어텐션, 화자 인식, 화자 검증

## 1. 서론

화자 검증은 한 쌍의 오디오가 동일한 화자에 의해 발화되었는지를 판별하는 것을 목적으로 한다. 화자 검증 시스템은 음성 신호로부터 음성의 특성에 나타난 화자 정체성 패턴을 추출할 수 있다. 이러한 패턴은 통계적으로 모델링되거나 판별력 있는 화자 표현으로 인코딩될 수 있다. 최근 몇 년 동안 연구자들은 이러한 화자 특성을 더욱 판별력 있는 화자 벡터로 인코딩하기 위해 상당한 노력을 기울여 왔다.

현재 최첨단 화자 검증 시스템은 딥러닝(Deep Learning, DL) 접근법을 기반으로 한다. 이러한 구조는 일반적으로 화자 분류기로 학습된 후 화자 임베딩 추출기로 사용된다. 화자 임베딩은 심층 신경망(Deep Neural Network, DNN)의 일부 후반 층에서 추출되는 고정 길이 벡터이다 [1]. 가장 잘 알려진 표현은 x-vector [2]이며, 이는 화자 인식의 최신 기술로 자리 잡았을 뿐 아니라 언어 인식 및 감정 인식과 같은 다른 과제에도 사용되고 있다 [3, 4].

본 논문에서는 화자 검증을 위한 Double Multi-Head Attention(MHA) 풀링 층을 제안한다. 이 층의 사용은 [25]에서 영감을 얻었다. [25]에서는 Double MHA를 이중 셀프 어텐션 블록으로 제시하여 이미지의 특징 통계를 포착하고 특징을 적응적으로 할당한다. 본 연구에서는 이 메커니즘을 두 개의 Self Attention 풀링 층을 결합하는 방식으로 사용하여 발화 수준 화자 임베딩을 생성한다.

CNN에서 출력된 인코딩 표현 시퀀스가 주어졌을 때, Self MHA는 $K$개의 부분 임베딩 시퀀스에 적용된 $K$개 헤드 어텐션의 컨텍스트 벡터를 연결한다. 이후 추가적인 Self Attention 메커니즘을 다중 헤드 컨텍스트 벡터에 적용한다. 이 어텐션 기반 풀링은 헤드 컨텍스트 벡터 집합을 하나의 전역 화자 표현으로 요약한다. 이 표현은 헤드 컨텍스트 벡터의 가중 평균으로 풀링되며, 헤드 가중치는 Self Attention 메커니즘을 통해 생성된다.

한편, 이 접근법은 모델이 시퀀스의 서로 다른 부분에 주의를 기울이는 동시에 인코딩 표현의 서로 다른 부분집합을 포착하도록 한다. 다른 한편으로, 풀링 층은 전역 컨텍스트 벡터를 생성하는 데 가장 관련성 높은 헤드 컨텍스트 벡터를 선택할 수 있도록 한다.

최근 화자 임베딩 추출에 사용되는 네트워크 구조 대부분은 프런트엔드 특징 추출기, 풀링 층 및 일련의 완전연결(Fully Connected, FC) 층으로 구성된다. 최근에는 다양한 네트워크 구성을 통해 오디오 발화를 화자 임베딩으로 인코딩하기 위한 여러 구조가 제안되었다 [5, 6, 7, 8, 9]. Mel-Frequency Cepstral Coefficient(MFCC) 특징을 사용하는 경우, Time Delay Neural Network(TDNN) [5, 6]이 현재 가장 널리 사용되는 구조이다. TDNN은 x-vector 프런트엔드로 사용되며, 일련의 1차원 확장 합성곱 신경망(CNN)으로 구성된다. TDNN을 사용하는 목적은 장기적인 특징 관계를 포착하여 MFCC 시퀀스를 더욱 판별력 있는 벡터 시퀀스로 인코딩하는 데 있다.

2차원 CNN도 화자 검증에서 경쟁력 있는 성능을 보였다. VGG [7, 10, 11]와 ResNet [8, 12, 13] 같은 컴퓨터 비전 구조는 Mel 스펙트로그램으로부터 화자 판별 정보를 포착하도록 변형되었다. 실제로 ResNet34는 최근 화자 검증 과제 [14, 15]에서 TDNN보다 우수한 성능을 보였다. 이 밖에도 수작업으로 설계된 특징을 사용하지 않고 원시 신호를 직접 처리하려는 연구가 진행되었다 [16, 17, 18].

본 논문에서 제안하는 Double Multi-Head Attention 풀링은 Self Multi-Head Attention을 기반으로 한 우리의 이전 접근법을 확장한 것이다. 풀링 층에 추가적인 셀프 어텐션 층을 도입하여 Multi-Head Attention이 생성한 컨텍스트 벡터를 하나의 화자 표현으로 요약한다. 제안 방법은 각 헤드가 포착한 정보의 중요도에 가중치를 부여하여 풀링 메커니즘을 개선하고, 더욱 판별력 있는 화자 임베딩을 생성한다.

이 연구는 스페인 연구과제 PID2019-107579RB-I00 / AEI / 10.13039/501100011033의 지원을 받았다.

[25]와 비교하면, 두 번째 풀링 층은 이미지에 적용된 Self Multi-Attention 메커니즘이 생성한 전역 기술자 대신 MHA가 생성한 헤드 컨텍스트 벡터에 대해 연산을 수행한다.

## 2. 제안 구조

제안 시스템의 구조는 그림 1에 제시되어 있다. 이 시스템은 가변 길이의 Mel 스펙트로그램 특징 집합을 입력으로 받아 화자 표현 시퀀스를 출력하는 CNN 기반 프런트엔드를 사용한다. 이후 이러한 화자 표현에 본 연구의 핵심 기여인 Double MHA 풀링을 적용한다.

Double MHA 층은 Self MHA 풀링과 각 헤드 컨텍스트 벡터의 정보를 하나의 화자 임베딩으로 요약하는 추가적인 Self Attention 층으로 구성된다. Self MHA 풀링과 Self Head Attention 층의 결합은 더욱 심층적인 셀프 어텐션 풀링 메커니즘을 제공한다(그림 2).

풀링 층에서 얻은 화자 임베딩은 일련의 FC 층을 거쳐 화자 사후확률을 예측한다. 이 네트워크 구조는 화자 분류기로서 Additive Margin Softmax(AMS) 손실 [26]을 사용하여 학습되며, 이후 화자 임베딩 추출기로 활용된다.

### 2.1 프런트엔드 특징 추출기

특징 추출 네트워크는 [11]에서 제안한 변형 VGG를 확장한 버전이다. 이 CNN은 네 개의 합성곱 블록으로 구성되며, 각 블록은 두 개의 연속된 합성곱 층과 $2 \times 2$ 스트라이드를 사용하는 최대 풀링 층으로 이루어진다. 따라서 $N$개의 프레임으로 구성된 스펙트로그램이 입력되면 VGG는 다운샘플링을 수행하여 $N/16$개의 표현 시퀀스를 출력한다.

VGG의 출력 $h \in \mathbb{R}^{M \times N/16 \times D'}$는 각각 $N/16 \times D'$ 차원을 갖는 $M$개의 특징 맵 집합이다. 이 특징 맵들을 연결하여 하나의 벡터 시퀀스로 구성한다. 이렇게 재구성된 은닉 상태 시퀀스는 $h \in \mathbb{R}^{N/16 \times D}$로 정의할 수 있으며, 여기서 $D = MD'$는 은닉 상태의 차원이다.

> **그림 1. 시스템 구조.**

### 표 1. CNN 구조

In Dim.과 Out Dim.은 각각 층의 입력 및 출력 특징 맵 수를 의미한다. Feat Size는 각 출력 특징 맵의 차원을 의미한다.

| 층 | 크기 | 입력 차원 | 출력 차원 | 스트라이드 | 특징 크기 |
|---|---:|---:|---:|---:|---:|
| conv11 | 3×3 | 1 | 128 | 1×1 | N×80 |
| conv12 | 3×3 | 128 | 128 | 1×1 | N×80 |
| mpool1 | 2×2 | - | - | 2×2 | N/2×40 |
| conv21 | 3×3 | 128 | 256 | 1×1 | N/2×40 |
| conv22 | 3×3 | 256 | 256 | 1×1 | N/2×40 |
| mpool2 | 2×2 | - | - | 2×2 | N/4×20 |
| conv31 | 3×3 | 256 | 512 | 1×1 | N/4×20 |
| conv32 | 3×3 | 512 | 512 | 1×1 | N/4×20 |
| mpool3 | 2×2 | - | - | 2×2 | N/8×10 |
| conv41 | 3×3 | 512 | 1024 | 1×1 | N/8×10 |
| conv42 | 3×3 | 1024 | 1024 | 1×1 | N/8×10 |
| mpool4 | 2×2 | - | - | 2×2 | N/16×5 |
| flatten | - | 1024 | 1 | - | N/16×5120 |

### 2.2 Self Multi-Head Attention 풀링

프런트엔드 특징 추출기가 출력한 은닉 상태 시퀀스는 $h = [h_1, h_2, \ldots, h_N]$으로 표현할 수 있으며, $h_t \in \mathbb{R}^{D}$이다. MHA 풀링에 $K$개의 헤드를 사용한다고 하면, 은닉 상태를 $h_t = [h_{t1}, h_{t2}, \ldots, h_{tK}]$로 정의할 수 있다. 여기서 $h_{tj} \in \mathbb{R}^{D/K}$이다. 즉, 각 특징 벡터는 $D/K$ 크기의 부분 특징 벡터 집합으로 분할된다.

마찬가지로 학습 가능한 파라미터 $u = [u_1, u_2, \ldots, u_K]$를 정의하며, $u_j \in \mathbb{R}^{D/K}$이다. 이후 인코딩된 시퀀스의 각 헤드에 Self Attention 연산을 적용한다. 각 헤드 정렬의 가중치는 다음과 같이 정의된다.

$$w_{tj} = \frac{\exp\left(h_{tj}^{T}u_j/\sqrt{d_h}\right)}{\sum_{l=1}^{N}\exp\left(h_{lj}^{T}u_j/\sqrt{d_h}\right)}$$

여기서 $w_{tj}$는 시퀀스의 $t$번째 단계에서 헤드 $j$가 갖는 어텐션 가중치이며, $d_h$는 은닉 상태 차원 $D/K$이다. 각 헤드가 은닉 상태의 부분공간에 해당한다고 보면, 해당 헤드의 가중치 시퀀스는 그 부분공간의 특징이 시퀀스에서 나타나는 확률밀도함수로 간주할 수 있다.

그런 다음 기본적인 Self Attention과 동일한 방식으로 각 헤드에 대해 새로운 풀링 표현을 계산한다.

$$c_j = \sum_{t=1}^{N}w_{tj}h_{tj}^{T}$$

여기서 $c_j \in \mathbb{R}^{D/K}$는 헤드 $j$에서 얻은 발화 수준 표현이다. 최종 발화 수준 표현은 모든 헤드의 발화 수준 벡터를 연결하여 얻는다.

$$c = [c_1,c_2,\ldots,c_K]$$

이 방법을 사용하면 네트워크가 서로 다른 영역에서 서로 다른 종류의 정보를 추출할 수 있다.

### 2.3 Double Multi-Head Attention

Self MHA 풀링의 주요 단점은 모든 헤드의 중요도가 동일하다고 가정한다는 점이다. 출력 컨텍스트 벡터는 모든 헤드 컨텍스트 벡터를 연결한 것이며, 다음 단계의 밀집 층에 입력으로 사용된다. 반면 Double MHA는 이러한 가정을 하지 않는다. 따라서 각 발화의 컨텍스트 벡터는 헤드 컨텍스트 벡터의 서로 다른 선형 결합으로 계산된다.

요약 벡터 $c$는 헤드 컨텍스트 벡터 $c_i$ 집합에 대한 가중 평균으로 정의된다. 헤드 컨텍스트 벡터 집합을 풀링하고 전체 컨텍스트 벡터 $c$를 얻기 위해 Self Attention을 적용한다.

$$w_i' = \frac{\exp\left(c_i^{T}u'/\sqrt{d_h}\right)}{\sum_{l=1}^{K}\exp\left(c_l^{T}u'/\sqrt{d_h}\right)}$$

여기서 $w_i'$는 각 헤드의 정렬 가중치이며, $u' \in \mathbb{R}^{D/K}$는 학습 가능한 파라미터이다. 컨텍스트 벡터 $c$는 헤드 컨텍스트 벡터들의 가중 평균으로 계산된다.

$$c = \sum_{i=1}^{K}w_i'c_i$$

> **그림 2. 헤드 5개를 사용한 Double MHA 풀링의 예.**

이 방법을 사용하면 각 발화의 컨텍스트 벡터가 가장 관련성이 높은 헤드와 가장 관련성이 낮은 헤드의 정보에 서로 다른 가중치를 부여하여 생성된다. 전체 풀링 층의 관점에서 Double MHA는 입력의 서로 다른 영역에서 서로 다른 화자 패턴을 포착하는 동시에, 각 발화에 대해 이러한 패턴들의 중요도에 가중치를 부여할 수 있다.

풀링에 사용되는 헤드 수는 컨텍스트 벡터의 차원과 VGG 특징 맵의 그룹화 방식을 동시에 결정한다. $M$개의 채널과 $K$개의 헤드를 사용한다고 하면, 각 헤드에 대해 $D'M/K$ 차원의 $c_i$ 컨텍스트 벡터를 생성하며, 이 벡터는 $M/K$개의 특징 맵 부분집합을 포함한다. 따라서 헤드 수가 증가하면 Double MHA가 고려할 수 있는 특징 부분집합의 수는 늘어나지만 최종 발화 수준 컨텍스트 벡터의 차원은 감소한다. 이는 생성할 수 있는 특징 부분집합의 수와 컨텍스트 벡터 부분공간에서 해당 특징이 얼마나 압축되는지 사이에 상충관계가 있음을 의미한다.

제안 방법을 비교하기 위해 두 가지 기준선을 고려하였다. Double MHA 풀링을 Self Attention과 Self MHA라는 두 가지 Self Attention 기반 풀링 방법과 비교하였다. 평가를 위해 다른 네트워크 블록이나 파라미터는 변경하지 않고 시스템의 풀링 층(그림 1)만 이러한 메커니즘으로 교체하였다. 검증 실험에 사용한 화자 임베딩은 각 풀링 방법에서 동일한 FC 층으로부터 추출하였다. 화자 임베딩 쌍 사이의 점수를 계산하기 위해 코사인 거리를 사용하였다.

제안 네트워크는 가변 길이 화자 발화를 분류하도록 학습되었다. 입력 특징으로는 25 ms 길이의 해밍 윈도와 10 ms의 윈도 이동을 사용하여 추출한 80차원 로그 Mel 스펙트로그램을 사용하였다. 오디오 특징은 켑스트럼 평균 정규화(CMN)로 정규화하였다. 이후 CNN 인코더는 $N \times 80$ 스펙트로그램을 입력으로 받아 $N/16 \times 5120$ 차원의 인코딩된 은닉 표현 시퀀스를 출력한다. 학습 시에는 $N=350$ 프레임 길이의 오디오 청크를 배치로 사용했으며, 테스트 시에는 전체 발화를 인코딩하였다. CNN 특징 추출기의 구성은 표 1에 제시되어 있다.

풀링 층에서는 Self MHA와 Double MHA 모두에 대해 헤드 수를 조정하였다. 제안한 CNN 구성에서는 8, 16, 32개의 헤드를 고려했으며, 이에 따라 각 헤드의 컨텍스트 벡터 $c_i$ 차원은 각각 640, 320, 160이 된다. 64개 헤드를 사용하는 모델은 학습이 불안정하여 제외하였다.

### 2.4 완전연결 층

풀링 층에서 얻은 발화 수준 화자 벡터는 네 개의 FC 층으로 구성된 구조에 입력된다(그림 1). 처음 두 FC 층 뒤에는 배치 정규화 [27]와 ReLU 활성화 함수를 적용한다. 세 번째 FC 층에는 밀집 층을 사용하며, 마지막 FC 층은 화자 분류 층이다. AMS를 사용하여 네트워크를 학습하므로 [26]에서 제안한 방식에 따라 세 번째 층에는 활성화 함수와 배치 정규화를 적용하지 않는다. 네트워크를 학습한 후에는 중간 FC 층 중 하나에서 화자 임베딩을 추출할 수 있다. [26]에 따라 세 번째 층 대신 두 번째 층을 화자 임베딩으로 사용하였다. 따라서 이 FC 층의 출력이 화자 검증 과제에 사용되는 화자 표현이 된다.

## 3. 실험 설정

본 연구의 제안 시스템은 VoxCeleb 데이터셋 [28, 7]을 사용하여 평가하였다. VoxCeleb은 6천 명 이상의 유명인에 대한 100만 개가 넘는 16 kHz 오디오 발화를 포함하는 대규모 멀티미디어 데이터베이스이다. VoxCeleb에는 여러 평가 프로토콜을 포함하는 두 가지 버전이 있다. 본 실험에서는 증강을 적용하지 않은 VoxCeleb2 개발 파티션을 사용하여 기준선과 제안 방법을 모두 학습하였다. 시스템 성능은 Vox1 test, Vox1-E 및 Vox1-H 조건에서 평가하였다. 이 프로토콜은 각각 37,611개, 581,480개, 552,536개의 Vox1 무작위 발화 쌍으로 구성된다. Vox1 test는 테스트 세트만 사용하며, Vox1-E는 전체 개발 코퍼스와 테스트 코퍼스를 사용한다. Vox1-H는 동일한 국적 및 성별의 화자들로 구성된 오디오 쌍으로 제한된다.

시스템의 마지막 블록은 네 개의 연속된 FC 층으로 구성된다. 처음 세 개의 밀집 층은 400차원이며, 마지막 FC 층은 학습 화자 레이블 수에 해당하는 5,994차원이다. 2.4절에서 언급한 바와 같이 배치 정규화는 처음 두 밀집 층에만 적용하였다.

네트워크는 $s=30$ 및 $m=0.4$의 하이퍼파라미터를 사용하는 AMS 손실로 학습하였다. 배치 크기는 128로 설정하였으며, 모든 모델은 학습률 $1\mathrm{e}{-4}$와 가중치 감쇠 $1\mathrm{e}{-3}$를 사용하는 Adam 옵티마이저로 학습하였다. 모델은 100 에포크 동안 학습했으며, 학습률 어닐링 전략을 사용하였다. 검증 성능이 15 에포크 동안 개선되지 않으면 학습률을 0.5배로 감소시켰다.

각 풀링 방법에 대한 헤드 컨텍스트 벡터와 전역 컨텍스트 벡터의 차원을 표 2에 포함하여 헤드 수와 모델 성능 사이의 관계를 분석하였다. 2.3절에서 논의한 바와 같이 Self MHA에서 $c_i$의 차원과 Double MHA에서 $c_i$ 및 $c$의 차원은 헤드 수에 반비례한다. 따라서 인코딩된 시퀀스에 적용되는 어텐션의 수와 각 어텐션이 포착할 수 있는 화자 정보의 양 사이에는 상충관계가 존재한다.

Double MHA에서 가장 낮은 성능은 8개 헤드 설정에서 나타났다. 이 설정에서는 $c_i$와 $c$의 차원이 모두 640이다. 최신 화자 임베딩의 차원은 대략 200~1,500 범위이다. 따라서 $c$의 차원을 더 줄이고 어텐션 수를 늘릴 여지가 있다. 헤드 수를 증가시키면 검증 성능이 향상되었다. 가장 우수한 Double MHA 모델은 32개 헤드를 사용했으며, 이때 컨텍스트 벡터 $c$의 차원은 160이다. 이 모델에서는 화자 정보가 더 낮은 차원의 표현으로 인코딩되며, 풀링 층은 CNN 채널의 서로 다른 32개 부분집합에 주의를 기울일 수 있다.

더 많은 헤드 수를 사용하는 모델도 고려하였으나, 지나치게 좁은 $c$ 차원으로 인해 학습이 불안정해져 학습할 수 없었다. 따라서 Double MHA는 병목 층으로 작동하는 Self MHA의 정규화된 확장으로 볼 수 있다. 한편 헤드 수의 선택은 CNN 구성과도 관련이 있다. 실험 결과 CNN 출력 특징 맵은 $M/K=32$개 채널의 부분집합으로 그룹화할 때 가장 효율적이었으며, 이는 160차원 임베딩의 부분 시퀀스에 해당한다. 해당 풀링 층에서 이 32개 컨텍스트 벡터 집합을 Double MHA로 효율적으로 평균화하면, 하나의 160차원 발화 수준 화자 표현을 얻을 수 있다.

## 4. 결과

제안 방법은 VoxCeleb 텍스트 비의존 화자 검증 과제에서 여러 어텐션 방법과 비교하여 평가하였다. 성능은 등가 오류율(Equal Error Rate, EER)과 탐지 비용 함수(Detection Cost Function, DCF)를 사용하여 평가하였다. DCF는 $C_{FA}=1$, $C_M=1$, $P_T=0.01$로 계산하였다. 실험 결과는 표 2에 제시되어 있다. 언급한 평가 지표와 함께 각 풀링 방법에 대한 헤드 컨텍스트 벡터 $c_i$ 및 전역 컨텍스트 벡터 $c$의 차원도 제시하였다.

Self Attention 풀링은 Self MHA와 비교하여 매우 유사한 결과를 보였다. Self Attention과 비교하면 Self MHA는 각각 8개 헤드를 사용한 Vox1-test와 16개 헤드를 사용한 Vox1-E 프로토콜에서 더 나은 성능을 보였다. Self Attention 대비 상대적 개선율은 8개 헤드 모델의 Vox1-test EER 기준 1.75%, 16개 헤드 모델의 Vox1-E EER 기준 0.58%였다. 반면 Vox1-H에서는 Self Attention이 EER 4.89%, DCF 0.0038로 가장 우수한 기준선 성능을 보였다. 가장 우수한 Self MHA 방식과 비교할 때 Self Attention의 상대적 개선은 EER 기준 0.58%에 불과했다. 이러한 유사한 결과는 Self MHA가 기본 Self Attention 풀링에 비해 뚜렷한 성능 향상을 가져오지 못했음을 의미한다.

Double MHA는 모든 헤드 수 설정에서 Self Attention 및 Self MHA보다 우수한 결과를 보였다. 평균적으로 32개 헤드 모델은 EER과 DCF 모두에서 모든 기준선 시스템을 능가했다. Vox1-test, Vox1-E 및 Vox1-H에서 32개 헤드를 사용한 Double MHA는 각각 32개 헤드를 사용한 Self MHA 모델과 비교하여 EER 기준 11.26%, 13.58%, 13.83%의 상대적 개선을 보였다. 이러한 성능 향상은 8개 및 16개 헤드 설정에서도 모든 프로토콜의 평균 기준으로 각각 5.23%와 5.62% 나타났다. 따라서 Double MHA는 가장 우수한 결과를 제공했으며, 모든 헤드 수 설정에서 Self MHA보다 효과적이었다.

### 표 2. VoxCeleb 1 프로토콜 평가 결과

헤드 컨텍스트 벡터와 전역 컨텍스트 벡터는 각각 $c_i$와 $c$로 표기하였다.

| 접근법 | 헤드 수 | $c_i$ 차원 | $c$ 차원 | Vox1 Test EER | Vox1 Test DCF | Vox1-E EER | Vox1-E DCF | Vox1-H EER | Vox1-H DCF |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Attention | 1 | 5120 | 5120 | 3.42 | 0.0031 | 3.42 | 0.0029 | 4.89 | 0.0038 |
| MHA | 8 | 640 | 5120 | 3.36 | 0.0029 | 3.44 | 0.0029 | 5.04 | 0.0040 |
| MHA | 16 | 320 | 5120 | 3.43 | 0.0032 | 3.40 | 0.0029 | 4.90 | 0.0040 |
| MHA | 32 | 160 | 5120 | 3.64 | 0.0032 | 3.68 | 0.0031 | 5.35 | 0.0042 |
| Double MHA | 8 | 640 | 640 | 3.27 | 0.0028 | 3.23 | 0.0028 | 4.69 | 0.0037 |
| Double MHA | 16 | 320 | 320 | **3.19** | **0.0027** | 3.22 | 0.0027 | 4.67 | 0.0038 |
| Double MHA | 32 | 160 | 160 | 3.23 | 0.0028 | **3.18** | **0.0026** | **4.61** | **0.0036** |

## 5. 결론

본 논문에서는 단기 표현을 풀링하여 발화 수준 화자 임베딩을 얻는 Double Multi-Head Attention 메커니즘을 구현하였다. 제안한 풀링 층은 Self Multi-Head Attention 풀링과 각 헤드의 컨텍스트 벡터를 하나의 화자 벡터로 요약하는 Self Attention 메커니즘으로 구성된다.

이 풀링 층은 CNN 기반 신경망에서 평가하였다. CNN은 스펙트로그램을 화자 벡터 시퀀스로 변환하며, 이 벡터들이 제안한 풀링 층의 입력으로 사용된다. 풀링 층의 출력 활성화는 일련의 밀집 층에 연결된다. 네트워크는 화자 분류기로 학습되며, 완전연결 층의 병목 층을 화자 임베딩으로 사용한다.

화자 임베딩을 추출하고 코사인 거리를 적용하여 텍스트 비의존 화자 검증 과제에서 제안 방법을 다른 풀링 방법과 비교하였다. 제안 방법은 기본 Self Attention 및 Self Multi-Head Attention 풀링 모두를 능가하였다. 실험 결과 Double MHA 기반 모델은 16개 및 32개 헤드에서 가장 우수한 성능을 보였다.

---

## 참고문헌

[1] Omid Ghahabi, Pooyan Safari, Javier Hernando, “화자 인식에서의 딥러닝,” *Development and Analysis of Deep Learning Architectures*, pp. 145–169, Springer, 2020.

[2] David Snyder, Daniel Garcia-Romero, Gregory Sell, Daniel Povey, Sanjeev Khudanpur, “화자 인식을 위한 강건한 DNN 임베딩인 X-vector,” *2018 IEEE International Conference on Acoustics, Speech and Signal Processing (ICASSP)*, IEEE, 2018, pp. 5329–5333.

[3] David Snyder, Daniel Garcia-Romero, Alan McCree, Gregory Sell, Daniel Povey, Sanjeev Khudanpur, “X-vector를 사용한 음성 언어 인식,” *Odyssey*, 2018, pp. 105–111.

[4] Raghavendra Pappagari, Tianzi Wang, Jesus Villalba, Nanxin Chen, Najim Dehak, “X-vector와 감정의 결합: 감정 인식과 화자 인식의 상호 의존성 연구,” arXiv preprint arXiv:2002.05039, 2020.

[5] David Snyder, Pegah Ghahremani, Daniel Povey, Daniel Garcia-Romero, Yishay Carmiel, Sanjeev Khudanpur, “종단 간 화자 검증을 위한 심층 신경망 기반 화자 임베딩,” *2016 IEEE Spoken Language Technology Workshop (SLT)*, IEEE, 2016, pp. 165–170.

[6] David Snyder, Daniel Garcia-Romero, Daniel Povey, Sanjeev Khudanpur, “텍스트 비의존 화자 검증을 위한 심층 신경망 임베딩,” *Interspeech*, 2017, pp. 999–1003.

[7] J. S. Chung, A. Nagrani, A. Zisserman, “VoxCeleb2: 심층 화자 인식,” *INTERSPEECH*, 2018.

[8] Gautam Bhattacharya, Jahangir Alam, Patrick Kenny, “심층 화자 인식: 모듈형인가, 단일형인가?” *Proc. Interspeech*, 2019, pp. 1143–1147.

[9] Pooyan Safari, Miquel India, Javier Hernando, “화자 인식을 위한 Self-Attention 인코딩 및 풀링,” arXiv preprint arXiv:2008.01077, 2020.

[10] Joon Son Chung, Arsha Nagrani, Andrew Zisserman, “VoxCeleb2: 심층 화자 인식,” arXiv preprint arXiv:1806.05622, 2018.

[11] Miquel India, Pooyan Safari, Javier Hernando, “화자 인식을 위한 Self Multi-Head Attention.”

[12] Jianfeng Zhou, Tao Jiang, Zheng Li, Lin Li, Qingyang Hong, “채널별 특징 반응과 가산 지도 소프트맥스 손실 함수를 이용한 심층 화자 임베딩 추출,” *Proc. Interspeech 2019*, pp. 2883–2887.

[13] Amirhossein Hajavi, Ali Etemad, “짧은 구간 화자 인식을 위한 심층 신경망,” arXiv preprint arXiv:1907.10420, 2019.

[14] Joon Son Chung, Arsha Nagrani, Ernesto Coto, Weidi Xie, Mitchell McLaren, Douglas A. Reynolds, Andrew Zisserman, “VoxSRC 2019: 최초의 VoxCeleb 화자 인식 챌린지,” arXiv preprint arXiv:1912.02522, 2019.

[15] Hossein Zeinali, Shuai Wang, Anna Silnova, Pavel Matějka, Oldřich Plchot, “VoxCeleb 화자 인식 챌린지 2019를 위한 BUT 시스템 설명,” arXiv preprint arXiv:1910.12592, 2019.

[16] Mirco Ravanelli, Yoshua Bengio, “SincNet을 이용한 원시 파형 기반 화자 인식,” arXiv preprint arXiv:1808.00158, 2018.

[17] Jee-Weon Jung, Hee-Soo Heo, Il-Ho Yang, Hye-Jin Shim, Ha-Jin Yu, “텍스트 비의존 화자 검증을 위한 원시 파형 기반 종단 간 DNN에서 화자 과적합 방지,” *Extraction*, vol. 8, no. 12, pp. 23–24, 2018.

[18] Jee-Weon Jung, Hee-Soo Heo, Ju-ho Kim, Hye-jin Shim, Ha-Jin Yu, “RawNet: 텍스트 비의존 화자 검증을 위한 원시 파형 기반 고급 종단 간 심층 신경망,” arXiv preprint arXiv:1904.08104, 2019.

[19] Weicheng Cai, Jinkun Chen, Ming Li, “종단 간 화자 및 언어 인식 시스템에서 인코딩 층과 손실 함수 탐색,” *Proc. Odyssey 2018 The Speaker and Language Recognition Workshop*, 2018, pp. 74–81.

[20] Weidi Xie, Arsha Nagrani, Joon Son Chung, Andrew Zisserman, “실환경 화자 인식을 위한 발화 수준 집계,” *ICASSP 2019*, IEEE, 2019, pp. 5791–5795.

[21] Youngmoon Jung, Younggwan Kim, Hyungjun Lim, Yeunju Choi, Hoirin Kim, “텍스트 비의존 화자 검증을 위한 볼록 길이 정규화를 이용한 공간 피라미드 인코딩,” arXiv preprint arXiv:1906.08333, 2019.

[22] Yingke Zhu, Tom Ko, David Snyder, Brian Mak, Daniel Povey, “텍스트 비의존 화자 검증을 위한 Self-Attentive 화자 임베딩,” *Interspeech*, 2018, pp. 3573–3577.

[23] Koji Okabe, Takafumi Koshinaka, Koichi Shinoda, “심층 화자 임베딩을 위한 어텐티브 통계 풀링,” arXiv preprint arXiv:1803.10963, 2018.

[24] Jingyu Li, Tan Lee, “이중 어텐션 네트워크를 이용한 텍스트 비의존 화자 검증,” arXiv preprint arXiv:2009.05485, 2020.

[25] Yunpeng Chen, Yannis Kalantidis, Jianshu Li, Shuicheng Yan, Jiashi Feng, “A²-Nets: 이중 어텐션 네트워크,” *Advances in Neural Information Processing Systems*, 2018, pp. 352–361.

[26] Yi Liu, Liang He, Jia Liu, “화자 검증을 위한 대규모 마진 소프트맥스 손실,” arXiv preprint arXiv:1904.03479, 2019.

[27] Sergey Ioffe, Christian Szegedy, “배치 정규화: 내부 공변량 변화 감소를 통한 심층 네트워크 학습 가속화,” arXiv preprint arXiv:1502.03167, 2015.

[28] A. Nagrani, J. S. Chung, A. Zisserman, “VoxCeleb: 대규모 화자 식별 데이터셋,” *INTERSPEECH*, 2017.