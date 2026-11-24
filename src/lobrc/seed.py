"""Global seeding for reproducible experiments.

Finance concept: a model's apparent edge can come from lucky random initialisation. Fixing
seeds makes a result repeatable, so differences between runs reflect real changes, not noise.
"""
from __future__ import annotations

import os
import random

import numpy as np
import torch


def set_seed(seed: int = 1234) -> None:
    """Seed python, numpy and torch (CPU and CUDA) and force deterministic cuDNN."""
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
