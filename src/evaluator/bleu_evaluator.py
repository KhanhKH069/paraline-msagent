"""
src/evaluator/bleu_evaluator.py

Đánh giá chất lượng dịch với nhiều metrics: BLEU, chrF, TER.
Hỗ trợ so sánh baseline NLLB vs fine-tuned model.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import evaluate
import sacrebleu
from sacrebleu.metrics import BLEU, CHRF, TER
from rich.console import Console
from rich.table import Table


console = Console()

_BLEU = BLEU(effective_order=True)
_CHRF = CHRF()
_TER  = TER()


def score_pair(hypothesis: str, reference: str) -> Dict[str, float]:
    """Tính điểm cho 1 cặp (hypothesis, reference)."""
    bleu  = _BLEU.sentence_score(hypothesis, [reference]).score
    chrf  = _CHRF.sentence_score(hypothesis, [reference]).score
    ter   = _TER.sentence_score(hypothesis, [reference]).score
    return {"bleu": round(bleu, 2), "chrf": round(chrf, 2), "ter": round(ter, 2)}


def score_corpus(
    hypotheses: List[str],
    references: List[str],
) -> Dict[str, float]:
    """Tính điểm corpus-level."""
    bleu_result = _BLEU.corpus_score(hypotheses, [references])
    chrf_result = _CHRF.corpus_score(hypotheses, [references])
    ter_result  = _TER.corpus_score(hypotheses, [references])
    return {
        "bleu":  round(bleu_result.score, 2),
        "chrf":  round(chrf_result.score, 2),
        "ter":   round(ter_result.score, 2),
        "n_sentences": len(hypotheses),
    }


class TranslationEvaluator:
    """So sánh baseline vs fine-tuned + phân tích lỗi."""

    def __init__(
        self,
        baseline_translator=None,
        finetuned_translator=None,
    ):
        self.baseline = baseline_translator
        self.finetuned = finetuned_translator

    def evaluate_file(
        self,
        src_file: str,
        ref_file: str,
        src_lang: str,
        tgt_lang: str,
        output_file: Optional[str] = None,
    ) -> Dict:
        """
        Evaluate trên file.
        src_file: 1 câu/dòng, ngôn ngữ nguồn
        ref_file: 1 câu/dòng, ngôn ngữ đích (reference)
        """
        srcs = Path(src_file).read_text(encoding="utf-8").strip().splitlines()
        refs = Path(ref_file).read_text(encoding="utf-8").strip().splitlines()

        assert len(srcs) == len(refs), "src và ref phải có số dòng bằng nhau"

        results = {"src_lang": src_lang, "tgt_lang": tgt_lang, "samples": []}

        baseline_hyps = []
        finetuned_hyps = []

        for i, (src, ref) in enumerate(zip(srcs, refs)):
            sample = {"id": i, "src": src, "ref": ref}

            if self.baseline:
                hyp_b = self.baseline.translate_sentence(src, src_lang, tgt_lang)
                sample["baseline"] = hyp_b
                sample["baseline_scores"] = score_pair(hyp_b, ref)
                baseline_hyps.append(hyp_b)

            if self.finetuned:
                hyp_f = self.finetuned.translate_sentence(src, src_lang, tgt_lang)
                sample["finetuned"] = hyp_f
                sample["finetuned_scores"] = score_pair(hyp_f, ref)
                finetuned_hyps.append(hyp_f)

            results["samples"].append(sample)

            if (i + 1) % 50 == 0:
                print(f"  Evaluated {i+1}/{len(srcs)} sentences...")

        # Corpus scores
        if baseline_hyps:
            results["baseline_corpus"] = score_corpus(baseline_hyps, refs)
        if finetuned_hyps:
            results["finetuned_corpus"] = score_corpus(finetuned_hyps, refs)

        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)

        self._print_summary(results)
        return results

    def _print_summary(self, results: Dict):
        table = Table(title=f"Evaluation: {results['src_lang']} → {results['tgt_lang']}")
        table.add_column("Model", style="cyan")
        table.add_column("BLEU ↑", style="green")
        table.add_column("chrF ↑", style="green")
        table.add_column("TER ↓", style="red")
        table.add_column("N", style="dim")

        if "baseline_corpus" in results:
            b = results["baseline_corpus"]
            table.add_row("Baseline (NLLB)", str(b["bleu"]), str(b["chrf"]), str(b["ter"]), str(b["n_sentences"]))
        if "finetuned_corpus" in results:
            f = results["finetuned_corpus"]
            table.add_row("Fine-tuned", str(f["bleu"]), str(f["chrf"]), str(f["ter"]), str(f["n_sentences"]))

        console.print(table)

    def find_worst_samples(self, results: Dict, metric: str = "bleu", top_n: int = 10) -> List[dict]:
        """Tìm top N câu có kết quả tệ nhất theo metric."""
        samples = results.get("samples", [])
        key = f"finetuned_scores" if "finetuned_scores" in (samples[0] if samples else {}) else "baseline_scores"
        sorted_samples = sorted(
            [s for s in samples if key in s],
            key=lambda s: s[key].get(metric, 0),
        )
        return sorted_samples[:top_n]
