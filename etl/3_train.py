"""Fine-tune one 8-channel U-Net (smp, resnet34 encoder) for change detection.

Input per patch: mosaic_t1 RGBN + mosaic_t2 RGBN (NaN->0), z-scored with pooled
mosaic stats. Ignore mask (ambiguous year ∪ NaN) zeroes the loss per-pixel.
20% of patches held out for validation; best val-dice checkpoint is saved.
"""
import json

import numpy as np
import rasterio
import torch
import segmentation_models_pytorch as smp
from torch.utils.data import DataLoader, Dataset

PATCH, BS, LR, EPOCHS = 256, 8, 3e-4, 100
ENCODER = "resnet34"
INDEX = "models/patch_index_train.npz"
CKPT = "models/unet.pt"
if not torch.cuda.is_available():
    raise RuntimeError("CUDA GPU is required")
DEV = "cuda"
PAIR_YEARS = {"train": (2019, 2021), "eval": (2021, 2024)}

# pooled stats of the mosaics (RGBN x 2), computed at 1/8 decimation
MEAN = np.array([0.0795, 0.0698, 0.0454, 0.2718] * 2, np.float32)
STD = np.array([0.0406, 0.0219, 0.0157, 0.0307] * 2, np.float32)


def build_model():
    return smp.Unet(encoder_name=ENCODER, encoder_weights="imagenet",
                    in_channels=8, classes=1, activation=None)


def normalize(x):
    return ((x - MEAN[:, None, None]) / STD[:, None, None]).astype(np.float32)


_srcs = {}


def _src(path):
    if path not in _srcs:
        _srcs[path] = rasterio.open(path)
    return _srcs[path]


def load_pair(name, col, row):
    """Read one patch: 8-band input, change label, ignore mask."""
    t1, t2 = PAIR_YEARS[name]
    w = rasterio.windows.Window(col, row, PATCH, PATCH)
    bands, nan = [], np.zeros((PATCH, PATCH), bool)
    for yr in (t1, t2):
        d = _src(f"data/mosaics/mosaic_{yr}.tif").read(window=w)
        nan |= np.isnan(d).any(axis=0)
        bands.append(np.nan_to_num(d, nan=0.0).clip(0, 1))
    x = np.concatenate(bands).astype(np.float32)
    chg = _src(f"models/labels/change_{name}.tif").read(1, window=w)
    ign = _src(f"models/labels/ignore_{name}.tif").read(1, window=w)
    ign = ((ign > 0) | nan).astype(np.uint8)
    return x, (chg > 0).astype(np.uint8), ign


class Patches(Dataset):
    def __init__(self, offs, augment=False):
        self.offs, self.augment = offs, augment

    def __len__(self):
        return len(self.offs)

    def __getitem__(self, i):
        c, r = self.offs[i]
        x, y, ign = load_pair("train", int(c), int(r))
        if self.augment:
            k = np.random.randint(4)
            x, y, ign = (np.rot90(x, k, (1, 2)).copy(), np.rot90(y, k).copy(),
                         np.rot90(ign, k).copy())
            if np.random.rand() < 0.5:
                x, y, ign = x[:, :, ::-1].copy(), y[:, ::-1].copy(), ign[:, ::-1].copy()
        return (torch.from_numpy(normalize(x)),
                torch.from_numpy(y[None].astype(np.float32)),
                torch.from_numpy(ign[None].astype(np.float32)))


def masked_losses(pred, y, ign):
    """Per-pixel masked BCE (pos_weight 10x — positives are ~1% of pixels) + Dice."""
    valid = 1.0 - ign
    pw = 1.0 + 9.0 * y
    bce = torch.nn.functional.binary_cross_entropy_with_logits(pred, y, reduction="none")
    bce = (bce * valid * pw).sum() / (valid * pw).sum().clamp(min=1)
    p, t = torch.sigmoid(pred) * valid, y * valid
    inter = (p * t).sum((1, 2, 3))
    union = (p + t).sum((1, 2, 3))
    dice = 1 - ((2 * inter + 1) / (union + 1)).mean()
    return bce + dice, dice


def main():
    offs = np.load(INDEX)["offs"]
    rng = np.random.default_rng(0)
    is_val = rng.random(len(offs)) < 0.2
    tr = DataLoader(Patches(offs[~is_val], augment=True), batch_size=BS,
                    shuffle=True, num_workers=4, pin_memory=True)
    va = DataLoader(Patches(offs[is_val]), batch_size=BS, num_workers=4, pin_memory=True)
    print(f"patches: train={(~is_val).sum()} val={is_val.sum()} | device={DEV}")

    model = build_model().to(DEV)
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    scaler = torch.amp.GradScaler(DEV)
    best = -1.0
    for ep in range(EPOCHS):
        model.train()
        run = 0.0
        for x, y, ign in tr:
            x, y, ign = x.to(DEV), y.to(DEV), ign.to(DEV)
            opt.zero_grad()
            with torch.amp.autocast(DEV):
                loss, _ = masked_losses(model(x), y, ign)
            scaler.scale(loss).backward()
            scaler.step(opt)
            scaler.update()
            run += loss.item()
        model.eval()
        vd, vn = 0.0, 0
        with torch.no_grad():
            for x, y, ign in va:
                x, y, ign = x.to(DEV), y.to(DEV), ign.to(DEV)
                with torch.amp.autocast(DEV):
                    _, dice = masked_losses(model(x), y, ign)
                vd += dice.item()
                vn += 1
        vd /= max(vn, 1)
        print(f"ep{ep:02d} train={run / max(len(tr), 1):.4f} val_dice_loss={vd:.4f}",
              flush=True)
        if 1 - vd > best:
            best = 1 - vd
            torch.save({"state_dict": model.state_dict(),
                        "config": {"in_channels": 8, "encoder": ENCODER}}, CKPT)
    json.dump({"best_val_dice": round(best, 4)}, open("models/train_report.json", "w"))
    print(f"best val dice {best:.4f} -> {CKPT}")


if __name__ == "__main__":
    main()
