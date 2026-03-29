"""
Add Speaker Script — thêm giọng mới vào Vietnamese Bert-VITS2.

Quy trình:
  1. Chuẩn bị audio mẫu (~30s audio sạch, không cần transcript)
  2. Chạy script này để:
     a. Trích xuất speaker embedding
     b. Đăng ký vào speakers.json
     c. (Tùy chọn) Chuẩn bị dataset fine-tuning

Chạy:
    # Thêm giọng từ một file mẫu
    python scripts/add_speaker.py \
        --name "nu_bac" \
        --display_name "Nữ - Miền Bắc" \
        --gender female \
        --region north \
        --audio_sample data/raw_audio/nu_bac_sample.wav

    # Thêm từ nhiều file (embedding sẽ chính xác hơn)
    python scripts/add_speaker.py \
        --name "nam_bac" \
        --audio_sample data/raw_audio/nam_bac_01.wav data/raw_audio/nam_bac_02.wav \
        --backend speechbrain

    # Xem danh sách speaker hiện tại
    python scripts/add_speaker.py --list
"""

import sys
import argparse
from pathlib import Path
from datetime import date

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from speakers.speaker_registry import SpeakerRegistry, Speaker, get_registry  # noqa: E402
from speakers.speaker_encoder import (  # noqa: E402
    extract_speaker_embedding, save_embedding, compare_speakers
)


def cmd_list(registry: SpeakerRegistry):
    """Hiện bảng danh sách speakers."""
    registry.print_table()


def cmd_add(args, registry: SpeakerRegistry):
    """Thêm speaker mới."""

    # Kiểm tra tên hợp lệ (slug)
    name = args.name.lower().replace(' ', '_').replace('-', '_')
    if not name.replace('_', '').isalnum():
        print(f"[AddSpeaker] ✗ Tên không hợp lệ: '{name}'. Chỉ dùng chữ, số, dấu gạch dưới.")
        return

    # Xác định speaker_id
    if args.speaker_id is not None:
        speaker_id = args.speaker_id
        existing = registry.get_by_id(speaker_id)
        if existing and not args.overwrite:
            print(f"[AddSpeaker] ✗ Speaker ID {speaker_id} đã tồn tại: '{existing.name}'")
            print("  Dùng --overwrite để ghi đè, hoặc chọn ID khác.")
            return
    else:
        speaker_id = registry.next_available_id()
        print(f"[AddSpeaker] Tự động gán speaker_id = {speaker_id}")

    print(f"\n{'─'*50}")
    print(f"  Thêm speaker mới: '{args.display_name or name}'")
    print(f"  ID: {speaker_id} | Gender: {args.gender} | Region: {args.region}")
    print(f"  Audio samples: {len(args.audio_sample)} file(s)")
    print(f"{'─'*50}\n")

    # Trích xuất embedding
    print("[AddSpeaker] Bước 1/3: Trích xuất speaker embedding...")
    embed = extract_speaker_embedding(
        args.audio_sample,
        backend=args.backend,
        device=args.device,
    )

    # Lưu embedding
    print("[AddSpeaker] Bước 2/3: Lưu embedding...")
    embed_path = save_embedding(embed, name)

    # Đăng ký vào registry
    print("[AddSpeaker] Bước 3/3: Đăng ký vào speakers.json...")
    speaker = Speaker(
        id=speaker_id,
        name=name,
        display_name=args.display_name or name,
        gender=args.gender,
        region=args.region,
        description=args.description or '',
        audio_sample=args.audio_sample[0],  # Lưu file đầu tiên làm mẫu
        embedding_path=embed_path,
        training_hours=0.0,
        added_at=str(date.today()),
        notes=args.notes or '',
    )
    registry.add(speaker, overwrite=args.overwrite)

    # Thành công
    print(f"\n{'═'*50}")
    print(f"  ✅ Speaker '{name}' (ID={speaker_id}) đã được thêm!")
    print(f"{'═'*50}")
    print("\n  Bước tiếp theo:")
    print("  1. Thu âm ~1-2 giờ audio của người này vào data/raw_audio/")
    print("  2. Tạo transcript tương ứng trong data/transcripts/")
    print(f"  3. Chạy: python scripts/prepare_dataset.py --speaker {speaker_id}")
    print("  4. Fine-tune: python training/train.py --config configs/multi_speaker.json")
    print()


def cmd_compare(args, registry: SpeakerRegistry):
    """So sánh 2 speaker embeddings."""
    sim = compare_speakers(args.compare[0], args.compare[1])
    if sim > 0.85:
        print("→ Rất giống nhau (có thể là cùng một người)")
    elif sim > 0.7:
        print("→ Tương đối giống")
    elif sim > 0.5:
        print("→ Khác nhau vừa phải")
    else:
        print("→ Hoàn toàn khác nhau (tốt cho multi-speaker!)")


def cmd_remove(args, registry: SpeakerRegistry):
    """Xóa speaker khỏi registry (không xóa embedding file)."""
    spk = registry.resolve(args.remove)
    if not spk:
        print(f"[AddSpeaker] ✗ Không tìm thấy speaker: '{args.remove}'")
        return

    confirm = input(f"Xác nhận xóa speaker '{spk.name}' (ID={spk.id})? [y/N] ")
    if confirm.lower() != 'y':
        print("Đã hủy.")
        return

    registry._data['speakers'] = [
        s for s in registry._data['speakers'] if s['id'] != spk.id
    ]
    registry._save()
    print(f"[AddSpeaker] ✓ Đã xóa speaker '{spk.name}' khỏi registry.")
    print(f"  (Embedding file vẫn còn tại: {spk.embedding_path})")


def main():
    parser = argparse.ArgumentParser(
        description='Quản lý speakers cho Vietnamese Bert-VITS2',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Subcommands via flags
    parser.add_argument('--list', action='store_true',
                        help='Hiển thị danh sách tất cả speakers')
    parser.add_argument('--compare', nargs=2, metavar=('SPEAKER_A', 'SPEAKER_B'),
                        help='So sánh cosine similarity giữa 2 speakers')
    parser.add_argument('--remove', metavar='NAME_OR_ID',
                        help='Xóa speaker khỏi registry')

    # Add speaker args
    parser.add_argument('--name', type=str,
                        help='Tên slug (dùng gạch dưới, ví dụ: nu_bac)')
    parser.add_argument('--display_name', type=str,
                        help='Tên hiển thị (ví dụ: "Nữ - Miền Bắc")')
    parser.add_argument('--gender', choices=['male', 'female', 'other'], default='female')
    parser.add_argument('--region', choices=['north', 'central', 'south'], default='north')
    parser.add_argument('--description', type=str, default='')
    parser.add_argument('--notes', type=str, default='')
    parser.add_argument('--audio_sample', nargs='+', metavar='FILE',
                        help='Một hoặc nhiều file audio mẫu')
    parser.add_argument('--speaker_id', type=int, default=None,
                        help='Speaker ID (tự động nếu không chỉ định)')
    parser.add_argument('--backend', choices=['resemblyzer', 'speechbrain'],
                        default='resemblyzer',
                        help='Backend trích xuất embedding')
    parser.add_argument('--device', type=str, default='cpu')
    parser.add_argument('--overwrite', action='store_true',
                        help='Ghi đè nếu speaker đã tồn tại')

    args = parser.parse_args()
    registry = get_registry()

    if args.list:
        cmd_list(registry)
    elif args.compare:
        cmd_compare(args, registry)
    elif args.remove:
        cmd_remove(args, registry)
    elif args.name and args.audio_sample:
        cmd_add(args, registry)
    else:
        parser.print_help()
        print("\nVí dụ nhanh:")
        print("  python scripts/add_speaker.py --list")
        print("  python scripts/add_speaker.py --name nu_bac --audio_sample sample.wav")


if __name__ == '__main__':
    main()
