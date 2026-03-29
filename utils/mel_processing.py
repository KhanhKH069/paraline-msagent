"""
Mel-spectrogram Processing — Vietnamese VITS2
"""

import torch
import torch.nn.functional as F


def spectrogram_torch(y, n_fft, sampling_rate, hop_size, win_size, center=False):
    """Tính STFT spectrogram từ waveform."""
    if torch.min(y) < -1.1:
        print(f'[Mel] Warning: min value = {torch.min(y).item():.4f}')
    if torch.max(y) > 1.1:
        print(f'[Mel] Warning: max value = {torch.max(y).item():.4f}')

    hann_window = torch.hann_window(win_size).to(dtype=y.dtype, device=y.device)

    y = F.pad(y.unsqueeze(1),
              (int((n_fft - hop_size) / 2), int((n_fft - hop_size) / 2)),
              mode='reflect').squeeze(1)

    spec = torch.stft(
        y, n_fft, hop_length=hop_size, win_length=win_size,
        window=hann_window, center=center,
        pad_mode='reflect', normalized=False, onesided=True,
        return_complex=True
    )
    spec = torch.abs(spec)
    spec = torch.sqrt(spec.pow(2).sum(-1) + 1e-6) if spec.dim() == 4 else spec
    return spec


def mel_spectrogram_torch(y, n_fft, num_mels, sampling_rate, hop_size,
                           win_size, fmin, fmax, center=False):
    """Tính mel-spectrogram từ waveform."""
    from librosa.filters import mel as librosa_mel

    mel_basis_key = f'{fmax}_{y.device}'
    if not hasattr(mel_spectrogram_torch, '_mel_basis'):
        mel_spectrogram_torch._mel_basis = {}

    if mel_basis_key not in mel_spectrogram_torch._mel_basis:
        mel_f = librosa_mel(sr=sampling_rate, n_fft=n_fft, n_mels=num_mels,
                            fmin=fmin, fmax=fmax)
        mel_spectrogram_torch._mel_basis[mel_basis_key] = \
            torch.from_numpy(mel_f).float().to(y.device)

    spec = spectrogram_torch(y, n_fft, sampling_rate, hop_size, win_size, center)
    mel_basis = mel_spectrogram_torch._mel_basis[mel_basis_key]
    mel = torch.matmul(mel_basis, spec)
    mel = spectral_normalize_torch(mel)
    return mel


def spectral_normalize_torch(magnitudes, C=1, clip_val=1e-5):
    """Log-scale normalization cho spectrogram."""
    return torch.log(torch.clamp(magnitudes, min=clip_val) * C)


def spectral_de_normalize_torch(magnitudes, C=1):
    """Inverse của spectral normalization."""
    return torch.exp(magnitudes) / C
