"""
gpu_utils.py - 自动检测并选择空闲GPU
在 vLLM 加载模型前调用，通过设置 CUDA_VISIBLE_DEVICES 环境变量选择显存最充裕的GPU
"""

import os
import subprocess
import logging

logger = logging.getLogger(__name__)


def get_gpu_free_memory() -> list[tuple[int, float]]:
    """
    查询每张GPU的空闲显存（MiB）
    返回: [(gpu_index, free_memory_mib), ...] 按空闲显存从大到小排序
    """
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.warning(f"nvidia-smi 执行失败: {result.stderr}")
            return []

        gpus = []
        for line in result.stdout.strip().split("\n"):
            parts = line.split(",")
            if len(parts) == 2:
                idx = int(parts[0].strip())
                free = float(parts[1].strip())
                gpus.append((idx, free))

        # 按空闲显存从大到小排序
        gpus.sort(key=lambda x: x[1], reverse=True)
        return gpus

    except FileNotFoundError:
        logger.warning("nvidia-smi 未找到，无法检测GPU")
        return []
    except Exception as e:
        logger.warning(f"GPU检测失败: {e}")
        return []


def auto_select_gpus(
    num_gpus: int = 2,
    min_free_mib: float = 30000,
) -> list[int]:
    """
    自动选择空闲显存最多的 num_gpus 张GPU

    Args:
        num_gpus: 需要的GPU数量
        min_free_mib: 每张GPU最低需要的空闲显存(MiB)，默认30GB

    Returns:
        选中的GPU索引列表，如果找不到足够GPU则返回空列表
    """
    gpus = get_gpu_free_memory()
    if not gpus:
        return []

    # 筛选出满足最低显存要求的GPU
    candidates = [(idx, free) for idx, free in gpus if free >= min_free_mib]

    if len(candidates) < num_gpus:
        logger.warning(
            f"只有 {len(candidates)} 张GPU有 ≥{min_free_mib:.0f} MiB 空闲显存，"
            f"需要 {num_gpus} 张。将选取显存最多的 {num_gpus} 张。"
        )
        # 退而求其次，选显存最多的
        candidates = gpus[:num_gpus]

    selected = [idx for idx, _ in candidates[:num_gpus]]
    return selected


def setup_cuda_devices(num_gpus: int = 2, min_free_mib: float = 30000):
    """
    自动检测空闲GPU并设置 CUDA_VISIBLE_DEVICES 环境变量。
    如果用户已手动设置了 CUDA_VISIBLE_DEVICES，则跳过自动选择。

    Args:
        num_gpus: 需要的GPU数量
        min_free_mib: 每张GPU最低需要的空闲显存(MiB)
    """
    # 如果用户已经手动指定了，尊重用户设置
    if os.environ.get("CUDA_VISIBLE_DEVICES"):
        user_gpus = os.environ["CUDA_VISIBLE_DEVICES"]
        print(f"  🎯 使用用户指定的GPU: CUDA_VISIBLE_DEVICES={user_gpus}")
        return

    selected = auto_select_gpus(num_gpus=num_gpus, min_free_mib=min_free_mib)
    if not selected:
        print("  ⚠️ 无法检测GPU，将使用默认设备")
        return

    # 打印GPU信息
    gpus = get_gpu_free_memory()
    gpu_info = {idx: free for idx, free in gpus}

    cuda_str = ",".join(str(i) for i in selected)
    os.environ["CUDA_VISIBLE_DEVICES"] = cuda_str

    print(f"  🔍 GPU 自动选择结果:")
    for idx, free in gpus:
        marker = " ✅ 选中" if idx in selected else ""
        print(f"     GPU {idx}: {free/1024:.1f} GiB 空闲{marker}")
    print(f"  🎯 CUDA_VISIBLE_DEVICES={cuda_str}")
