"""
Trainer — 학습 루프 (Phase 1·2·3 공통)

기능:
  - 페이즈별 PhaseScheduler 로 모델 플래그 자동 전환
  - 단독/페어 배치에 따른 gradient 제어
  - 체크포인트 저장 / 재개
  - 기본 validation 루프
"""

import os
import time
import logging
import csv
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from .losses import DualYOLOLoss
from .metrics import MeanAveragePrecision, decode_detections
from .phases import PhaseConfig, PhaseScheduler, build_optimizer, build_scheduler, PHASE_DEFAULTS

logger = logging.getLogger(__name__)


class Trainer:
    def __init__(
        self,
        model: nn.Module,
        train_loader: DataLoader,
        val_loader: DataLoader | None,
        phase: int,
        cfg: PhaseConfig | None = None,
        save_dir: str = "checkpoints",
        device: str | None = None,
        amp: bool = True,
        grad_accum_steps: int = 1,
    ):
        self.model = model
        self.train_loader = train_loader
        self.val_loader = val_loader
        self.phase = phase
        self.cfg = cfg or PHASE_DEFAULTS[phase]
        self.save_dir = Path(save_dir) / f"phase{phase}"
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.metrics_path = self.save_dir / "metrics.csv"
        self.amp = amp
        self.grad_accum_steps = max(1, grad_accum_steps)

        # 학습 장치
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)
        self.model.to(self.device)

        # optimizer와 학습률 스케줄러
        self.optimizer = build_optimizer(model, phase)
        self.lr_scheduler = build_scheduler(self.optimizer, self.cfg.max_epochs)

        # 페이즈 스케줄러(flag 관리)
        self.phase_sched = PhaseScheduler(
            model,
            phase,
            self.cfg,
            optimizer=self.optimizer,
            lr_scheduler=self.lr_scheduler,
        )

        # 손실 함수
        class_weights = torch.tensor(self.cfg.class_weights, device=self.device)
        loss_kwargs: dict = {"class_weights": class_weights}
        if self.cfg.aux_weight is not None:
            loss_kwargs["aux_weight"] = self.cfg.aux_weight
        if self.cfg.fus_reg_weight is not None:
            loss_kwargs["fus_reg_weight"] = self.cfg.fus_reg_weight
        loss_kwargs["empty_obj_weight"] = self.cfg.empty_objectness_weight
        self.criterion = DualYOLOLoss(**loss_kwargs).to(self.device)

        self.scaler = torch.cuda.amp.GradScaler(enabled=amp and self.device.type == "cuda")
        self.start_epoch = 0
        self.best_val_loss = float("inf")
        self.best_map50 = 0.0

    # ------------------------------------------------------------------
    def _write_epoch_metrics(
        self,
        epoch: int,
        train_metrics: dict[str, float],
        val_metrics: dict[str, float],
        elapsed_sec: float,
    ) -> None:
        """epoch별 지표를 CSV에 누적 저장."""
        row = {
            "phase": self.phase,
            "epoch": epoch,
            "elapsed_sec": elapsed_sec,
            "lr": self.optimizer.param_groups[0]["lr"],
            "train_loss": train_metrics.get("total", float("nan")),
        }
        row.update({f"train_{key}": value for key, value in train_metrics.items()})
        row.update(val_metrics)

        columns = [
            "phase",
            "epoch",
            "elapsed_sec",
            "lr",
            "train_loss",
            "val_loss",
            "mAP50",
            "mAP50_95",
            "AP_person",
            "AP_boar",
            "AP_deer",
            "AP_non_target",
            "Precision_person",
            "Recall_person",
            "F1_person",
        ]
        columns.extend(sorted(key for key in row if key not in columns))

        existing_rows: list[dict] = []
        if self.metrics_path.exists():
            with self.metrics_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                existing_rows = list(reader)
                if reader.fieldnames:
                    columns = list(dict.fromkeys([*reader.fieldnames, *columns]))

        mode = "w" if existing_rows else "a"
        with self.metrics_path.open(mode, encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            for existing in existing_rows:
                writer.writerow(existing)
            writer.writerow(row)

    # ------------------------------------------------------------------
    @staticmethod
    def _looks_like_state_dict(value) -> bool:
        return isinstance(value, dict) and value and all(
            isinstance(k, str) and torch.is_tensor(v)
            for k, v in value.items()
        )

    @staticmethod
    def _strip_module_prefix(state_dict: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        if not any(key.startswith("module.") for key in state_dict):
            return state_dict
        return {
            key.removeprefix("module."): value
            for key, value in state_dict.items()
        }

    @classmethod
    def _extract_model_state_dict(cls, checkpoint) -> dict[str, torch.Tensor]:
        if cls._looks_like_state_dict(checkpoint):
            return cls._strip_module_prefix(checkpoint)
        if not isinstance(checkpoint, dict):
            raise ValueError(
                "checkpoint 형식을 해석하지 못했습니다. "
                "model state_dict 또는 Trainer checkpoint를 사용해야 합니다."
            )
        for key in ("model", "model_state_dict", "state_dict"):
            value = checkpoint.get(key)
            if cls._looks_like_state_dict(value):
                return cls._strip_module_prefix(value)
        raise ValueError(
            "checkpoint에서 model state_dict를 찾지 못했습니다. "
            "지원 형식: raw state_dict, {'model': ...}, "
            "{'model_state_dict': ...}, {'state_dict': ...}."
        )

    def load_model_weights(self, ckpt_path: str):
        """phase 전환용: 모델 weight만 로드하고 학습 상태는 새로 시작."""
        ckpt = torch.load(ckpt_path, map_location=self.device)
        state_dict = self._extract_model_state_dict(ckpt)
        self.model.load_state_dict(state_dict)
        logger.info(f"{ckpt_path}에서 모델 weight만 초기화했습니다.")

    def load_checkpoint(self, ckpt_path: str):
        ckpt = torch.load(ckpt_path, map_location=self.device)
        ckpt_phase = ckpt.get("phase") if isinstance(ckpt, dict) else None
        if ckpt_phase is not None and int(ckpt_phase) != self.phase:
            raise ValueError(
                "--resume은 같은 phase 중단 재개 전용입니다. "
                f"현재 phase={self.phase}, checkpoint phase={ckpt_phase}. "
                "이전 phase weight로 새 phase를 시작하려면 --init-from을 사용하세요."
            )
        self.model.load_state_dict(self._extract_model_state_dict(ckpt))
        self.optimizer.load_state_dict(ckpt["optimizer"])
        if "scheduler" in ckpt:
            self.lr_scheduler.load_state_dict(ckpt["scheduler"])
        if "scaler" in ckpt:
            self.scaler.load_state_dict(ckpt["scaler"])
        self.start_epoch = ckpt.get("epoch", 0) + 1
        self.phase_sched.restore_for_epoch(self.start_epoch)
        self.best_val_loss = ckpt.get("best_val_loss", float("inf"))
        self.best_map50 = ckpt.get("best_map50", 0.0)
        logger.info(f"{ckpt_path}에서 재개했습니다. 시작 에폭: {self.start_epoch}")

    def save_checkpoint(
        self,
        epoch: int,
        val_loss: float,
        map50: float = 0.0,
        name: str | None = None,
    ):
        tag = name or f"epoch_{epoch:03d}"
        path = self.save_dir / f"{tag}.pt"
        torch.save({
            "epoch": epoch,
            "model": self.model.state_dict(),
            "optimizer": self.optimizer.state_dict(),
            "scheduler": self.lr_scheduler.state_dict(),
            "scaler": self.scaler.state_dict(),
            "best_val_loss": self.best_val_loss,
            "best_map50": self.best_map50,
            "val_loss": val_loss,
            "map50": map50,
            "phase": self.phase,
        }, path)
        logger.info(f"체크포인트 저장 완료 → {path}")

    # ------------------------------------------------------------------
    def _to_device(self, batch: dict) -> dict:
        out = {}
        for k, v in batch.items():
            if isinstance(v, torch.Tensor):
                out[k] = v.to(self.device)
            elif isinstance(v, list):
                out[k] = [
                    x.to(self.device) if isinstance(x, torch.Tensor) else x
                    for x in v
                ]
            else:
                out[k] = v
        return out

    def _forward_losses(self, batch: dict) -> dict[str, torch.Tensor]:
        batch = self._to_device(batch)

        rgb     = batch.get("rgb")          # [B,3,H,W] 또는 None
        thermal = batch.get("thermal")      # [B,1,H,W] 또는 None
        cond    = batch["cond_vec"]          # [B,3]
        gt_boxes  = batch["boxes"]           # Tensor[N,4] 리스트
        gt_labels = batch["labels"]          # Tensor[N] 리스트

        # 모달리티 dropout(1단계)
        p_drop = self.cfg.modality_dropout_prob
        if p_drop > 0 and rgb is not None and thermal is not None:
            drop_rgb = rgb is not None and torch.rand(1).item() < p_drop
            drop_thm = thermal is not None and torch.rand(1).item() < p_drop
            if drop_rgb and drop_thm:
                if torch.rand(1).item() < 0.5:
                    drop_rgb = False
                else:
                    drop_thm = False
            if drop_rgb:
                rgb = None
            if drop_thm:
                thermal = None

        # 단독 모달 배치: 해당 백본만 gradient 활성화
        rgb_only = (rgb is not None and thermal is None)
        thm_only = (thermal is not None and rgb is None)

        with torch.cuda.amp.autocast(enabled=self.amp and self.device.type == "cuda"):
            out = self.model(rgb, thermal, cond)

            # 단독 모달에서는 존재하는 백본의 보조 손실만 계산
            aux_labels_rgb = batch.get("aux_label") if not thm_only else None
            aux_labels_thm = batch.get("aux_label") if not rgb_only else None

            losses = self.criterion(
                out,
                gt_boxes,
                gt_labels,
                aux_labels_rgb=aux_labels_rgb,
                aux_labels_thm=aux_labels_thm,
                cond_vec=cond,
                aux_active=self.model.aux_active,
                uncertainty_active=self.model.uncertainty_active,
                fusion_reg_active=self.phase_sched.fusion_reg_active,
            )

        return losses

    @torch.no_grad()
    def _val_epoch(self) -> dict[str, float]:
        self.model.eval()
        total_loss = 0.0
        n = 0
        metric = MeanAveragePrecision(
            num_classes=4,
            iou_thresh=0.5,
            iou_thresholds=[x / 100 for x in range(50, 100, 5)],
            operating_conf=0.50,
        )
        for batch in self.val_loader:
            batch = self._to_device(batch)
            rgb     = batch.get("rgb")
            thermal = batch.get("thermal")
            cond    = batch["cond_vec"]
            gt_boxes  = batch["boxes"]
            gt_labels = batch["labels"]

            out = self.model(rgb, thermal, cond)
            losses = self.criterion(
                out, gt_boxes, gt_labels,
                aux_labels_rgb=batch.get("aux_label"),
                aux_labels_thm=batch.get("aux_label"),
                cond_vec=cond,
                aux_active=self.model.aux_active,
                uncertainty_active=self.model.uncertainty_active,
                fusion_reg_active=self.phase_sched.fusion_reg_active,
            )
            total_loss += losses["total"].item()
            preds = decode_detections(out)
            metric.update(preds, gt_boxes, gt_labels)
            n += 1
        self.model.train()
        metrics = metric.compute()
        metrics["val_loss"] = total_loss / max(n, 1)
        return metrics

    # ------------------------------------------------------------------
    def train(self):
        logger.info(
            f"=== {self.phase}단계 학습 시작 "
            f"(에폭 {self.start_epoch}~{self.cfg.max_epochs - 1}) ==="
        )
        self.model.train()
        last_val_loss = float("inf")
        last_map50 = 0.0
        has_best = self.best_val_loss < float("inf")

        for epoch in range(self.start_epoch, self.cfg.max_epochs):
            self.phase_sched.step(epoch)

            epoch_losses: dict[str, float] = {}
            t0 = time.time()
            self.optimizer.zero_grad(set_to_none=True)

            for step, batch in enumerate(self.train_loader):
                losses = self._forward_losses(batch)
                scaled_total = losses["total"] / self.grad_accum_steps
                self.scaler.scale(scaled_total).backward()

                should_step = (
                    (step + 1) % self.grad_accum_steps == 0
                    or (step + 1) == len(self.train_loader)
                )
                if should_step:
                    self.scaler.unscale_(self.optimizer)
                    torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=10.0)
                    self.scaler.step(self.optimizer)
                    self.scaler.update()
                    self.optimizer.zero_grad(set_to_none=True)

                step_losses = {k: v.item() for k, v in losses.items()}
                for k, v in step_losses.items():
                    epoch_losses[k] = epoch_losses.get(k, 0.0) + v

            n_steps = len(self.train_loader)
            avg = {k: v / n_steps for k, v in epoch_losses.items()}
            elapsed = time.time() - t0

            log_str = (
                f"{self.phase}단계 | 에폭 {epoch:03d} | "
                + " | ".join(f"{k}={v:.4f}" for k, v in avg.items())
                + f" | {elapsed:.1f}s"
            )
            logger.info(log_str)
            print(log_str)

            self.lr_scheduler.step()

            # 검증
            val_loss = float("inf")
            map50 = 0.0
            if self.val_loader is not None:
                val_metrics = self._val_epoch()
                val_loss = val_metrics["val_loss"]
                map50 = val_metrics["mAP50"]
                metric_str = " | ".join(
                    f"{k}={v:.4f}" for k, v in val_metrics.items() if v == v
                )
                logger.info(f"  {metric_str}")
                print(f"  {metric_str}")
            else:
                val_metrics = {}

            self._write_epoch_metrics(epoch, avg, val_metrics, elapsed)

            last_val_loss = val_loss
            last_map50 = map50

            if self.val_loader is not None and (not has_best or map50 > self.best_map50):
                self.best_map50 = map50
                self.best_val_loss = val_loss
                has_best = True
                self.save_checkpoint(epoch, val_loss, map50, "best")

            # 주기 저장
            if (epoch + 1) % 5 == 0:
                self.save_checkpoint(epoch, val_loss, map50)

        # 최종 저장
        self.save_checkpoint(
            self.cfg.max_epochs - 1,
            last_val_loss,
            last_map50,
            "final",
        )
        logger.info(f"{self.phase}단계 학습이 완료되었습니다.")
