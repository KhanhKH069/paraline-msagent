# NLLB Trainer Makefile
# ─────────────────────────────────────────────────────────────────────────────

PYTHON  ?= python
VENV    ?= .venv
CONFIG_DATA  ?= configs/data_config.yaml
CONFIG_TRAIN ?= configs/train_config.yaml

.PHONY: help venv install install-spacy download-model download-data \
        prepare annotate train evaluate translate clean test

# ─── Help ────────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  NLLB Contextual Trainer — JA/EN/VI"
	@echo "  ────────────────────────────────────"
	@echo "  make install         Install Python dependencies"
	@echo "  make install-spacy   Download spaCy models (ja/en/vi)"
	@echo "  make download-model  Download NLLB-200-distilled-600M"
	@echo "  make download-data   Download OPUS parallel corpora"
	@echo "  make prepare         Preprocess + filter + split dataset"
	@echo "  make annotate        Add chunk annotations to processed data"
	@echo "  make train           Fine-tune NLLB"
	@echo "  make evaluate        Evaluate on test set"
	@echo "  make translate       Interactive translate demo"
	@echo "  make test            Run unit tests"
	@echo "  make clean           Remove generated files"
	@echo ""

# ─── Environment ─────────────────────────────────────────────────────────────
venv:
	$(PYTHON) -m venv $(VENV)
	@echo "Activate with: source $(VENV)/bin/activate"

install:
	pip install -r requirements.txt

install-spacy:
	$(PYTHON) -m spacy download ja_core_news_sm
	$(PYTHON) -m spacy download en_core_web_sm
	@echo "Tiếng Việt: pip install https://github.com/explosion/spacy-models/releases/download/vi_core_news_lg-3.7.0/vi_core_news_lg-3.7.0-py3-none-any.whl"

# ─── Data ────────────────────────────────────────────────────────────────────
download-model:
	$(PYTHON) scripts/download_model.py

download-data:
	$(PYTHON) scripts/download_data.py --source opus --lang-pair ja-en --limit 200000
	$(PYTHON) scripts/download_data.py --source opus --lang-pair en-vi --limit 200000
	$(PYTHON) scripts/download_data.py --source opus --lang-pair ja-vi --limit 50000
	$(PYTHON) scripts/download_data.py --merge-domain

prepare:
	$(PYTHON) scripts/prepare_data.py --config $(CONFIG_DATA)

annotate:
	$(PYTHON) scripts/annotate_chunks.py --dir data/processed

# ─── Training ────────────────────────────────────────────────────────────────
train:
	$(PYTHON) scripts/train.py --config $(CONFIG_TRAIN)

train-fast:
	$(PYTHON) scripts/train.py --config $(CONFIG_TRAIN) --epochs 2 --batch-size 8

# ─── Evaluation ──────────────────────────────────────────────────────────────
evaluate:
	@echo "Evaluating JA → VI..."
	$(PYTHON) scripts/evaluate.py \
		--checkpoint models/finetuned/best \
		--src-file data/processed/test_ja.txt \
		--ref-file data/processed/test_vi.txt \
		--src-lang ja --tgt-lang vi \
		--output eval_ja_vi.json

# ─── Translation demo ─────────────────────────────────────────────────────────
translate:
	$(PYTHON) scripts/translate.py \
		--text "会議は午後3時に始まります。プロジェクトのデプロイについて話し合います。" \
		--src ja --tgt vi --debug

translate-en-vi:
	$(PYTHON) scripts/translate.py \
		--text "The sprint review is scheduled for Friday and we need to finish the API documentation." \
		--src en --tgt vi --debug

# ─── Tests ───────────────────────────────────────────────────────────────────
test:
	$(PYTHON) -m pytest tests/ -v

test-chunker:
	$(PYTHON) -m pytest tests/test_chunker.py -v

# ─── Pipeline: chạy toàn bộ từ đầu ──────────────────────────────────────────
all: install install-spacy download-model download-data prepare annotate train

# ─── Cleanup ─────────────────────────────────────────────────────────────────
clean:
	rm -rf data/processed/*.jsonl
	rm -rf models/checkpoints/
	rm -f eval_*.json
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -name "*.pyc" -delete

clean-models:
	rm -rf models/finetuned/
	@echo "Fine-tuned models removed."
