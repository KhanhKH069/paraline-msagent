"""
Speaker-Conditioned Text Encoder với PhoBERT
Cải tiến từ VITS2: speaker vector conditioned tại transformer block thứ 3
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn import Conv1d


class MultiHeadAttention(nn.Module):
    """Multi-head self-attention với relative position encoding."""

    def __init__(self, channels, out_channels, n_heads, p_dropout=0.0, proximal_bias=False):
        super().__init__()
        assert channels % n_heads == 0, "channels phải chia hết cho n_heads"
        self.channels = channels
        self.out_channels = out_channels
        self.n_heads = n_heads
        self.p_dropout = p_dropout
        self.k_channels = channels // n_heads

        self.conv_q = Conv1d(channels, channels, 1)
        self.conv_k = Conv1d(channels, channels, 1)
        self.conv_v = Conv1d(channels, channels, 1)
        self.conv_o = Conv1d(channels, out_channels, 1)
        self.drop = nn.Dropout(p_dropout)

    def forward(self, x, c, attn_mask=None):
        q = self.conv_q(x)
        k = self.conv_k(c)
        v = self.conv_v(c)
        x, _ = self.attention(q, k, v, mask=attn_mask)
        x = self.conv_o(x)
        return x

    def attention(self, query, key, value, mask=None):
        b, d, t_s = key.size()
        t_t = query.size(2)
        query = query.view(b, self.n_heads, self.k_channels, t_t).transpose(2, 3)
        key = key.view(b, self.n_heads, self.k_channels, t_s).transpose(2, 3)
        value = value.view(b, self.n_heads, self.k_channels, t_s).transpose(2, 3)

        scores = torch.matmul(query / (self.k_channels ** 0.5), key.transpose(-2, -1))
        if mask is not None:
            scores = scores.masked_fill(mask == 0, -1e4)
        p_attn = F.softmax(scores, dim=-1)
        p_attn = self.drop(p_attn)
        output = torch.matmul(p_attn, value)
        output = output.transpose(2, 3).contiguous().view(b, d, t_t)
        return output, p_attn


class FFN(nn.Module):
    """Feed-forward network với convolution."""

    def __init__(self, in_channels, out_channels, filter_channels, kernel_size, p_dropout=0.0):
        super().__init__()
        self.conv_1 = Conv1d(in_channels, filter_channels, kernel_size, padding=kernel_size // 2)
        self.conv_2 = Conv1d(filter_channels, out_channels, kernel_size, padding=kernel_size // 2)
        self.drop = nn.Dropout(p_dropout)

    def forward(self, x, x_mask):
        x = self.conv_1(x * x_mask)
        x = torch.relu(x)
        x = self.drop(x)
        x = self.conv_2(x * x_mask)
        return x * x_mask


class TransformerBlock(nn.Module):
    """Một transformer block: self-attention + FFN + LayerNorm."""

    def __init__(self, hidden_channels, filter_channels, n_heads, kernel_size=1,
                 p_dropout=0.0, gin_channels=0):
        super().__init__()
        self.self_attn = MultiHeadAttention(hidden_channels, hidden_channels, n_heads, p_dropout)
        self.norm1 = nn.LayerNorm(hidden_channels)
        self.ffn = FFN(hidden_channels, hidden_channels, filter_channels, kernel_size, p_dropout)
        self.norm2 = nn.LayerNorm(hidden_channels)
        self.drop = nn.Dropout(p_dropout)

        # Speaker conditioning (VITS2 speaker-conditioned encoder)
        if gin_channels > 0:
            self.spk_cond = Conv1d(gin_channels, hidden_channels, 1)

    def forward(self, x, x_mask, g=None, attn_mask=None):
        # Speaker conditioning
        if g is not None and hasattr(self, 'spk_cond'):
            x = x + self.spk_cond(g)

        # Self-attention
        residual = x
        x = self.self_attn(x, x, attn_mask)
        x = self.drop(x)
        x = self.norm1((residual + x).mT).mT

        # FFN
        residual = x
        x = self.ffn(x, x_mask)
        x = self.drop(x)
        x = self.norm2((residual + x).mT).mT

        return x * x_mask


class PhoBERTFeatureExtractor(nn.Module):
    """
    Trích xuất semantic features từ PhoBERT.
    Freeze N layer đầu để tiết kiệm VRAM và tránh catastrophic forgetting.
    """

    def __init__(self, model_name: str = "vinai/phobert-base-v2",
                 freeze_layers: int = 8, output_dim: int = 192):
        super().__init__()
        try:
            from transformers import AutoModel
            self.bert = AutoModel.from_pretrained(model_name)
            bert_hidden = self.bert.config.hidden_size  # 768 cho base

            # Freeze N layer đầu
            if freeze_layers > 0:
                for i, layer in enumerate(self.bert.encoder.layer):
                    if i < freeze_layers:
                        for param in layer.parameters():
                            param.requires_grad = False
                # Luôn freeze embedding layer
                for param in self.bert.embeddings.parameters():
                    param.requires_grad = False

            # Project từ 768 → hidden_channels của VITS2
            self.proj = nn.Linear(bert_hidden, output_dim)
            self.available = True
            print(f"[PhoBERT] Loaded '{model_name}', frozen {freeze_layers} layers.")

        except ImportError:
            print("[PhoBERT] Warning: transformers not installed. PhoBERT disabled.")
            self.available = False
        except Exception as e:
            print(f"[PhoBERT] Warning: Failed to load PhoBERT: {e}")
            self.available = False

    def forward(self, input_ids, attention_mask=None):
        """
        Args:
            input_ids: [B, T] token ids từ PhoBERT tokenizer
            attention_mask: [B, T]
        Returns:
            features: [B, T, output_dim]
        """
        if not self.available:
            return None

        outputs = self.bert(input_ids=input_ids, attention_mask=attention_mask)
        hidden_states = outputs.last_hidden_state  # [B, T, 768]
        projected = self.proj(hidden_states)       # [B, T, output_dim]
        return projected


class TextEncoder(nn.Module):
    """
    Speaker-conditioned Text Encoder (VITS2).

    Pipeline:
      phoneme ids → embedding → transformer blocks → (m_p, logs_p)
      PhoBERT features được inject vào tại block thứ 3 (hoặc đầu)
    """

    def __init__(self, n_vocab, out_channels, hidden_channels, filter_channels,
                 n_heads, n_layers, kernel_size, p_dropout, gin_channels=0,
                 use_phobert=True, phobert_model="vinai/phobert-base-v2"):
        super().__init__()
        self.n_vocab = n_vocab
        self.out_channels = out_channels
        self.hidden_channels = hidden_channels
        self.filter_channels = filter_channels
        self.n_heads = n_heads
        self.n_layers = n_layers
        self.kernel_size = kernel_size
        self.p_dropout = p_dropout

        # Phoneme embedding
        self.emb = nn.Embedding(n_vocab, hidden_channels)
        nn.init.normal_(self.emb.weight, 0.0, hidden_channels ** -0.5)

        # PhoBERT extractor
        self.use_phobert = use_phobert
        if use_phobert:
            self.phobert = PhoBERTFeatureExtractor(
                model_name=phobert_model,
                output_dim=hidden_channels
            )
            # Gate để blend PhoBERT với phoneme embedding
            self.bert_gate = nn.Linear(hidden_channels * 2, hidden_channels)

        # Transformer blocks
        # Speaker conditioning được inject tại block thứ 3 (index 2)
        self.blocks = nn.ModuleList()
        for i in range(n_layers):
            spk_gin = gin_channels if i == 2 else 0  # VITS2: condition tại block 3
            self.blocks.append(
                TransformerBlock(
                    hidden_channels, filter_channels, n_heads,
                    kernel_size, p_dropout, gin_channels=spk_gin
                )
            )

        self.proj = Conv1d(hidden_channels, out_channels * 2, 1)

    def forward(self, x, x_lengths, g=None, bert_feats=None):
        """
        Args:
            x: phoneme ids [B, T]
            x_lengths: [B]
            g: speaker embedding [B, gin_channels, 1]
            bert_feats: PhoBERT token ids hoặc pre-computed features [B, T, H]
        Returns:
            x: encoded text [B, H, T]
            m_p, logs_p: prior distribution params
            x_mask: [B, 1, T]
        """
        x = self.emb(x) * (self.hidden_channels ** 0.5)  # [B, T, H]

        # Kết hợp PhoBERT features
        if self.use_phobert and bert_feats is not None:
            if bert_feats.dim() == 2:
                # bert_feats là token ids, cần extract
                bert_out = self.phobert(bert_feats)
            else:
                # bert_feats đã là features [B, T, H]
                bert_out = bert_feats

            if bert_out is not None:
                # Align độ dài (PhoBERT có thể tokenize khác)
                if bert_out.size(1) != x.size(1):
                    bert_out = F.interpolate(
                        bert_out.transpose(1, 2),
                        size=x.size(1),
                        mode='linear',
                        align_corners=False
                    ).transpose(1, 2)

                # Blend: gate(concat(phoneme, bert))
                combined = torch.cat([x, bert_out], dim=-1)
                x = self.bert_gate(combined)

        x = x.transpose(1, 2)  # [B, H, T]

        # Attention mask
        x_mask = self._length_to_mask(x_lengths, x.size(2)).unsqueeze(1).to(x.dtype)
        attn_mask = x_mask.unsqueeze(2) * x_mask.unsqueeze(-1)

        # Transformer blocks
        for i, block in enumerate(self.blocks):
            # Chỉ block thứ 3 nhận speaker embedding
            block_g = g if i == 2 else None
            x = block(x, x_mask, g=block_g, attn_mask=attn_mask)

        # Project → prior params
        stats = self.proj(x) * x_mask
        m, logs = torch.split(stats, self.out_channels, dim=1)
        return x, m, logs, x_mask

    @staticmethod
    def _length_to_mask(length, max_len):
        x = torch.arange(max_len, dtype=length.dtype, device=length.device)
        return x.unsqueeze(0) < length.unsqueeze(1)
