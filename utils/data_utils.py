"""
Dataset Utilities — Vietnamese TTS
PyTorch Dataset + Collate cho training VITS2
"""

import os
import numpy as np
import torch
from torch.utils.data import Dataset

from utils.audio import load_wav
from utils.mel_processing import spectrogram_torch


class VietnameseTTSDataset(Dataset):
    """
    Dataset cho Vietnamese TTS.
    Đọc từ list.txt: path/to/wav|văn bản|speaker_id
    """

    def __init__(self, list_path: str, hps, augment: bool = False):
        self.hps = hps
        self.augment = augment
        self.data = self._load_list(list_path)

        # Build symbol table
        from inference.infer import SYMBOLS, SYMBOL_TO_ID, text_to_sequence
        self.symbols = SYMBOLS
        self.symbol_to_id = SYMBOL_TO_ID
        self._text_to_sequence = text_to_sequence

        # Filter theo độ dài
        self.data = [d for d in self.data if self._is_valid(d)]
        print(f"[Dataset] Loaded {len(self.data)} samples from {list_path}")

    def _load_list(self, path: str):
        data = []
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split('|')
                if len(parts) >= 2:
                    audio_path = parts[0]
                    text = parts[1]
                    speaker_id = int(parts[2]) if len(parts) > 2 else 0
                    data.append((audio_path, text, speaker_id))
        return data

    def _is_valid(self, item):
        audio_path, text, _ = item
        if not os.path.exists(audio_path):
            return False
        if len(text) < 2:
            return False
        return True

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        audio_path, text, speaker_id = self.data[idx]

        # Text → sequence
        seq = self._text_to_sequence(text)

        # Audio → spectrogram
        wav, sr = load_wav(audio_path, target_sr=self.hps.data.sampling_rate)

        # Optional augmentation
        if self.augment:
            wav = self._augment(wav, sr)

        wav_tensor = torch.FloatTensor(wav).unsqueeze(0)

        # Spectrogram
        spec = spectrogram_torch(
            wav_tensor,
            self.hps.data.filter_length,
            self.hps.data.sampling_rate,
            self.hps.data.hop_length,
            self.hps.data.win_length,
            center=False
        ).squeeze(0)

        return (
            torch.LongTensor(seq),           # phoneme ids
            spec,                             # spectrogram
            wav_tensor.squeeze(0),           # raw audio
            torch.LongTensor([speaker_id]),  # speaker id
        )

    def _augment(self, wav: np.ndarray, sr: int) -> np.ndarray:
        """Augmentation nhẹ: volume, speed."""
        # Random volume ±3dB
        gain = np.random.uniform(0.7, 1.3)
        wav = wav * gain

        # Random noise rất nhỏ
        if np.random.random() < 0.1:
            noise_level = np.random.uniform(0.0, 0.001)
            wav = wav + np.random.randn(len(wav)) * noise_level

        return np.clip(wav, -1.0, 1.0)


class VietnameseTTSCollate:
    """Collate function: pad sequences để tạo batch đồng nhất."""

    def __call__(self, batch):
        # Sort by text length (descending) cho packed sequence
        batch.sort(key=lambda x: len(x[0]), reverse=True)

        # Unpack
        seqs, specs, wavs, speakers = zip(*batch)

        # Pad text sequences
        max_len = max(len(s) for s in seqs)
        x_padded = torch.zeros(len(seqs), max_len, dtype=torch.long)
        x_lengths = torch.LongTensor([len(s) for s in seqs])
        for i, s in enumerate(seqs):
            x_padded[i, :len(s)] = s

        # Pad specs
        max_spec_len = max(s.size(1) for s in specs)
        n_mel = specs[0].size(0)
        spec_padded = torch.zeros(len(specs), n_mel, max_spec_len)
        spec_lengths = torch.LongTensor([s.size(1) for s in specs])
        for i, s in enumerate(specs):
            spec_padded[i, :, :s.size(1)] = s

        # Pad wavs
        max_wav_len = max(w.size(0) for w in wavs)
        wav_padded = torch.zeros(len(wavs), 1, max_wav_len)
        wav_lengths = torch.LongTensor([w.size(0) for w in wavs])
        for i, w in enumerate(wavs):
            wav_padded[i, 0, :w.size(0)] = w

        # Speakers
        speaker_ids = torch.cat(speakers)

        return (
            x_padded, x_lengths,
            spec_padded, spec_lengths,
            wav_padded, wav_lengths,
            speaker_ids,
            None, None,  # bert_ids, bert_mask (optional)
        )
