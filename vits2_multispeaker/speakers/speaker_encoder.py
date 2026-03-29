"""
Speaker Encoder — trích xuất speaker embedding từ audio mẫu.

Cách hoạt động:
  1. Load audio mẫu của người nói (30s–5 phút là đủ)
  2. Chạy qua ECAPA-TDNN hoặc x-vector để lấy embedding 256-dim
  3. Lưu embedding .pt vào speakers/embeddings/<name>.pt
  4. Embedding này được inject vào VITS2 lúc inference để "nói giọng đó"

Hai backend được hỗ trợ:
  - 'resemblyzer'  : nhanh, nhẹ, đủ dùng (~256-dim)
  - 'speechbrain'  : chính xác hơn, cần GPU (ECAPA-TDNN)
"""

import os
import torch
import numpy as np
from pathlib import Path
from typing import Union


EMBEDDINGS_DIR = Path(__file__).parent / 'embeddings'
EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)


# ─── Backend: Resemblyzer (nhẹ, nhanh) ──────────────────────────────────────

def extract_with_resemblyzer(audio_paths: list) -> np.ndarray:
    """
    Dùng Resemblyzer (GE2E model của Google) để lấy 256-dim speaker embedding.
    Tổng hợp nhiều file audio → lấy trung bình để ổn định hơn.

    Cài: pip install resemblyzer
    """
    try:
        from resemblyzer import VoiceEncoder, preprocess_wav
    except ImportError:
        raise ImportError(
            "Cần cài resemblyzer:\n"
            "  pip install resemblyzer"
        )

    encoder = VoiceEncoder()
    embeds = []

    for path in audio_paths:
        wav = preprocess_wav(path)
        if len(wav) < 16000:  # < 1 giây
            print(f"[SpeakerEncoder] ⚠ Audio quá ngắn, bỏ qua: {path}")
            continue
        embed = encoder.embed_utterance(wav)
        embeds.append(embed)

    if not embeds:
        raise ValueError("Không có audio hợp lệ để trích xuất embedding.")

    mean_embed = np.mean(embeds, axis=0)
    mean_embed = mean_embed / np.linalg.norm(mean_embed)  # L2 normalize
    return mean_embed.astype(np.float32)


# ─── Backend: SpeechBrain ECAPA-TDNN (chính xác hơn) ───────────────────────

def extract_with_speechbrain(audio_paths: list, device: str = 'cpu') -> np.ndarray:
    """
    Dùng ECAPA-TDNN (SpeechBrain) — chính xác hơn, cần download ~70MB model.
    Output: 192-dim embedding.

    Cài: pip install speechbrain
    """
    try:
        from speechbrain.pretrained import EncoderClassifier
    except ImportError:
        raise ImportError(
            "Cần cài speechbrain:\n"
            "  pip install speechbrain"
        )

    classifier = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        run_opts={"device": device},
        savedir="speakers/pretrained_models/ecapa"
    )

    embeds = []
    for path in audio_paths:
        signal, fs = classifier.load_audio(path)
        if signal.shape[-1] < fs:
            print(f"[SpeakerEncoder] ⚠ Audio quá ngắn, bỏ qua: {path}")
            continue
        embed = classifier.encode_batch(signal.unsqueeze(0))
        embeds.append(embed.squeeze().cpu().numpy())

    if not embeds:
        raise ValueError("Không có audio hợp lệ để trích xuất embedding.")

    mean_embed = np.mean(embeds, axis=0)
    mean_embed = mean_embed / np.linalg.norm(mean_embed)
    return mean_embed.astype(np.float32)


# ─── Hàm chính ───────────────────────────────────────────────────────────────

def extract_speaker_embedding(
    audio_paths: Union[str, list],
    backend: str = 'resemblyzer',
    device: str = 'cpu',
) -> np.ndarray:
    """
    Trích xuất speaker embedding từ một hoặc nhiều file audio.

    Args:
        audio_paths: Một file hoặc danh sách file audio (.wav)
        backend: 'resemblyzer' (mặc định, nhanh) hoặc 'speechbrain' (chính xác hơn)
        device: 'cpu' hoặc 'cuda'

    Returns:
        numpy array shape [embedding_dim]
    """
    if isinstance(audio_paths, str):
        audio_paths = [audio_paths]

    audio_paths = [str(p) for p in audio_paths]

    # Kiểm tra file tồn tại
    missing = [p for p in audio_paths if not os.path.exists(p)]
    if missing:
        raise FileNotFoundError(f"Không tìm thấy file: {missing}")

    print(f"[SpeakerEncoder] Trích xuất embedding từ {len(audio_paths)} file ({backend})...")

    if backend == 'resemblyzer':
        embed = extract_with_resemblyzer(audio_paths)
    elif backend == 'speechbrain':
        embed = extract_with_speechbrain(audio_paths, device)
    else:
        raise ValueError(f"Backend không hợp lệ: '{backend}'. Chọn 'resemblyzer' hoặc 'speechbrain'.")

    print(f"[SpeakerEncoder] ✓ Embedding shape: {embed.shape}, norm: {np.linalg.norm(embed):.4f}")
    return embed


def save_embedding(embed: np.ndarray, speaker_name: str) -> str:
    """
    Lưu embedding thành file .pt.

    Returns:
        Đường dẫn file đã lưu.
    """
    out_path = str(EMBEDDINGS_DIR / f'{speaker_name}.pt')
    tensor = torch.FloatTensor(embed)
    torch.save(tensor, out_path)
    print(f"[SpeakerEncoder] ✓ Saved embedding: {out_path}")
    return out_path


def load_embedding(speaker_name_or_path: str) -> torch.Tensor:
    """
    Load embedding đã lưu.

    Args:
        speaker_name_or_path: Tên speaker (tự tìm trong embeddings/) hoặc full path.
    """
    path = speaker_name_or_path
    if not os.path.exists(path):
        path = str(EMBEDDINGS_DIR / f'{speaker_name_or_path}.pt')
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Không tìm thấy embedding: '{speaker_name_or_path}'\n"
            f"Chạy trước: python scripts/add_speaker.py --name {speaker_name_or_path} ..."
        )
    return torch.load(path, map_location='cpu')


def compare_speakers(name_a: str, name_b: str) -> float:
    """
    Tính cosine similarity giữa 2 speaker embedding.
    1.0 = giống hệt, 0.0 = khác hoàn toàn.
    Dùng để kiểm tra xem 2 audio mẫu có đúng cùng người không.
    """
    embed_a = load_embedding(name_a).float()
    embed_b = load_embedding(name_b).float()
    similarity = torch.nn.functional.cosine_similarity(
        embed_a.unsqueeze(0), embed_b.unsqueeze(0)
    ).item()
    print(f"[SpeakerEncoder] Similarity({name_a}, {name_b}) = {similarity:.4f}")
    return similarity


def project_embedding_to_model_dim(embed: torch.Tensor, target_dim: int = 256) -> torch.Tensor:
    """
    Nếu embedding dim từ encoder (192 từ ECAPA, 256 từ Resemblyzer) 
    khác với gin_channels trong config → project về đúng dim.
    """
    if embed.shape[-1] == target_dim:
        return embed
    # Linear interpolation đơn giản (không cần train)
    return torch.nn.functional.interpolate(
        embed.unsqueeze(0).unsqueeze(0),
        size=target_dim,
        mode='linear',
        align_corners=False
    ).squeeze()
