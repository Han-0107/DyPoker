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
        lora_paths: Optional[list] = None,
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
        self.lora_paths = lora_paths

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
            lora_paths=self.lora_paths,
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
        logger.debug(f"[{self.player_name}] User prompt:\n{user_prompt}")

        for attempt in range(self.max_retries):
            try:
                raw_response = self._call_llm(system_prompt, user_prompt)
                logger.info(f"[{self.player_name}] Raw LLM response (attempt {attempt+1}): {raw_response[:300]}")
                decision = self._parse_llm_response(raw_response, game_state)
                decision["raw_response"] = raw_response
                decision["input_prompt"] = user_prompt

                logger.info(f"[{self.player_name}] LLM decision: {decision['action']} "
                            f"(amount={decision.get('amount', 0)})")
                self.decision_history.append(decision)
                return decision

            except Exception as e:
                logger.warning(
                    f"[{self.player_name}] LLM attempt {attempt+1} failed: {e}"
                )
                if attempt < self.max_retries - 1:
                    time.sleep(0.5)

        # ── 智能回退策略 ──
        logger.warning(f"[{self.player_name}] All LLM attempts failed, using smart fallback")
        valid = game_state.get("valid_actions", [])
        call_amount = game_state.get("call_amount", 0)
        your_chips = game_state.get("your_chips", 0)
        pot = game_state.get("pot", 0)

        # 智能回退：根据底池赔率和手牌决定
        if "check" in valid:
            # 能check就check，不要白白fold
            return {"action": "check", "amount": 0, "reasoning": "Fallback: check (free to see)"}
        elif "call" in valid and call_amount <= pot * 0.3 and your_chips > call_amount * 3:
            # 跟注金额小于底池30%且筹码充足，倾向于call
            return {"action": "call", "amount": 0, "reasoning": "Fallback: call (good pot odds)"}
        elif "call" in valid and call_amount <= game_state.get("big_blind", 10):
            # 只需要跟一个大盲，值得看看
            return {"action": "call", "amount": 0, "reasoning": "Fallback: call (only 1 BB)"}
        elif "fold" in valid:
            return {"action": "fold", "amount": 0, "reasoning": "Fallback: fold"}
        else:
            return {"action": valid[0] if valid else "fold", "amount": 0,
                    "reasoning": "Fallback: first valid action"}

    def _parse_llm_response(
        self, raw: str, game_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """解析LLM的JSON响应，支持 Qwen3 thinking 模式和多种输出格式"""
        # ── 分离 thinking 内容 ──
        thinking = ""
        answer = raw
        think_match = re.search(r'<think>(.*?)</think>', raw, re.DOTALL)
        if think_match:
            thinking = think_match.group(1).strip()
            answer = raw[think_match.end():].strip()

        action = None
        reasoning = ""
        amount = 0

        # ── 尝试从正式回答中提取JSON ──
        json_match = re.search(r'\{[^{}]*\}', answer, re.DOTALL)
        if not json_match:
            json_match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)

        if json_match:
            try:
                data = json.loads(json_match.group())
                action = data.get("action", "").lower().strip()
                reasoning = data.get("reasoning", "")
                amount = data.get("raise_amount", 0)
            except json.JSONDecodeError:
                pass

        # ── 如果JSON解析失败，尝试从文本中提取动作 ──
        if not action:
            text_lower = answer.lower() if answer else raw.lower()
            # 按优先级匹配（先匹配更具体的）
            if re.search(r'\ball[\s_-]?in\b', text_lower):
                action = "all_in"
            elif re.search(r'\braise\b', text_lower):
                action = "raise"
                # 尝试提取金额
                amt_match = re.search(r'raise\s*(?:to\s*)?(\d+(?:\.\d+)?)', text_lower)
                if amt_match:
                    amount = float(amt_match.group(1))
            elif re.search(r'\bbet\b', text_lower):
                action = "raise"
                amt_match = re.search(r'bet\s*(\d+(?:\.\d+)?)', text_lower)
                if amt_match:
                    amount = float(amt_match.group(1))
            elif re.search(r'\bcall\b', text_lower):
                action = "call"
            elif re.search(r'\bcheck\b', text_lower):
                action = "check"
            elif re.search(r'\bfold\b', text_lower):
                action = "fold"
            else:
                raise ValueError(f"Cannot parse action from LLM response: {raw[:300]}")

        # ── 验证动作合法性 ──
        valid_actions = game_state.get("valid_actions", [])
        if action not in valid_actions:
            # 智能映射
            if action == "bet" and "raise" in valid_actions:
                action = "raise"
            elif action == "check" and "call" in valid_actions:
                action = "call"
            elif action == "call" and "check" in valid_actions:
                action = "check"
            elif action == "raise" and "all_in" in valid_actions and "raise" not in valid_actions:
                action = "all_in"
            elif action in ("fold",) and "check" in valid_actions:
                # 不要在能check的时候fold
                action = "check"
            elif "check" in valid_actions:
                action = "check"
            elif "call" in valid_actions:
                action = "call"
            else:
                action = "fold"

        # ── 处理raise金额 ──
        if action == "raise":
            min_raise = game_state.get("min_raise", 10)
            call_amount = game_state.get("call_amount", 0)
            your_chips = game_state.get("your_chips", 0)
            min_total = call_amount + min_raise

            if isinstance(amount, str):
                try:
                    amount = float(amount)
                except ValueError:
                    amount = min_total

            # 如果raise_amount <= call_amount，说明实际上是call而非raise
            if amount <= call_amount and call_amount > 0 and "call" in valid_actions:
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
