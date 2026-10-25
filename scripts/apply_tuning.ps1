<#
.SYNOPSIS
    Kernel-level Unified Memory & Bus Scaling Unlock for ASUS Zenbook A16 (UX3607OA)
    Target SoC: Qualcomm Snapdragon X2 Elite Extreme (X2E-94-100 / SC8480XP, 48GB LPDDR5x)

.DESCRIPTION
    Applies verified kernel registry overrides for:
      - Stage 1: Hexagon NPU V81 SMMU 32GB allocation unlock (Big-Endian 0x00008000 MB),
                 Adreno X2-90 (Adreno 880) WDDM shared memory commit limit expansion (75% / ~35.71 GB),
                 and WDDM TDR timeout extension (15 seconds).
      - Stage 2: Qualcomm PEP (qcpep_8480) LPDDR5x high-performance bus scaling threshold reduction
                 (2600 MHz -> 1800 MHz) and ASUS Optimization Performance fan profile.
      - Stage 3: Dedicated VRAM reporting (qwMemorySize = 4GB, DedicatedSegmentSize = 2048MB)
                 and HVCI (Memory Integrity) Stage-2 MMU translation overhead disable.

.PARAMETER MaxStage
    Maximum tuning stage to apply (1, 2, or 3). Default is 3.

.PARAMETER Force
    Bypass strict ASUS Zenbook A16 (UX3607OA) / X2E-94-100 hardware model verification.
#>
[CmdletBinding()]
param(
    [ValidateRange(1, 3)]
    [int]$MaxStage = 3,
    [switch]$Force
)

#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$backupDir = Join-Path $repoRoot "backups"
$logDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$logFile = Join-Path $logDir "apply_result.txt"
$backupFile = Join-Path $backupDir "backup_before_tuning.json"

Start-Transcript -Path $logFile -Force

Write-Output "================================================================="
Write-Output " ASUS Zenbook A16 (UX3607OA) / X2E-94-100 Kernel Unlock Utility"
Write-Output "================================================================="

# 0. Strict Hardware Model Guard (UX3607OA + Snapdragon X2 Elite Extreme X2E-94-100)
$cs = Get-CimInstance Win32_ComputerSystem
$cpuName = (Get-ItemProperty "HKLM:\HARDWARE\DESCRIPTION\System\CentralProcessor\0").ProcessorNameString
Write-Output "Detected Model : $($cs.Model)"
Write-Output "Detected SoC   : $cpuName"

if (-not $Force) {
    if ($cs.Model -notmatch "UX3607OA" -or $cpuName -notmatch "X2E94100") {
        throw "Hardware mismatch! This tuning package is strictly designed for ASUS Zenbook A16 (UX3607OA) with Snapdragon X2 Elite Extreme (X2E-94-100). Use -Force to override."
    }
}

$smmuKey = Get-ChildItem "HKLM:\SYSTEM\CurrentControlSet\Enum\ACPI\VEN_QCOM&DEV_0FF0*" -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $_.PSChildName -eq "SMMU" } | Select-Object -First 1

if (-not $smmuKey) {
    throw "Could not locate Qualcomm Hexagon NPU SMMU registry key (ACPI\VEN_QCOM&DEV_0FF0...\Device Parameters\NSPM\SMMU)."
}

$smmuPath = $smmuKey.PSPath
$gfxPath  = "HKLM:\SYSTEM\CurrentControlSet\Control\GraphicsDrivers"
$mmPath   = "HKLM:\SYSTEM\CurrentControlSet\Control\GraphicsDrivers\MemoryManager"
$pepPath  = "HKLM:\SYSTEM\CurrentControlSet\Services\qcpep_8480\Parameters"
$dispPath = "HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000"
$hvciPath = "HKLM:\SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity"
$pwrPath  = "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power"

Write-Output "`n=== [Step 0] Backing up current registry state ==="
$origSmmuBytes = (Get-ItemProperty -Path $smmuPath -Name "FastRPCSIDAllocation").FastRPCSIDAllocation
$origSmmuHex = ($origSmmuBytes | ForEach-Object { $_.ToString("X2") }) -join " "
Write-Output "Original FastRPCSIDAllocation: $origSmmuHex"

if (-not (Test-Path $backupFile)) {
    $backupObj = @{
        Timestamp                      = (Get-Date).ToString("o")
        Model                          = $cs.Model
        SoC                            = $cpuName
        SMMU_Path                      = $smmuPath
        FastRPCSIDAllocation_Hex       = $origSmmuHex
        SelectivelyEnableDdrPerfMode   = (Get-ItemProperty -Path $pepPath -Name "SelectivelyEnableDdrPerfMode").SelectivelyEnableDdrPerfMode
        DDRPerfModeCpuFreqThresholdMhz = (Get-ItemProperty -Path $pepPath -Name "DDRPerfModeCpuFreqThresholdMhz").DDRPerfModeCpuFreqThresholdMhz
        HardwareInformation_MemorySize = (Get-ItemProperty -Path $dispPath -Name "HardwareInformation.MemorySize")."HardwareInformation.MemorySize"
        HVCI_Enabled                   = (Get-ItemProperty -Path $hvciPath -Name "Enabled").Enabled
        HiberbootEnabled               = (Get-ItemProperty -Path $pwrPath -Name "HiberbootEnabled").HiberbootEnabled
    }
    $backupObj | ConvertTo-Json -Depth 4 | Set-Content -Path $backupFile -Encoding UTF8
    Write-Output "Saved initial backup to: $backupFile"
} else {
    Write-Output "Existing initial backup preserved at: $backupFile"
}

if ($MaxStage -ge 1) {
    Write-Output "`n=== [Stage 1] Applying NPU 32GB SMMU Unlock + GPU 75% (~35.7GB) Commit Limit + 15s TDR ==="
    # 1-A. NPU SMMU: qcnspmcdm8480.sys (0x14003ee30) parses [12..15], [20..23], [28..31] as Big-Endian uint32 MB << 20
    # Change 0x00004000 (16,384 MB = 16 GB) -> 0x00008000 (32,768 MB = 32 GB) at Big-Endian indices 14, 22, 30
    [byte[]]$newSmmuBytes = $origSmmuBytes.Clone()
    if ($newSmmuBytes.Length -eq 32) {
        $newSmmuBytes[12] = 0x00; $newSmmuBytes[13] = 0x00; $newSmmuBytes[14] = 0x80; $newSmmuBytes[15] = 0x00
        $newSmmuBytes[20] = 0x00; $newSmmuBytes[21] = 0x00; $newSmmuBytes[22] = 0x80; $newSmmuBytes[23] = 0x00
        $newSmmuBytes[28] = 0x00; $newSmmuBytes[29] = 0x00; $newSmmuBytes[30] = 0x80; $newSmmuBytes[31] = 0x00
        Set-ItemProperty -Path $smmuPath -Name "FastRPCSIDAllocation" -Value $newSmmuBytes -Type Binary
    } else {
        throw "Unexpected FastRPCSIDAllocation byte length: $($newSmmuBytes.Length)"
    }

    # 1-B. GPU Shared System Partition Commit Limit (75% of 48GB = ~35.71 GB)
    # Verified in qcdxkm8480.sys @ 0x140631bf4 (64-bit calculation into [x19, #0x588])
    if (-not (Test-Path $mmPath)) {
        New-Item -Path $mmPath -Force | Out-Null
    }
    Set-ItemProperty -Path $mmPath -Name "SystemPartitionCommitLimitPercentage" -Value 75 -Type DWord

    # 1-C. GPU TDR Timeout Extension (2s -> 15s)
    Set-ItemProperty -Path $gfxPath -Name "TdrDelay" -Value 15 -Type DWord
    Set-ItemProperty -Path $gfxPath -Name "TdrDdiDelay" -Value 15 -Type DWord
}

if ($MaxStage -ge 2) {
    Write-Output "`n=== [Stage 2] Applying LPDDR5x Bus Perf Mode Scaling & Power Profile ==="
    # 2-A. Enable selective DDR high-performance mode & lower CPU freq trigger threshold from 2600 MHz to 1800 MHz
    Set-ItemProperty -Path $pepPath -Name "SelectivelyEnableDdrPerfMode" -Value 1 -Type DWord
    Set-ItemProperty -Path $pepPath -Name "DDRPerfModeCpuFreqThresholdMhz" -Value 1800 -Type DWord

    # 2-B. Ensure ASUS Optimization Fan Mode is set to Performance (2)
    $asusKey = "HKLM:\SOFTWARE\ASUS\ASUS System Control Interface\AsusOptimization\ASUS Keyboard Hotkeys"
    if (Test-Path $asusKey) {
        Set-ItemProperty -Path $asusKey -Name "QuietFan" -Value 2 -Type DWord
        Set-ItemProperty -Path $asusKey -Name "QuietFanDC" -Value 2 -Type DWord
    }
}

if ($MaxStage -ge 3) {
    Write-Output "`n=== [Stage 3] Applying Dedicated VRAM Reporting & Disabling HVCI Stage-2 Overhead ==="
    # 3-A. Dedicated VRAM Reporting for legacy game/application compatibility
    Set-ItemProperty -Path $dispPath -Name "HardwareInformation.MemorySize" -Value ([int]-2147483648) -Type DWord
    Set-ItemProperty -Path $dispPath -Name "HardwareInformation.qwMemorySize" -Value ([uint64]0x100000000) -Type QWord
    Set-ItemProperty -Path $dispPath -Name "DedicatedSegmentSize" -Value 2048 -Type DWord

    # 3-B. Disable HVCI (Memory Integrity) to eliminate Stage-2 page table walk overhead
    Set-ItemProperty -Path $hvciPath -Name "Enabled" -Value 0 -Type DWord
}

# Mandatory Safety Invariant: Keep HiberbootEnabled = 0 on Snapdragon ARM64 to prevent TPM/DPAPI MasterKey loss
Set-ItemProperty -Path $pwrPath -Name "HiberbootEnabled" -Value 0 -Type DWord

Write-Output "`n=== [Verification] Reading back applied registry values ==="
$verifySmmu = ((Get-ItemProperty -Path $smmuPath -Name "FastRPCSIDAllocation").FastRPCSIDAllocation | ForEach-Object { $_.ToString("X2") }) -join " "
Write-Output "Verified FastRPCSIDAllocation         : $verifySmmu"
Write-Output "Verified SystemPartitionCommitLimitPct: $((Get-ItemProperty -Path $mmPath).SystemPartitionCommitLimitPercentage)%"
Write-Output "Verified TdrDelay / TdrDdiDelay       : $((Get-ItemProperty -Path $gfxPath).TdrDelay)s / $((Get-ItemProperty -Path $gfxPath).TdrDdiDelay)s"
Write-Output "Verified SelectivelyEnableDdrPerfMode : $((Get-ItemProperty -Path $pepPath).SelectivelyEnableDdrPerfMode)"
Write-Output "Verified DDRPerfModeCpuFreqThreshold  : $((Get-ItemProperty -Path $pepPath).DDRPerfModeCpuFreqThresholdMhz) MHz"
Write-Output "Verified HardwareInfo.qwMemorySize    : $((Get-ItemProperty -Path $dispPath).'HardwareInformation.qwMemorySize') bytes"
Write-Output "Verified DedicatedSegmentSize         : $((Get-ItemProperty -Path $dispPath).DedicatedSegmentSize) MB"
Write-Output "Verified HVCI Enabled                 : $((Get-ItemProperty -Path $hvciPath).Enabled)"
Write-Output "Verified HiberbootEnabled (DPAPI Safe): $((Get-ItemProperty -Path $pwrPath).HiberbootEnabled)"
Write-Output "`n=== TUNING APPLIED SUCCESSFULLY (REBOOT REQUIRED) ==="

Stop-Transcript
