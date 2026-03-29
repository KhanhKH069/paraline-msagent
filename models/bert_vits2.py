"""
Vietnamese Bert-VITS2 — Main Model Architecture
Dựa trên paper: VITS2 (Kong et al., 2023) + PhoBERT integration
"""

import math
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn import Conv1d
from torch.nn.utils import weight_norm, remove_weight_norm

from models.text_encoder import TextEncoder
from models.duration_predictor import StochasticDurationPredictor
from models.normalizing_flows import ResidualCouplingTransformers
from models.hifigan import Generator as HiFiGANGenerator


# ─── Posterior Encoder (dùng lúc training) ───────────────────────────────────

class PosteriorEncoder(nn.Module):
    """
    Encode mel-spectrogram → latent posterior distribution q(z|x).
    Dùng WaveNet-style dilated convolutions.
    """

    def __init__(self, in_channels, inter_channels, hidden_channels,
                 kernel_size, dilation_rate, n_layers, gin_channels=0):
        super().__init__()
        self.in_channels = in_channels
        self.inter_channels = inter_channels
        self.hidden_channels = hidden_channels
        self.kernel_size = kernel_size
        self.dilation_rate = dilation_rate
        self.n_layers = n_layers
        self.gin_channels = gin_channels

        self.pre = Conv1d(in_channels, hidden_channels, 1)
        self.enc = WaveNet(
            hidden_channels, kernel_size, dilation_rate, n_layers,
            gin_channels=gin_channels
        )
        self.proj = Conv1d(hidden_channels, inter_channels * 2, 1)

    def forward(self, x, x_lengths, g=None):
        x_mask = sequence_mask(x_lengths, x.size(2)).unsqueeze(1).to(x.dtype)
        x = self.pre(x) * x_mask
        x = self.enc(x, x_mask, g=g)
        stats = self.proj(x) * x_mask
        m, logs = torch.split(stats, self.inter_channels, dim=1)
        z = (m + torch.randn_like(m) * torch.exp(logs)) * x_mask
        return z, m, logs, x_mask


# ─── WaveNet (dùng trong Posterior Encoder) ──────────────────────────────────

class WaveNet(nn.Module):
    """Dilated causal WaveNet-style residual network."""

    def __init__(self, hidden_channels, kernel_size, dilation_rate, n_layers,
                 gin_channels=0, p_dropout=0.0):
        super().__init__()
        self.hidden_channels = hidden_channels
        self.kernel_size = kernel_size
        self.dilation_rate = dilation_rate
        self.n_layers = n_layers
        self.gin_channels = gin_channels

        self.in_layers = nn.ModuleList()
        self.res_skip_layers = nn.ModuleList()
        self.drop = nn.Dropout(p_dropout)

        if gin_channels != 0:
            self.cond_layer = weight_norm(Conv1d(gin_channels, 2 * hidden_channels * n_layers, 1))

        for i in range(n_layers):
            dilation = dilation_rate ** i
            padding = int((kernel_size * dilation - dilation) / 2)
            in_layer = weight_norm(Conv1d(
                hidden_channels, 2 * hidden_channels, kernel_size,
                dilation=dilation, padding=padding
            ))
            self.in_layers.append(in_layer)

            if i < n_layers - 1:
                res_skip_channels = 2 * hidden_channels
            else:
                res_skip_channels = hidden_channels
            res_skip_layer = weight_norm(Conv1d(hidden_channels, res_skip_channels, 1))
            self.res_skip_layers.append(res_skip_layer)

    def forward(self, x, x_mask, g=None, **kwargs):
        output = torch.zeros_like(x)
        n_channels_tensor = torch.IntTensor([self.hidden_channels])

        if g is not None:
            g = self.cond_layer(g)

        for i in range(self.n_layers):
            x_in = self.in_layers[i](x)
            if g is not None:
                cond_offset = i * 2 * self.hidden_channels
                g_l = g[:, cond_offset:cond_offset + 2 * self.hidden_channels, :]
            else:
                g_l = torch.zeros_like(x_in)

            acts = fused_add_tanh_sigmoid_multiply(x_in, g_l, n_channels_tensor)
            acts = self.drop(acts)
            res_skip_acts = self.res_skip_layers[i](acts)

            if i < self.n_layers - 1:
                res_acts = res_skip_acts[:, :self.hidden_channels, :]
                x = (x + res_acts) * x_mask
                output = output + res_skip_acts[:, self.hidden_channels:, :]
            else:
                output = output + res_skip_acts
        return output * x_mask

    def remove_weight_norm(self):
        if self.gin_channels != 0:
            remove_weight_norm(self.cond_layer)
        for layer in self.in_layers:
            remove_weight_norm(layer)
        for layer in self.res_skip_layers:
            remove_weight_norm(layer)


# ─── Model chính: SynthesizerTrn ─────────────────────────────────────────────

class SynthesizerTrn(nn.Module):
    """
    Vietnamese Bert-VITS2 Synthesizer (Training mode).

    Kiến trúc:
      - TextEncoder (speaker-conditioned, PhoBERT embeddings)
      - StochasticDurationPredictor (adversarial learning)
      - ResidualCouplingTransformers (normalizing flows + transformer block)
      - PosteriorEncoder (chỉ dùng lúc training)
      - HiFiGAN Generator (decoder)
    """

    def __init__(
        self,
        n_vocab,
        spec_channels,
        segment_size,
        inter_channels,
        hidden_channels,
        filter_channels,
        n_heads,
        n_layers,
        kernel_size,
        p_dropout,
        resblock,
        resblock_kernel_sizes,
        resblock_dilation_sizes,
        upsample_rates,
        upsample_initial_channel,
        upsample_kernel_sizes,
        n_speakers=0,
        gin_channels=0,
        use_phobert=True,
        phobert_model="vinai/phobert-base-v2",
        use_transformer_flows=True,
        use_stochastic_dur_pred=True,
        use_speaker_conditioned_encoder=False,
        **kwargs
    ):
        super().__init__()

        self.n_vocab = n_vocab
        self.spec_channels = spec_channels
        self.inter_channels = inter_channels
        self.hidden_channels = hidden_channels
        self.filter_channels = filter_channels
        self.n_heads = n_heads
        self.n_layers = n_layers
        self.kernel_size = kernel_size
        self.p_dropout = p_dropout
        self.resblock = resblock
        self.resblock_kernel_sizes = resblock_kernel_sizes
        self.resblock_dilation_sizes = resblock_dilation_sizes
        self.upsample_rates = upsample_rates
        self.upsample_initial_channel = upsample_initial_channel
        self.upsample_kernel_sizes = upsample_kernel_sizes
        self.segment_size = segment_size
        self.n_speakers = n_speakers
        self.gin_channels = gin_channels
        self.use_phobert = use_phobert

        # Text Encoder với PhoBERT
        self.enc_p = TextEncoder(
            n_vocab,
            inter_channels,
            hidden_channels,
            filter_channels,
            n_heads,
            n_layers,
            kernel_size,
            p_dropout,
            gin_channels=gin_channels if use_speaker_conditioned_encoder else 0,
            use_phobert=use_phobert,
            phobert_model=phobert_model,
        )

        # HiFi-GAN Decoder
        self.dec = HiFiGANGenerator(
            inter_channels, resblock, resblock_kernel_sizes,
            resblock_dilation_sizes, upsample_rates, upsample_initial_channel,
            upsample_kernel_sizes, gin_channels=gin_channels
        )

        # Posterior Encoder (training only)
        self.enc_q = PosteriorEncoder(
            spec_channels, inter_channels, hidden_channels,
            5, 1, 16, gin_channels=gin_channels
        )

        # Normalizing Flows với Transformer Block (VITS2 cải tiến)
        self.flow = ResidualCouplingTransformers(
            inter_channels, hidden_channels, 5, 1, 4,
            gin_channels=gin_channels,
            use_transformer_flows=use_transformer_flows
        )

        # Duration Predictor
        if use_stochastic_dur_pred:
            self.dp = StochasticDurationPredictor(
                hidden_channels, 192, 3, 0.5, 4, gin_channels=gin_channels
            )
        else:
            self.dp = DeterministicDurationPredictor(
                hidden_channels, 256, 3, 0.5, gin_channels=gin_channels
            )

        # Speaker embedding (multi-speaker)
        if n_speakers > 1:
            self.emb_g = nn.Embedding(n_speakers, gin_channels)

    def forward(self, x, x_lengths, y, y_lengths, sid=None, bert_feats=None):
        """
        Training forward pass.

        Args:
            x: phoneme token ids [B, T_text]
            x_lengths: độ dài text [B]
            y: mel-spectrogram [B, n_mel, T_mel]
            y_lengths: độ dài mel [B]
            sid: speaker id [B] (multi-speaker)
            bert_feats: PhoBERT features [B, T_text, 768]
        """
        # Speaker embedding
        g = None
        if self.n_speakers > 1 and sid is not None:
            g = self.emb_g(sid).unsqueeze(-1)  # [B, gin_channels, 1]

        # Text encoding
        x, m_p, logs_p, x_mask = self.enc_p(x, x_lengths, g=g, bert_feats=bert_feats)

        # Posterior encoding từ mel
        z, m_q, logs_q, y_mask = self.enc_q(y, y_lengths, g=g)

        # Normalizing flows: posterior → prior
        z_p = self.flow(z, y_mask, g=g)

        # Monotonic Alignment Search
        with torch.no_grad():
            s_p_sq_r = torch.exp(-2 * logs_p)
            neg_cent1 = torch.sum(-0.5 * math.log(2 * math.pi) - logs_p, [1], keepdim=True)
            neg_cent2 = torch.matmul(-0.5 * (z_p ** 2).mT, s_p_sq_r)
            neg_cent3 = torch.matmul(z_p.mT, (m_p * s_p_sq_r))
            neg_cent4 = torch.sum(-0.5 * (m_p ** 2) * s_p_sq_r, [1], keepdim=True)
            neg_cent = neg_cent1 + neg_cent2 + neg_cent3 + neg_cent4

            # Gaussian noise cho MAS (VITS2 improvement)
            epsilon = torch.std(neg_cent) * torch.randn_like(neg_cent) * 0.01
            neg_cent = neg_cent + epsilon

            attn_mask = torch.unsqueeze(x_mask, 2) * torch.unsqueeze(y_mask, -1)
            from utils.monotonic_align import maximum_path
            attn = maximum_path(neg_cent, attn_mask.squeeze(1)).unsqueeze(1).detach()

        # Duration từ attention
        w = attn.sum(2)

        # Duration predictor loss
        if hasattr(self.dp, 'is_stochastic') and self.dp.is_stochastic:
            l_length = self.dp(x, x_mask, w, g=g)
            l_length = l_length / torch.sum(x_mask)
        else:
            logw_ = torch.log(w + 1e-6) * x_mask
            logw = self.dp(x, x_mask, g=g)
            l_length = torch.sum((logw - logw_) ** 2, [1, 2]) / torch.sum(x_mask)

        # Project text → mel frame
        m_p = torch.matmul(attn.squeeze(1), m_p.mT).mT
        logs_p = torch.matmul(attn.squeeze(1), logs_p.mT).mT

        # Slice segment for decoder
        z_slice, ids_slice = rand_slice_segments(z, y_lengths, self.segment_size)
        o = self.dec(z_slice, g=g)

        return o, l_length, attn, ids_slice, x_mask, y_mask, (z, z_p, m_p, logs_p, m_q, logs_q)

    @torch.no_grad()
    def infer(self, x, x_lengths, sid=None, bert_feats=None, noise_scale=0.667,
              length_scale=1.0, noise_scale_w=0.8, max_len=None):
        """
        Inference forward pass.

        Returns:
            o: audio waveform [B, 1, T_audio]
            attn: alignment map
            y_mask: output mask
        """
        g = None
        if self.n_speakers > 1 and sid is not None:
            g = self.emb_g(sid).unsqueeze(-1)

        x, m_p, logs_p, x_mask = self.enc_p(x, x_lengths, g=g, bert_feats=bert_feats)

        # Duration prediction
        logw = self.dp(x, x_mask, g=g, reverse=True, noise_scale=noise_scale_w)
        w = torch.exp(logw) * x_mask * length_scale
        w_ceil = torch.ceil(w)

        y_lengths = torch.clamp_min(torch.sum(w_ceil, [1, 2]), 1).long()
        y_mask = sequence_mask(y_lengths, None).to(x_mask.dtype)
        attn_mask = torch.unsqueeze(x_mask, 2) * torch.unsqueeze(y_mask, -1)
        attn = generate_path(w_ceil, attn_mask)

        m_p = torch.matmul(attn.squeeze(1), m_p.mT).mT
        logs_p = torch.matmul(attn.squeeze(1), logs_p.mT).mT

        z_p = m_p + torch.randn_like(m_p) * torch.exp(logs_p) * noise_scale
        z = self.flow(z_p, y_mask, g=g, reverse=True)
        o = self.dec((z * y_mask)[:, :, :max_len], g=g)

        return o, attn, y_mask, (z, z_p, m_p, logs_p)


# ─── Utilities ───────────────────────────────────────────────────────────────

def sequence_mask(length, max_length=None):
    if max_length is None:
        max_length = length.max()
    x = torch.arange(max_length, dtype=length.dtype, device=length.device)
    return x.unsqueeze(0) < length.unsqueeze(1)


def rand_slice_segments(x, x_lengths=None, segment_size=4):
    b, d, t = x.size()
    if x_lengths is None:
        x_lengths = t
    ids_str_max = torch.clamp(x_lengths - segment_size + 1, min=0)
    ids_str = (torch.rand([b]).to(device=x.device) * ids_str_max).to(dtype=torch.long)
    ret = slice_segments(x, ids_str, segment_size)
    return ret, ids_str


def slice_segments(x, ids_str, segment_size):
    gather_indices = ids_str.view(x.size(0), 1, 1).repeat(1, x.size(1), 1)
    gather_indices = gather_indices + torch.arange(segment_size, device=x.device).view(1, 1, -1)
    return torch.gather(x, 2, gather_indices)


def generate_path(duration, mask):
    b, _, t_y, t_x = mask.shape
    cum_duration = torch.cumsum(duration, -1)
    cum_duration_flat = cum_duration.view(b * t_x)
    path = sequence_mask(cum_duration_flat, t_y).to(mask.dtype)
    path = path.view(b, t_x, t_y)
    path = path - F.pad(path, [0, 0, 1, 0, 0, 0])[:, :-1]
    path = path.unsqueeze(1).mT * mask
    return path


def fused_add_tanh_sigmoid_multiply(input_a, input_b, n_channels):
    n_channels_int = n_channels[0]
    in_act = input_a + input_b
    t_act = torch.tanh(in_act[:, :n_channels_int, :])
    s_act = torch.sigmoid(in_act[:, n_channels_int:, :])
    acts = t_act * s_act
    return acts


class DeterministicDurationPredictor(nn.Module):
    """Fallback: deterministic duration predictor (L2 loss)."""
    is_stochastic = False

    def __init__(self, in_channels, filter_channels, kernel_size, p_dropout, gin_channels=0):
        super().__init__()
        self.drop = nn.Dropout(p_dropout)
        self.conv_1 = Conv1d(in_channels, filter_channels, kernel_size, padding=kernel_size // 2)
        self.norm_1 = nn.LayerNorm(filter_channels)
        self.conv_2 = Conv1d(filter_channels, filter_channels, kernel_size, padding=kernel_size // 2)
        self.norm_2 = nn.LayerNorm(filter_channels)
        self.proj = Conv1d(filter_channels, 1, 1)
        if gin_channels != 0:
            self.cond = Conv1d(gin_channels, in_channels, 1)

    def forward(self, x, x_mask, g=None, reverse=False, **kwargs):
        x = torch.detach(x)
        if g is not None:
            g = torch.detach(g)
            x = x + self.cond(g)
        x = self.conv_1(x * x_mask)
        x = torch.relu(self.norm_1(x.mT).mT)
        x = self.drop(x)
        x = self.conv_2(x * x_mask)
        x = torch.relu(self.norm_2(x.mT).mT)
        x = self.drop(x)
        x = self.proj(x * x_mask)
        return x * x_mask
