# ASUS Zenbook A16 (`UX3607OA`) — Snapdragon X2 Elite Extreme (`X2E-94-100`) Kernel Memory & Bus Unlock

> [!IMPORTANT]
> **Strictly Hardware-Specific (ASUS Zenbook A16 `UX3607OA` Only)**
> Every kernel registry override, byte offset, and benchmark in this repository was reverse-engineered and verified **exclusively** on the **ASUS Zenbook A16 (`UX3607OA`)** equipped with the **Qualcomm Snapdragon X2 Elite Extreme (`X2E-94-100` / `SC8480XP`, 48 GB LPDDR5x Unified Memory)** and its corresponding Windows ARM64 kernel drivers (`qcdxkm8480.sys`, `qcnspmcdm8480.sys`, `qcpep8480.sys`).
> The tuning script enforces a strict hardware model guard (`UX3607OA` & `X2E94100`) and will automatically abort on any other machine unless `-Force` is explicitly passed.

---

## 1. Overview: Architectural Comparison with `Zagitta/gpu-unlock`

While [`Zagitta/gpu-unlock`](https://github.com/Zagitta/gpu-unlock) removes an artificial **compute throughput (instruction issue-rate) lock** on discrete NVIDIA Ampere GPUs, the Snapdragon X2 Elite Extreme (`X2E-94-100`) 48 GB Unified Memory platform suffers from the exact opposite bottleneck: **artificial memory capacity and bus-scaling locks** imposed by Windows WDDM and Qualcomm kernel driver defaults.

| Dimension | NVIDIA Ampere (`Zagitta/gpu-unlock`) | **ASUS Zenbook A16 (`X2E-94-100`, 48 GB Unified RAM)** |
| :--- | :--- | :--- |
| **Hardware Architecture** | Discrete GPU with fixed 24 GB dedicated VRAM | Unified SoC where 18-core Oryon Gen3 CPU, Adreno X2-90 GPU (`Adreno 880`), and Hexagon NPU V81 (80 TOPS) share **48 GB LPDDR5x (228 GB/s)** |
| **The Artificial Lock** | **Compute Lock**: Fuse registers (`SS0`/`SS1`) halve FP16/BF16 FMA instruction throughput to 50% | **Memory Capacity & Scaling Lock**: Compute units run at 100% full spec, but driver/OS limits cap allocations at **16 GB for NPU** and **23.81 GB (50%) for GPU** |
| **Unlock Mechanism** | SEC2 Booter stack buffer overflow + ROP exploit + PCIe Function Level Reset | Signed-driver-safe **kernel registry table overrides** parsed during `DriverEntry` / `DxgkDdiAddDevice` (`qcnspmcdm8480.sys`, `qcdxkm8480.sys`, `qcpep8480.sys`) |
| **Primary Benefit** | Executes the same model 2x faster (breaks **Compute-bound** ceiling) | **Loads 30B–70B+ LLMs and massive workloads directly into NPU/GPU memory** without CPU fallback or TDR resets (breaks **Memory-bound** ceiling) |

---

## 2. What the 3-Stage Kernel Unlock Does

### Stage 1: NPU 32 GB SMMU Unlock + GPU 35.71 GB Commit Limit + 15s TDR (100% Integrity Safe)
1. **Hexagon NPU V81 SMMU 32 GB Allocation Unlock (`qcnspmcdm8480.sys`)**
   * **Registry Key**: `HKLM\SYSTEM\CurrentControlSet\Enum\ACPI\VEN_QCOM&DEV_0FF0...\Device Parameters\NSPM\SMMU`
   * **Value**: `FastRPCSIDAllocation` (`REG_BINARY`, 32 bytes)
   * **Mechanism**: Disassembly of `qcnspmcdm8480.sys` (`0x14003ee30`–`0x14003ef38`) reveals that the driver parses byte slices `[12..15]`, `[20..23]`, and `[28..31]` as **Big-Endian 32-bit integers (`bfi` assembly sequence) shifted left by 20 bits (`lsl #20`, MB to Bytes)**.
   * **Change**: Modifies the three SID group maximum allocation fields from `00 00 40 00` (`0x00004000` MB = **16 GB**) to `00 00 80 00` (`0x00008000` MB = **32 GB**) at byte indices `14`, `22`, and `30`.
2. **Adreno X2-90 (`Adreno 880`) Shared Memory Commit Limit Expansion (`qcdxkm8480.sys`)**
   * **Registry Key**: `HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers\MemoryManager`
   * **Value**: `SystemPartitionCommitLimitPercentage = 75` (`REG_DWORD`)
   * **Mechanism**: Disassembly of `qcdxkm8480.sys` (`0x140631b4c`–`0x140631ca8`) proves that `SystemMemoryCommitLimit` suffers from a 32-bit shift bug (`lsl w26, w8, #20`), overflowing at 4 GB. In contrast, `SystemPartitionCommitLimitPercentage` (`1..100`) uses **64-bit arithmetic (`(TotalRAM - 512MB) / 100 * Pct`)** to store the driver's internal partition commit limit at `[x19, #0x588]`.
   * **Change**: Raises WDDM shared GPU memory ceiling from the default 50% (`23.81 GB`) to **75% (`35.71 GB`)**.
3. **WDDM GPU TDR Timeout Extension (`dxgkrnl.sys`)**
   * **Registry Key**: `HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers`
   * **Values**: `TdrDelay = 15`, `TdrDdiDelay = 15` (`REG_DWORD`, default 2s → **15s**)
   * **Benefit**: Prevents Windows from resetting the Adreno driver during heavy LLM prefill passes or long compute shaders.

### Stage 2: LPDDR5x Memory Bus Responsiveness & Thermal Profile
1. **Qualcomm Power Engine Plug-in (`qcpep_8480`) DDR Performance Mode Scaling**
   * **Registry Key**: `HKLM\SYSTEM\CurrentControlSet\Services\qcpep_8480\Parameters`
   * **Values**: `SelectivelyEnableDdrPerfMode = 1`, `DDRPerfModeCpuFreqThresholdMhz = 1800` (default `2600 MHz` → **`1800 MHz`**)
   * **Benefit**: Triggers full 12-channel LPDDR5x high-performance bus bandwidth mode as soon as CPU clocks cross 1.8 GHz instead of waiting for 2.6 GHz.
2. **ASUS Optimization Fan Profile**
   * Sets `QuietFan = 2` and `QuietFanDC = 2` (Performance profile).

### Stage 3: Dedicated VRAM Reporting & HVCI Stage-2 MMU Overhead Removal
1. **Dedicated VRAM Reporting (`Display Class 0000`)**
   * Sets `HardwareInformation.qwMemorySize = 4294967296` (4 GB) and `DedicatedSegmentSize = 2048` (2 GB) for legacy games and creative apps that fail when `AdapterRAM = 0`.
2. **HVCI (Core Isolation — Memory Integrity) Disable**
   * Sets `HKLM\SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity\Enabled = 0` to eliminate Hypervisor Stage-2 kernel code page table verification overhead.
   * *(Optional: If you prefer to keep Windows Security Memory Integrity enabled, apply up to Stage 2 via `-MaxStage 2`.)*
3. **Snapdragon ARM64 DPAPI Safety Guard**
   * Explicitly enforces `HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Power\HiberbootEnabled = 0` to prevent the Snapdragon ARM64 Fast Startup TPM/DPAPI MasterKey desynchronization bug.

---

## 3. Post-Reboot Live Verification & Benchmark Results

Measured on **ASUS Zenbook A16 (`UX3607OA`, `X2E-94-100`, 48 GB RAM)** using [`benchmarks/verify_and_benchmark.py`](benchmarks/verify_and_benchmark.py):

| Benchmark / Verification Metric | Factory Default (Before) | **Unlocked (After Reboot)** | Verification API / Method |
| :--- | :--- | :--- | :--- |
| **WDDM Shared GPU Memory (`SharedSystemMemory`)** | `23.81 GB` (50%) | **`35.71 GB` (`38,345,327,616 B`)** | `dxgi.dll` (`IDXGIAdapter1::GetDesc1`) |
| **Adreno X2-90 Real D3D12 Buffer Allocation** | `E_OUTOFMEMORY` above 23.8 GB | **`30.0 GB` allocated & freed cleanly** | `d3d12.dll` (`CreateCommittedResource` on `DEFAULT` heap) |
| **Hexagon NPU V81 FastRPC SMMU Mapping** | Hard-capped at `16.0 GB` | **`22.0 GB` DMA-mapped cleanly** | `libcdsprpc.dll` (`rpcmem_alloc2` + `rpcmem_to_fd`) |
| **Hexagon NPU V81 D3D12 MCDM Allocation** | Capped at `16.0 GB` | **`28.0 GB` allocated cleanly** | `dxcore.dll` + `d3d12.dll` (`MCDM Core Compute`) |
| **Adreno X2-90 OpenCL 3.0 Memory Bandwidth** | — | **`157.57 GB/s`** (`10 GB in 63.47 ms`) | `OpenCL.dll` (`float4` STREAM Copy Kernel) |
| **Adreno X2-90 Sustained Compute Throughput** | — | **`6.60 TFLOPS` (FP32) / `9.17 TFLOPS` (FP16)** | `OpenCL.dll` (8-way unrolled FMA Kernel) |

---

## 4. Quick Start

### Apply Unlock (Stages 1–3)
Right-click `apply-tuning.cmd` and select **Run as administrator**, or run from an elevated PowerShell prompt and **reboot**:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\apply_tuning.ps1
```

> **Note on Windows Security "Memory Integrity" (HVCI):**
> Stage 3 disables HVCI (`HypervisorEnforcedCodeIntegrity\Enabled = 0`) to remove Stage-2 MMU page table walk overhead, which causes Windows Security to display a *"Memory integrity is off"* notice after reboot.
> Because the **32 GB NPU unlock and 35.71 GB GPU unlock (Stage 1) and LPDDR5x bus scaling (Stage 2) work 100% identically with HVCI enabled**, you can keep Memory Integrity turned ON by running with `-MaxStage 2`:
> ```powershell
> powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\apply_tuning.ps1 -MaxStage 2
> ```
> Or re-enable Memory Integrity anytime while keeping all other unlocks active:
> ```powershell
> Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity" -Name "Enabled" -Value 1 -Type DWord
> ```

### Run Post-Reboot Verification & Benchmarks
Double-click `run-benchmarks.cmd` or run:

```powershell
python .\benchmarks\verify_and_benchmark.py
```

### Restore Factory Defaults
Right-click `restore-defaults.cmd` and select **Run as administrator**, or run from an elevated PowerShell prompt and reboot:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\restore_defaults.ps1
```

---

## 5. Repository Structure

* [`apply-tuning.cmd`](apply-tuning.cmd) — UAC self-elevating batch launcher for applying the kernel unlock
* [`restore-defaults.cmd`](restore-defaults.cmd) — UAC self-elevating batch launcher for restoring factory defaults
* [`run-benchmarks.cmd`](run-benchmarks.cmd) — Batch launcher for the post-reboot verification & benchmark suite
* [`scripts/apply_tuning.ps1`](scripts/apply_tuning.ps1) — Stage 1–3 kernel tuning PowerShell script with hardware model guard and automatic JSON backup
* [`scripts/restore_defaults.ps1`](scripts/restore_defaults.ps1) — Factory default restoration PowerShell script
* [`benchmarks/verify_and_benchmark.py`](benchmarks/verify_and_benchmark.py) — Live DXGI, D3D12 (30 GB GPU), FastRPC/MCDM (22–28 GB NPU), and OpenCL 3.0 bandwidth/TFLOPS benchmark suite
* [`tools/inspect_drivers.py`](tools/inspect_drivers.py) — Read-only PE binary inspector for locating registry parameter VAs and file offsets in Qualcomm drivers
* [`docs/KERNEL_ANALYSIS.md`](docs/KERNEL_ANALYSIS.md) — Detailed ARM64 disassembly and reverse-engineering writeup
