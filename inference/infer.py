"""
Inference Script — Vietnamese Bert-VITS2
Chuyển văn bản tiếng Việt → file audio WAV

Chạy:
    python inference/infer.py \
        --text "Xin chào, tôi là trợ lý giọng nói." \
        --checkpoint checkpoints/G_100000.pth \
        --output outputs/hello.wav
"""

import os
import sys
import json
import argparse
import time
from pathlib import Path

import torch
import soundfile as sf

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from text.cleaners.vietnamese_cleaners import vietnamese_cleaners  # noqa: E402
from text.phoneme.vi_g2p import g2p_text  # noqa: E402


# ─── Symbol table ────────────────────────────────────────────────────────────

def build_symbol_table():
    """Xây dựng bảng ký hiệu phoneme → index."""
    # Bảng phoneme cơ bản tiếng Việt
    specials = ['<PAD>', '<UNK>', '<BOS>', '<EOS>', '<PUNCT_,>',
                '<PUNCT_.>', '<PUNCT_!>', '<PUNCT_?>']

    # Initials
    initials = ['B', 'C', 'CH', 'DD', 'F', 'G', 'H', 'K', 'KH', 'KW',
                'L', 'M', 'N', 'NG', 'NH', 'P', 'R', 'S', 'T', 'TH',
                'TR', 'V', 'Z']

    # Nuclei (simplified)
    nuclei = ['A', 'AA', 'AX', 'AI', 'AO', 'AU', 'AU2', 'AM', 'AM2', 'AM3',
              'AN', 'AN2', 'AN3', 'ANG', 'ANG2', 'ANG3', 'ANH', 'ACH',
              'AP', 'AP3', 'AT', 'AT3', 'AC', 'AC3',
              'E', 'EE', 'EM', 'EM2', 'EN', 'EN2', 'ENG', 'ENH', 'ECH',
              'EP', 'EP2', 'ET', 'ET2', 'EO', 'EU',
              'I', 'IA', 'IE', 'IU', 'IM', 'IN', 'INH', 'ICH', 'IP', 'IT',
              'O', 'OA', 'OE', 'OI', 'OI2', 'OM', 'OM2', 'ON', 'ON2',
              'ONG', 'ONG2', 'OP', 'OP2', 'OT', 'OT2', 'OC', 'OC2', 'OO', 'OO2',
              'OR', 'ORM', 'ORN', 'ORI', 'ORP',
              'U', 'UA', 'UI', 'UM', 'UN', 'UNG', 'UP', 'UT', 'UC', 'UO', 'UOI',
              'UR', 'URA', 'URI', 'URM', 'URN', 'URNG', 'URT', 'URO', 'UROI', 'UROU',
              'Y', 'YA', 'YE', 'YI',
              'UYA', 'UYE', 'UYU']

    # Tạo tất cả phoneme tokens (initial_nucleus_tone)
    tones = ['0', '1', '2', '3', '4', '5']
    all_phones = []
    for n in nuclei:
        for t in tones:
            all_phones.append(f'{n}_{t}')  # không có initial
        for i in initials:
            for t in tones:
                all_phones.append(f'{i}_{n}_{t}')

    symbols = specials + all_phones
    symbol_to_id = {s: i for i, s in enumerate(symbols)}
    return symbols, symbol_to_id


SYMBOLS, SYMBOL_TO_ID = build_symbol_table()


def text_to_sequence(text: str, use_g2p: bool = True) -> list:
    """Chuyển văn bản → danh sách integer indices."""
    # Normalize trước
    text = vietnamese_cleaners(text)

    # G2P
    if use_g2p:
        phonemes = g2p_text(text)
    else:
        phonemes = list(text)  # character-level fallback

    # Map sang indices
    ids = []
    for ph in phonemes:
        if ph in SYMBOL_TO_ID:
            ids.append(SYMBOL_TO_ID[ph])
        else:
            ids.append(SYMBOL_TO_ID.get('<UNK>', 1))

    return ids


# ─── Inference ───────────────────────────────────────────────────────────────

class VietnameseTTS:
    """
    Wrapper class để inference dễ dàng.
    Hỗ trợ cả single-speaker và multi-speaker.
    """

    def __init__(
        self,
        checkpoint_path: str,
        config_path: str = None,
        device: str = None,
    ):
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
        print(f"[TTS] Device: {self.device}")

        # Load config
        if config_path is None:
            # Tự tìm config cạnh checkpoint
            config_path = str(Path(checkpoint_path).parent / 'config.json')
            if not os.path.exists(config_path):
                config_path = 'configs/base_vi.json'

        with open(config_path, 'r') as f:
            self.hps = json.load(f)

        # Load model
        self._load_model(checkpoint_path)
        print(f"[TTS] Model loaded from {checkpoint_path}")

    def _load_model(self, checkpoint_path: str):
        """Load và khởi tạo model."""
        from models.bert_vits2 import SynthesizerTrn

        m = self.hps.get('model', {})
        d = self.hps.get('data', {})

        self.model = SynthesizerTrn(
            n_vocab=len(SYMBOLS),
            spec_channels=d.get('filter_length', 1024) // 2 + 1,
            segment_size=d.get('segment_size', 8192) // d.get('hop_length', 256),
            inter_channels=m.get('inter_channels', 192),
            hidden_channels=m.get('hidden_channels', 192),
            filter_channels=m.get('filter_channels', 768),
            n_heads=m.get('n_heads', 2),
            n_layers=m.get('n_layers', 6),
            kernel_size=m.get('kernel_size', 3),
            p_dropout=0.0,  # No dropout at inference
            resblock=m.get('resblock', '1'),
            resblock_kernel_sizes=m.get('resblock_kernel_sizes', [3, 7, 11]),
            resblock_dilation_sizes=m.get('resblock_dilation_sizes', [[1,3,5],[1,3,5],[1,3,5]]),
            upsample_rates=m.get('upsample_rates', [8, 8, 2, 2]),
            upsample_initial_channel=m.get('upsample_initial_channel', 512),
            upsample_kernel_sizes=m.get('upsample_kernel_sizes', [16, 16, 4, 4]),
            n_speakers=d.get('n_speakers', 1),
            use_phobert=m.get('use_phobert', True),
            phobert_model=m.get('phobert_model', 'vinai/phobert-base-v2'),
            use_transformer_flows=m.get('use_transformer_flows', True),
            use_stochastic_dur_pred=m.get('use_stochastic_dur_pred', True),
        ).to(self.device)

        ckpt = torch.load(checkpoint_path, map_location=self.device)
        state_dict = ckpt.get('model', ckpt)
        self.model.load_state_dict(state_dict, strict=False)
        self.model.eval()

    @torch.no_grad()
    def synthesize(
        self,
        text: str,
        speaker_id: int = 0,
        noise_scale: float = 0.667,
        noise_scale_w: float = 0.8,
        length_scale: float = 1.0,
    ) -> tuple:
        """
        Tổng hợp giọng nói từ văn bản.

        Args:
            text: Văn bản tiếng Việt
            speaker_id: Speaker ID (multi-speaker)
            noise_scale: Variance của prior (0 = deterministic)
            noise_scale_w: Variance của duration predictor
            length_scale: Tốc độ đọc (>1 = chậm hơn, <1 = nhanh hơn)

        Returns:
            (audio_array, sample_rate)
        """
        t_start = time.time()

        # Text → sequence
        seq = text_to_sequence(text)
        if not seq:
            raise ValueError(f"Không chuyển được text sang phoneme: '{text}'")

        x = torch.LongTensor([seq]).to(self.device)
        x_lengths = torch.LongTensor([len(seq)]).to(self.device)
        sid = torch.LongTensor([speaker_id]).to(self.device) \
              if self.hps.get('data', {}).get('n_speakers', 1) > 1 else None

        # Inference
        audio, attn, y_mask, _ = self.model.infer(
            x, x_lengths,
            sid=sid,
            noise_scale=noise_scale,
            noise_scale_w=noise_scale_w,
            length_scale=length_scale,
        )

        audio = audio[0, 0].float().cpu().numpy()
        sr = self.hps.get('data', {}).get('sampling_rate', 22050)

        elapsed = time.time() - t_start
        audio_duration = len(audio) / sr
        rtf = elapsed / audio_duration
        print(f"[TTS] Synthesized {audio_duration:.2f}s audio in {elapsed:.2f}s (RTF={rtf:.3f})")

        return audio, sr

    def synthesize_to_file(self, text: str, output_path: str, **kwargs):
        """Tổng hợp và lưu thành file WAV."""
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        audio, sr = self.synthesize(text, **kwargs)
        sf.write(output_path, audio, sr)
        print(f"[TTS] Saved: {output_path}")
        return output_path


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Vietnamese Bert-VITS2 Inference')
    parser.add_argument('--text', type=str, required=True, help='Văn bản cần đọc')
    parser.add_argument('--checkpoint', type=str, required=True, help='Path đến checkpoint .pth')
    parser.add_argument('--config', type=str, default=None, help='Path đến config JSON')
    parser.add_argument('--output', type=str, default='outputs/output.wav')
    parser.add_argument('--speaker', type=int, default=0, help='Speaker ID')
    parser.add_argument('--noise_scale', type=float, default=0.667)
    parser.add_argument('--noise_scale_w', type=float, default=0.8)
    parser.add_argument('--length_scale', type=float, default=1.0,
                        help='Tốc độ đọc (1.0=bình thường, 1.2=chậm hơn, 0.8=nhanh hơn)')
    args = parser.parse_args()

    tts = VietnameseTTS(args.checkpoint, args.config)

    print(f"\n📝 Text: {args.text}")
    print(f"🔊 Output: {args.output}\n")

    tts.synthesize_to_file(
        args.text,
        args.output,
        speaker_id=args.speaker,
        noise_scale=args.noise_scale,
        noise_scale_w=args.noise_scale_w,
        length_scale=args.length_scale,
    )

    print("\n✅ Xong!")


if __name__ == '__main__':
    main()
