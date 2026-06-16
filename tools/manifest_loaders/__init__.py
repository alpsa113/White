from .gop import (
    load_gop_class_yolo_pair_source,
    load_gop_class_yolo_source,
    load_gop_empty_folder_source,
)
from .legacy import (
    load_coco_source,
    load_kaist_source,
    load_manifest_source,
    load_yolo_source,
)


LOADERS = {
    "coco": load_coco_source,
    "manifest": load_manifest_source,
    "yolo": load_yolo_source,
    "kaist": load_kaist_source,
    "gop_class_yolo": load_gop_class_yolo_source,
    "gop_class_yolo_pair": load_gop_class_yolo_pair_source,
    "gop_empty_folder": load_gop_empty_folder_source,
}


__all__ = ["LOADERS"]
