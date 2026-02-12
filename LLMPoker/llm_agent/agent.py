"""
LLMAgent - 利用本地 vLLM 进行德州扑克决策的代理
仅支持本地部署模型，通过 vLLM 引擎直接推理
"""

from __future__ import annotations
import json
import logging
import re
import time
from typing import Dict, Any, Optional

from .prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)


class LLMAgent:
    """
    LLM 扑克代理（本地 vLLM）
    通过本地加载的 vLLM 模型根据游戏状态做出决策
    """

    def __init__(
        self,
        player_name: str,
        llm_model: str,
        temperature: float = 0.7,
        max_retries: int = 3,
        vllm_tensor_parallel_size: int = 1,
        vllm_gpu_memory_utilization: float = 0.9,
        vllm_max_model_len: int = 4096,
    ):
        self.player_name = player_name
        self.llm_model = llm_model
        self.temperature = temperature
        self.max_retries = max_retries
        self.prompt_builder = PromptBuilder()
        self.decision_history: list = []
        # vLLM参数
        self.vllm_tensor_parallel_size = vllm_tensor_parallel_size
        self.vllm_gpu_memory_utilization = vllm_gpu_memory_utilization
        self.vllm_max_model_len = vllm_max_model_len

    # =========================================================
    #  LLM 调用（本地 vLLM）
    # =========================================================

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """调用本地 vLLM 引擎获取响应"""
        from .vllm_provider import vllm_chat_completion

        return vllm_chat_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_path=self.llm_model,
            temperature=self.temperature,
            max_tokens=4096,
            tensor_parallel_size=self.vllm_tensor_parallel_size,
            gpu_memory_utilization=self.vllm_gpu_memory_utilization,
            max_model_len=self.vllm_max_model_len,
        )

    # =========================================================
    #  决策逻辑
    # =========================================================

    def make_decision(self, game_state: Dict[str, Any]) -> Dict[str, Any]:
        """
        根据游戏状态调用LLM做出决策
        返回: {"action": str, "amount": int, "reasoning": str}
        """
        user_prompt = self.prompt_builder.build_decision_prompt(
            game_state, self.player_name
        )
        system_prompt = self.prompt_builder.SYSTEM_PROMPT

        logger.info(f"\n{'─'*40}")
        logger.info(f"[{self.player_name}] Asking LLM for decision...")

        for attempt in range(self.max_retries):
            try:
                raw_response = self._call_llm(system_prompt, user_prompt)
                decision = self._parse_llm_response(raw_response, game_state)
                decision["raw_response"] = raw_response
                decision["input_prompt"] = user_prompt

                logger.info(f"[{self.player_name}] LLM decision: {decision}")
                self.decision_history.append(decision)
                return decision

            except Exception as e:
                logger.warning(
                    f"[{self.player_name}] LLM attempt {attempt+1} failed: {e}"
                )
                if attempt < self.max_retries - 1:
                    time.sleep(1)

        # 回退策略：尝试check，否则fold
        logger.warning(f"[{self.player_name}] All LLM attempts failed, using fallback")
        valid = game_state.get("valid_actions", [])
        if "check" in valid:
            return {"action": "check", "amount": 0, "reasoning": "Fallback: check"}
        return {"action": "fold", "amount": 0, "reasoning": "Fallback: fold"}

    def _parse_llm_response(
        self, raw: str, game_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """解析LLM的JSON响应，支持 Qwen3 thinking 模式"""
        # ── 分离 thinking 内容 ──
        thinking = ""
        answer = raw
        think_match = re.search(r'<think>(.*?)</think>', raw, re.DOTALL)
        if think_match:
            thinking = think_match.group(1).strip()
            # 取 </think> 之后的内容作为正式回答
            answer = raw[think_match.end():].strip()

        # 尝试从正式回答中提取JSON
        json_match = re.search(r'\{[^{}]*\}', answer, re.DOTALL)
        if not json_match:
            # 回退：尝试从整个原始回复中提取
            json_match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
        else:
            raise ValueError(f"No JSON found in LLM response: {raw[:300]}")

        action = data.get("action", "fold").lower().strip()
        reasoning = data.get("reasoning", "")
        amount = data.get("raise_amount", 0)

        # 验证动作合法性
        valid_actions = game_state.get("valid_actions", [])
        if action not in valid_actions:
            # 尝试智能映射
            if action == "bet" and "raise" in valid_actions:
                action = "raise"
            elif action == "check" and "call" in valid_actions:
                action = "call"
            elif action == "call" and "check" in valid_actions:
                action = "check"
            elif "check" in valid_actions:
                action = "check"
            else:
                action = "fold"

        # 处理raise金额
        if action == "raise":
            min_raise = game_state.get("min_raise", 10)
            call_amount = game_state.get("call_amount", 0)
            your_chips = game_state.get("your_chips", 0)
            min_total = call_amount + min_raise

            if isinstance(amount, str):
                try:
                    amount = int(amount)
                except ValueError:
                    amount = min_total

            # 如果raise_amount <= call_amount，说明实际上是call而非raise
            if amount == call_amount and call_amount > 0 and "call" in valid_actions:
                action = "call"
                amount = 0
            elif amount < min_total:
                amount = min_total

            if action == "raise" and amount >= your_chips:
                action = "all_in"
                amount = 0

        return {
            "action": action,
            "amount": int(amount) if action == "raise" else 0,
            "reasoning": reasoning,
            "thinking": thinking,
        }
