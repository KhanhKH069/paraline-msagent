"""
scripts/evaluate.py

So sánh baseline vs fine-tuned model trên test set.

Usage:
    python scripts/evaluate.py \
        --checkpoint models/finetuned/best \
        --src-file data/processed/test_ja.txt \
        --ref-file data/processed/test_vi.txt \
        --src-lang ja --tgt-lang vi
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.translator.contextual_translator import ContextualTranslator
from src.evaluator.bleu_evaluator import TranslationEvaluator


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True, help="Fine-tuned model path")
    parser.add_argument("--baseline", default="facebook/nllb-200-distilled-600M",
                        help="Baseline model (default: NLLB 600M)")
    parser.add_argument("--src-file", required=True)
    parser.add_argument("--ref-file", required=True)
    parser.add_argument("--src-lang", default="ja")
    parser.add_argument("--tgt-lang", default="vi")
    parser.add_argument("--output", default="eval_results.json")
    parser.add_argument("--no-baseline", action="store_true")
    args = parser.parse_args()

    print("Loading fine-tuned model...")
    finetuned = ContextualTranslator(model_path=args.checkpoint)

    baseline = None
    if not args.no_baseline:
        print("Loading baseline model...")
        baseline = ContextualTranslator(model_path=args.baseline, use_chunk_prefix=False)

    evaluator = TranslationEvaluator(
        baseline_translator=baseline,
        finetuned_translator=finetuned,
    )

    print(f"\nEvaluating {args.src_lang} → {args.tgt_lang}...")
    evaluator.evaluate_file(
        src_file=args.src_file,
        ref_file=args.ref_file,
        src_lang=args.src_lang,
        tgt_lang=args.tgt_lang,
        output_file=args.output,
    )

    print(f"\nResults saved to: {args.output}")


if __name__ == "__main__":
    main()
