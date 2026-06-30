"""
3단계 학습 시나리오 — optimizer / scheduler / 플래그 관리

PhaseConfig: 각 페이즈의 활성화 플래그 + optimizer 하이퍼파라미터
build_optimizer: 모델 파라미터 그룹 → AdamW optimizer
PhaseScheduler: 페이즈 전환 및 3단계 백본 동결/해제 관리
"""

from dataclasses import dataclass, field
import torch
import torch.optim as optim
from torch.optim.lr_scheduler import CosineAnnealingLR


@dataclass
class PhaseConfig:
    phase: int
    max_epochs: int

    # 활성화 플래그
    aux_active: bool = True
    uncertainty_active: bool = False
    uncertainty_start_epoch: int | None = None
    fusion_reg_active: bool = False

    # 3단계 전용: 백본 동결 → 해제 전환 epoch
    backbone_unfreeze_epoch: int | None = None   # None이면 동결 유지

    # 샘플러 제어
    allow_rgb_only: bool = True
    allow_thm_only: bool = True
    allow_pairs: bool = True
    modality_dropout_prob: float = 0.0

    # 손실 가중치 오버라이드(None이면 DualYOLOLoss 기본값 사용)
    aux_weight: float | None = None
    fus_reg_weight: float | None = None

    # 클래스 가중치 (index: person=0, boar=1, deer=2, non_target=3)
    class_weights: list[float] = field(default_factory=lambda: [1.0, 1.0, 1.0, 0.1])


# 시나리오 기본 설정
PHASE_DEFAULTS: dict[int, PhaseConfig] = {
    1: PhaseConfig(
        phase=1,
        max_epochs=30,
        aux_active=True,
        uncertainty_active=False,
        fusion_reg_active=False,
        allow_rgb_only=True,
        allow_thm_only=True,
        allow_pairs=True,
        modality_dropout_prob=0.2,
    ),
    2: PhaseConfig(
        phase=2,
        max_epochs=20,
        aux_active=True,
        uncertainty_active=False,
        uncertainty_start_epoch=10,
        fusion_reg_active=True,
        allow_rgb_only=False,
        allow_thm_only=False,
        allow_pairs=True,
        modality_dropout_prob=0.05,
    ),
    3: PhaseConfig(
        phase=3,
        max_epochs=15,
        aux_active=False,
        uncertainty_active=True,
        uncertainty_start_epoch=0,
        fusion_reg_active=True,
        allow_rgb_only=True,
        allow_thm_only=True,
        allow_pairs=True,
        backbone_unfreeze_epoch=8,  # 8 epoch 이후 전체 해제
    ),
}


def build_optimizer(model, phase: int) -> optim.Optimizer:
    """모델의 파라미터 그룹을 읽어 AdamW optimizer 생성."""
    param_groups = model.get_param_groups(phase)
    # 빈 파라미터 그룹 제거
    param_groups = [g for g in param_groups if len(list(g["params"])) > 0]
    return optim.AdamW(param_groups, weight_decay=1e-4)


def build_scheduler(
    optimizer: optim.Optimizer,
    max_epochs: int,
    eta_min: float = 1e-7,
) -> CosineAnnealingLR:
    return CosineAnnealingLR(optimizer, T_max=max_epochs, eta_min=eta_min)


class PhaseScheduler:
    """페이즈 전환 및 3단계 백본 동결 전환 관리.

    사용법:
        scheduler = PhaseScheduler(model, phase=2, cfg=PHASE_DEFAULTS[2])
        for epoch in range(cfg.max_epochs):
            scheduler.step(epoch)
            # model.aux_active, model.uncertainty_active 자동 갱신
    """

    def __init__(
        self,
        model,
        phase: int,
        cfg: PhaseConfig | None = None,
        optimizer: optim.Optimizer | None = None,
        lr_scheduler: CosineAnnealingLR | None = None,
    ):
        self.model = model
        self.phase = phase
        self.cfg = cfg or PHASE_DEFAULTS[phase]
        self.optimizer = optimizer
        self.lr_scheduler = lr_scheduler
        self._backbone_unfrozen = False

        # 3단계: 시작 시 백본 동결
        if phase == 3:
            model.freeze_backbone()

        self._apply_flags(epoch=0)

    def _apply_flags(self, epoch: int):
        m = self.model
        m.set_aux_active(self.cfg.aux_active)

        if self.cfg.uncertainty_start_epoch is not None:
            m.set_uncertainty_active(epoch >= self.cfg.uncertainty_start_epoch)
        else:
            m.set_uncertainty_active(self.cfg.uncertainty_active)

    def step(self, epoch: int):
        self._apply_flags(epoch)

        # 3단계: 백본 동결 해제
        if (
            self.phase == 3
            and self.cfg.backbone_unfreeze_epoch is not None
            and epoch >= self.cfg.backbone_unfreeze_epoch
            and not self._backbone_unfrozen
        ):
            print(f"[페이즈 스케줄러] 에폭 {epoch}: 백본 동결을 해제했습니다.")
            self.model.unfreeze_backbone()
            self._set_all_param_group_lr(5e-6)
            self._backbone_unfrozen = True

    def restore_for_epoch(self, epoch: int):
        self._apply_flags(epoch)
        if (
            self.phase == 3
            and self.cfg.backbone_unfreeze_epoch is not None
            and epoch >= self.cfg.backbone_unfreeze_epoch
        ):
            self.model.unfreeze_backbone()
            self._backbone_unfrozen = True

    @property
    def fusion_reg_active(self) -> bool:
        return self.cfg.fusion_reg_active

    def _set_all_param_group_lr(self, lr: float):
        if self.optimizer is None:
            return

        for group in self.optimizer.param_groups:
            group["lr"] = lr
            if "initial_lr" in group:
                group["initial_lr"] = lr

        if self.lr_scheduler is not None and hasattr(self.lr_scheduler, "base_lrs"):
            self.lr_scheduler.base_lrs = [lr for _ in self.optimizer.param_groups]
