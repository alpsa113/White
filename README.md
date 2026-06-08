# 북한 지역 합성 기상레이더 기반 위험기상 감시 시스템

위성·낙뢰·지형 데이터를 ML로 학습(남한 레이더 정답)하여, 레이더가 없는 북한 상공의
강수 분포를 "합성 레이더" 형태로 추정하고 접경 위험기상을 감시하는 시스템.

## 개념
```
GK-2A 위성 + 낙뢰 + DEM  →  [U-Net 학습: 남한 레이더 합성=정답]  →  북한 합성 반사도
                                                                      ↓
                                          GPM/IMERG 검증 · 접경 위험 경보 · 대시보드
```

## 폴더 구조
- `data/raw` — 원본 다운로드 (git 제외)
- `data/processed` — 격자 정합·정규화된 학습셋 (git 제외)
- `src/collect` — 데이터 수집(API/FTP)
- `src/preprocess` — 좌표·격자 정합, 시간 동기화
- `src/model` — U-Net 등 모델 정의·학습
- `src/inference` — 북한 추론·합성 반사도 생성
- `service` — FastAPI 백엔드 + 웹 대시보드
- `configs` — 설정(yaml)
- `models` — 학습된 가중치 (git 제외)

## 환경 구축
```bash
conda env create -f environment.yml
conda activate nk-radar
python -c "import torch; print('CUDA:', torch.cuda.is_available())"
```

## 데이터 출처
- GK-2A 위성: 국가기상위성센터 / 기상자료개방포털
- 레이더 합성(정답): 기상자료개방포털 (CAPPI/HSR)
- 낙뢰: 기상자료개방포털
- GPM/IMERG(검증): NASA GES DISC
- DEM: Copernicus / SRTM

## 진행 단계
1. [ ] 데이터 수집 파이프라인
2. [ ] 격자 정합 + 학습셋 구축
3. [ ] U-Net 베이스라인
4. [ ] nowcasting 고도화
5. [ ] 검증(접경/GPM/사례)
6. [ ] 위험 감시 로직 + 대시보드 + 배포
