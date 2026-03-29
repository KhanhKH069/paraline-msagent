"""
Monotonic Alignment Search (MAS) — từ Glow-TTS
Tìm alignment có log-likelihood cao nhất giữa text và audio.

VITS2 cải tiến: thêm Gaussian noise vào Q values ở đầu training
để tránh bị stuck ở local optima (xem Section 2.2 của paper).
"""

import numpy as np
import torch


def maximum_path_numpy(value, mask):
    """
    Thuật toán MAS bằng numpy (dùng khi không có CUDA kernel).

    Args:
        value: log-likelihood matrix [B, T_text, T_mel]
        mask: binary mask [B, T_text, T_mel]

    Returns:
        path: binary alignment matrix [B, T_text, T_mel]
    """
    value = value * mask
    device = value.device
    dtype = value.dtype

    value_np = value.cpu().float().numpy()
    mask_np = mask.cpu().numpy().astype(bool)

    b, t_x, t_y = value_np.shape
    direction = np.zeros_like(value_np, dtype=np.int32)
    v = np.zeros((b, t_x), dtype=np.float32)
    x_range = np.arange(t_x, dtype=np.float32).reshape(1, -1)

    for j in range(t_y):
        v0 = np.pad(v, [[0, 0], [1, 0]], mode='constant',
                    constant_values=-np.inf)[:, :-1]
        v1 = v
        max_mask = v1 >= v0
        v_max = np.where(max_mask, v1, v0)
        direction[:, :, j] = max_mask

        index_mask = x_range <= j
        v = np.where(index_mask, v_max + value_np[:, :, j], -np.inf)

    # Traceback
    path = np.zeros_like(value_np, dtype=np.float32)
    index = mask_np[:, :, 0].sum(1).astype(np.int32) - 1

    for j in range(t_y - 1, -1, -1):
        path[np.arange(b), index, j] = 1
        index = index + direction[np.arange(b), index, j] - 1

    path = path * mask_np
    path = torch.from_numpy(path).to(device=device, dtype=dtype)
    return path


def maximum_path(neg_cent, mask):
    """
    Entry point cho MAS. Dùng CUDA kernel nếu có, fallback sang numpy.

    Args:
        neg_cent: negative centroid matrix [B, T_mel, T_text] (hoặc [B, T_text, T_mel])
        mask: [B, T_text, T_mel] hoặc phù hợp

    Returns:
        path: binary alignment [B, T_text, T_mel]
    """
    # Thử dùng monotonic_align CUDA kernel (nếu đã compile)
    try:
        from monotonic_align import maximum_path as _maximum_path_cuda
        return _maximum_path_cuda(neg_cent, mask)
    except ImportError:
        pass

    # Fallback: numpy implementation
    # neg_cent shape: [B, T_text, T_mel]
    return maximum_path_numpy(neg_cent, mask)
