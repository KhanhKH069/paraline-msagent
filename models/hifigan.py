"""
HiFi-GAN Generator — Decoder của VITS2
Chuyển latent z → raw audio waveform 22050 Hz
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn import Conv1d, ConvTranspose1d, Conv2d
from torch.nn.utils import weight_norm, remove_weight_norm, spectral_norm


LRELU_SLOPE = 0.1


def init_weights(m, mean=0.0, std=0.01):
    if isinstance(m, (Conv1d, ConvTranspose1d)):
        m.weight.data.normal_(mean, std)


def get_padding(kernel_size, dilation=1):
    return int((kernel_size * dilation - dilation) / 2)


class ResBlock1(nn.Module):
    """Multi-receptive field fusion residual block (Type 1)."""

    def __init__(self, channels, kernel_size=3, dilation=(1, 3, 5)):
        super().__init__()
        self.convs1 = nn.ModuleList([
            weight_norm(Conv1d(channels, channels, kernel_size, 1,
                               dilation=d, padding=get_padding(kernel_size, d)))
            for d in dilation
        ])
        self.convs2 = nn.ModuleList([
            weight_norm(Conv1d(channels, channels, kernel_size, 1,
                               dilation=1, padding=get_padding(kernel_size, 1)))
            for _ in dilation
        ])
        self.convs1.apply(init_weights)
        self.convs2.apply(init_weights)

    def forward(self, x, x_mask=None):
        for c1, c2 in zip(self.convs1, self.convs2):
            xt = F.leaky_relu(x, LRELU_SLOPE)
            xt = c1(xt)
            if x_mask is not None:
                xt = xt * x_mask
            xt = F.leaky_relu(xt, LRELU_SLOPE)
            xt = c2(xt)
            if x_mask is not None:
                xt = xt * x_mask
            x = xt + x
        if x_mask is not None:
            x = x * x_mask
        return x

    def remove_weight_norm(self):
        for layer in self.convs1 + self.convs2:
            remove_weight_norm(layer)


class ResBlock2(nn.Module):
    """Multi-receptive field fusion residual block (Type 2)."""

    def __init__(self, channels, kernel_size=3, dilation=(1, 3)):
        super().__init__()
        self.convs = nn.ModuleList([
            weight_norm(Conv1d(channels, channels, kernel_size, 1,
                               dilation=d, padding=get_padding(kernel_size, d)))
            for d in dilation
        ])
        self.convs.apply(init_weights)

    def forward(self, x, x_mask=None):
        for c in self.convs:
            xt = F.leaky_relu(x, LRELU_SLOPE)
            xt = c(xt)
            if x_mask is not None:
                xt = xt * x_mask
            x = xt + x
        if x_mask is not None:
            x = x * x_mask
        return x

    def remove_weight_norm(self):
        for layer in self.convs:
            remove_weight_norm(layer)


class Generator(nn.Module):
    """
    HiFi-GAN Generator.
    Upsample latent z từ mel-frame rate lên audio sample rate.

    Mặc định:
      upsample_rates = [8, 8, 2, 2]  → tổng upscale = 256
      Với hop_length=256, 22050Hz → mel rate ~86 frames/s

    Kiến trúc:
      Conv → [Upsample → MRF residual block] × 4 → Conv → Tanh
    """

    def __init__(
        self,
        initial_channel,
        resblock,
        resblock_kernel_sizes,
        resblock_dilation_sizes,
        upsample_rates,
        upsample_initial_channel,
        upsample_kernel_sizes,
        gin_channels=0,
    ):
        super().__init__()
        self.num_kernels = len(resblock_kernel_sizes)
        self.num_upsamples = len(upsample_rates)

        self.conv_pre = weight_norm(Conv1d(
            initial_channel, upsample_initial_channel, 7, 1, padding=3
        ))

        resblock_cls = ResBlock1 if resblock == '1' else ResBlock2

        self.ups = nn.ModuleList()
        self.resblocks = nn.ModuleList()

        for i, (u, k) in enumerate(zip(upsample_rates, upsample_kernel_sizes)):
            ch = upsample_initial_channel // (2 ** (i + 1))
            self.ups.append(weight_norm(ConvTranspose1d(
                ch * 2, ch, k, u, padding=(k - u) // 2
            )))
            for j, (k_r, d_r) in enumerate(zip(resblock_kernel_sizes, resblock_dilation_sizes)):
                self.resblocks.append(resblock_cls(ch, k_r, d_r))

        self.conv_post = weight_norm(Conv1d(ch, 1, 7, 1, padding=3, bias=False))

        self.ups.apply(init_weights)
        self.conv_post.apply(init_weights)

        if gin_channels != 0:
            self.cond = Conv1d(gin_channels, upsample_initial_channel, 1)

    def forward(self, x, g=None):
        """
        Args:
            x: latent z [B, inter_channels, T_mel]
            g: speaker embedding [B, gin_channels, 1]
        Returns:
            audio: [B, 1, T_audio]
        """
        x = self.conv_pre(x)
        if g is not None:
            x = x + self.cond(g)

        for i, up in enumerate(self.ups):
            x = F.leaky_relu(x, LRELU_SLOPE)
            x = up(x)

            xs = None
            for j in range(self.num_kernels):
                if xs is None:
                    xs = self.resblocks[i * self.num_kernels + j](x)
                else:
                    xs += self.resblocks[i * self.num_kernels + j](x)
            x = xs / self.num_kernels

        x = F.leaky_relu(x)
        x = self.conv_post(x)
        x = torch.tanh(x)

        return x

    def remove_weight_norm(self):
        for layer in self.ups:
            remove_weight_norm(layer)
        for layer in self.resblocks:
            layer.remove_weight_norm()
        remove_weight_norm(self.conv_pre)
        remove_weight_norm(self.conv_post)


# ─── Multi-Period Discriminator (dùng trong training) ────────────────────────

class DiscriminatorP(nn.Module):
    """Period discriminator."""

    def __init__(self, period, kernel_size=5, stride=3, use_spectral_norm=False):
        super().__init__()
        self.period = period
        norm_f = spectral_norm if use_spectral_norm else weight_norm


        self.convs = nn.ModuleList([
            norm_f(Conv2d(1, 32, (kernel_size, 1), (stride, 1), padding=(get_padding(kernel_size, 1), 0))),
            norm_f(Conv2d(32, 128, (kernel_size, 1), (stride, 1), padding=(get_padding(kernel_size, 1), 0))),
            norm_f(Conv2d(128, 512, (kernel_size, 1), (stride, 1), padding=(get_padding(kernel_size, 1), 0))),
            norm_f(Conv2d(512, 1024, (kernel_size, 1), (stride, 1), padding=(get_padding(kernel_size, 1), 0))),
            norm_f(Conv2d(1024, 1024, (kernel_size, 1), 1, padding=(get_padding(kernel_size, 1), 0))),
        ])
        self.conv_post = norm_f(Conv2d(1024, 1, (3, 1), 1, padding=(1, 0)))

    def forward(self, x):
        fmap = []
        b, c, t = x.shape
        if t % self.period != 0:
            n_pad = self.period - (t % self.period)
            x = F.pad(x, (0, n_pad), 'reflect')
        x = x.view(b, c, -1, self.period)

        for layer in self.convs:
            x = layer(x)
            x = F.leaky_relu(x, LRELU_SLOPE)
            fmap.append(x)
        x = self.conv_post(x)
        fmap.append(x)
        x = torch.flatten(x, 1, -1)
        return x, fmap


class MultiPeriodDiscriminator(nn.Module):
    """MPD: kết hợp nhiều period discriminators."""

    def __init__(self, use_spectral_norm=False):
        super().__init__()
        periods = [2, 3, 5, 7, 11]
        self.discriminators = nn.ModuleList([
            DiscriminatorP(p, use_spectral_norm=use_spectral_norm) for p in periods
        ])

    def forward(self, y, y_hat):
        y_d_rs, y_d_gs, fmap_rs, fmap_gs = [], [], [], []
        for d in self.discriminators:
            y_d_r, fmap_r = d(y)
            y_d_g, fmap_g = d(y_hat)
            y_d_rs.append(y_d_r)
            y_d_gs.append(y_d_g)
            fmap_rs.append(fmap_r)
            fmap_gs.append(fmap_g)
        return y_d_rs, y_d_gs, fmap_rs, fmap_gs
