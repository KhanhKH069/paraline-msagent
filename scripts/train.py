"""
scripts/train.py

Chạy fine-tuning NLLB.

Usage:
    python scripts/train.py --config configs/train_config.yaml
    python scripts/train.py --config configs/train_config.yaml --fp16 false
"""

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.trainer.nllb_trainer import NLLBFinetuner, NLLBTrainerConfig


def main():
    parser = argparse.ArgumentParser(description="Fine-tune NLLB")
    parser.add_argument("--config", default="configs/train_config.yaml")
    parser.add_argument("--fp16", type=str, default=None)
    parser.add_argument("--epochs", type=int, default=None)
    parser.add_argument("--lr", type=float, default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--chunk-loss-weight", type=float, default=None)
    parser.add_argument("--output-dir", type=str, default=None)
    args = parser.parse_args()

    with open(args.config, "r") as f:
        cfg_dict = yaml.safe_load(f)

    model_cfg = cfg_dict.get("model", {})
    train_cfg = cfg_dict.get("training", {})
    data_cfg  = cfg_dict.get("data", {})
    chunk_cfg = cfg_dict.get("chunk_training", {})

    # Build config object
    config = NLLBTrainerConfig(
        model_path=model_cfg.get("name_or_path", "facebook/nllb-200-distilled-600M"),
        output_dir=args.output_dir or train_cfg.get("output_dir", "models/finetuned"),
        train_file=str(Path(data_cfg.get("processed_dir", "data/processed")) / data_cfg.get("train_file", "train.jsonl")),
        valid_file=str(Path(data_cfg.get("processed_dir", "data/processed")) / data_cfg.get("validation_file", "valid.jsonl")),
        test_file=str(Path(data_cfg.get("processed_dir", "data/processed")) / data_cfg.get("test_file", "test.jsonl")),

        num_train_epochs=args.epochs or train_cfg.get("num_train_epochs", 5),
        per_device_train_batch_size=args.batch_size or train_cfg.get("per_device_train_batch_size", 16),
        per_device_eval_batch_size=train_cfg.get("per_device_eval_batch_size", 16),
        gradient_accumulation_steps=train_cfg.get("gradient_accumulation_steps", 4),
        learning_rate=args.lr or train_cfg.get("learning_rate", 5e-5),
        warmup_ratio=train_cfg.get("warmup_ratio", 0.05),
        weight_decay=train_cfg.get("weight_decay", 0.01),
        fp16=(args.fp16.lower() == "true" if args.fp16 else train_cfg.get("fp16", True)),
        max_input_length=256,
        max_target_length=256,
        chunk_loss_weight=args.chunk_loss_weight or chunk_cfg.get("chunk_loss_weight", 0.3),
        seed=train_cfg.get("seed", 42),
    )

    print("=" * 60)
    print("NLLB Fine-tuning Config:")
    print(f"  Model:        {config.model_path}")
    print(f"  Output:       {config.output_dir}")
    print(f"  Epochs:       {config.num_train_epochs}")
    print(f"  Batch size:   {config.per_device_train_batch_size} (x{config.gradient_accumulation_steps} grad accum)")
    print(f"  LR:           {config.learning_rate}")
    print(f"  Chunk loss λ: {config.chunk_loss_weight}")
    print(f"  FP16:         {config.fp16}")
    print("=" * 60)

    finetuner = NLLBFinetuner(config)
    finetuner.train()

    print("\n🎉 Training complete!")


if __name__ == "__main__":
    main()
