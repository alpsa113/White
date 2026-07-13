"""
DualYOLO 학습 엔트리포인트

사용법:
    # 1단계 시작
    python train.py --phase 1

    # 2단계 시작(1단계 모델 weight에서)
    python train.py --phase 2 --init-from checkpoints/phase1/best.pt

    # 3단계 시작
    python train.py --phase 3 --init-from checkpoints/phase2/best.pt

    # 커스텀 설정
    python train.py --phase 1 --batch 16 --epochs 50 --img-size 640
"""

import argparse
from dataclasses import replace
import logging
import sys
from pathlib import Path

import yaml

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent))

from model import DualYOLO
from data import build_loaders
from training import Trainer
from training.phases import PHASE_DEFAULTS, PhaseConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
COLAB_ARTIFACT_ROOT = Path("/content/drive/MyDrive/dual_yolo")


def default_save_dir() -> str:
    """Colab Drive가 마운트되어 있으면 Drive checkpoint 경로를 기본값으로 사용."""
    if COLAB_ARTIFACT_ROOT.exists():
        return str(COLAB_ARTIFACT_ROOT / "checkpoints")
    return "checkpoints"


def load_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def build_phase_config(phase: int, phase_yaml: dict, epochs: int | None) -> PhaseConfig:
    """phases.yaml 값을 기본 페이즈 설정 위에 얹어 PhaseConfig 생성."""
    cfg = replace(PHASE_DEFAULTS[phase])
    for key, value in phase_yaml.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)
    if epochs:
        cfg.max_epochs = epochs
    return cfg


def run_training(
    phase: int,
    resume: str | None = None,
    init_from: str | None = None,
    model_cfg_path: str = "configs/model.yaml",
    phase_cfg_path: str = "configs/phases.yaml",
    save_dir: str | None = None,
    batch: int | None = None,
    epochs: int | None = None,
    img_size: int = 640,
    device: str | None = None,
    amp: bool = True,
) -> Trainer:
    """설정 파일을 읽고 학습기를 구성한 뒤 학습을 실행."""
    if resume and init_from:
        raise ValueError("--resume과 --init-from은 동시에 사용할 수 없습니다.")
    save_dir = save_dir or default_save_dir()

    model_cfg = load_yaml(model_cfg_path)
    phases_yaml = load_yaml(phase_cfg_path)
    phase_yaml = phases_yaml[f"phase{phase}"]

    phase_cfg = build_phase_config(phase, phase_yaml, epochs)

    m_cfg = model_cfg["model"]
    t_cfg = model_cfg["training"]
    batch_size = batch or t_cfg.get("batch_size", 8)
    grad_accum_steps = t_cfg.get("grad_accum_steps", 1)
    num_workers = t_cfg.get("num_workers", 4)

    logger.info(
        f"{phase}단계 | 배치={batch_size} | "
        f"누적={grad_accum_steps} | 에폭={phase_cfg.max_epochs} | 이미지={img_size}"
    )

    # ── 모델 ───────────────────────────────────────────────────────
    model = DualYOLO(
        fusion_dim=m_cfg.get("fusion_dim", 256),
        fpn_dim=m_cfg.get("fpn_dim", 256),
        cond_dim=m_cfg.get("cond_dim", 3),
        backbone_cfg=m_cfg.get("backbone", {}),
    )
    logger.info(
        f"모델 파라미터 수: {sum(p.numel() for p in model.parameters()):,}"
    )

    # ── 데이터 ─────────────────────────────────────────────────────
    train_loader, val_loader = build_loaders(
        phase_yaml, batch_size, num_workers, img_size
    )
    logger.info(f"학습 배치 수: {len(train_loader)}")
    if val_loader is not None:
        logger.info(f"검증 배치 수: {len(val_loader)}")

    # ── 학습기 ───────────────────────────────────────────────────
    trainer = Trainer(
        model=model,
        train_loader=train_loader,
        val_loader=val_loader,
        phase=phase,
        cfg=phase_cfg,
        save_dir=save_dir,
        device=device,
        amp=amp,
        grad_accum_steps=grad_accum_steps,
    )

    if resume:
        trainer.load_checkpoint(resume)
    if init_from:
        trainer.load_model_weights(init_from)

    trainer.train()
    return trainer


# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="DualYOLO 학습")
    parser.add_argument("--phase", type=int, choices=[1, 2, 3], required=True)
    parser.add_argument("--resume", type=str, default=None,
                        help="같은 phase 중단 재개용 checkpoint 경로")
    parser.add_argument("--init-from", type=str, default=None,
                        help="이전 phase 모델 weight로 새 phase를 시작할 checkpoint 경로")
    parser.add_argument("--model-cfg", type=str,
                        default="configs/model.yaml")
    parser.add_argument("--phase-cfg", type=str,
                        default="configs/phases.yaml")
    parser.add_argument(
        "--save-dir",
        type=str,
        default=None,
        help="checkpoint/metrics 저장 루트. Colab Drive가 있으면 기본값은 /content/drive/MyDrive/dual_yolo/checkpoints",
    )
    parser.add_argument("--batch",    type=int, default=None)
    parser.add_argument("--epochs",   type=int, default=None)
    parser.add_argument("--img-size", type=int, default=640)
    parser.add_argument("--device",   type=str, default=None)
    parser.add_argument("--no-amp",   action="store_true")
    args = parser.parse_args()

    run_training(
        phase=args.phase,
        resume=args.resume,
        init_from=args.init_from,
        model_cfg_path=args.model_cfg,
        phase_cfg_path=args.phase_cfg,
        save_dir=args.save_dir,
        batch=args.batch,
        epochs=args.epochs,
        img_size=args.img_size,
        device=args.device,
        amp=not args.no_amp,
    )


if __name__ == "__main__":
    main()
