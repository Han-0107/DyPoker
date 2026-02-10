"""
vLLM Provider - 使用vLLM加载本地模型进行推理
支持本地加载Qwen3-32B等大模型，提供与其他provider一致的接口
"""

from __future__ import annotations
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# 全局单例，避免重复加载模型
_vllm_engine = None
_vllm_tokenizer = None


def get_vllm_engine(
    model_path: str,
    tensor_parallel_size: int = 1,
    gpu_memory_utilization: float = 0.9,
    max_model_len: int = 4096,
    dtype: str = "auto",
    enforce_eager: bool = False,
):
    """
    获取全局vLLM引擎单例（惰性加载）
    """
    global _vllm_engine, _vllm_tokenizer

    if _vllm_engine is not None:
        return _vllm_engine, _vllm_tokenizer

    logger.info(f"Loading vLLM model from: {model_path}")
    logger.info(f"  tensor_parallel_size={tensor_parallel_size}")
    logger.info(f"  gpu_memory_utilization={gpu_memory_utilization}")
    logger.info(f"  max_model_len={max_model_len}")

    from vllm import LLM, SamplingParams
    from transformers import AutoTokenizer

    _vllm_engine = LLM(
        model=model_path,
        tensor_parallel_size=tensor_parallel_size,
        gpu_memory_utilization=gpu_memory_utilization,
        max_model_len=max_model_len,
        dtype=dtype,
        enforce_eager=enforce_eager,
        trust_remote_code=True,
    )

    _vllm_tokenizer = AutoTokenizer.from_pretrained(
        model_path, trust_remote_code=True
    )

    logger.info("vLLM model loaded successfully!")
    return _vllm_engine, _vllm_tokenizer


def vllm_chat_completion(
    system_prompt: str,
    user_prompt: str,
    model_path: str,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    tensor_parallel_size: int = 1,
    gpu_memory_utilization: float = 0.9,
    max_model_len: int = 4096,
) -> str:
    """
    使用vLLM进行聊天补全
    构建chat messages -> apply_chat_template -> vLLM generate
    """
    from vllm import SamplingParams

    engine, tokenizer = get_vllm_engine(
        model_path=model_path,
        tensor_parallel_size=tensor_parallel_size,
        gpu_memory_utilization=gpu_memory_utilization,
        max_model_len=max_model_len,
    )

    # 构建消息
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # 使用tokenizer的chat template构建prompt
    prompt_text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=True,   # Qwen3: 开启thinking模式，深度推理
    )

    sampling_params = SamplingParams(
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=0.95,
        top_k=20,
        stop=["<|im_end|>", "<|endoftext|>"],
    )

    import tqdm
    # 临时禁用tqdm进度条，避免终端输出推理进度噪音
    _orig_tqdm = tqdm.tqdm
    tqdm.tqdm = lambda *a, **kw: _orig_tqdm(*a, **{**kw, "disable": True})
    try:
        outputs = engine.generate([prompt_text], sampling_params)
    finally:
        tqdm.tqdm = _orig_tqdm
    generated_text = outputs[0].outputs[0].text.strip()

    return generated_text


def shutdown_vllm():
    """关闭vLLM引擎，释放GPU显存"""
    global _vllm_engine, _vllm_tokenizer
    if _vllm_engine is not None:
        del _vllm_engine
        _vllm_engine = None
    if _vllm_tokenizer is not None:
        del _vllm_tokenizer
        _vllm_tokenizer = None

    import torch
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    logger.info("vLLM engine shutdown complete.")
