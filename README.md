# 소리 데이터 기반 GOP 적 침투 경계 시스템

전방 GOP(일반전초) 환경에서 마이크/음향센서로 수집한 **소리 데이터**를 ML로 분석하여
적 침투 관련 음향(발자국·금속음·말소리·철책 절단음·차량/드론 등)을 탐지하고,
실시간으로 경계병에게 경보를 제공하는 시스템.

## 개념
```
음향센서 수집  →  [전처리: 멜-스펙트로그램]  →  [CNN/CRNN 음향 이벤트 탐지]
                                                        ↓
                                   실시간 추론 · 침투 위험 경보 · 대시보드
```

## 탐지 대상(예시)
- 침투 관련: 발자국, 금속 마찰음, 철책 절단/절곡음, 말소리, 차량·드론음, 총성
- 배경(정상): 바람, 비, 새/동물, 평상 소음

## 폴더 구조
- `data/raw` — 원본 음원(녹음/공개데이터) (git 제외)
- `data/processed` — 스펙트로그램·증강된 학습셋 (git 제외)
- `src/collect` — 음향 수집/인입 (센서·파일)
- `src/preprocess` — 스펙트로그램 변환, 노이즈 처리, 데이터 증강
- `src/model` — CNN/CRNN 음향 분류·이벤트 탐지 모델
- `src/inference` — 실시간 탐지·경보 판정
- `service` — FastAPI 백엔드 + 경보 대시보드
- `configs` — 설정(yaml)
- `models` — 학습된 가중치 (git 제외)

## 환경 구축
```bash
conda env create -f environment.yml
conda activate gop-acoustic
python -c "import torch, torchaudio; print('CUDA:', torch.cuda.is_available())"
```

## 데이터 출처(후보)
- 공개 환경음/이벤트: AudioSet, ESC-50, UrbanSound8K, DCASE(SED) 데이터셋
- 총성·차량 등 특수음: 공개 데이터셋 + 자체 녹음
- ※ 군 특수 음향은 비공개 → 공개 유사음으로 학습 후 자체 데이터로 보정

## 진행 단계
1. [ ] 음향 데이터 수집 파이프라인
2. [ ] 전처리(멜-스펙트로그램) + 데이터 증강
3. [ ] CNN 베이스라인 분류기
4. [ ] CRNN/SED 고도화(연속 스트림 이벤트 탐지)
5. [ ] 검증(혼동행렬·오경보율 FAR·탐지율)
6. [ ] 실시간 추론 + 경보 대시보드 + 배포
