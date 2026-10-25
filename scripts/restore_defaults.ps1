<#
.SYNOPSIS
    Restores Factory Default Kernel Settings for ASUS Zenbook A16 (UX3607OA)
    Target SoC: Qualcomm Snapdragon X2 Elite Extreme (X2E-94-100 / SC8480XP)
#>
[CmdletBinding()]
param()

#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$logFile = Join-Path $logDir "restore_result.txt"

Start-Transcript -Path $logFile -Force

Write-Output "================================================================="
Write-Output " Restoring Factory Default Kernel Settings (UX3607OA / X2E-94-100)"
Write-Output "================================================================="

$smmuKey = Get-ChildItem "HKLM:\SYSTEM\CurrentControlSet\Enum\ACPI\VEN_QCOM&DEV_0FF0*" -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $_.PSChildName -eq "SMMU" } | Select-Object -First 1

if (-not $smmuKey) {
    throw "Could not locate Qualcomm Hexagon NPU SMMU registry key."
}
$smmuPath = $smmuKey.PSPath

# 1. NPU SMMU (Restore 16GB Big-Endian 0x00004000 at bytes [12..15], [20..23], [28..31])
[byte[]]$origSmmu = @(
    0x0B, 0x00, 0x05, 0x09,
    0x00, 0x00, 0x00, 0x20,
    0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x40, 0x00,
    0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x40, 0x00,
    0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x40, 0x00
)
Set-ItemProperty -Path $smmuPath -Name "FastRPCSIDAllocation" -Value $origSmmu -Type Binary

# 2. GraphicsDrivers & MemoryManager
$gfxPath = "HKLM:\SYSTEM\CurrentControlSet\Control\GraphicsDrivers"
Remove-ItemProperty -Path $gfxPath -Name "TdrDelay" -ErrorAction SilentlyContinue
Remove-ItemProperty -Path $gfxPath -Name "TdrDdiDelay" -ErrorAction SilentlyContinue

$mmPath = "HKLM:\SYSTEM\CurrentControlSet\Control\GraphicsDrivers\MemoryManager"
if (Test-Path $mmPath) {
    Remove-ItemProperty -Path $mmPath -Name "SystemPartitionCommitLimitPercentage" -ErrorAction SilentlyContinue
}

# 3. qcpep_8480 Parameters
$pepPath = "HKLM:\SYSTEM\CurrentControlSet\Services\qcpep_8480\Parameters"
Set-ItemProperty -Path $pepPath -Name "SelectivelyEnableDdrPerfMode" -Value 0 -Type DWord
Set-ItemProperty -Path $pepPath -Name "DDRPerfModeCpuFreqThresholdMhz" -Value 2600 -Type DWord

# 4. Display Class 0000
$dispPath = "HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000"
Set-ItemProperty -Path $dispPath -Name "HardwareInformation.MemorySize" -Value 0 -Type DWord
Remove-ItemProperty -Path $dispPath -Name "HardwareInformation.qwMemorySize" -ErrorAction SilentlyContinue
Remove-ItemProperty -Path $dispPath -Name "DedicatedSegmentSize" -ErrorAction SilentlyContinue

# 5. HVCI (Re-enable Memory Integrity)
$hvciPath = "HKLM:\SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity"
Set-ItemProperty -Path $hvciPath -Name "Enabled" -Value 1 -Type DWord

# 6. Keep HiberbootEnabled = 0 (Snapdragon ARM64 DPAPI protection)
Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power" -Name "HiberbootEnabled" -Value 0 -Type DWord

Write-Output "=== Factory Defaults Restored Successfully (Reboot Required) ==="
Stop-Transcript
