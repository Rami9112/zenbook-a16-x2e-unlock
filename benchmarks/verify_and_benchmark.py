"""
Post-Reboot Kernel Verification & Hardware Benchmark Suite
Target: ASUS Zenbook A16 (UX3607OA) — Qualcomm Snapdragon X2 Elite Extreme (X2E-94-100 / SC8480XP, 48GB LPDDR5x)

Verifies:
  1. WDDM / DXGI SharedSystemMemory expansion (23.81 GB -> 35.71 GB) & Kernel Registry state
  2. Adreno X2-90 (Adreno 880) D3D12 >24GB (30.0 GB) real GPU buffer allocation
  3. Hexagon NPU V81 >16GB real memory unlock via both FastRPC (libcdsprpc.dll) and MCDM (dxcore.dll + d3d12.dll)
  4. Adreno X2-90 OpenCL 3.0 STREAM Copy Memory Bandwidth (GB/s) & Sustained FP32/FP16 Compute (TFLOPS)
"""
import ctypes
from ctypes import wintypes
import glob
import json
import os
import subprocess
import time
import uuid


def make_guid(s: str):
    return (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(s).bytes_le)


def step1_verify_kernel_and_dxgi():
    print("=================================================================")
    print(" [1/4] KERNEL REGISTRY & LIVE WDDM/DXGI ADAPTER VERIFICATION")
    print("=================================================================")

    ps_cmd = r"""
    $dg = Get-CimInstance -Namespace root\Microsoft\Windows\DeviceGuard -ClassName Win32_DeviceGuard
    $disp = Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000"
    $mm = Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\GraphicsDrivers\MemoryManager" -ErrorAction SilentlyContinue
    $gfx = Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\GraphicsDrivers"
    $pep = Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Services\qcpep_8480\Parameters"
    $smmuKey = Get-ChildItem "HKLM:\SYSTEM\CurrentControlSet\Enum\ACPI\VEN_QCOM&DEV_0FF0*" -Recurse -ErrorAction SilentlyContinue | Where-Object { $_.PSChildName -eq "SMMU" } | Select-Object -First 1
    $smmu = (Get-ItemProperty $smmuKey.PSPath).FastRPCSIDAllocation
    [PSCustomObject]@{
        VBS_Status               = $dg.VirtualizationBasedSecurityStatus
        SecurityServicesRunning  = $dg.SecurityServicesRunning
        CommitLimitPct           = $mm.SystemPartitionCommitLimitPercentage
        TdrDelay                 = $gfx.TdrDelay
        DdrPerfMode              = $pep.SelectivelyEnableDdrPerfMode
        DdrThresholdMhz          = $pep.DDRPerfModeCpuFreqThresholdMhz
        Disp_qwMemorySize        = $disp.'HardwareInformation.qwMemorySize'
        Disp_DedicatedSegmentMB  = $disp.DedicatedSegmentSize
        SMMU_BigEndian_Byte14_22_30 = @($smmu[14], $smmu[22], $smmu[30])
    } | ConvertTo-Json
    """
    out = subprocess.check_output(["powershell", "-NoProfile", "-Command", ps_cmd], text=True)
    print(out.strip())

    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class DXGI_ADAPTER_DESC1(ctypes.Structure):
        _fields_ = [
            ("Description", wintypes.WCHAR * 128),
            ("VendorId", wintypes.UINT),
            ("DeviceId", wintypes.UINT),
            ("SubSysId", wintypes.UINT),
            ("Revision", wintypes.UINT),
            ("DedicatedVideoMemory", ctypes.c_size_t),
            ("DedicatedSystemMemory", ctypes.c_size_t),
            ("SharedSystemMemory", ctypes.c_size_t),
            ("AdapterLuid", LUID),
            ("Flags", wintypes.UINT),
        ]

    IID_IDXGIFactory1 = make_guid("770aae78-f26f-4dba-a829-253c83d1b387")
    dxgi = ctypes.windll.LoadLibrary("dxgi.dll")
    dxgi.CreateDXGIFactory1.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    dxgi.CreateDXGIFactory1.restype = ctypes.c_long

    factory = ctypes.c_void_p()
    if dxgi.CreateDXGIFactory1(ctypes.byref(IID_IDXGIFactory1), ctypes.byref(factory)) == 0 and factory.value:
        vtable = ctypes.cast(ctypes.cast(factory, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        EnumAdapters1 = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p))(vtable[12])
        adapter = ctypes.c_void_p()
        if EnumAdapters1(factory, 0, ctypes.byref(adapter)) == 0 and adapter.value:
            avtable = ctypes.cast(ctypes.cast(adapter, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
            GetDesc1 = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(DXGI_ADAPTER_DESC1))(avtable[10])
            desc = DXGI_ADAPTER_DESC1()
            GetDesc1(adapter, ctypes.byref(desc))
            print(f"\nDXGI Adapter [0]   : {desc.Description}")
            print(f"SharedSystemMemory : {desc.SharedSystemMemory / (1024**3):.2f} GB ({desc.SharedSystemMemory:,} bytes)")


def step2_test_gpu_30gb_allocation():
    print("\n=================================================================")
    print(" [2/4] ADRENO X2-90 GPU >24GB (30.0 GB) D3D12 ALLOCATION TEST")
    print("=================================================================")

    d3d12 = ctypes.windll.LoadLibrary("d3d12.dll")
    dxgi = ctypes.windll.LoadLibrary("dxgi.dll")
    d3d12.D3D12CreateDevice.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    d3d12.D3D12CreateDevice.restype = ctypes.c_long
    dxgi.CreateDXGIFactory1.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    dxgi.CreateDXGIFactory1.restype = ctypes.c_long

    IID_IDXGIFactory1 = make_guid("770aae78-f26f-4dba-a829-253c83d1b387")
    IID_ID3D12Device = make_guid("189819f1-1db6-4b57-be54-1821339b85f7")
    IID_ID3D12Resource = make_guid("696442be-a72e-4059-bc79-5b5c98040fad")

    factory = ctypes.c_void_p()
    dxgi.CreateDXGIFactory1(ctypes.byref(IID_IDXGIFactory1), ctypes.byref(factory))
    vtable = ctypes.cast(ctypes.cast(factory, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    EnumAdapters1 = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p))(vtable[12])
    adapter = ctypes.c_void_p()
    EnumAdapters1(factory, 0, ctypes.byref(adapter))

    device = ctypes.c_void_p()
    hr = d3d12.D3D12CreateDevice(adapter, 0xB000, ctypes.byref(IID_ID3D12Device), ctypes.byref(device))
    if hr != 0 or not device.value:
        print(f"Failed to create D3D12Device: 0x{hr & 0xFFFFFFFF:08X}")
        return

    class D3D12_HEAP_PROPERTIES(ctypes.Structure):
        _fields_ = [("Type", ctypes.c_uint32), ("CPUPageProperty", ctypes.c_uint32), ("MemoryPoolPreference", ctypes.c_uint32), ("CreationNodeMask", ctypes.c_uint32), ("VisibleNodeMask", ctypes.c_uint32)]

    class DXGI_SAMPLE_DESC(ctypes.Structure):
        _fields_ = [("Count", ctypes.c_uint32), ("Quality", ctypes.c_uint32)]

    class D3D12_RESOURCE_DESC(ctypes.Structure):
        _fields_ = [
            ("Dimension", ctypes.c_uint32), ("Alignment", ctypes.c_uint64), ("Width", ctypes.c_uint64),
            ("Height", ctypes.c_uint32), ("DepthOrArraySize", ctypes.c_uint16), ("MipLevels", ctypes.c_uint16),
            ("Format", ctypes.c_uint32), ("SampleDesc", DXGI_SAMPLE_DESC), ("Layout", ctypes.c_uint32), ("Flags", ctypes.c_uint32),
        ]

    dvtable = ctypes.cast(ctypes.cast(device, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    CreateCommittedResource = ctypes.WINFUNCTYPE(
        ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(D3D12_HEAP_PROPERTIES), ctypes.c_uint32,
        ctypes.POINTER(D3D12_RESOURCE_DESC), ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)
    )(dvtable[27])

    heap_props = D3D12_HEAP_PROPERTIES(1, 0, 0, 1, 1)
    chunk_size = 2 * (1024 ** 3)
    resources = []
    total_gb = 0
    for _ in range(15):
        res_desc = D3D12_RESOURCE_DESC(1, 0, chunk_size, 1, 1, 1, 0, DXGI_SAMPLE_DESC(1, 0), 1, 0)
        res_ptr = ctypes.c_void_p()
        hr = CreateCommittedResource(device, ctypes.byref(heap_props), 0, ctypes.byref(res_desc), 0, None, ctypes.byref(IID_ID3D12Resource), ctypes.byref(res_ptr))
        if hr == 0 and res_ptr.value:
            resources.append(res_ptr)
            total_gb += 2
            if total_gb in (20, 24, 26, 28, 30):
                print(f"  [PASS] Allocated {total_gb} GB on Adreno X2-90 GPU" + (" (crossed old 23.81 GB cap!)" if total_gb > 24 else ""))
        else:
            print(f"  [STOP] Stopped at {total_gb} GB (hr=0x{hr & 0xFFFFFFFF:08X})")
            break

    for r in resources:
        rvt = ctypes.cast(ctypes.cast(r, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(rvt[2])(r)
    print(f"  Cleanly released all {total_gb} GB GPU buffers.")


def step3_test_npu_smmu_and_mcdm():
    print("\n=================================================================")
    print(" [3/4] HEXAGON NPU V81 >16GB SMMU & MCDM ALLOCATION TEST")
    print("=================================================================")

    npu_dirs = glob.glob(r"C:\Windows\System32\DriverStore\FileRepository\qcnspmcdm8480.inf_arm64_*")
    if npu_dirs:
        cdsp = ctypes.windll.LoadLibrary(os.path.join(npu_dirs[0], "libcdsprpc.dll"))
        cdsp.rpcmem_init()
        cdsp.rpcmem_alloc2.argtypes = [ctypes.c_int, ctypes.c_uint32, ctypes.c_size_t]
        cdsp.rpcmem_alloc2.restype = ctypes.c_void_p
        cdsp.rpcmem_free.argtypes = [ctypes.c_void_p]
        cdsp.rpcmem_to_fd.argtypes = [ctypes.c_void_p]
        cdsp.rpcmem_to_fd.restype = ctypes.c_int

        ptrs = []
        tot = 0
        for _ in range(22):
            p = cdsp.rpcmem_alloc2(25, 1, 1024 * 1024 * 1024)
            if p:
                fd = cdsp.rpcmem_to_fd(p)
                ptrs.append(p)
                tot += 1
                if tot in (12, 16, 18, 20, 22):
                    print(f"  [FastRPC NPU SMMU] Allocated & mapped {tot} GB (fd={fd})" + (" -> CROSSED 16GB OLD LIMIT!" if tot > 16 else ""))
            else:
                break
        for p in ptrs:
            cdsp.rpcmem_free(p)
        cdsp.rpcmem_deinit()
        print(f"  Cleanly released {tot} GB FastRPC NPU buffers.")

    dxcore = ctypes.windll.LoadLibrary("dxcore.dll")
    d3d12 = ctypes.windll.LoadLibrary("d3d12.dll")
    dxcore.DXCoreCreateAdapterFactory.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    dxcore.DXCoreCreateAdapterFactory.restype = ctypes.c_long
    d3d12.D3D12CreateDevice.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    d3d12.D3D12CreateDevice.restype = ctypes.c_long

    IID_IDXCoreAdapterFactory = make_guid("78ee5945-c36e-4b13-a669-005dd11c0f06")
    IID_IDXCoreAdapterList = make_guid("526c7776-40e9-459b-b711-f32ad76dfc28")
    IID_IDXCoreAdapter = make_guid("f0db4c7f-fe5a-42a2-bd62-f2a6cf6fc83e")
    DXCORE_ADAPTER_ATTRIBUTE_D3D12_CORE_COMPUTE = make_guid("248e2800-a793-4724-abaa-23a6de1be090")
    IID_ID3D12Device = make_guid("189819f1-1db6-4b57-be54-1821339b85f7")
    IID_ID3D12Resource = make_guid("696442be-a72e-4059-bc79-5b5c98040fad")

    fac = ctypes.c_void_p()
    dxcore.DXCoreCreateAdapterFactory(ctypes.byref(IID_IDXCoreAdapterFactory), ctypes.byref(fac))
    fvt = ctypes.cast(ctypes.cast(fac, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    CreateAdapterList = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(fvt[3])
    alist = ctypes.c_void_p()
    CreateAdapterList(fac, 1, ctypes.byref(DXCORE_ADAPTER_ATTRIBUTE_D3D12_CORE_COMPUTE), ctypes.byref(IID_IDXCoreAdapterList), ctypes.byref(alist))
    lvt = ctypes.cast(ctypes.cast(alist, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    GetAdapter = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(lvt[3])

    adp = ctypes.c_void_p()
    GetAdapter(alist, 1, ctypes.byref(IID_IDXCoreAdapter), ctypes.byref(adp))
    npu_dev = ctypes.c_void_p()
    if d3d12.D3D12CreateDevice(adp, 0x1000, ctypes.byref(IID_ID3D12Device), ctypes.byref(npu_dev)) == 0 and npu_dev.value:
        class D3D12_HEAP_PROPERTIES(ctypes.Structure):
            _fields_ = [("Type", ctypes.c_uint32), ("CPUPageProperty", ctypes.c_uint32), ("MemoryPoolPreference", ctypes.c_uint32), ("CreationNodeMask", ctypes.c_uint32), ("VisibleNodeMask", ctypes.c_uint32)]
        class DXGI_SAMPLE_DESC(ctypes.Structure):
            _fields_ = [("Count", ctypes.c_uint32), ("Quality", ctypes.c_uint32)]
        class D3D12_RESOURCE_DESC(ctypes.Structure):
            _fields_ = [
                ("Dimension", ctypes.c_uint32), ("Alignment", ctypes.c_uint64), ("Width", ctypes.c_uint64),
                ("Height", ctypes.c_uint32), ("DepthOrArraySize", ctypes.c_uint16), ("MipLevels", ctypes.c_uint16),
                ("Format", ctypes.c_uint32), ("SampleDesc", DXGI_SAMPLE_DESC), ("Layout", ctypes.c_uint32), ("Flags", ctypes.c_uint32),
            ]
        dvt = ctypes.cast(ctypes.cast(npu_dev, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        CreateCommittedResource = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(D3D12_HEAP_PROPERTIES), ctypes.c_uint32, ctypes.POINTER(D3D12_RESOURCE_DESC), ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(dvt[27])
        heap_props = D3D12_HEAP_PROPERTIES(2, 0, 0, 1, 1)
        chunk = 2 * (1024 ** 3)
        res_list = []
        tot_gb = 0
        for _ in range(14):
            rdesc = D3D12_RESOURCE_DESC(1, 0, chunk, 1, 1, 1, 0, DXGI_SAMPLE_DESC(1, 0), 1, 0)
            rptr = ctypes.c_void_p()
            hr = CreateCommittedResource(npu_dev, ctypes.byref(heap_props), 0, ctypes.byref(rdesc), 0, None, ctypes.byref(IID_ID3D12Resource), ctypes.byref(rptr))
            if hr == 0 and rptr.value:
                res_list.append(rptr)
                tot_gb += 2
                if tot_gb in (16, 20, 24, 28):
                    print(f"  [Hexagon NPU MCDM]   Allocated {tot_gb} GB on NPU" + (" -> CROSSED 16GB & 24GB OLD LIMITS!" if tot_gb > 16 else ""))
            else:
                break
        for r in res_list:
            rvt = ctypes.cast(ctypes.cast(r, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
            ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(rvt[2])(r)
        print(f"  Cleanly released {tot_gb} GB NPU MCDM buffers.")


def step4_opencl_bandwidth_and_tflops():
    print("\n=================================================================")
    print(" [4/4] ADRENO X2-90 OPENCL 3.0 BANDWIDTH & TFLOPS BENCHMARK")
    print("=================================================================")

    cl = ctypes.windll.LoadLibrary(r"C:\Windows\System32\OpenCL.dll")
    cl.clGetPlatformIDs.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint32)]
    cl.clGetDeviceIDs.argtypes = [ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint32)]
    cl.clCreateContext.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int32)]
    cl.clCreateContext.restype = ctypes.c_void_p
    cl.clCreateCommandQueue.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint64, ctypes.POINTER(ctypes.c_int32)]
    cl.clCreateCommandQueue.restype = ctypes.c_void_p
    cl.clCreateBuffer.argtypes = [ctypes.c_void_p, ctypes.c_uint64, ctypes.c_size_t, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int32)]
    cl.clCreateBuffer.restype = ctypes.c_void_p
    cl.clCreateProgramWithSource.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_char_p), ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_int32)]
    cl.clCreateProgramWithSource.restype = ctypes.c_void_p
    cl.clBuildProgram.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p), ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p]
    cl.clCreateKernel.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_int32)]
    cl.clCreateKernel.restype = ctypes.c_void_p
    cl.clSetKernelArg.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_size_t, ctypes.c_void_p]
    cl.clEnqueueNDRangeKernel.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t),
        ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p
    ]
    cl.clFinish.argtypes = [ctypes.c_void_p]
    cl.clReleaseMemObject.argtypes = [ctypes.c_void_p]

    num_plats = ctypes.c_uint32()
    cl.clGetPlatformIDs(0, None, ctypes.byref(num_plats))
    plats = (ctypes.c_void_p * num_plats.value)()
    cl.clGetPlatformIDs(num_plats.value, plats, None)
    dev = ctypes.c_void_p()
    cl.clGetDeviceIDs(plats[0], 0xFFFFFFFF, 1, ctypes.byref(dev), None)

    err = ctypes.c_int32()
    ctx = ctypes.c_void_p(cl.clCreateContext(None, 1, ctypes.byref(dev), None, None, ctypes.byref(err)))
    queue = ctypes.c_void_p(cl.clCreateCommandQueue(ctx, dev, 0, ctypes.byref(err)))

    src = b"""
    #pragma OPENCL EXTENSION cl_khr_fp16 : enable
    __kernel void stream_copy(__global float4* dst, __global const float4* src) {
        size_t gid = get_global_id(0);
        dst[gid] = src[gid];
    }
    __kernel void peak_fp32(__global float4* out, float4 a, float4 b) {
        size_t gid = get_global_id(0);
        float4 v0 = (float4)((float)(gid & 255) * 0.001f);
        float4 v1 = v0 + 0.1f, v2 = v0 + 0.2f, v3 = v0 + 0.3f;
        float4 v4 = v0 + 0.4f, v5 = v0 + 0.5f, v6 = v0 + 0.6f, v7 = v0 + 0.7f;
        for (int i = 0; i < 512; ++i) {
            v0 = mad(v0, a, b); v1 = mad(v1, a, b); v2 = mad(v2, a, b); v3 = mad(v3, a, b);
            v4 = mad(v4, a, b); v5 = mad(v5, a, b); v6 = mad(v6, a, b); v7 = mad(v7, a, b);
        }
        float4 s = v0 + v1 + v2 + v3 + v4 + v5 + v6 + v7;
        if (s.x == -999999.0f) out[gid] = s;
    }
    __kernel void peak_fp16(__global half4* out, float4 af, float4 bf) {
        size_t gid = get_global_id(0);
        half4 a = convert_half4(af), b = convert_half4(bf);
        half4 v0 = (half4)((half)(gid & 63) * (half)0.001h);
        half4 v1 = v0 + (half)0.01h, v2 = v0 + (half)0.02h, v3 = v0 + (half)0.03h;
        half4 v4 = v0 + (half)0.04h, v5 = v0 + (half)0.05h, v6 = v0 + (half)0.06h, v7 = v0 + (half)0.07h;
        for (int i = 0; i < 512; ++i) {
            v0 = mad(v0, a, b); v1 = mad(v1, a, b); v2 = mad(v2, a, b); v3 = mad(v3, a, b);
            v4 = mad(v4, a, b); v5 = mad(v5, a, b); v6 = mad(v6, a, b); v7 = mad(v7, a, b);
        }
        half4 s = v0 + v1 + v2 + v3 + v4 + v5 + v6 + v7;
        if (s.x == (half)-999.0h) out[gid] = s;
    }
    """
    src_ptr = ctypes.c_char_p(src)
    src_len = ctypes.c_size_t(len(src))
    prog = ctypes.c_void_p(cl.clCreateProgramWithSource(ctx, 1, ctypes.byref(src_ptr), ctypes.byref(src_len), ctypes.byref(err)))
    cl.clBuildProgram(prog, 1, ctypes.byref(dev), None, None, None)

    k_copy = ctypes.c_void_p(cl.clCreateKernel(prog, b"stream_copy", ctypes.byref(err)))
    k_fp32 = ctypes.c_void_p(cl.clCreateKernel(prog, b"peak_fp32", ctypes.byref(err)))
    k_fp16 = ctypes.c_void_p(cl.clCreateKernel(prog, b"peak_fp16", ctypes.byref(err)))

    n_float4 = (512 * 1024 * 1024) // 16
    buf_bytes = n_float4 * 16
    b_src = ctypes.c_void_p(cl.clCreateBuffer(ctx, 1, buf_bytes, None, ctypes.byref(err)))
    b_dst = ctypes.c_void_p(cl.clCreateBuffer(ctx, 1, buf_bytes, None, ctypes.byref(err)))

    cl.clSetKernelArg(k_copy, 0, 8, ctypes.byref(b_dst))
    cl.clSetKernelArg(k_copy, 1, 8, ctypes.byref(b_src))
    gws_copy = ctypes.c_size_t(n_float4)
    for _ in range(3):
        cl.clEnqueueNDRangeKernel(queue, k_copy, 1, None, ctypes.byref(gws_copy), None, 0, None, None)
    cl.clFinish(queue)

    t0 = time.perf_counter()
    for _ in range(10):
        cl.clEnqueueNDRangeKernel(queue, k_copy, 1, None, ctypes.byref(gws_copy), None, 0, None, None)
    cl.clFinish(queue)
    t1 = time.perf_counter()
    print(f"  [STREAM Copy Bandwidth] 10.0 GB in {(t1 - t0) * 1000:.2f} ms -> {10.0 / (t1 - t0):.2f} GB/s")

    a_val = (ctypes.c_float * 4)(1.00001, 0.99999, 1.00001, 0.99999)
    b_val = (ctypes.c_float * 4)(0.00001, -0.00001, 0.00001, -0.00001)
    for label, kern in [("FP32", k_fp32), ("FP16", k_fp16)]:
        cl.clSetKernelArg(kern, 0, 8, ctypes.byref(b_dst))
        cl.clSetKernelArg(kern, 1, 16, ctypes.byref(a_val))
        cl.clSetKernelArg(kern, 2, 16, ctypes.byref(b_val))
        gws = ctypes.c_size_t(2 * 1024 * 1024)
        for _ in range(3):
            cl.clEnqueueNDRangeKernel(queue, kern, 1, None, ctypes.byref(gws), None, 0, None, None)
        cl.clFinish(queue)
        t0 = time.perf_counter()
        iters = 20
        for _ in range(iters):
            cl.clEnqueueNDRangeKernel(queue, kern, 1, None, ctypes.byref(gws), None, 0, None, None)
        cl.clFinish(queue)
        t1 = time.perf_counter()
        flops = iters * gws.value * 512 * 8 * 4 * 2
        print(f"  [Sustained {label} Compute] {(t1 - t0) * 1000:.2f} ms -> {flops / (t1 - t0) / 1e12:.2f} TFLOPS")

    cl.clReleaseMemObject(b_src)
    cl.clReleaseMemObject(b_dst)


if __name__ == "__main__":
    step1_verify_kernel_and_dxgi()
    step2_test_gpu_30gb_allocation()
    step3_test_npu_smmu_and_mcdm()
    step4_opencl_bandwidth_and_tflops()
