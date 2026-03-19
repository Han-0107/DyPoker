"""
vLLM Provider - 使用vLLM加载本地模型进行推理
支持本地加载大模型 + LoRA adapter，提供与其他provider一致的接口
"""

from __future__ import annotations
import json
import logging
import os
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# 全局单例，避免重复加载模型
_vllm_engine = None
_vllm_tokenizer = None
_loaded_model_path: Optional[str] = None
_loaded_lora_paths: Optional[List[str]] = None
_lora_request = None  # 运行时使用的 LoRARequest 对象


def _detect_lora_adapter(model_path: str) -> Optional[str]:
    """
    检测 model_path 是否为 LoRA adapter 目录。
    如果是，返回 base_model_name_or_path；否则返回 None。
    """
    adapter_config_path = os.path.join(model_path, "adapter_config.json")
    if os.path.isfile(adapter_config_path):
        try:
            with open(adapter_config_path, "r") as f:
                cfg = json.load(f)
            base = cfg.get("base_model_name_or_path")
            if base:
                logger.info(f"Detected LoRA adapter at {model_path}, base model: {base}")
                return base
        except Exception as e:
            logger.warning(f"Failed to read adapter_config.json: {e}")
    return None


def get_vllm_engine(
    model_path: str,
    tensor_parallel_size: int = 1,
    gpu_memory_utilization: float = 0.9,
    max_model_len: int = 4096,
    dtype: str = "auto",
    enforce_eager: bool = False,
    lora_paths: Optional[List[str]] = None,
):
    """
    获取全局vLLM引擎单例（惰性加载）
    自动检测 LoRA adapter 并正确加载 base model + adapter
    """
    global _vllm_engine, _vllm_tokenizer, _loaded_model_path, _loaded_lora_paths, _lora_request

    # 如果已加载且模型相同，直接复用
    if _vllm_engine is not None:
        if model_path == _loaded_model_path and lora_paths == _loaded_lora_paths:
            return _vllm_engine, _vllm_tokenizer
        shutdown_vllm()

    # ── 自动检测 LoRA adapter ──
    base_model = _detect_lora_adapter(model_path)
    actual_lora_path = None

    if base_model is not None:
        # model_path 是 LoRA adapter，实际加载 base model
        actual_lora_path = os.path.abspath(model_path)
        actual_model_path = base_model
        logger.info(f"Loading base model: {actual_model_path}")
        logger.info(f"Will apply LoRA adapter: {actual_lora_path}")
    else:
        actual_model_path = model_path
        # 如果通过 lora_paths 参数指定了 LoRA
        if lora_paths and len(lora_paths) > 0:
            actual_lora_path = lora_paths[0]

    logger.info(f"Loading vLLM model from: {actual_model_path}")
    logger.info(f"  tensor_parallel_size={tensor_parallel_size}")
    logger.info(f"  gpu_memory_utilization={gpu_memory_utilization}")
    logger.info(f"  max_model_len={max_model_len}")

    from vllm import LLM, SamplingParams
    from transformers import AutoTokenizer

    enable_lora = actual_lora_path is not None

    _vllm_engine = LLM(
        model=actual_model_path,
        tensor_parallel_size=tensor_parallel_size,
        gpu_memory_utilization=gpu_memory_utilization,
        max_model_len=max_model_len,
        dtype=dtype,
        enforce_eager=enforce_eager,
        trust_remote_code=True,
        enable_lora=enable_lora,
        max_lora_rank=64 if enable_lora else None,
    )

    # 对于 LoRA adapter，tokenizer 从 adapter 目录加载（可能有 chat_template 覆盖）
    tokenizer_path = actual_lora_path if actual_lora_path else actual_model_path
    _vllm_tokenizer = AutoTokenizer.from_pretrained(
        tokenizer_path, trust_remote_code=True
    )

    # 创建 LoRA request 对象
    if actual_lora_path:
        from vllm.lora.request import LoRARequest
        _lora_request = LoRARequest(
            lora_name="poker_lora",
            lora_int_id=1,
            lora_path=actual_lora_path,
        )
        logger.info(f"LoRA adapter loaded: {actual_lora_path}")
    else:
        _lora_request = None

    _loaded_model_path = model_path
    _loaded_lora_paths = lora_paths

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
    lora_paths: Optional[List[str]] = None,
) -> str:
    """
    使用vLLM进行聊天补全
    构建chat messages -> apply_chat_template -> vLLM generate
    自动使用 LoRA adapter（如果已加载）
    """
    global _lora_request
    from vllm import SamplingParams

    engine, tokenizer = get_vllm_engine(
        model_path=model_path,
        tensor_parallel_size=tensor_parallel_size,
        gpu_memory_utilization=gpu_memory_utilization,
        max_model_len=max_model_len,
        lora_paths=lora_paths,
    )

    # 构建消息
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # 使用tokenizer的chat template构建prompt
    # 仅在模型支持时开启 thinking；对 Qwen2.5 等无思维链 token 的模型强行开启会导致输出退化
    supports_thinking = False
    try:
        vocab = tokenizer.get_vocab()
        supports_thinking = any(tok in vocab for tok in ["<think>", "<｜think｜>"])
    except Exception:
        supports_thinking = False

    try:
        prompt_text = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=supports_thinking,
        )
    except TypeError:
        # 某些 tokenizer 不支持 enable_thinking 参数
        prompt_text = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
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
        outputs = engine.generate(
            [prompt_text],
            sampling_params,
            lora_request=_lora_request,
        )
    finally:
        tqdm.tqdm = _orig_tqdm
    generated_text = outputs[0].outputs[0].text.strip()

    logger.debug(f"LLM raw output: {generated_text[:500]}")
    return generated_text


def shutdown_vllm():
    """关闭vLLM引擎，释放GPU显存"""
    global _vllm_engine, _vllm_tokenizer, _lora_request
    if _vllm_engine is not None:
        del _vllm_engine
        _vllm_engine = None
    if _vllm_tokenizer is not None:
        del _vllm_tokenizer
        _vllm_tokenizer = None
    _lora_request = None
    global _loaded_model_path, _loaded_lora_paths
    _loaded_model_path = None
    _loaded_lora_paths = None

    import torch
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    logger.info("vLLM engine shutdown complete.")
