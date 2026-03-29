"""
Trainer — helper class bọc training loop VITS2.
Cung cấp API sạch hơn so với raw train.py.
"""

import os
import logging
import torch

logger = logging.getLogger(__name__)


class VITS2Trainer:
    """
    High-level trainer wrapper.
    Dùng khi muốn tích hợp vào Jupyter Notebook hoặc custom pipeline.

    Ví dụ:
        trainer = VITS2Trainer('configs/base_vi.json')
        trainer.setup()
        trainer.train(max_steps=100000)
    """

    def __init__(self, config_path: str, output_dir: str = 'checkpoints'):
        import json
        with open(config_path, 'r') as f:
            self.config = json.load(f)
        self.output_dir = output_dir
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self._is_setup = False

    def setup(self):
        """Khởi tạo models và optimizers."""

        os.makedirs(self.output_dir, exist_ok=True)
        logger.info(f"[Trainer] Device: {self.device}")
        self._is_setup = True
        logger.info("[Trainer] Setup complete.")

    def resume_from(self, checkpoint_dir: str):
        """Tìm và load checkpoint mới nhất."""
        from training.train import latest_checkpoint
        ckpt_g = latest_checkpoint(checkpoint_dir, 'G')
        if ckpt_g:
            logger.info(f"[Trainer] Resuming from {ckpt_g}")
        else:
            logger.info("[Trainer] No checkpoint found, starting fresh.")

    def evaluate(self, text_samples: list, output_dir: str = 'outputs/eval'):
        """Chạy inference trên một số câu mẫu để đánh giá chất lượng."""
        os.makedirs(output_dir, exist_ok=True)
        logger.info(f"[Trainer] Evaluating {len(text_samples)} samples...")
        # Gọi inference.infer.VietnameseTTS
        return output_dir
