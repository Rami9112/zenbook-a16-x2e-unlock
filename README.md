# ASUS Zenbook A16 (`UX3607OA`) — Snapdragon X2 Elite Extreme (`X2E-94-100`) Kernel Memory & Bus Unlock

> [!IMPORTANT]
> **하드웨어 전용 안내 (Strictly Hardware-Specific)**
> 이 저장소의 모든 분석과 튜닝 스크립트는 오직 **ASUS Zenbook A16 (`UX3607OA`) / Qualcomm Snapdragon X2 Elite Extreme (`X2E-94-100` / `SC8480XP`, 48GB LPDDR5x 통합 메모리)** 단일 기종 및 해당 드라이버(`qcdxkm8480.sys`, `qcnspmcdm8480.sys`, `qcpep8480.sys`)에 한해서만 검증되었습니다.
> 스크립트 내부에 하드웨어 모델 검증 가드가 포함되어 있어 다른 노트북에서는 실행이 자동 차단됩니다.

---

## 1. 개요: 왜 이 튜닝이 필요한가? (`gpu-unlock`과의 구조적 비교)

NVIDIA RTX 30(Ampere) 시리즈의 펌웨어 언락([`Zagitta/gpu-unlock`](https://github.com/Zagitta/gpu-unlock))과 스냅드래곤 X2 Elite Extreme(`X2E-94-100`) 48GB 통합 메모리 노트북은 **정반대 방향의 족쇄**를 차고 있습니다.

| 비교 항목 | NVIDIA Ampere (`Zagitta/gpu-unlock`) | **ASUS Zenbook A16 (`X2E-94-100`, 48GB RAM)** |
| :--- | :--- | :--- |
| **하드웨어 아키텍처** | 전용 24GB VRAM을 가진 외장 GPU | CPU(18코어) · GPU(Adreno X2-90) · NPU(Hexagon V81)가 **48GB LPDDR5x(228GB/s)를 공유**하는 통합 SoC |
| **걸려 있는 제한** | **연산 속도(Compute) 락**: 퓨즈 레지스터(`SS0`/`SS1`)로 FP16/BF16 명령어 처리량을 50%로 제한 | **메모리 용량(Capacity) & 버스 스케일링 락**: 연산기는 100% 풀스펙이지만 OS/드라이버가 **NPU 16GB / GPU 23.8GB**로 메모리 할당 상한을 제한 |
| **언락 메커니즘** | SEC2 Booter 버퍼 오버플로우 + ROP 익스플로잇 + PCIe FLR | 드라이버 서명 훼손 없이 커널 드라이버(`qcnspmcdm8480.sys`, `qcdxkm8480.sys`, `qcpep8480.sys`)의 **레지스트리 구성 테이블 오버라이드** |
| **핵심 효과** | 동일 크기 모델을 2배 빠르게 연산 (Compute-bound 돌파) | **30B~70B급 초대형 AI 모델 및 고사양 작업을 NPU/GPU에 통째로 적재** (Memory-bound 돌파) |

---

## 2. 단계별 커널 튜닝 내역

### Stage 1: NPU 32GB SMMU 언락 + GPU 35.7GB 확장 + TDR 연장 (무결성 100%)
1. **Hexagon NPU V81 SMMU 32GB 매핑 언락 (`qcnspmcdm8480.sys`)**
   * 경로: `HKLM\SYSTEM\CurrentControlSet\Enum\ACPI\VEN_QCOM&DEV_0FF0...\Device Parameters\NSPM\SMMU`
   * 값: `FastRPCSIDAllocation` (`REG_BINARY`)
   * `qcnspmcdm8480.sys` 역어셈블리(`0x14003ee30`) 결과, 오프셋 `[12..15]`, `[20..23]`, `[28..31]`을 **Big-Endian 32-bit MB(`bfi` 조립 후 `lsl #20`)**로 파싱함을 확인.
   * 기존 `00 00 40 00` (`0x00004000` MB = **16GB**) → `00 00 80 00` (`0x00008000` MB = **32GB**)로 확장.
2. **Adreno X2-90 (`Adreno 880`) 공유 메모리 커밋 한도 확장 (`qcdxkm8480.sys`)**
   * 경로: `HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers\MemoryManager`
   * 값: `SystemPartitionCommitLimitPercentage = 75` (`REG_DWORD`)
   * `qcdxkm8480.sys` 역어셈블리(`0x140631b4c`) 결과, `SystemMemoryCommitLimit`은 32-bit 시프트(`lsl w26, w8, #20`) 버그로 4GB 이상에서 오버플로우가 나는 반면, `SystemPartitionCommitLimitPercentage`는 **64-bit 연산(`(TotalRAM - 512MB) / 100 * Pct`)**으로 내부 커밋 한도(`[x19, #0x588]`)를 설정함을 확인.
   * WDDM GPU 공유 메모리를 기본 50%(`23.81 GB`) → **75%(`35.71 GB`)**로 확장.
3. **GPU TDR 타임아웃 연장 (`dxgkrnl.sys`)**
   * 경로: `HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers`
   * 값: `TdrDelay = 15`, `TdrDdiDelay = 15` (기본 2초 → **15초**)
   * 대형 LLM 프롬프트 처리(Prefill) 및 고부하 컴퓨트 셰이더 실행 중 드라이버 강제 리셋 방지.

### Stage 2: LPDDR5x 메모리 버스 반응성 & 팬 프로파일 최적화
1. **Qualcomm PEP (`qcpep_8480`) DDR 고성능 모드 진입 임계값 완화**
   * 경로: `HKLM\SYSTEM\CurrentControlSet\Services\qcpep_8480\Parameters`
   * 값: `SelectivelyEnableDdrPerfMode = 1`, `DDRPerfModeCpuFreqThresholdMhz = 1800` (기본 `2600 MHz` → **`1800 MHz`**)
2. **ASUS Optimization 팬 프로파일 고정**
   * `QuietFan = 2`, `QuietFanDC = 2` (Performance 모드)

### Stage 3: 가상 전용 VRAM 보고 & HVCI Stage-2 변환 오버헤드 해제
1. **전용 VRAM 보고값 추가 (`Display Class 0000`)**
   * `HardwareInformation.qwMemorySize = 4294967296` (4GB), `DedicatedSegmentSize = 2048` (2GB)
2. **HVCI (코어 격리 - 메모리 무결성) 비활성화**
   * `HKLM\SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity\Enabled = 0`
   * Hypervisor Stage-2 커널 코드 페이지 검증 오버헤드 제거 (원치 않을 경우 Stage 2까지만 적용 가능: `.\scripts\apply_tuning.ps1 -MaxStage 2`).
3. **Snapdragon ARM64 DPAPI 보호 안전장치**
   * `HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Power\HiberbootEnabled = 0` 강제 유지 (빠른 시작으로 인한 TPM/DPAPI MasterKey 유실 방지).

---

## 3. 재부팅 후 실측 검증 및 벤치마크 결과

[`benchmarks/verify_and_benchmark.py`](benchmarks/verify_and_benchmark.py)를 통해 재부팅 후 실제 하드웨어에서 측정한 결과입니다:

| 테스트 항목 | 튜닝 전 (Factory Default) | **튜닝 후 실측 (Unlocked)** | 검증 방법 |
| :--- | :--- | :--- | :--- |
| **WDDM GPU 공유 메모리 (`SharedSystemMemory`)** | `23.81 GB` (50%) | **`35.71 GB` (`38,345,327,616 B`)** | `dxgi.dll` (`IDXGIAdapter1::GetDesc1`) |
| **Adreno X2-90 실제 D3D12 버퍼 할당** | 23.8GB 초과 시 `E_OUTOFMEMORY` | **`30.0 GB` 연속 할당 및 해제 성공** | `d3d12.dll` (`CreateCommittedResource`) |
| **Hexagon NPU V81 FastRPC SMMU 매핑** | `16.0 GB`에서 매핑 차단 | **`22.0 GB` 연속 DMA 매핑 성공** | `libcdsprpc.dll` (`rpcmem_alloc2` + `rpcmem_to_fd`) |
| **Hexagon NPU V81 D3D12 MCDM 할당** | `16.0 GB` 제한 | **`28.0 GB` 연속 할당 성공** | `dxcore.dll` + `d3d12.dll` (`MCDM Core Compute`) |
| **Adreno X2-90 OpenCL 3.0 메모리 대역폭** | — | **`157.57 GB/s`** (`10 GB in 63.47 ms`) | `OpenCL.dll` (`float4` STREAM Copy Kernel) |
| **Adreno X2-90 지속 연산 성능 (Sustained)** | — | **`6.60 TFLOPS` (FP32) / `9.17 TFLOPS` (FP16)** | `OpenCL.dll` (8-way unrolled FMA Kernel) |

---

## 4. 사용 방법 (Quick Start)

### 전체 튜닝 적용 (Stage 1 ~ 3)
`apply-tuning.cmd`를 우클릭하여 **관리자 권한으로 실행**하거나, 관리자 PowerShell에서 아래 명령어를 실행한 뒤 **재부팅**합니다:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\apply_tuning.ps1
```

> **팁 (윈도우 보안 '메모리 무결성' 기능을 유지하고 싶다면):**
> Stage 3에는 HVCI(코어 격리 메모리 무결성) 비활성화가 포함되어 있어 재부팅 후 Windows 보안에서 *"메모리 무결성이 꺼져 있음"* 알림이 뜰 수 있습니다. 만약 메모리 무결성(HVCI)을 켠 채로 NPU 32GB + GPU 35.7GB + DDR 버스 부스트만 적용하고 싶다면 `-MaxStage 2` 옵션을 사용하세요:
> ```powershell
> powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\apply_tuning.ps1 -MaxStage 2
> ```

### 실측 벤치마크 및 검증 실행 (재부팅 후)
`run-benchmarks.cmd`를 실행하거나 터미널에서 아래 명령어를 실행합니다:

```powershell
python .\benchmarks\verify_and_benchmark.py
```

### 공장 초기화 (전체 원복)
언제든 `restore-defaults.cmd`를 실행하거나 관리자 PowerShell에서 아래 명령어를 실행한 뒤 재부팅하면 모든 설정이 출고 초기값으로 복원됩니다:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\restore_defaults.ps1
```

---

## 5. 디렉터리 구조

* [`apply-tuning.cmd`](apply-tuning.cmd) — 관리자 권한 자동 승격 및 튜닝 적용 배치 파일
* [`restore-defaults.cmd`](restore-defaults.cmd) — 공장 초기값 원복 배치 파일
* [`run-benchmarks.cmd`](run-benchmarks.cmd) — 재부팅 후 GPU/NPU 메모리 할당 및 대역폭 벤치마크 실행 파일
* [`scripts/apply_tuning.ps1`](scripts/apply_tuning.ps1) — 하드웨어 가드 및 자동 백업이 포함된 Stage 1~3 커널 튜닝 스크립트
* [`scripts/restore_defaults.ps1`](scripts/restore_defaults.ps1) — 초기 레지스트리 복원 스크립트
* [`benchmarks/verify_and_benchmark.py`](benchmarks/verify_and_benchmark.py) — DXGI, D3D12(GPU 30GB), FastRPC/MCDM(NPU 22~28GB), OpenCL 3.0 벤치마크 스위트
* [`tools/inspect_drivers.py`](tools/inspect_drivers.py) — 커널 드라이버(`qcdxkm8480.sys`, `qcnspmcdm8480.sys`, `qcpep8480.sys`) 오프셋 검증 스크립트
* [`docs/KERNEL_ANALYSIS.md`](docs/KERNEL_ANALYSIS.md) — ARM64 커널 드라이버 역어셈블리 상세 기술 분석 문서
