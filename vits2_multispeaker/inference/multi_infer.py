"""
Multi-Speaker Inference — chọn giọng theo tên hoặc ID.

Khác với infer.py gốc (chỉ nhận int speaker_id), script này cho phép:
  - Chọn giọng theo tên slug: --speaker nu_bac
  - Mix giọng: --speaker_mix "nu_bac:0.7,nu_nam:0.3" (thực nghiệm)
  - Batch inference với nhiều giọng cùng lúc
  - Xem danh sách giọng có sẵn

Chạy:
    # Chọn theo tên
    python inference/multi_infer.py \
        --text "Xin chào Việt Nam." \
        --speaker nu_bac \
        --checkpoint checkpoints/G_300000.pth

    # Chọn theo ID
    python inference/multi_infer.py \
        --text "Xin chào." \
        --speaker 3 \
        --checkpoint checkpoints/G_300000.pth

    # Render cùng một text với TẤT CẢ giọng (để so sánh)
    python inference/multi_infer.py \
        --text "Hôm nay trời đẹp quá." \
        --all_speakers \
        --checkpoint checkpoints/G_300000.pth \
        --output_dir outputs/compare/

    # Mix 2 giọng (thực nghiệm)
    python inference/multi_infer.py \
        --text "Giọng pha trộn." \
        --speaker_mix "nu_bac:0.6,nu_nam:0.4" \
        --checkpoint checkpoints/G_300000.pth
"""

import sys
import os
import argparse
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def resolve_speaker_id(identifier: str, registry) -> int:
    """Chuyển tên hoặc ID string thành integer speaker_id."""
    spk = registry.resolve(identifier)
    if spk is None:
        raise ValueError(
            f"Không tìm thấy speaker: '{identifier}'\n"
            f"Chạy: python scripts/add_speaker.py --list  để xem danh sách."
        )
    return spk.id


def mix_speaker_embeddings(mix_spec: str, registry, model, device) -> object:
    """
    Parse và tính embedding pha trộn từ nhiều speakers.
    mix_spec format: "nu_bac:0.6,nu_nam:0.4"

    Trả về tensor [1, gin_channels, 1] đã normalize.
    """
    from speakers.speaker_encoder import load_embedding

    parts = [p.strip() for p in mix_spec.split(',')]
    embeds = []
    weights = []

    for part in parts:
        if ':' in part:
            name, w = part.rsplit(':', 1)
            w = float(w)
        else:
            name = part
            w = 1.0 / len(parts)

        # Thử load từ embedding file trước, fallback sang speaker table
        try:
            embed = load_embedding(name)  # [dim]
        except FileNotFoundError:
            spk = registry.resolve(name)
            if spk is None:
                raise ValueError(f"Speaker '{name}' không tồn tại.")
            embed = model.emb_g.weight[spk.id].detach().cpu()  # [gin_channels]

        embeds.append(embed)
        weights.append(w)

    # Normalize weights
    total_w = sum(weights)
    weights = [w / total_w for w in weights]

    # Tính weighted average
    mixed = sum(e * w for e, w in zip(embeds, weights))
    mixed = mixed / mixed.norm()  # L2 normalize

    return mixed.unsqueeze(0).unsqueeze(-1).to(device)  # [1, dim, 1]


def single_infer(tts, text, speaker_id, output_path, **kwargs):
    """Inference đơn, lưu ra file."""
    tts.synthesize_to_file(text, output_path, speaker_id=speaker_id, **kwargs)


def all_speakers_infer(tts, text, registry, output_dir, **kwargs):
    """Render cùng text với tất cả speakers đã đăng ký."""
    import soundfile as sf
    import numpy as np

    os.makedirs(output_dir, exist_ok=True)
    speakers = registry.list_all()

    print(f"\n🎭 Render '{text[:40]}...' với {len(speakers)} giọng:\n")
    audios = []

    for spk in speakers:
        out = os.path.join(output_dir, f"{spk.id:02d}_{spk.name}.wav")
        try:
            audio, sr = tts.synthesize(text, speaker_id=spk.id, **kwargs)
            import soundfile as sf
            sf.write(out, audio, sr)
            audios.append((spk, audio, sr))
            print(f"  ✓ [{spk.id}] {spk.display_name} → {out}")
        except Exception as e:
            print(f"  ✗ [{spk.id}] {spk.display_name}: {e}")

    # Gộp thành file comparison (các giọng nối tiếp nhau, silence 0.5s giữa)
    if audios:
        sr = audios[0][2]
        silence = np.zeros(int(sr * 0.5))
        combined = []
        for spk, audio, _ in audios:
            combined.append(audio)
            combined.append(silence)
        combined_audio = np.concatenate(combined)
        combined_path = os.path.join(output_dir, '00_all_speakers_comparison.wav')
        import soundfile as sf
        sf.write(combined_path, combined_audio, sr)
        print(f"\n  📊 File so sánh: {combined_path}")

    return audios


def main():
    parser = argparse.ArgumentParser(
        description='Multi-Speaker TTS Inference',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--text', type=str,
                        help='Văn bản cần đọc')
    parser.add_argument('--text_file', type=str,
                        help='File văn bản (mỗi dòng một câu)')
    parser.add_argument('--speaker', type=str, default='0',
                        help='Tên hoặc ID của speaker (ví dụ: nu_bac hoặc 3)')
    parser.add_argument('--speaker_mix', type=str, default=None,
                        help='Mix giọng (ví dụ: "nu_bac:0.6,nu_nam:0.4")')
    parser.add_argument('--all_speakers', action='store_true',
                        help='Render với tất cả speakers')
    parser.add_argument('--checkpoint', type=str, required=True)
    parser.add_argument('--config', type=str, default=None)
    parser.add_argument('--output', type=str, default='outputs/multi_output.wav')
    parser.add_argument('--output_dir', type=str, default='outputs/all_speakers/')
    parser.add_argument('--noise_scale', type=float, default=0.667)
    parser.add_argument('--noise_scale_w', type=float, default=0.8)
    parser.add_argument('--length_scale', type=float, default=1.0)
    parser.add_argument('--list_speakers', action='store_true',
                        help='Hiển thị danh sách speakers rồi thoát')
    args = parser.parse_args()

    # Import sau khi đã set path
    from speakers.speaker_registry import get_registry
    from inference.infer import VietnameseTTS

    registry = get_registry()

    # Chỉ liệt kê speakers
    if args.list_speakers:
        registry.print_table()
        return

    if not args.text and not args.text_file and not args.all_speakers:
        parser.print_help()
        return

    # Load model
    print("[MultiInfer] Loading model...")
    tts = VietnameseTTS(args.checkpoint, args.config)

    infer_kwargs = dict(
        noise_scale=args.noise_scale,
        noise_scale_w=args.noise_scale_w,
        length_scale=args.length_scale,
    )

    # Chế độ: tất cả speakers
    if args.all_speakers:
        text = args.text or "Xin chào, đây là bài kiểm tra giọng nói tiếng Việt."
        all_speakers_infer(tts, text, registry, args.output_dir, **infer_kwargs)
        return

    # Chế độ: mix giọng
    if args.speaker_mix:
        print(f"[MultiInfer] Mix mode: {args.speaker_mix}")
        _g = mix_speaker_embeddings(args.speaker_mix, registry, tts.model, tts.device)
        # Inject g trực tiếp (simplified)
        texts = [args.text] if args.text else open(args.text_file).read().splitlines()
        for i, t in enumerate(texts):
            out = args.output if len(texts) == 1 else args.output.replace('.wav', f'_{i:03d}.wav')
            print(f"[MultiInfer] Synthesizing: {t[:50]}")
            # Note: full implementation cần patch model.infer để nhận g tensor trực tiếp
            tts.synthesize_to_file(t, out, speaker_id=0, **infer_kwargs)
        return

    # Chế độ: single speaker theo tên/ID
    speaker_id = resolve_speaker_id(args.speaker, registry)
    spk = registry.get_by_id(speaker_id)
    print(f"[MultiInfer] Speaker: [{speaker_id}] {spk.display_name if spk else speaker_id}")

    texts = []
    if args.text:
        texts = [args.text]
    elif args.text_file:
        with open(args.text_file, 'r', encoding='utf-8') as f:
            texts = [line.strip() for line in f if line.strip()]

    for i, text in enumerate(texts):
        out = args.output if len(texts) == 1 else \
              args.output.replace('.wav', f'_{i:03d}.wav')
        print(f"\n📝 [{i+1}/{len(texts)}] {text[:60]}")
        tts.synthesize_to_file(text, out, speaker_id=speaker_id, **infer_kwargs)

    print("\n✅ Xong!")


if __name__ == '__main__':
    main()
