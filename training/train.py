"""
Training Script — Vietnamese Bert-VITS2
Chạy: python training/train.py --config configs/base_vi.json
"""

import os
import sys
import json
import logging
import argparse
from pathlib import Path

import torch
import torch.distributed as dist
from torch.cuda.amp import GradScaler, autocast
from torch.nn.parallel import DistributedDataParallel as DDP
from torch.utils.data import DataLoader
from torch.utils.tensorboard import SummaryWriter

# Thêm root vào path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from models.bert_vits2 import SynthesizerTrn  # noqa: E402
from models.hifigan import MultiPeriodDiscriminator  # noqa: E402
from training.losses import (  # noqa: E402
    discriminator_loss, generator_loss,
    feature_loss, kl_loss, mel_loss, LossTracker
)
from utils.data_utils import VietnameseTTSDataset, VietnameseTTSCollate  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s — %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# ─── Config loader ───────────────────────────────────────────────────────────

class HParams:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            if isinstance(v, dict):
                setattr(self, k, HParams(**v))
            else:
                setattr(self, k, v)

    def __contains__(self, key):
        return hasattr(self, key)


def load_hparams(config_path: str) -> HParams:
    with open(config_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return HParams(**data)


# ─── Checkpoint utilities ────────────────────────────────────────────────────

def save_checkpoint(model, optimizer, learning_rate, iteration, checkpoint_path):
    """Lưu checkpoint."""
    state_dict = model.module.state_dict() if hasattr(model, 'module') else model.state_dict()
    torch.save({
        'model': state_dict,
        'optimizer': optimizer.state_dict(),
        'learning_rate': learning_rate,
        'iteration': iteration,
    }, checkpoint_path)
    logger.info(f"Checkpoint saved: {checkpoint_path} (step {iteration})")


def load_checkpoint(checkpoint_path: str, model, optimizer=None):
    """Load checkpoint."""
    assert os.path.exists(checkpoint_path), f"Checkpoint không tồn tại: {checkpoint_path}"
    ckpt = torch.load(checkpoint_path, map_location='cpu')

    if hasattr(model, 'module'):
        model.module.load_state_dict(ckpt['model'])
    else:
        model.load_state_dict(ckpt['model'])

    if optimizer is not None and 'optimizer' in ckpt:
        optimizer.load_state_dict(ckpt['optimizer'])

    iteration = ckpt.get('iteration', 0)
    learning_rate = ckpt.get('learning_rate', 2e-4)
    logger.info(f"Loaded checkpoint: {checkpoint_path} (step {iteration})")
    return model, optimizer, learning_rate, iteration


def latest_checkpoint(checkpoint_dir: str, prefix: str = 'G') -> str:
    """Tìm checkpoint mới nhất theo prefix."""
    ckpts = sorted(
        Path(checkpoint_dir).glob(f'{prefix}_*.pth'),
        key=lambda p: int(p.stem.split('_')[1])
    )
    return str(ckpts[-1]) if ckpts else None


# ─── Training loop ───────────────────────────────────────────────────────────

def train(rank: int, n_gpus: int, hps: HParams):
    """Main training function (chạy trên GPU nếu có, fallback CPU)."""

    # Distributed setup
    if n_gpus > 1:
        dist.init_process_group(
            backend='nccl',
            init_method='env://',
            world_size=n_gpus,
            rank=rank
        )

    torch.manual_seed(hps.train.seed)
    use_cuda = torch.cuda.is_available() and n_gpus > 0
    device = torch.device(f'cuda:{rank}') if use_cuda else torch.device('cpu')
    if not use_cuda:
        logger.warning("CUDA không khả dụng — chạy trên CPU (chậm hơn nhiều)")
        hps.train.fp16_run = False  # fp16 không hỗ trợ trên CPU

    # ── Dataset & Dataloader ──
    train_dataset = VietnameseTTSDataset(
        hps.data.training_files,
        hps,
        augment=True
    )
    _val_dataset = VietnameseTTSDataset(
        hps.data.validation_files,
        hps,
        augment=False
    )

    collate_fn = VietnameseTTSCollate()

    if n_gpus > 1:
        from torch.utils.data.distributed import DistributedSampler
        train_sampler = DistributedSampler(train_dataset, num_replicas=n_gpus, rank=rank, shuffle=True)
        train_loader = DataLoader(train_dataset, batch_size=hps.train.batch_size,
                                  num_workers=4, pin_memory=True,
                                  collate_fn=collate_fn, sampler=train_sampler)
    else:
        train_loader = DataLoader(train_dataset, batch_size=hps.train.batch_size,
                                  num_workers=4, pin_memory=True,
                                  collate_fn=collate_fn, shuffle=True)

    # ── Models ──
    net_g = SynthesizerTrn(
        n_vocab=len(train_dataset.symbols),
        spec_channels=hps.data.filter_length // 2 + 1,
        segment_size=hps.train.segment_size // hps.data.hop_length,
        inter_channels=hps.model.inter_channels,
        hidden_channels=hps.model.hidden_channels,
        filter_channels=hps.model.filter_channels,
        n_heads=hps.model.n_heads,
        n_layers=hps.model.n_layers,
        kernel_size=hps.model.kernel_size,
        p_dropout=hps.model.p_dropout,
        resblock=hps.model.resblock,
        resblock_kernel_sizes=hps.model.resblock_kernel_sizes,
        resblock_dilation_sizes=hps.model.resblock_dilation_sizes,
        upsample_rates=hps.model.upsample_rates,
        upsample_initial_channel=hps.model.upsample_initial_channel,
        upsample_kernel_sizes=hps.model.upsample_kernel_sizes,
        n_speakers=hps.data.n_speakers,
        gin_channels=getattr(hps.model, 'speaker_embedding_dim', 0) if hps.data.n_speakers > 1 else 0,
        use_phobert=hps.model.use_phobert,
        phobert_model=hps.model.phobert_model,
        use_transformer_flows=hps.model.use_transformer_flows,
        use_stochastic_dur_pred=hps.model.use_stochastic_dur_pred,
    ).to(device)

    net_d = MultiPeriodDiscriminator(
        use_spectral_norm=hps.model.use_spectral_norm
    ).to(device)

    if n_gpus > 1:
        net_g = DDP(net_g, device_ids=[rank], find_unused_parameters=True)
        net_d = DDP(net_d, device_ids=[rank])

    # ── Optimizers ──
    optim_g = torch.optim.AdamW(
        net_g.parameters(),
        lr=hps.train.learning_rate,
        betas=hps.train.betas,
        eps=hps.train.eps,
        weight_decay=0.01
    )
    optim_d = torch.optim.AdamW(
        net_d.parameters(),
        lr=hps.train.learning_rate,
        betas=hps.train.betas,
        eps=hps.train.eps,
        weight_decay=0.01
    )

    # ── Load checkpoint nếu có ──
    global_step = 0
    ckpt_g = latest_checkpoint('checkpoints', 'G')
    ckpt_d = latest_checkpoint('checkpoints', 'D')
    if ckpt_g:
        net_g, optim_g, lr, global_step = load_checkpoint(ckpt_g, net_g, optim_g)
    if ckpt_d:
        net_d, optim_d, _, _ = load_checkpoint(ckpt_d, net_d, optim_d)

    # ── Learning rate scheduler ──
    scheduler_g = torch.optim.lr_scheduler.ExponentialLR(
        optim_g, gamma=hps.train.lr_decay
    )
    scheduler_d = torch.optim.lr_scheduler.ExponentialLR(
        optim_d, gamma=hps.train.lr_decay
    )

    # ── Mixed precision scaler ──
    scaler = GradScaler(enabled=hps.train.fp16_run)

    # ── TensorBoard (chỉ rank 0) ──
    writer = SummaryWriter(log_dir='logs') if rank == 0 else None

    # ── Training ──
    logger.info(f"[rank {rank}] Starting training — global_step={global_step}")
    net_g.train()
    net_d.train()

    for epoch in range(hps.train.epochs):
        if n_gpus > 1:
            train_sampler.set_epoch(epoch)

        tracker = LossTracker()

        for batch_idx, batch in enumerate(train_loader):
            (x, x_lengths, spec, spec_lengths, y, y_lengths,
             speakers, bert_ids, bert_mask) = [
                b.to(device) if b is not None else None for b in batch
            ]

            # ── Generator forward ──
            with autocast(enabled=hps.train.fp16_run):
                (y_hat, l_length, attn, ids_slice, x_mask, z_mask,
                 (z, z_p, m_p, logs_p, m_q, logs_q)) = net_g(
                    x, x_lengths, spec, spec_lengths,
                    sid=speakers,
                    bert_feats=bert_ids
                )

                # Slice real audio để khớp với segment
                from models.bert_vits2 import slice_segments
                y_mel_slice = slice_segments(
                    y, ids_slice * hps.data.hop_length, hps.train.segment_size
                )

                # Losses
                loss_mel = mel_loss(y_hat, y_mel_slice) * hps.train.c_mel
                loss_kl = kl_loss(z_p, logs_q, m_p, logs_p, z_mask) * hps.train.c_kl
                loss_dur = l_length

                # Discriminator (detach generator output)
                y_hat_det = y_hat.detach()
                y_d_hat_r, y_d_hat_g, fmap_r, fmap_g = net_d(y_mel_slice, y_hat_det)
                loss_disc, _, _ = discriminator_loss(y_d_hat_r, y_d_hat_g)

            # ── Update Discriminator ──
            optim_d.zero_grad()
            scaler.scale(loss_disc).backward()
            scaler.unscale_(optim_d)
            torch.nn.utils.clip_grad_norm_(net_d.parameters(), max_norm=1000.0)
            scaler.step(optim_d)

            # ── Update Generator ──
            with autocast(enabled=hps.train.fp16_run):
                y_d_hat_r, y_d_hat_g, fmap_r, fmap_g = net_d(y_mel_slice, y_hat)
                loss_fm = feature_loss(fmap_r, fmap_g)
                loss_gen, _ = generator_loss(y_d_hat_g)
                loss_g_total = loss_gen + loss_fm + loss_mel + loss_kl + loss_dur

            optim_g.zero_grad()
            scaler.scale(loss_g_total).backward()
            scaler.unscale_(optim_g)
            torch.nn.utils.clip_grad_norm_(net_g.parameters(), max_norm=1000.0)
            scaler.step(optim_g)
            scaler.update()

            global_step += 1

            # ── Logging ──
            tracker.update(
                loss_g=loss_g_total,
                loss_d=loss_disc,
                loss_mel=loss_mel,
                loss_kl=loss_kl,
                loss_dur=loss_dur,
                loss_fm=loss_fm,
            )

            if rank == 0 and global_step % hps.train.log_interval == 0:
                logger.info(f"Epoch {epoch} | Step {global_step} | {tracker}")
                if writer:
                    for k, v in tracker.average().items():
                        writer.add_scalar(f'train/{k}', v, global_step)
                tracker.reset()

            # ── Save checkpoint ──
            if rank == 0 and global_step % hps.train.eval_interval == 0:
                os.makedirs('checkpoints', exist_ok=True)
                save_checkpoint(net_g, optim_g, hps.train.learning_rate,
                                 global_step, f'checkpoints/G_{global_step}.pth')
                save_checkpoint(net_d, optim_d, hps.train.learning_rate,
                                 global_step, f'checkpoints/D_{global_step}.pth')

        scheduler_g.step()
        scheduler_d.step()

    if writer:
        writer.close()
    logger.info("Training complete!")


# ─── Entry point ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Train Vietnamese Bert-VITS2')
    parser.add_argument('--config', type=str, default='configs/base_vi.json')
    parser.add_argument('--n_gpus', type=int, default=torch.cuda.device_count())
    parser.add_argument('--dry_run', action='store_true',
                        help='Chỉ chạy 1 batch để kiểm tra pipeline')
    args = parser.parse_args()

    hps = load_hparams(args.config)
    n_gpus = max(0, args.n_gpus) if torch.cuda.is_available() else 0
    if args.dry_run:
        hps.train.epochs = 1
        hps.train.log_interval = 1
        hps.train.eval_interval = 999999  # Không save checkpoint khi dry_run
        logger.info("=== DRY RUN MODE: chỉ chạy 1 epoch để kiểm tra ===")

    logger.info(f"Config: {args.config}")
    logger.info(f"GPUs: {n_gpus}")
    logger.info(f"PhoBERT: {hps.model.use_phobert}")
    logger.info(f"Batch size: {hps.train.batch_size}")

    os.makedirs('checkpoints', exist_ok=True)
    os.makedirs('logs', exist_ok=True)

    if n_gpus > 1:
        import torch.multiprocessing as mp
        os.environ['MASTER_ADDR'] = 'localhost'
        os.environ['MASTER_PORT'] = '12355'
        mp.spawn(train, args=(n_gpus, hps), nprocs=n_gpus, join=True)
    else:
        train(0, 1, hps)


if __name__ == '__main__':
    main()
