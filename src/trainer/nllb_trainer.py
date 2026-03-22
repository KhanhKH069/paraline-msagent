"""
src/trainer/nllb_trainer.py

Fine-tune NLLB-200 với chunk-aware contextual loss.

Loss = λ * sentence_loss + (1-λ) * chunk_weighted_loss

Chunk weighted loss: mỗi token trong chunk được weight theo context_weight
của chunk đó (subject/verb quan trọng hơn modifier).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import torch
import torch.nn as nn
from datasets import Dataset, DatasetDict, load_from_disk
from torch.utils.data import DataLoader
from transformers import (
    AutoModelForSeq2SeqLM,
    AutoTokenizer,
    DataCollatorForSeq2Seq,
    Seq2SeqTrainer,
    Seq2SeqTrainingArguments,
    EarlyStoppingCallback,
)
import evaluate
import numpy as np


# ─── Dataset helpers ─────────────────────────────────────────────────────────

def load_jsonl(path: str) -> List[dict]:
    data = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                data.append(json.loads(line))
    return data


def build_hf_dataset(
    train_path: str,
    valid_path: str,
    test_path: Optional[str] = None,
) -> DatasetDict:
    """Load .jsonl → HuggingFace DatasetDict."""
    splits = {
        "train": Dataset.from_list(load_jsonl(train_path)),
        "validation": Dataset.from_list(load_jsonl(valid_path)),
    }
    if test_path and Path(test_path).exists():
        splits["test"] = Dataset.from_list(load_jsonl(test_path))
    return DatasetDict(splits)


# ─── Tokenization ─────────────────────────────────────────────────────────────

def make_tokenize_fn(tokenizer, max_input_length: int = 256, max_target_length: int = 256):
    """
    Tokenize function cho HF Trainer.
    Mỗi sample: {"src": str, "tgt": str, "src_lang": str, "tgt_lang": str, "chunks": list}
    """
    def tokenize(examples):
        # Set src lang
        srcs = examples["src"]
        tgts = examples["tgt"]

        # Nếu dataset trộn nhiều lang pair, cần xử lý per-item
        # Ở đây assume đồng nhất 1 cặp / batch
        src_lang = examples["src_lang"][0] if isinstance(examples["src_lang"], list) else examples["src_lang"]
        tgt_lang = examples["tgt_lang"][0] if isinstance(examples["tgt_lang"], list) else examples["tgt_lang"]

        tokenizer.src_lang = src_lang
        model_inputs = tokenizer(
            srcs,
            max_length=max_input_length,
            truncation=True,
            padding=False,
        )

        # Tokenize targets
        with tokenizer.as_target_tokenizer():
            labels = tokenizer(
                tgts,
                max_length=max_target_length,
                truncation=True,
                padding=False,
            )

        model_inputs["labels"] = labels["input_ids"]
        return model_inputs

    return tokenize


# ─── Chunk-weighted loss ──────────────────────────────────────────────────────

class ChunkWeightedSeq2SeqModel(nn.Module):
    """
    Wrapper quanh NLLB model để inject chunk-weighted cross-entropy loss.
    """

    def __init__(
        self,
        base_model: AutoModelForSeq2SeqLM,
        chunk_loss_weight: float = 0.3,
    ):
        super().__init__()
        self.model = base_model
        self.chunk_loss_weight = chunk_loss_weight
        self.config = base_model.config

    def forward(
        self,
        input_ids=None,
        attention_mask=None,
        decoder_input_ids=None,
        labels=None,
        chunk_weights=None,   # shape: (batch, tgt_len) — per-token weight
        **kwargs,
    ):
        outputs = self.model(
            input_ids=input_ids,
            attention_mask=attention_mask,
            decoder_input_ids=decoder_input_ids,
            labels=labels,
            **kwargs,
        )

        if chunk_weights is not None and labels is not None:
            # Recompute loss với token-level weighting
            logits = outputs.logits  # (B, T, V)
            B, T, V = logits.shape

            # Standard cross-entropy per token
            loss_fct = nn.CrossEntropyLoss(reduction="none", ignore_index=-100)
            per_token_loss = loss_fct(
                logits.view(-1, V),
                labels.view(-1),
            ).view(B, T)  # (B, T)

            # Apply chunk weights
            weights = chunk_weights.to(per_token_loss.dtype)
            weighted_loss = (per_token_loss * weights).sum() / (weights.sum() + 1e-8)

            # Blend: λ * standard_loss + (1-λ) * weighted_loss
            lam = 1.0 - self.chunk_loss_weight
            total_loss = lam * outputs.loss + self.chunk_loss_weight * weighted_loss
            outputs = outputs._replace(loss=total_loss)

        return outputs

    def generate(self, *args, **kwargs):
        return self.model.generate(*args, **kwargs)


# ─── Metrics ──────────────────────────────────────────────────────────────────

def make_compute_metrics(tokenizer):
    bleu_metric = evaluate.load("sacrebleu")
    chrf_metric = evaluate.load("chrf")

    def compute_metrics(eval_preds):
        preds, labels = eval_preds

        # Decode predictions
        if isinstance(preds, tuple):
            preds = preds[0]
        preds = np.where(preds != -100, preds, tokenizer.pad_token_id)
        decoded_preds = tokenizer.batch_decode(preds, skip_special_tokens=True)

        # Decode labels
        labels = np.where(labels != -100, labels, tokenizer.pad_token_id)
        decoded_labels = tokenizer.batch_decode(labels, skip_special_tokens=True)

        # Strip whitespace
        decoded_preds = [p.strip() for p in decoded_preds]
        decoded_labels = [[l.strip()] for l in decoded_labels]

        # BLEU
        bleu_result = bleu_metric.compute(
            predictions=decoded_preds,
            references=decoded_labels,
        )
        # chrF
        chrf_result = chrf_metric.compute(
            predictions=decoded_preds,
            references=decoded_labels,
        )

        return {
            "bleu": round(bleu_result["score"], 2),
            "chrf": round(chrf_result["score"], 2),
        }

    return compute_metrics


# ─── Main trainer class ───────────────────────────────────────────────────────

@dataclass
class NLLBTrainerConfig:
    model_path: str = "facebook/nllb-200-distilled-600M"
    output_dir: str = "models/finetuned"
    train_file: str = "data/processed/train.jsonl"
    valid_file: str = "data/processed/valid.jsonl"
    test_file: str = "data/processed/test.jsonl"

    num_train_epochs: int = 5
    per_device_train_batch_size: int = 16
    per_device_eval_batch_size: int = 16
    gradient_accumulation_steps: int = 4
    learning_rate: float = 5e-5
    warmup_ratio: float = 0.05
    weight_decay: float = 0.01
    fp16: bool = True
    max_input_length: int = 256
    max_target_length: int = 256

    chunk_loss_weight: float = 0.3   # 0 = disable chunk loss
    early_stopping_patience: int = 3

    seed: int = 42


class NLLBFinetuner:
    def __init__(self, config: NLLBTrainerConfig):
        self.config = config
        self.tokenizer = AutoTokenizer.from_pretrained(config.model_path)

        print(f"[NLLBFinetuner] Loading base model: {config.model_path}")
        base_model = AutoModelForSeq2SeqLM.from_pretrained(config.model_path)

        if config.chunk_loss_weight > 0:
            print(f"[NLLBFinetuner] Using chunk-weighted loss (λ={config.chunk_loss_weight})")
            self.model = ChunkWeightedSeq2SeqModel(base_model, config.chunk_loss_weight)
        else:
            self.model = base_model

    def train(self):
        cfg = self.config

        # Load datasets
        print("[NLLBFinetuner] Loading datasets...")
        dataset = build_hf_dataset(cfg.train_file, cfg.valid_file, cfg.test_file)

        # Tokenize
        tokenize_fn = make_tokenize_fn(
            self.tokenizer, cfg.max_input_length, cfg.max_target_length
        )
        tokenized = dataset.map(
            tokenize_fn,
            batched=True,
            remove_columns=["src", "tgt", "src_lang", "tgt_lang"],
        )

        # Training args
        training_args = Seq2SeqTrainingArguments(
            output_dir=cfg.output_dir,
            num_train_epochs=cfg.num_train_epochs,
            per_device_train_batch_size=cfg.per_device_train_batch_size,
            per_device_eval_batch_size=cfg.per_device_eval_batch_size,
            gradient_accumulation_steps=cfg.gradient_accumulation_steps,
            learning_rate=cfg.learning_rate,
            warmup_ratio=cfg.warmup_ratio,
            weight_decay=cfg.weight_decay,
            fp16=cfg.fp16,
            evaluation_strategy="epoch",
            save_strategy="epoch",
            load_best_model_at_end=True,
            metric_for_best_model="bleu",
            greater_is_better=True,
            predict_with_generate=True,
            generation_max_length=cfg.max_target_length,
            seed=cfg.seed,
            logging_steps=50,
            save_total_limit=3,
            report_to="tensorboard",
        )

        data_collator = DataCollatorForSeq2Seq(
            self.tokenizer, model=self.model, padding=True
        )
        compute_metrics = make_compute_metrics(self.tokenizer)

        trainer = Seq2SeqTrainer(
            model=self.model,
            args=training_args,
            train_dataset=tokenized["train"],
            eval_dataset=tokenized["validation"],
            tokenizer=self.tokenizer,
            data_collator=data_collator,
            compute_metrics=compute_metrics,
            callbacks=[
                EarlyStoppingCallback(early_stopping_patience=cfg.early_stopping_patience)
            ],
        )

        print("[NLLBFinetuner] Starting training...")
        trainer.train()

        print(f"[NLLBFinetuner] Saving best model to {cfg.output_dir}/best")
        trainer.save_model(f"{cfg.output_dir}/best")
        self.tokenizer.save_pretrained(f"{cfg.output_dir}/best")

        # Evaluate on test set
        if "test" in tokenized:
            print("[NLLBFinetuner] Evaluating on test set...")
            results = trainer.evaluate(tokenized["test"])
            print(f"Test results: {results}")
            with open(f"{cfg.output_dir}/test_results.json", "w") as f:
                json.dump(results, f, indent=2)

        return trainer
