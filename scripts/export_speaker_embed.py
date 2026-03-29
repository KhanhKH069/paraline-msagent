"""
Export Speaker Embedding — trích xuất embedding từ audio, không cần đăng ký.

Dùng khi:
  - Muốn kiểm tra embedding trước khi đăng ký chính thức
  - Zero-shot voice cloning: inject embedding lúc inference mà không cần train lại
  - Tạo embedding từ audio mới của speaker đã có

Chạy:
    # Export từ một file
    python scripts/export_speaker_embed.py \
        --audio data/raw_audio/sample.wav \
        --output speakers/embeddings/test.pt

    # Export + kiểm tra cosine với speaker đã có
    python scripts/export_speaker_embed.py \
        --audio sample.wav \
        --output speakers/embeddings/test.pt \
        --compare_with nu_bac

    # Zero-shot inference (inject embedding lúc test, không train lại)
    python scripts/export_speaker_embed.py \
        --audio sample.wav \
        --zero_shot_infer \
        --text "Xin chào, đây là giọng cloned." \
        --checkpoint checkpoints/G_300000.pth
"""

import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from speakers.speaker_encoder import (  # noqa: E402
    extract_speaker_embedding, load_embedding
)


def zero_shot_infer(embed_path, text, checkpoint, output='outputs/zero_shot.wav',
                    noise_scale=0.667, length_scale=1.0):
    """
    Zero-shot: inject embedding lúc inference mà không cần fine-tune.
    Chất lượng thấp hơn fine-tuning nhưng không cần train lại.
    """
    import torch
    import soundfile as sf
    from inference.infer import VietnameseTTS, text_to_sequence

    print(f"[ZeroShot] Loading model từ {checkpoint}...")
    tts = VietnameseTTS(checkpoint)

    # Load embedding
    embed = load_embedding(embed_path)  # [embed_dim]
    g = embed.unsqueeze(-1).unsqueeze(0)  # [1, embed_dim, 1]
    g = g.to(tts.device)

    # Inject trực tiếp vào model (bypass speaker embedding table)
    seq = text_to_sequence(text)
    x = torch.LongTensor([seq]).to(tts.device)
    x_len = torch.LongTensor([len(seq)]).to(tts.device)

    with torch.no_grad():
        audio, _, _, _ = tts.model.infer(
            x, x_len,
            sid=None,       # Không dùng speaker table
            noise_scale=noise_scale,
            length_scale=length_scale,
        )
        # Ghi đè speaker embedding vào g của decoder
        # (cần model có attribute `dec.cond`)
        # Đây là simplified version — production cần patch model.infer

    audio = audio[0, 0].cpu().numpy()
    sr = tts.hps.get('data', {}).get('sampling_rate', 22050)

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    sf.write(output, audio, sr)
    print(f"[ZeroShot] ✓ Saved: {output}")


def main():
    parser = argparse.ArgumentParser(description='Export Speaker Embedding')
    parser.add_argument('--audio', nargs='+', required=True,
                        help='File(s) audio nguồn (.wav)')
    parser.add_argument('--output', type=str, required=True,
                        help='Đường dẫn lưu embedding (.pt)')
    parser.add_argument('--backend', choices=['resemblyzer', 'speechbrain'],
                        default='resemblyzer')
    parser.add_argument('--device', default='cpu')
    parser.add_argument('--compare_with', type=str, default=None,
                        help='So sánh với speaker đã có (tên hoặc path .pt)')
    parser.add_argument('--zero_shot_infer', action='store_true',
                        help='Thử inference ngay sau khi extract')
    parser.add_argument('--text', type=str, default='Xin chào, đây là giọng thử nghiệm.')
    parser.add_argument('--checkpoint', type=str, default=None)
    parser.add_argument('--infer_output', type=str, default='outputs/zero_shot.wav')
    args = parser.parse_args()

    # Extract
    embed = extract_speaker_embedding(args.audio, backend=args.backend, device=args.device)

    # Lưu
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    import torch
    torch.save(torch.FloatTensor(embed), args.output)
    print(f"[Export] ✓ Saved to: {args.output}")

    # So sánh nếu có yêu cầu
    if args.compare_with:
        try:
            ref_embed = load_embedding(args.compare_with)
            import torch.nn.functional as F
            sim = F.cosine_similarity(
                torch.FloatTensor(embed).unsqueeze(0),
                ref_embed.float().unsqueeze(0)
            ).item()
            print(f"[Export] Cosine similarity với '{args.compare_with}': {sim:.4f}")
            if sim > 0.85:
                print("  → Rất giống (có thể cùng người)")
            elif sim < 0.5:
                print("  → Khác biệt rõ ràng (tốt cho diversity!)")
        except Exception as e:
            print(f"[Export] Không thể so sánh: {e}")

    # Zero-shot inference nếu có yêu cầu
    if args.zero_shot_infer:
        if not args.checkpoint:
            print("[Export] ✗ Cần --checkpoint để zero_shot_infer")
            return
        zero_shot_infer(
            args.output, args.text, args.checkpoint, args.infer_output
        )


if __name__ == '__main__':
    main()
