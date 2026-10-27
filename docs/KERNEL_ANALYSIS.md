# ARM64 Kernel Driver Reverse-Engineering Analysis (`SC8480XP` / Glymur)

This document details the ARM64 disassembly and binary structure analysis of the three Qualcomm kernel-mode drivers shipped on the **ASUS Zenbook A16 (`UX3607OA`, `Snapdragon X2 Elite Extreme X2E-94-100`)**.

---

## 1. Hexagon NPU V81 SMMU 16 GB Cap (`qcnspmcdm8480.sys`)

* **Driver Binary**: `C:\Windows\System32\DriverStore\FileRepository\qcnspmcdm8480.inf_arm64_4feba84cfc7ee278\qcnspmcdm8480.sys`
* **Driver Version**: `30.0.220.11010`
* **Registry Path**: `HKLM\SYSTEM\CurrentControlSet\Enum\ACPI\VEN_QCOM&DEV_0FF0&SUBSYS_CRD08480&REV_0056\...\Device Parameters\NSPM\SMMU`

### 1.1 Disassembly of `FastRPCSIDAllocation` Parser (`0x14003edcc`–`0x14003ef38`)
During device initialization, `qcnspmcdm8480.sys` reads `FastRPCSMMUVABits` (`0x2A` = 42-bit, 4 TB SMMU virtual address space) and a 32-byte `REG_BINARY` table named `FastRPCSIDAllocation` from the `NSPM\SMMU` subkey.

Factory default value (32 bytes):
```text
[00..03] 0B 00 05 09   -> Total SIDs (11), SID group start indices (0, 5, 9)
[04..07] 00 00 00 20   -> Big-Endian 0x00000020 MB (32 MB base block size)
[08..11] 00 00 00 00   -> Group 0 Base Offset (0 MB)
[12..15] 00 00 40 00   -> Group 0 Max Allocation (Big-Endian 0x00004000 = 16,384 MB = 16 GB)
[16..19] 00 00 00 00   -> Group 1 Base Offset (0 MB)
[20..23] 00 00 40 00   -> Group 1 Max Allocation (Big-Endian 0x00004000 = 16,384 MB = 16 GB)
[24..27] 00 00 00 00   -> Group 2 Base Offset (0 MB)
[28..31] 00 00 40 00   -> Group 2 Max Allocation (Big-Endian 0x00004000 = 16,384 MB = 16 GB)
```

Disassembling `0x14003ee3c`–`0x14003ee74` shows that the driver reconstructs each 4-byte integer in **Big-Endian** byte order using `bfi` (Bitfield Insert) instructions before shifting left by 20 bits (`lsl #20`, converting Megabytes to Bytes):

```arm
14003ee3c: ldrb w14, [sp, #0x41c]       // byte[12] = 0x00
14003ee54: ldrb w12, [sp, #0x41d]       // byte[13] = 0x00
14003ee5c: bfi  x12, x14, #8, #8        // (byte[12] << 8) | byte[13]
14003ee60: ldrb w14, [sp, #0x41e]       // byte[14] = 0x40 (16 GB) -> 0x80 (32 GB)
14003ee64: bfi  x14, x12, #8, #17       // (byte[12] << 16) | (byte[13] << 8) | byte[14]
14003ee68: ldrb w12, [sp, #0x41f]       // byte[15] = 0x00
14003ee6c: bfi  x12, x14, #8, #26       // Big-Endian uint32: 0x00004000 (16,384 MB)
14003ee70: lsl  x12, x12, #20           // Convert MB -> Bytes (0x400000000 = 16 GB)
```

By changing bytes `14`, `22`, and `30` from `0x40` to `0x80` (`00 00 80 00` = `0x00008000` MB), the driver computes `0x00008000 << 20` = **`0x800000000` (32 GB)** per SID category, doubling the NPU SMMU mapping ceiling while staying well within the 42-bit (`0x3FFFFFFFFFF`) SMMU aperture mask verified at `0x14003f00c`.

---

## 2. Adreno X2-90 (`Adreno 880`) GPU Commit Limit (`qcdxkm8480.sys`)

* **Driver Binary**: `C:\Windows\System32\DriverStore\FileRepository\qcdx8480.inf_arm64_329644ff8fe1ee68\qcdxkm8480.sys`
* **Driver Version**: `32.0.172.2`

### 2.1 The 32-Bit Overflow Trap (`SystemMemoryCommitLimit`) vs. 64-Bit Path (`SystemPartitionCommitLimitPercentage`)
At `0x140631b4c`–`0x140631ca8`, `qcdxkm8480.sys` queries `\Registry\Machine\System\CurrentControlSet\Control\GraphicsDrivers\MemoryManager`:

1. **`SystemMemoryCommitLimit` (Broken for >= 4 GB)**:
   ```arm
   140631b88: ldr w8, [sp, #0x14]
   140631b8c: lsl w26, w8, #20          // 32-bit register shift! Truncates at 4096 MB (4 GB)!
   ```
   Because the compiler emitted a 32-bit `lsl w26, w8, #20` instruction, any value `>= 4096` (4 GB) overflows `w26`.
2. **`SystemPartitionCommitLimitPercentage` (Clean 64-Bit Calculation)**:
   ```arm
   140631c0c: ldr  w1, [sp, #0x14]      // SystemPartitionCommitLimitPercentage (1..100)
   140631c10: sub  w8, w1, #0x1
   140631c14: cmp  w8, #0x63            // Validates 1 <= w1 <= 100
   140631c18: csel w23, w1, w23, ls
   ...
   140631c68: ldr  x8, [x19, #0x268]    // Total System RAM in bytes (64-bit)
   140631c74: sub  x10, x8, x10         // x10 = TotalRAM - SmallSystemMemorySize (512 MB)
   140631c78: cbz  w23, 0x140631c9c     // If unset, branches to 0x140631c9c (lsr x12, x10, #1 -> 50% cap)
   140631c80: umulh x9, x10, x8         // 64-bit division: x10 / 100
   ...
   140631c94: mul  x12, x9, x8          // 64-bit multiply: (x10 / 100) * Percentage
   140631ca8: str  x8, [x19, #0x588]    // Stores 64-bit byte limit into [x19, #0x588]
   ```
   Setting `SystemPartitionCommitLimitPercentage = 75` uses full 64-bit arithmetic to set `[x19, #0x588]` to `38,345,327,616` bytes (**35.71 GB**), which WDDM / DXGI directly exposes as `SharedSystemMemory`.

---

## 3. Qualcomm Power Engine Plug-in (`qcpep8480.sys`)

* **Driver Binary**: `C:\Windows\System32\DriverStore\FileRepository\qcpep.wd8480.inf_arm64_b1cce52682dd6621\qcpep8480.sys`
* **Registry Path**: `HKLM\SYSTEM\CurrentControlSet\Services\qcpep_8480\Parameters`
* The internal 24-byte parameter descriptor table at `0x1402f4040` (`SelectivelyEnableDdrPerfMode`, index `0x52`) and `0x1402f4058` (`DDRPerfModeCpuFreqThresholdMhz`, index `0x53`) controls when the Power Engine Plug-in votes for high-performance LPDDR5x bus frequency scaling based on Oryon CPU cluster frequency.
