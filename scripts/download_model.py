"""
scripts/download_model.py

Tải NLLB-200 model về local.
Supports: huggingface snapshot_download → models/pretrained/

Usage:
    python scripts/download_model.py
    python scripts/download_model.py --model facebook/nllb-200-distilled-1.3B
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def download_model(model_name: str, save_dir: str):
    from huggingface_hub import snapshot_download

    print(f"Downloading {model_name}...")
    local_path = snapshot_download(
        repo_id=model_name,
        local_dir=save_dir,
        ignore_patterns=["*.msgpack", "flax_model*", "tf_model*", "rust_model*"],
    )
    print(f"Model saved to: {local_path}")
    return local_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        default="facebook/nllb-200-distilled-600M",
        help="HuggingFace model ID",
    )
    parser.add_argument(
        "--save-dir",
        default=None,
        help="Local save path (default: models/pretrained/<model-name>)",
    )
    args = parser.parse_args()

    model_name = args.model
    save_dir = args.save_dir or f"models/pretrained/{model_name.replace('/', '_')}"
    Path(save_dir).mkdir(parents=True, exist_ok=True)

    download_model(model_name, save_dir)

    # Update .env or print instructions
    print("\n✅ Done! Add to your .env or config:")
    print(f"   MODEL_PATH={save_dir}")
    print(f"\nOr use directly in train_config.yaml:")
    print(f"   model:\n     name_or_path: {save_dir}")


if __name__ == "__main__":
    main()
