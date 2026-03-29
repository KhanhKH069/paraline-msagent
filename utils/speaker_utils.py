"""
Speaker Utilities — helper functions cho multi-speaker workflow.
"""

import os
import torch


def build_speaker_id_map_from_dataset(list_path: str) -> dict:
    """
    Đọc dataset list.txt và xây dựng mapping name → id từ cột speaker_id.
    Dùng để verify dataset có đúng speaker_id không.

    Returns:
        dict: {speaker_name_or_id: count_of_samples}
    """
    counts = {}
    with open(list_path, 'r', encoding='utf-8') as f:
        for line in f:
            parts = line.strip().split('|')
            if len(parts) >= 3:
                sid = parts[2].strip()
                counts[sid] = counts.get(sid, 0) + 1
    return counts


def estimate_training_hours(list_path: str, speaker_id: int) -> float:
    """
    Ước tính số giờ audio của một speaker cụ thể trong dataset.
    """
    import soundfile as sf

    total = 0.0
    with open(list_path, 'r', encoding='utf-8') as f:
        for line in f:
            parts = line.strip().split('|')
            if len(parts) >= 3 and int(parts[2].strip()) == speaker_id:
                try:
                    info = sf.info(parts[0])
                    total += info.duration
                except Exception:
                    pass
    return total / 3600.0


def check_speaker_readiness(speaker_name: str) -> dict:
    """
    Kiểm tra speaker đã sẵn sàng để train chưa.
    Returns dict với các thông tin cần thiết.
    """
    from speakers.speaker_registry import get_registry
    registry = get_registry()

    spk = registry.get(speaker_name)
    if not spk:
        return {'ready': False, 'error': f"Speaker '{speaker_name}' chưa được đăng ký."}

    issues = []
    if not os.path.exists(spk.audio_sample):
        issues.append(f"Thiếu audio sample: {spk.audio_sample}")
    if not os.path.exists(spk.embedding_path):
        issues.append(f"Thiếu embedding: {spk.embedding_path}")
    if spk.training_hours < 0.5:
        issues.append(f"Ít audio training: {spk.training_hours:.2f}h (khuyến nghị ≥ 1h)")

    return {
        'ready': len(issues) == 0,
        'speaker': spk,
        'issues': issues,
        'training_hours': spk.training_hours,
    }


def interpolate_speakers(
    model,
    speaker_id_a: int,
    speaker_id_b: int,
    alpha: float = 0.5,
    device: str = 'cpu',
) -> torch.Tensor:
    """
    Tính embedding pha trộn tuyến tính giữa 2 speakers.
    alpha=0.0 → 100% speaker A
    alpha=1.0 → 100% speaker B
    alpha=0.5 → 50/50

    Dùng để tạo "giọng mới" nằm giữa 2 giọng đã có,
    hoặc để tạo hiệu ứng chuyển giọng dần (voice morphing).
    """
    emb_a = model.emb_g.weight[speaker_id_a].detach()  # [gin_channels]
    emb_b = model.emb_g.weight[speaker_id_b].detach()  # [gin_channels]

    mixed = (1 - alpha) * emb_a + alpha * emb_b
    mixed = mixed / mixed.norm()  # L2 normalize

    return mixed.unsqueeze(0).unsqueeze(-1).to(device)  # [1, gin_channels, 1]


def print_speaker_stats(list_path: str):
    """In thống kê số lượng sample và giờ audio theo speaker."""
    from speakers.speaker_registry import get_registry
    registry = get_registry()

    counts = build_speaker_id_map_from_dataset(list_path)
    speakers = {str(s.id): s for s in registry.list_all()}

    print(f"\n{'─'*60}")
    print(f"  PHÂN BỐ DỮ LIỆU THEO SPEAKER ({list_path})")
    print(f"{'─'*60}")
    print(f"  {'ID':>4}  {'Tên':20} {'Samples':>8}  {'Giờ train':>10}")
    print(f"{'─'*60}")

    for sid_str, count in sorted(counts.items()):
        spk = speakers.get(sid_str)
        name = spk.display_name if spk else f"ID={sid_str}"
        hours = estimate_training_hours(list_path, int(sid_str)) if list_path else 0
        status = '✓' if hours >= 1.0 else '⚠'
        print(f"  {sid_str:>4}  {name:20} {count:>8}  {hours:>9.2f}h  {status}")

    print(f"{'─'*60}\n")
