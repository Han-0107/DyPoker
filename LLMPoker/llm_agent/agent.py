"""
LLMAgent - 利用LLM进行德州扑克决策的代理
通过HTTP API与游戏服务器通信，实现解耦
"""

from __future__ import annotations
import json
import logging
import re
import time
from typing import Dict, Any, Optional

import requests

from .prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)


class LLMAgent:
    """
    LLM 扑克代理
    通过调用LLM API根据游戏状态做出决策
    通过HTTP API与游戏服务器通信
    """

    def __init__(
        self,
        player_name: str,
        game_server_url: str = "http://localhost:8000",
        llm_api_url: str = "http://localhost:11434/api/chat",  # Ollama默认地址
        llm_model: str = "llama3.1:8b",
        llm_api_key: Optional[str] = None,
        llm_provider: str = "ollama",  # "ollama", "openai", "custom", "vllm"
        temperature: float = 0.7,
        max_retries: int = 3,
        # vLLM专用参数
        vllm_tensor_parallel_size: int = 1,
        vllm_gpu_memory_utilization: float = 0.9,
        vllm_max_model_len: int = 4096,
    ):
        self.player_name = player_name
        self.game_server_url = game_server_url.rstrip("/")
        self.llm_api_url = llm_api_url
        self.llm_model = llm_model
        self.llm_api_key = llm_api_key
        self.llm_provider = llm_provider
        self.temperature = temperature
        self.max_retries = max_retries
        self.prompt_builder = PromptBuilder()
        self.decision_history: list = []
        # vLLM参数
        self.vllm_tensor_parallel_size = vllm_tensor_parallel_size
        self.vllm_gpu_memory_utilization = vllm_gpu_memory_utilization
        self.vllm_max_model_len = vllm_max_model_len

    # =========================================================
    #  与游戏服务器通信
    # =========================================================

    def get_game_state(self) -> Dict[str, Any]:
        """从游戏服务器获取当前游戏状态"""
        resp = requests.get(
            f"{self.game_server_url}/game/state",
            params={"player_name": self.player_name},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def submit_action(self, action: str, amount: int = 0) -> Dict[str, Any]:
        """向游戏服务器提交动作"""
        payload = {
            "player_name": self.player_name,
            "action": action,
            "amount": amount,
        }
        resp = requests.post(
            f"{self.game_server_url}/game/action",
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    # =========================================================
    #  LLM 调用
    # =========================================================

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """调用LLM API获取响应"""
        if self.llm_provider == "ollama":
            return self._call_ollama(system_prompt, user_prompt)
        elif self.llm_provider == "openai":
            return self._call_openai(system_prompt, user_prompt)
        elif self.llm_provider == "vllm":
            return self._call_vllm(system_prompt, user_prompt)
        elif self.llm_provider == "custom":
            return self._call_custom(system_prompt, user_prompt)
        else:
            raise ValueError(f"Unknown LLM provider: {self.llm_provider}")

    def _call_ollama(self, system_prompt: str, user_prompt: str) -> str:
        """调用 Ollama API"""
        payload = {
            "model": self.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {
                "temperature": self.temperature,
            },
        }
        resp = requests.post(self.llm_api_url, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"]

    def _call_openai(self, system_prompt: str, user_prompt: str) -> str:
        """调用 OpenAI 兼容API（支持OpenAI, DeepSeek, etc.）"""
        headers = {
            "Content-Type": "application/json",
        }
        if self.llm_api_key:
            headers["Authorization"] = f"Bearer {self.llm_api_key}"

        payload = {
            "model": self.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": 500,
        }
        resp = requests.post(self.llm_api_url, json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def _call_custom(self, system_prompt: str, user_prompt: str) -> str:
        """调用自定义API（用户可自行扩展）"""
        payload = {
            "system": system_prompt,
            "user": user_prompt,
            "model": self.llm_model,
            "temperature": self.temperature,
        }
        resp = requests.post(self.llm_api_url, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", data.get("content", ""))

    def _call_vllm(self, system_prompt: str, user_prompt: str) -> str:
        """调用本地vLLM引擎（直接Python调用，无需HTTP）"""
        from .vllm_provider import vllm_chat_completion

        return vllm_chat_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_path=self.llm_model,  # vllm模式下llm_model存的是模型路径
            temperature=self.temperature,
            max_tokens=512,
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
        """解析LLM的JSON响应"""
        # 尝试从回复中提取JSON
        json_match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
        else:
            raise ValueError(f"No JSON found in LLM response: {raw[:200]}")

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

            if amount < min_total:
                amount = min_total
            if amount >= your_chips:
                action = "all_in"
                amount = 0

        return {
            "action": action,
            "amount": int(amount) if action == "raise" else 0,
            "reasoning": reasoning,
        }

    # =========================================================
    #  自动运行循环
    # =========================================================

    def run_loop(self, poll_interval: float = 1.0):
        """
        持续运行的代理循环：
        1. 轮询游戏服务器获取状态
        2. 如果轮到自己，调用LLM做出决策
        3. 提交决策给服务器
        """
        logger.info(f"[{self.player_name}] Agent loop started")
        logger.info(f"  Game server: {self.game_server_url}")
        logger.info(f"  LLM: {self.llm_provider} / {self.llm_model}")

        while True:
            try:
                state = self.get_game_state()

                # 检查游戏是否结束
                if state.get("phase") == "FINISHED":
                    logger.info(f"[{self.player_name}] Game finished")
                    break

                # 检查是否轮到自己
                if state.get("current_player") != self.player_name:
                    time.sleep(poll_interval)
                    continue

                # 做出决策
                decision = self.make_decision(state)

                # 提交动作
                result = self.submit_action(decision["action"], decision.get("amount", 0))
                logger.info(f"[{self.player_name}] Action result: {result}")

                time.sleep(0.5)  # 短暂延迟

            except requests.exceptions.ConnectionError:
                logger.error(f"[{self.player_name}] Cannot connect to game server")
                time.sleep(3)
            except KeyboardInterrupt:
                logger.info(f"[{self.player_name}] Agent stopped by user")
                break
            except Exception as e:
                logger.error(f"[{self.player_name}] Error: {e}")
                time.sleep(2)


class RandomAgent:
    """随机决策代理（用于测试，不需要LLM）"""

    def __init__(self, player_name: str):
        self.player_name = player_name

    def make_decision(self, game_state: Dict[str, Any]) -> Dict[str, Any]:
        import random
        valid_actions = game_state.get("valid_actions", ["fold"])

        # 简单策略：70%概率check/call, 20%概率raise, 10%概率fold
        r = random.random()
        if r < 0.1 and "fold" in valid_actions:
            return {"action": "fold", "amount": 0, "reasoning": "Random fold"}
        elif r < 0.3 and "raise" in valid_actions:
            min_raise = game_state.get("min_raise", 10)
            call_amount = game_state.get("call_amount", 0)
            amount = call_amount + min_raise * random.randint(1, 3)
            return {"action": "raise", "amount": amount, "reasoning": "Random raise"}
        elif "call" in valid_actions:
            return {"action": "call", "amount": 0, "reasoning": "Random call"}
        elif "check" in valid_actions:
            return {"action": "check", "amount": 0, "reasoning": "Random check"}
        else:
            return {"action": "fold", "amount": 0, "reasoning": "Random fallback fold"}
