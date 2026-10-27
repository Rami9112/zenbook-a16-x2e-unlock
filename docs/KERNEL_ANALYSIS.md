# ARM64 Kernel Driver Reverse-Engineering Analysis (`SC8480XP` / Glymur)

본 문서는 **ASUS Zenbook A16 (`UX3607OA`, `Snapdragon X2 Elite Extreme X2E-94-100`)**에 탑재된 퀄컴 커널 드라이버 3종을 `llvm-objdump`로 역어셈블리하여 규명한 레지스트리 파싱 구조와 메모리/전력 제한 메커니즘을 정리한 기술 문서입니다.

---

## 1. Hexagon NPU V81 SMMU 16GB Cap (`qcnspmcdm8480.sys`)

* **드라이버 경로**: `C:\Windows\System32\DriverStore\FileRepository\qcnspmcdm8480.inf_arm64_4feba84cfc7ee278\qcnspmcdm8480.sys`
* **버전**: `30.0.220.11010`
* **레지스트리 경로**: `HKLM\SYSTEM\CurrentControlSet\Enum\ACPI\VEN_QCOM&DEV_0FF0&SUBSYS_CRD08480&REV_0056\...\Device Parameters\NSPM\SMMU`

### 1.1 `FastRPCSIDAllocation` 파싱 루틴 (`0x14003edcc` ~ `0x14003ef38`)
`qcnspmcdm8480.sys`는 `NSPM\SMMU` 하위에서 `FastRPCSMMUVABits` (`0x2A` = 42-bit, 4TB 가상 주소 공간)와 32바이트 바이너리 값인 `FastRPCSIDAllocation`을 읽습니다.

기본값(32 Bytes):
```text
[00..03] 0B 00 05 09   -> 총 SID 개수(11), 그룹 경계 인덱스(0, 5, 9)
[04..07] 00 00 00 20   -> Big-Endian 0x00000020 MB (32 MB 기본 블록)
[08..11] 00 00 00 00   -> Group 0 Base Offset (0 MB)
[12..15] 00 00 40 00   -> Group 0 Max Allocation (Big-Endian 0x00004000 = 16,384 MB = 16 GB)
[16..19] 00 00 00 00   -> Group 1 Base Offset (0 MB)
[20..23] 00 00 40 00   -> Group 1 Max Allocation (Big-Endian 0x00004000 = 16,384 MB = 16 GB)
[24..27] 00 00 00 00   -> Group 2 Base Offset (0 MB)
[28..31] 00 00 40 00   -> Group 2 Max Allocation (Big-Endian 0x00004000 = 16,384 MB = 16 GB)
```

역어셈블리 코드(`0x14003ee54` ~ `0x14003ee74`)를 보면 리틀 엔디안이 아닌 **빅 엔디안(Big-Endian)** 순서로 바이트를 조립한 뒤 20비트 좌측 시프트(`lsl #20`, 즉 `1 MB` 곱셈)를 수행합니다:

```arm
14003ee3c: ldrb w14, [sp, #0x41c]       // byte[12] = 0x00
14003ee54: ldrb w12, [sp, #0x41d]       // byte[13] = 0x00
14003ee5c: bfi  x12, x14, #8, #8        // (byte[12] << 8) | byte[13]
14003ee60: ldrb w14, [sp, #0x41e]       // byte[14] = 0x40 (or 0x80)
14003ee64: bfi  x14, x12, #8, #17       // (byte[12] << 16) | (byte[13] << 8) | byte[14]
14003ee68: ldrb w12, [sp, #0x41f]       // byte[15] = 0x00
14003ee6c: bfi  x12, x14, #8, #26       // Big-Endian uint32: 0x00004000 (16,384 MB)
14003ee70: lsl  x12, x12, #20           // Convert MB -> Bytes (0x400000000 = 16 GB)
```

따라서 인덱스 **14, 22, 30번 바이트**를 `0x40`에서 `0x80`으로 변경하면 각 SID 그룹의 SMMU 최대 매핑 크기가 `0x00008000 << 20` = **`0x800000000` (32 GB)**로 정확히 2배 확장됩니다.

---

## 2. Adreno X2-90 (`Adreno 880`) GPU Commit Limit (`qcdxkm8480.sys`)

* **드라이버 경로**: `C:\Windows\System32\DriverStore\FileRepository\qcdx8480.inf_arm64_329644ff8fe1ee68\qcdxkm8480.sys`
* **버전**: `32.0.172.2`

### 2.1 32비트 오버플로우 함정(`SystemMemoryCommitLimit`)과 64비트 해법(`SystemPartitionCommitLimitPercentage`)
`qcdxkm8480.sys`의 `0x140631b4c` ~ `0x140631ca8` 루틴은 `\Registry\Machine\System\CurrentControlSet\Control\GraphicsDrivers\MemoryManager` 키에서 다음 4개 값을 조회합니다:

1. `SystemMemoryCommitLimit`:
   ```arm
   140631b88: ldr w8, [sp, #0x14]
   140631b8c: lsl w26, w8, #20          // 32-bit 레지스터(w26)에서 20비트 시프트! 4096MB 이상 시 오버플로우!
   ```
   드라이버가 32비트 레지스터 `w26`에 `lsl #20`을 수행하기 때문에 4GB 이상의 값을 넣으면 상위 비트가 잘려 나갑니다.
2. `SystemPartitionCommitLimitPercentage`:
   ```arm
   140631c0c: ldr  w1, [sp, #0x14]      // SystemPartitionCommitLimitPercentage (1..100)
   140631c10: sub  w8, w1, #0x1
   140631c14: cmp  w8, #0x63            // 1 <= w1 <= 100 범위 검증
   140631c18: csel w23, w1, w23, ls
   ...
   140631c68: ldr  x8, [x19, #0x268]    // Total System RAM (64-bit bytes)
   140631c74: sub  x10, x8, x10         // x10 = TotalRAM - SmallSystemMemorySize (512MB)
   140631c78: cbz  w23, 0x140631c9c     // 미설정 시 0x140631c9c (lsr x12, x10, #1 = 50% 제한)로 분기
   140631c80: umulh x9, x10, x8         // 64-bit 나눗셈 (x10 / 100)
   ...
   140631c94: mul  x12, x9, x8          // 64-bit 곱셈 ((x10 / 100) * Percentage)
   140631ca8: str  x8, [x19, #0x588]    // 내부 Aperture/Partition Commit Limit 저장
   ```
   `SystemPartitionCommitLimitPercentage`를 `75`로 설정하면 64비트 연산을 통해 `(48GB - 512MB) * 0.75 = 35.71 GB (38,345,327,616 bytes)`가 손실 없이 `[x19, #0x588]`에 기록됩니다.

---

## 3. Qualcomm Power Engine Plug-in (`qcpep8480.sys`)

* **드라이버 경로**: `C:\Windows\System32\DriverStore\FileRepository\qcpep.wd8480.inf_arm64_b1cce52682dd6621\qcpep8480.sys`
* **레지스트리 경로**: `HKLM\SYSTEM\CurrentControlSet\Services\qcpep_8480\Parameters`
* 내부 파라미터 테이블(`0x1402f4040`, `0x1402f4058`)에서 `SelectivelyEnableDdrPerfMode`(인덱스 `0x52`)와 `DDRPerfModeCpuFreqThresholdMhz`(인덱스 `0x53`)를 읽어 CPU 클럭에 따른 LPDDR5x 버스 고성능 모드 진입 시점을 제어합니다.
