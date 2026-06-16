import torch
from torch.utils.data import ConcatDataset, Sampler


def dataset_sample_tags(dataset) -> list[set[str]]:
    if isinstance(dataset, ConcatDataset):
        tags: list[set[str]] = []
        for ds in dataset.datasets:
            tags.extend(dataset_sample_tags(ds))
        return tags

    if hasattr(dataset, "samples"):
        return [set(sample.get("tags", [])) for sample in dataset.samples]

    return [set() for _ in range(len(dataset))]


def dataset_sample_modalities(dataset) -> list[str]:
    if isinstance(dataset, ConcatDataset):
        modalities: list[str] = []
        for ds in dataset.datasets:
            modalities.extend(dataset_sample_modalities(ds))
        return modalities

    if hasattr(dataset, "samples"):
        default_modality = getattr(dataset, "modality", "pair")
        return [
            str(sample.get("modality") or default_modality)
            for sample in dataset.samples
        ]

    return ["pair" for _ in range(len(dataset))]


def validate_allowed_modalities(dataset, phase_yaml: dict, split_name: str):
    allowed = {
        "rgb": bool(phase_yaml.get("allow_rgb_only", True)),
        "thermal": bool(phase_yaml.get("allow_thm_only", True)),
        "pair": bool(phase_yaml.get("allow_pairs", True)),
    }
    modalities = dataset_sample_modalities(dataset)
    counts: dict[str, int] = {}
    for modality in modalities:
        counts[modality] = counts.get(modality, 0) + 1

    disallowed = {
        modality: count
        for modality, count in counts.items()
        if not allowed.get(modality, False)
    }
    if disallowed:
        allowed_names = [name for name, ok in allowed.items() if ok]
        raise ValueError(
            f"{split_name} 데이터셋에 허용되지 않은 모달리티가 포함되어 있습니다: "
            f"{disallowed}. 허용 모달리티: {allowed_names}"
        )


def build_hard_negative_weights(dataset, cfg: dict) -> torch.Tensor | None:
    if not cfg or not cfg.get("enabled", False):
        return None

    tag_weights = cfg.get("weights", {})
    base_weight = float(cfg.get("base_weight", 1.0))
    weights = []
    for tags in dataset_sample_tags(dataset):
        weight = base_weight
        for tag in tags:
            weight = max(weight, float(tag_weights.get(tag, base_weight)))
        weights.append(weight)

    if not weights or max(weights) == min(weights):
        return None

    return torch.tensor(weights, dtype=torch.double)


class ModalityHomogeneousBatchSampler(Sampler[list[int]]):
    def __init__(
        self,
        modalities: list[str],
        batch_size: int,
        drop_last: bool,
        shuffle: bool = True,
        weights: torch.Tensor | None = None,
    ):
        self.batch_size = batch_size
        self.drop_last = drop_last
        self.shuffle = shuffle
        self.weights = weights
        self.groups: dict[str, list[int]] = {}
        for idx, modality in enumerate(modalities):
            self.groups.setdefault(modality, []).append(idx)

    def __iter__(self):
        batches: list[list[int]] = []
        for indices in self.groups.values():
            if not indices:
                continue
            sample_count = self._sample_count(indices)
            ordered = self._order_group(indices, sample_count)
            for start in range(0, len(ordered), self.batch_size):
                batch = ordered[start:start + self.batch_size]
                if len(batch) == self.batch_size or (batch and not self.drop_last):
                    batches.append(batch)

        if self.shuffle and batches:
            order = torch.randperm(len(batches)).tolist()
            batches = [batches[i] for i in order]

        yield from batches

    def _sample_count(self, indices: list[int]) -> int:
        if self.weights is None:
            return len(indices)
        total_weight = float(self.weights.sum().item())
        if total_weight <= 0:
            return len(indices)
        group_weight = float(self.weights[indices].sum().item())
        return max(1, round(len(self.weights) * group_weight / total_weight))

    def _order_group(self, indices: list[int], sample_count: int) -> list[int]:
        if self.weights is not None:
            group_weights = self.weights[indices]
            if group_weights.numel() > 0:
                sampled = torch.multinomial(
                    group_weights,
                    num_samples=sample_count,
                    replacement=True,
                ).tolist()
                return [indices[i] for i in sampled]

        if self.shuffle:
            order = torch.randperm(len(indices)).tolist()
            return [indices[i] for i in order]
        return list(indices)

    def __len__(self) -> int:
        total = 0
        for indices in self.groups.values():
            sample_count = self._sample_count(indices)
            n = sample_count // self.batch_size
            if not self.drop_last and sample_count % self.batch_size:
                n += 1
            total += n
        return total
