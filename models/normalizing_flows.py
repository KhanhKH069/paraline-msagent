"""
Normalizing Flows với Transformer Block (VITS2)

Cải tiến so với VITS1:
- Thêm transformer block (small) vào mỗi coupling layer
- Transformer nắm bắt long-term dependency — convolution không làm được
- Ablation: +0.06 MOS
- Hình 2 trong paper: attention map cho thấy transformer thu thập
  thông tin từ vị trí xa, ngoài receptive field của convolution
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn import Conv1d


# ─── Transformer block nhỏ cho Flows ─────────────────────────────────────────

class SmallTransformerBlock(nn.Module):
    """
    Transformer block nhỏ dùng trong Normalizing Flows.
    'Small' nghĩa là: ít head, không có FFN phức tạp.
    Mục đích: capture long-range dependency mà convolution bỏ qua.
    """

    def __init__(self, channels, n_heads=2, p_dropout=0.0):
        super().__init__()
        assert channels % n_heads == 0
        self.n_heads = n_heads
        self.d_k = channels // n_heads

        self.q = Conv1d(channels, channels, 1)
        self.k = Conv1d(channels, channels, 1)
        self.v = Conv1d(channels, channels, 1)
        self.out = Conv1d(channels, channels, 1)
        self.norm = nn.LayerNorm(channels)
        self.drop = nn.Dropout(p_dropout)

    def forward(self, x, x_mask=None):
        B, C, T = x.shape
        residual = x

        # Multi-head attention
        q = self.q(x).view(B, self.n_heads, self.d_k, T).transpose(2, 3)
        k = self.k(x).view(B, self.n_heads, self.d_k, T).transpose(2, 3)
        v = self.v(x).view(B, self.n_heads, self.d_k, T).transpose(2, 3)

        scores = torch.matmul(q, k.transpose(-2, -1)) / (self.d_k ** 0.5)
        if x_mask is not None:
            mask = x_mask.squeeze(1)  # [B, T]
            scores = scores.masked_fill(
                mask.unsqueeze(1).unsqueeze(2) == 0, -1e4
            )
        attn = F.softmax(scores, dim=-1)
        attn = self.drop(attn)

        out = torch.matmul(attn, v)  # [B, heads, T, d_k]
        out = out.transpose(2, 3).contiguous().view(B, C, T)
        out = self.out(out)

        # Residual + LayerNorm
        x = self.norm((residual + out).mT).mT
        if x_mask is not None:
            x = x * x_mask
        return x


# ─── WaveNet Convolution Block ───────────────────────────────────────────────

class ConvBlock(nn.Module):
    """Dilated convolution block (giữ nguyên từ VITS1)."""

    def __init__(self, channels, kernel_size=5, dilation_rate=1, n_layers=4,
                 gin_channels=0, p_dropout=0.0):
        super().__init__()
        self.n_layers = n_layers
        self.in_layers = nn.ModuleList()
        self.res_skip_layers = nn.ModuleList()
        self.drop = nn.Dropout(p_dropout)

        if gin_channels:
            self.cond = Conv1d(gin_channels, channels * 2 * n_layers, 1)

        for i in range(n_layers):
            dil = dilation_rate ** i
            pad = (kernel_size * dil - dil) // 2
            self.in_layers.append(
                Conv1d(channels, 2 * channels, kernel_size, dilation=dil, padding=pad)
            )
            self.res_skip_layers.append(
                Conv1d(channels, channels * (2 if i < n_layers - 1 else 1), 1)
            )

    def forward(self, x, x_mask, g=None):
        output = torch.zeros_like(x)
        h = self.n_layers

        g_expanded = self.cond(g) if g is not None and hasattr(self, 'cond') else None

        for i, (in_l, rs_l) in enumerate(zip(self.in_layers, self.res_skip_layers)):
            x_in = in_l(x)
            if g_expanded is not None:
                cond_offset = i * 2 * x.size(1)
                x_in = x_in + g_expanded[:, cond_offset:cond_offset + 2 * x.size(1), :]

            # Gated activation
            acts = torch.tanh(x_in[:, :x.size(1), :]) * torch.sigmoid(x_in[:, x.size(1):, :])
            acts = self.drop(acts)
            rs = rs_l(acts)

            if i < h - 1:
                x = (x + rs[:, :x.size(1), :]) * x_mask
                output = output + rs[:, x.size(1):, :]
            else:
                output = output + rs

        return output * x_mask


# ─── Coupling Layer với Transformer Block ────────────────────────────────────

class TransformerCouplingLayer(nn.Module):
    """
    Residual coupling layer (VITS2):
    - Convolution block (local patterns)
    - + Small transformer block (long-range patterns)
    - Residual connection

    x = [x_0, x_1] split
    x_1' = x_1 * exp(s(x_0)) + t(x_0)
    output = [x_0, x_1']
    """

    def __init__(self, channels, hidden_channels, kernel_size, dilation_rate,
                 n_layers, gin_channels=0, mean_only=False,
                 use_transformer=True, n_heads=2):
        super().__init__()
        assert channels % 2 == 0
        self.channels = channels
        self.hidden_channels = hidden_channels
        self.half_channels = channels // 2
        self.mean_only = mean_only
        self.use_transformer = use_transformer

        self.pre = Conv1d(self.half_channels, hidden_channels, 1)
        self.conv_block = ConvBlock(
            hidden_channels, kernel_size, dilation_rate, n_layers, gin_channels
        )

        if use_transformer:
            self.transformer = SmallTransformerBlock(hidden_channels, n_heads)

        self.post = Conv1d(
            hidden_channels,
            self.half_channels * (1 if mean_only else 2),
            1
        )
        self.post.weight.data.zero_()
        self.post.bias.data.zero_()

    def forward(self, x, x_mask, g=None, reverse=False):
        x_0, x_1 = torch.split(x, self.half_channels, dim=1)

        h = self.pre(x_0)
        h = self.conv_block(h, x_mask, g=g)

        # Transformer block (VITS2 cải tiến)
        if self.use_transformer:
            h = self.transformer(h, x_mask)

        stats = self.post(h) * x_mask

        if not self.mean_only:
            m, log_s = torch.split(stats, self.half_channels, dim=1)
        else:
            m = stats
            log_s = torch.zeros_like(m)

        if not reverse:
            x_1 = m + x_1 * torch.exp(log_s) * x_mask
            x = torch.cat([x_0, x_1], dim=1)
            logdet = torch.sum(log_s, dim=[1, 2])
            return x, logdet
        else:
            x_1 = (x_1 - m) * torch.exp(-log_s) * x_mask
            x = torch.cat([x_0, x_1], dim=1)
            return x


class Flip(nn.Module):
    """Flip operation — đổi chiều channels (miễn phí về log-det)."""

    def forward(self, x, *args, reverse=False, **kwargs):
        x = torch.flip(x, [1])
        if not reverse:
            return x, torch.zeros(x.size(0)).to(dtype=x.dtype, device=x.device)
        return x


# ─── Main: Residual Coupling Transformers ─────────────────────────────────────

class ResidualCouplingTransformers(nn.Module):
    """
    Stack of coupling layers với transformer blocks xen kẽ.
    VITS2: n_flow_layer=4 coupling layers, mỗi layer có 1 transformer block.
    """

    def __init__(self, channels, hidden_channels, kernel_size, dilation_rate,
                 n_layers, n_flows=4, gin_channels=0, use_transformer_flows=True):
        super().__init__()
        self.channels = channels
        self.hidden_channels = hidden_channels
        self.n_layers = n_layers
        self.n_flows = n_flows

        self.flows = nn.ModuleList()
        for i in range(n_flows):
            self.flows.append(
                TransformerCouplingLayer(
                    channels, hidden_channels, kernel_size, dilation_rate,
                    n_layers, gin_channels=gin_channels, mean_only=True,
                    use_transformer=use_transformer_flows
                )
            )
            self.flows.append(Flip())

    def forward(self, x, x_mask, g=None, reverse=False):
        """
        forward: posterior → prior (training)
        reverse: prior → posterior (inference)
        """
        if not reverse:
            for flow in self.flows:
                x, _ = flow(x, x_mask, g=g, reverse=False)
        else:
            for flow in reversed(self.flows):
                x = flow(x, x_mask, g=g, reverse=True)
        return x
