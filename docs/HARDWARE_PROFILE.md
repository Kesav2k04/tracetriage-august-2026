# Hardware profile

Measured on 2026-08-16, 15:35 IST. Bob should size work against these numbers rather than guessing, and should not assume a modest machine.

| | |
|---|---|
| **CPU** | AMD Ryzen 9 6900HX, **8 physical / 16 logical cores** |
| **RAM** | **16 GB** |
| **GPU** | **NVIDIA RTX 3070 Ti Laptop, 8 GB VRAM**, compute capability 8.6, 46 SMs |
| **Primary disk** | Micron 2450 NVMe, 954 GB. `D:` has 103 GB free. |
| **Additional** | 1 TB external drive available for archival |
| **CUDA** | driver 572.16, `torch 2.13.0+cu126`, `torch.cuda.is_available() == True` |

**Measured GPU speedup: 14.9x** (4096² matmul, 23.4 ms GPU vs 347.5 ms CPU).

---

## Use the GPU. It is installed and verified.

The venv originally carried CPU-only torch, which was a mistake given the card present. It now carries `torch 2.13.0+cu126` and `torchvision 0.28.0+cu126`.

Training a dual-view encoder, running a multi-seed head ensemble, or sweeping calibration on CPU here would waste roughly an order of magnitude of wall-clock time for no reason. Move tensors to `cuda` and assert the device in training code rather than silently falling back.

**Guard against a silent CPU fallback.** A training run that quietly lands on CPU still finishes, just fifteen times slower, and nothing in the output says so. Log the device explicitly and fail loudly if CUDA was expected and is absent.

### CI stays CPU, deliberately

`pyproject.toml` pins plain `torch`, not the CUDA build, and `.github/workflows/ci.yml` runs on CPU GitHub runners. That is correct and must stay: the clean-clone reproduction claim has to hold on a machine with no GPU. The CUDA build is a **local development override**, applied with:

```bash
uv pip install --python .venv/Scripts/python.exe \
  --index-url https://download.pytorch.org/whl/cu126 \
  --index-strategy unsafe-best-match \
  --reinstall-package torch --reinstall-package torchvision torch torchvision
```

Any model that ships must produce identical bounded outputs on both, which is what the ONNX export in the plan's advanced ceiling is for. **A result that only reproduces on the GPU is not reproducible.**

---

## The real constraint is 16 GB of RAM, not disk

With disk effectively unlimited, the binding limits become:

**1. RAM, 16 GB.** A 47 GB snapshot cannot be loaded into memory, and neither can a tenth of it. Every pipeline stage must stream:

- read Parquet lazily with `polars.scan_parquet`, never `read_parquet` on the full set
- process waterfalls in batches, releasing arrays between them
- compute features to disk in chunks; never materialise a full image tensor stack
- a 9,230-image RGB stack at 604 x 1550 is roughly **26 GB in float32**. It does not fit. Precompute embeddings to disk instead.

**2. VRAM, 8 GB.** Constrains batch size, especially at the waterfall's native 1603 px height. Crop to the plot box first, downsample deliberately, and record the downsample factor in the receipt. Use mixed precision. If a batch does not fit, reduce the batch, not the evaluation.

**3. Download courtesy, not bandwidth.** SatNOGS is volunteer-run. The 0.4 s spacing stays regardless of how fast the link is. At roughly 0.7 s per waterfall including transfer, 27,690 artifacts is about **5.4 hours**. That is a scheduling fact, not a disk fact.

**4. The deadline.** 31 August, 23:59 ET. This is the constraint that actually binds, which is why the snapshot is staged below.

---

## Staged snapshot, so the download is never on the critical path

A single 47 GB download would block the kill gate for most of a day. Staging removes it from the critical path entirely, and costs nothing because the snapshot builder is already specified as resumable (task A1).

| Stage | Observations | Waterfalls | Size | Time | Purpose |
|---|---|---|---|---|---|
| **1** | 2,500 | ~2,300 | ~4 GB | ~45 min | Unblocks gates 3, 4 and 5 immediately. Bob builds and tests the whole Wave A path on this. |
| **2** | 30,000 total | ~27,700 | ~47 GB | ~5 h, run overnight | Full statistical power for cold-entity holdouts and grouped bootstrap. |

Stage 1 gives roughly 250 decisive negatives and 470 decisive positives: thin for a final claim, ample for building and debugging every module.

Stage 2 gives roughly **3,050 decisive negatives and 5,650 decisive positives**. That is what the four holdouts need, because when whole stations and transmitters are held out, each cold-entity test set is only a fraction of the total, and a grouped bootstrap over a few hundred examples produces intervals too wide to claim anything with.

**Run stage 2 overnight while Bob works on Wave B.** Do not wait on it.

### Stratify stage 2, do not just take a bigger contiguous block

A larger single window mostly buys more of the same stations and satellites. Spend the extra size on coverage that the evaluation actually needs:

- **multiple time windows**, not one, so the chronological holdout tests real temporal drift rather than one week's conditions
- **deliberate coverage of rare client families.** At least six appear in the population and 6% of records carry no client version at all. The plan's "unsupported client format" failure state needs real examples, and cold-format generalisation needs them in a held-out pool.
- **enough distinct stations and transmitters reserved for the cold pools** that holding them out still leaves a usable training set

Record the sampling design in the dataset manifest. A stratified sample described as a random one is a leakage claim waiting to fail review.
