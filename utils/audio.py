"""
Audio Utilities — Vietnamese Bert-VITS2
Các hàm xử lý audio: load, resample, normalize, spectrogram
"""

import os
import numpy as np
import soundfile as sf


def load_wav(path: str, target_sr: int = 22050) -> tuple:
    """
    Load file audio và resample về target_sr.

    Returns:
        (data: np.ndarray float32, sr: int)
    """
    data, sr = sf.read(path, dtype='float32')

    # Mono
    if data.ndim > 1:
        data = data.mean(axis=1)

    # Resample nếu cần
    if sr != target_sr:
        import librosa
        data = librosa.resample(data, orig_sr=sr, target_sr=target_sr)
        sr = target_sr

    return data, sr


def save_wav(data: np.ndarray, path: str, sr: int = 22050):
    """Lưu audio array thành file WAV."""
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    # Normalize để tránh clipping
    if np.abs(data).max() > 1.0:
        data = data / np.abs(data).max() * 0.95
    sf.write(path, data, sr)


def normalize_audio(data: np.ndarray, target_lufs: float = -23.0) -> np.ndarray:
    """
    Normalize audio theo LUFS (EBU R128).
    Đơn giản hóa: chỉ dùng RMS normalization.
    """
    rms = np.sqrt(np.mean(data ** 2))
    if rms < 1e-8:
        return data
    # Chuyển target_lufs thành linear RMS (~= LUFS với sine wave)
    target_rms = 10 ** (target_lufs / 20.0)
    return data * (target_rms / rms)


def check_audio_quality(path: str, min_duration: float = 1.0,
                         max_noise_ratio: float = 0.3) -> dict:
    """
    Kiểm tra chất lượng audio file.

    Returns:
        dict với các thông số: duration, snr_estimate, is_valid, warnings
    """
    try:
        info = sf.info(path)
        data, sr = sf.read(path, dtype='float32')
        if data.ndim > 1:
            data = data.mean(axis=1)

        duration = len(data) / sr
        rms_total = np.sqrt(np.mean(data ** 2))

        # Ước lượng noise từ 10% frame im lặng nhất
        frame_size = int(sr * 0.02)
        n_frames = len(data) // frame_size
        rms_frames = np.array([
            np.sqrt(np.mean(data[i*frame_size:(i+1)*frame_size]**2))
            for i in range(n_frames)
        ])
        noise_floor = np.percentile(rms_frames, 10)
        snr_estimate = 20 * np.log10(rms_total / (noise_floor + 1e-10))

        warnings = []
        if duration < min_duration:
            warnings.append(f"Audio quá ngắn: {duration:.2f}s")
        if info.channels > 1:
            warnings.append("Stereo — cần convert sang Mono")
        if info.samplerate not in [22050, 44100]:
            warnings.append(f"Sample rate bất thường: {info.samplerate}")
        if snr_estimate < 20:
            warnings.append(f"SNR thấp: {snr_estimate:.1f} dB — có thể có nhiều tạp âm")

        return {
            'path': path,
            'duration': duration,
            'sample_rate': info.samplerate,
            'channels': info.channels,
            'snr_estimate_db': snr_estimate,
            'rms_db': 20 * np.log10(rms_total + 1e-10),
            'is_valid': len(warnings) == 0,
            'warnings': warnings,
        }

    except Exception as e:
        return {
            'path': path,
            'is_valid': False,
            'warnings': [f'Lỗi đọc file: {e}'],
        }
