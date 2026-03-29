"""
Training Losses cho Vietnamese Bert-VITS2

Gồm:
- Generator losses (mel reconstruction, KL divergence, feature matching, adversarial)
- Discriminator losses (MPD + MSD)
- Duration predictor losses (adversarial + MSE)
"""

import torch
import torch.nn.functional as F


# ─── Discriminator Losses ────────────────────────────────────────────────────

def discriminator_loss(disc_real_outputs, disc_generated_outputs):
    """
    Least-squares GAN discriminator loss.
    D muốn: real → 1, fake → 0
    """
    loss = 0.0
    r_losses, g_losses = [], []

    for dr, dg in zip(disc_real_outputs, disc_generated_outputs):
        r_loss = torch.mean((1 - dr) ** 2)
        g_loss = torch.mean(dg ** 2)
        loss += r_loss + g_loss
        r_losses.append(r_loss.item())
        g_losses.append(g_loss.item())

    return loss, r_losses, g_losses


# ─── Generator Adversarial Loss ──────────────────────────────────────────────

def generator_loss(disc_outputs):
    """
    Generator adversarial loss.
    G muốn: fake → 1
    """
    loss = 0.0
    gen_losses = []

    for dg in disc_outputs:
        loss_item = torch.mean((1 - dg) ** 2)
        gen_losses.append(loss_item)
        loss += loss_item

    return loss, gen_losses


# ─── Feature Matching Loss ───────────────────────────────────────────────────

def feature_loss(fmap_r, fmap_g):
    """
    L1 distance giữa discriminator feature maps của real vs generated.
    Giúp generator học được high-frequency detail.
    """
    loss = 0.0
    for dr, dg in zip(fmap_r, fmap_g):
        for rl, gl in zip(dr, dg):
            rl = rl.float().detach()
            gl = gl.float()
            loss += torch.mean(torch.abs(rl - gl))
    return loss * 2


# ─── KL Divergence Loss ──────────────────────────────────────────────────────

def kl_loss(z_p, logs_q, m_p, logs_p, z_mask):
    """
    KL(q || p) = KL(N(m_q, s_q) || N(m_p, s_p))
    Trong VITS2, z_p = flow(z_q) đã transform sang prior space.

    = 0.5 * (logs_p - logs_q + exp(2*(logs_q - logs_p)) + ((z_p - m_p)/exp(logs_p))^2 - 1)
    """
    z_p = z_p.float()
    logs_q = logs_q.float()
    m_p = m_p.float()
    logs_p = logs_p.float()
    z_mask = z_mask.float()

    kl = logs_p - logs_q - 0.5
    kl += 0.5 * ((z_p - m_p) ** 2) * torch.exp(-2. * logs_p)
    kl += 0.5 * torch.exp(2. * (logs_q - logs_p))

    kl = torch.sum(kl * z_mask)
    loss_k = kl / torch.sum(z_mask)
    return loss_k


# ─── Mel Reconstruction Loss ─────────────────────────────────────────────────

def mel_loss(y_hat, y, n_fft=1024, n_mels=80, sample_rate=22050,
             hop_length=256, win_length=1024, fmin=0, fmax=None):
    """
    L1 loss giữa mel-spectrogram của generated vs real audio.
    Loss này chiếm tỷ trọng lớn nhất (c_mel=45 trong config).
    """
    from utils.mel_processing import mel_spectrogram_torch

    y_mel = mel_spectrogram_torch(
        y.squeeze(1).float(), n_fft, n_mels, sample_rate,
        hop_length, win_length, fmin, fmax
    )
    y_hat_mel = mel_spectrogram_torch(
        y_hat.squeeze(1).float(), n_fft, n_mels, sample_rate,
        hop_length, win_length, fmin, fmax
    )
    return F.l1_loss(y_mel, y_hat_mel)


# ─── Convenience: Tổng hợp tất cả losses ────────────────────────────────────

class LossTracker:
    """Theo dõi và tính trung bình các losses trong training."""

    def __init__(self):
        self._sums = {}
        self._counts = {}

    def update(self, **kwargs):
        for k, v in kwargs.items():
            if isinstance(v, torch.Tensor):
                v = v.item()
            self._sums[k] = self._sums.get(k, 0.0) + v
            self._counts[k] = self._counts.get(k, 0) + 1

    def average(self):
        return {k: self._sums[k] / self._counts[k] for k in self._sums}

    def reset(self):
        self._sums.clear()
        self._counts.clear()

    def __str__(self):
        avgs = self.average()
        return ' | '.join(f'{k}: {v:.4f}' for k, v in avgs.items())
