"""
Read-Only Kernel Driver PE & AeoB Binary Inspector
Target: ASUS Zenbook A16 (UX3607OA) — Qualcomm Snapdragon X2 Elite Extreme (X2E-94-100 / SC8480XP)

Locates and verifies the exact registry key offsets inside:
  - qcdxkm8480.sys (Adreno X2-90 / Adreno 880 WDDM Kernel Mode Driver)
  - qcnspmcdm8480.sys (Hexagon NPU V81 MCDM Driver)
  - qcpep8480.sys (Qualcomm Power Engine Plug-in Driver)
"""
import glob
import os
import struct


def inspect_driver_strings():
    patterns = {
        "qcdxkm8480.sys": (
            r"C:\Windows\System32\DriverStore\FileRepository\qcdx8480.inf_arm64_*\qcdxkm8480.sys",
            [
                "\\Registry\\Machine\\System\\CurrentControlSet\\Control\\GraphicsDrivers\\MemoryManager",
                "SystemPartitionCommitLimitPercentage",
                "SystemMemoryCommitLimit",
                "HardwareInformation.MemorySize",
                "\\REGISTRY\\MACHINE\\Software\\QCOM\\Drivers\\DxKMD",
            ],
        ),
        "qcnspmcdm8480.sys": (
            r"C:\Windows\System32\DriverStore\FileRepository\qcnspmcdm8480.inf_arm64_*\qcnspmcdm8480.sys",
            [
                "NSPM\\SMMU",
                "FastRPCSMMUVABits",
                "FastRPCSIDAllocation",
                "FastRPCCDSPBounds",
            ],
        ),
        "qcpep8480.sys": (
            r"C:\Windows\System32\DriverStore\FileRepository\qcpep.wd8480.inf_arm64_*\qcpep8480.sys",
            [
                "SelectivelyEnableDdrPerfMode",
                "DDRPerfModeCpuFreqThresholdMhz",
                "DisableDcvsMaxPerfLimit",
                "EnableAlwaysBoostPerf",
            ],
        ),
    }

    for drv_name, (pat, keys) in patterns.items():
        matches = sorted(glob.glob(pat), key=os.path.getmtime, reverse=True)
        if not matches:
            print(f"[WARN] {drv_name} not found at {pat}")
            continue
        path = matches[0]
        with open(path, "rb") as f:
            data = f.read()

        e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
        num_sections = struct.unpack_from("<H", data, e_lfanew + 6)[0]
        opt_hdr_size = struct.unpack_from("<H", data, e_lfanew + 20)[0]
        image_base = struct.unpack_from("<Q", data, e_lfanew + 24 + 24)[0]
        sec_offset = e_lfanew + 24 + opt_hdr_size
        sections = []
        for i in range(num_sections):
            s_name, v_size, v_addr, r_size, r_ptr = struct.unpack_from("<8sIIII", data, sec_offset + i * 40)
            sections.append((s_name.rstrip(b"\x00").decode("ascii", "ignore"), v_addr, v_size, r_ptr, r_size))

        def file_to_va(foff):
            for _, v_addr, _, r_ptr, r_size in sections:
                if r_ptr <= foff < r_ptr + r_size:
                    return image_base + v_addr + (foff - r_ptr)
            return None

        print(f"=== {drv_name} ({path}) ===")
        for k in keys:
            foff = data.find(k.encode("utf-16le"))
            va = file_to_va(foff) if foff != -1 else None
            print(f"  {k}: file_offset={hex(foff) if foff != -1 else 'N/A'}, VA={hex(va) if va else 'N/A'}")


if __name__ == "__main__":
    inspect_driver_strings()
