"""
Stochastic Duration Predictor với Adversarial Learning (VITS2)

Cải tiến so với VITS1:
- Flow-based → adversarial GAN-based
- Time step-wise discriminator
- Train riêng biệt (last 30k steps) → nhanh hơn 20%
- Ablation: +0.14 MOS so với deterministic predictor
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn import Conv1d


class DilatedDepthSepConv(nn.Module):
    """Dilated depth-separable convolution block."""

    def __init__(self, channels, kernel_size, dilation):
        super().__init__()
        padding = (kernel_size - 1) * dilation // 2
        self.depthwise = Conv1d(channels, channels, kernel_size,
                                dilation=dilation, padding=padding,
                                groups=channels)
        self.pointwise = Conv1d(channels, channels, 1)
        self.norm = nn.LayerNorm(channels)

    def forward(self, x, x_mask):
        residual = x
        x = self.depthwise(x * x_mask)
        x = self.pointwise(x)
        x = F.mish(self.norm(x.mT).mT)
        return (x + residual) * x_mask


class DurationGenerator(nn.Module):
    """
    Generator G(z_d, h_text) → predicted duration d_hat.
    Input: h_text (text hidden), Gaussian noise z_d
    Output: duration per token (log scale)
    """

    def __init__(self, in_channels, hidden_channels, kernel_size, p_dropout,
                 n_flows=4, gin_channels=0):
        super().__init__()
        self.in_channels = in_channels
        self.hidden_channels = hidden_channels
        self.n_flows = n_flows

        self.pre = Conv1d(in_channels, hidden_channels, 1)
        self.drop = nn.Dropout(p_dropout)

        # Noise conditioning
        self.noise_proj = Conv1d(1, hidden_channels, 1)

        # Dilated convolution stack
        self.convs = nn.ModuleList([
            DilatedDepthSepConv(hidden_channels, kernel_size, 2 ** i)
            for i in range(4)
        ])

        if gin_channels != 0:
            self.cond = Conv1d(gin_channels, hidden_channels, 1)

        self.proj = Conv1d(hidden_channels, 1, 1)

    def forward(self, x, x_mask, z=None, g=None):
        """
        Args:
            x: h_text [B, C, T]
            x_mask: [B, 1, T]
            z: Gaussian noise [B, 1, T] — nếu None thì sample
            g: speaker embedding [B, G, 1]
        Returns:
            logw_hat: predicted log-duration [B, 1, T]
        """
        x = self.pre(x)
        if g is not None:
            x = x + self.cond(g)

        if z is None:
            z = torch.randn_like(x[:, :1, :])
        z_embed = self.noise_proj(z)
        x = x + z_embed

        for conv in self.convs:
            x = conv(x, x_mask)
            x = self.drop(x)

        logw_hat = self.proj(x) * x_mask
        return logw_hat


class TimeStepWiseDiscriminator(nn.Module):
    """
    Time step-wise discriminator D(d, h_text).
    Phân biệt real duration (từ MAS) vs predicted duration,
    cho TỪNG TOKEN riêng lẻ — xử lý được sequence có độ dài thay đổi.
    """

    def __init__(self, in_channels, hidden_channels, kernel_size, gin_channels=0):
        super().__init__()
        self.pre = Conv1d(in_channels + 1, hidden_channels, 1)  # +1 cho duration

        self.convs = nn.ModuleList([
            nn.Sequential(
                Conv1d(hidden_channels, hidden_channels, kernel_size,
                       padding=kernel_size // 2),
                nn.LeakyReLU(0.2),
            )
            for _ in range(3)
        ])

        if gin_channels != 0:
            self.cond = Conv1d(gin_channels, hidden_channels, 1)

        self.proj = Conv1d(hidden_channels, 1, 1)

    def forward(self, d, h_text, x_mask, g=None):
        """
        Args:
            d: duration values [B, 1, T] (log scale)
            h_text: text hidden [B, C, T]
            x_mask: [B, 1, T]
            g: speaker embedding
        Returns:
            score: [B, 1, T] — per-token real/fake score
        """
        x = torch.cat([h_text, d], dim=1)
        x = self.pre(x)
        if g is not None:
            x = x + self.cond(g)
        for conv in self.convs:
            x = conv(x) * x_mask
        return self.proj(x) * x_mask


class StochasticDurationPredictor(nn.Module):
    """
    Stochastic Duration Predictor (VITS2 main improvement).

    Training:
        - Generator dự đoán duration từ h_text + noise
        - Discriminator phân biệt real (MAS) vs predicted
        - Loss: least-squares GAN + MSE

    Inference:
        - Chỉ dùng Generator (reverse=True)
        - noise_scale điều chỉnh variability
    """

    is_stochastic = True

    def __init__(self, in_channels, hidden_channels, kernel_size, p_dropout,
                 n_flows=4, gin_channels=0):
        super().__init__()
        self.generator = DurationGenerator(
            in_channels, hidden_channels, kernel_size, p_dropout,
            n_flows, gin_channels
        )
        self.discriminator = TimeStepWiseDiscriminator(
            in_channels, hidden_channels, kernel_size, gin_channels
        )

    def forward(self, x, x_mask, w=None, g=None, reverse=False, noise_scale=1.0):
        """
        Training: x, x_mask, w (real duration từ MAS), g
                  → trả về generator loss scalar
        Inference: x, x_mask, g, reverse=True
                  → trả về predicted log-duration
        """
        if reverse:
            # Inference mode
            z = torch.randn_like(x[:, :1, :]) * noise_scale
            logw = self.generator(x, x_mask, z=z, g=g)
            return logw

        # Training mode
        assert w is not None, "w (real duration) required for training"

        # Generator prediction
        z_d = torch.randn_like(x[:, :1, :])
        logw_hat = self.generator(x, x_mask, z=z_d, g=g)

        # Real duration (log scale, từ MAS)
        logw = torch.log(w + 1e-6) * x_mask

        # Discriminator scores
        score_real = self.discriminator(logw.detach(), x.detach(), x_mask, g=g.detach() if g is not None else None)
        score_fake = self.discriminator(logw_hat.detach(), x.detach(), x_mask, g=g.detach() if g is not None else None)

        # Least-squares GAN loss (Mao et al., 2017)
        _loss_d = torch.mean((score_real - 1) ** 2) + torch.mean(score_fake ** 2)

        # Generator adversarial loss
        score_fake_g = self.discriminator(logw_hat, x, x_mask, g=g)
        loss_g_adv = torch.mean((score_fake_g - 1) ** 2)

        # MSE regularization
        loss_mse = F.mse_loss(logw_hat * x_mask, logw * x_mask)

        # Tổng loss (trả về cho training loop)
        # loss_dur = loss_g_adv + loss_mse (generator)
        # loss_disc_dur = loss_d (discriminator)
        total_gen_loss = (loss_g_adv + loss_mse) / torch.sum(x_mask)

        return total_gen_loss

    def get_discriminator_loss(self, x, x_mask, w, g=None):
        """Lấy discriminator loss riêng (cần optimizer riêng)."""
        logw_hat = self.generator(x, x_mask, g=g).detach()
        logw = torch.log(w + 1e-6) * x_mask

        score_real = self.discriminator(logw, x, x_mask, g=g)
        score_fake = self.discriminator(logw_hat, x, x_mask, g=g)

        loss_d = torch.mean((score_real - 1) ** 2) + torch.mean(score_fake ** 2)
        return loss_d
