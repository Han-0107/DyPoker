"""
LLMAgent - 利用本地 vLLM 进行德州扑克决策的代理
支持两种模式：
  - 单 Agent 模式：直接由标准策略 Agent 做出决策
  - Multi-Agent 模式：标准策略 Agent + 对手分析 Agent + Coordinator 协调决策
"""

from __future__ import annotations
import json
import logging
import re
import time
from typing import Dict, Any, Optional, List

from .prompt_builder import PromptBuilder
from .opponent_analyzer import OpponentAnalyzer, StrategyType
from .coordinator import Coordinator

logger = logging.getLogger(__name__)


class LLMAgent:
    """
    LLM 扑克代理（本地 vLLM）
    通过本地加载的 vLLM 模型根据游戏状态做出决策

    支持 multi-agent 模式:
      - Agent 1 (Standard Strategy): 经过 SFT/GRPO 训练的标准策略
      - Agent 2 (Opponent Analyzer): 分析对手历史行为并分类策略类型
      - Coordinator: 综合两个 Agent 的建议给出最终决策
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
        enable_multi_agent: bool = True,
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

        # Multi-Agent 组件
        self.enable_multi_agent = enable_multi_agent
        self.opponent_analyzer = OpponentAnalyzer(my_name=player_name)
        self.coordinator = Coordinator()

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
        根据游戏状态调用LLM做出决策。
        如果启用了 multi-agent 模式，将执行三步流程：
          1. 标准策略 Agent 给出基准决策
          2. 对手分析 Agent 分析对手策略类型
          3. Coordinator 综合两者给出最终决策

        返回: {"action": str, "amount": int, "reasoning": str}
        """
        # ── Step 1: 标准策略 Agent 决策 ──
        standard_decision = self._standard_agent_decision(game_state)

        if not self.enable_multi_agent:
            return standard_decision

        # ── Step 2: 对手分析 Agent ──
        opponent_analysis = self._opponent_analysis_step(game_state)

        # 如果对手分析没有有效数据，直接返回标准决策
        if not opponent_analysis or opponent_analysis.strip() == "No opponent data available yet.":
            logger.info(f"[{self.player_name}] No opponent data, using standard decision only")
            return standard_decision

        # ── Step 3: Coordinator 综合决策 ──
        final_decision = self._coordinator_decision(
            game_state, standard_decision, opponent_analysis
        )

        return final_decision

    def _standard_agent_decision(self, game_state: Dict[str, Any]) -> Dict[str, Any]:
        """
        标准策略 Agent 决策（原始的 SFT/GRPO 训练模型）
        """
        user_prompt = self.prompt_builder.build_decision_prompt(
            game_state, self.player_name
        )
        system_prompt = self.prompt_builder.SYSTEM_PROMPT

        logger.info(f"\n{'─'*40}")
        logger.info(f"[{self.player_name}] [Standard Agent] Asking LLM for decision...")
        logger.debug(f"[{self.player_name}] User prompt:\n{user_prompt}")

        for attempt in range(self.max_retries):
            try:
                raw_response = self._call_llm(system_prompt, user_prompt)
                logger.info(f"[{self.player_name}] [Standard Agent] Raw response (attempt {attempt+1}): {raw_response[:300]}")
                decision = self._parse_llm_response(raw_response, game_state)
                decision["raw_response"] = raw_response
                decision["input_prompt"] = user_prompt
                decision["agent"] = "standard"

                logger.info(f"[{self.player_name}] [Standard Agent] Decision: {decision['action']} "
                            f"(amount={decision.get('amount', 0)})")
                return decision

            except Exception as e:
                logger.warning(
                    f"[{self.player_name}] [Standard Agent] Attempt {attempt+1} failed: {e}"
                )
                if attempt < self.max_retries - 1:
                    time.sleep(0.5)

        # ── 智能回退策略 ──
        logger.warning(f"[{self.player_name}] [Standard Agent] All attempts failed, using smart fallback")
        return self._smart_fallback(game_state)

    def _opponent_analysis_step(self, game_state: Dict[str, Any]) -> str:
        """
        对手分析 Agent 步骤：
        使用 OpponentAnalyzer 的统计数据生成对手策略分析文本。
        基于规则的分析（不需要额外 LLM 调用，效率更高）。
        """
        players = game_state.get("players", [])
        active_opponents = [
            p["name"] for p in players
            if p["name"] != self.player_name and p.get("is_active", True)
        ]

        if not active_opponents:
            return ""

        # 使用 OpponentAnalyzer 生成分析文本
        analysis_text = self.opponent_analyzer.get_opponent_analysis_text(
            opponents=active_opponents,
            game_state=game_state,
        )

        logger.info(f"[{self.player_name}] [Opponent Analyzer] Analysis:\n{analysis_text[:500]}")
        return analysis_text

    def _coordinator_decision(
        self,
        game_state: Dict[str, Any],
        standard_decision: Dict[str, Any],
        opponent_analysis: str,
    ) -> Dict[str, Any]:
        """
        Coordinator 综合决策：结合标准策略和对手分析给出最终决策。
        """
        coordinator_prompt = Coordinator.build_coordinator_prompt(
            game_state=game_state,
            player_name=self.player_name,
            standard_decision=standard_decision,
            opponent_analysis=opponent_analysis,
        )
        coordinator_system = Coordinator.COORDINATOR_SYSTEM_PROMPT

        logger.info(f"[{self.player_name}] [Coordinator] Generating final decision...")
        logger.debug(f"[{self.player_name}] [Coordinator] Prompt:\n{coordinator_prompt}")

        for attempt in range(self.max_retries):
            try:
                raw_response = self._call_llm(coordinator_system, coordinator_prompt)
                logger.info(f"[{self.player_name}] [Coordinator] Raw response (attempt {attempt+1}): {raw_response[:300]}")

                final_decision = Coordinator.parse_coordinator_response(
                    raw=raw_response,
                    game_state=game_state,
                    fallback_decision=standard_decision,
                )
                final_decision["raw_response"] = raw_response
                final_decision["standard_decision"] = standard_decision.get("action")
                final_decision["agent"] = "coordinator"

                logger.info(
                    f"[{self.player_name}] [Coordinator] Final: {final_decision['action']} "
                    f"(standard was: {standard_decision.get('action')})"
                )
                self.decision_history.append(final_decision)
                return final_decision

            except Exception as e:
                logger.warning(
                    f"[{self.player_name}] [Coordinator] Attempt {attempt+1} failed: {e}"
                )
                if attempt < self.max_retries - 1:
                    time.sleep(0.5)

        # Coordinator 失败时回退到标准策略 Agent 的决策
        logger.warning(f"[{self.player_name}] [Coordinator] All attempts failed, using standard agent decision")
        standard_decision["agent"] = "standard_fallback"
        self.decision_history.append(standard_decision)
        return standard_decision

    def record_hand_result(
        self,
        action_history: List[Dict[str, Any]],
        positions: Dict[str, str],
        big_blind: int = 10,
    ):
        """
        记录一手牌结束后的对手行为数据。
        应在每手牌结束后由 main 循环调用。

        Args:
            action_history: 该手牌的行动历史
            positions: 玩家位置映射 {player_name: position_name}
            big_blind: 大盲注额度
        """
        if self.enable_multi_agent:
            self.opponent_analyzer.record_hand_actions(
                action_history=action_history,
                positions=positions,
                big_blind=big_blind,
            )

    def get_opponent_summaries(self) -> List[Dict[str, Any]]:
        """获取所有对手的策略分析摘要（用于日志和调试）"""
        summaries = []
        for opp_name in self.opponent_analyzer.opponent_stats:
            summaries.append(self.opponent_analyzer.get_stats_summary(opp_name))
        return summaries

    @staticmethod
    def _smart_fallback(game_state: Dict[str, Any]) -> Dict[str, Any]:
        """智能回退策略"""
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

        # ── 处理raise金额（amount 语义为 "raise to" 目标总额）──
        if action == "raise":
            min_raise = game_state.get("min_raise", 10)
            call_amount = game_state.get("call_amount", 0)
            current_bet = game_state.get("current_bet", 0)
            your_chips = game_state.get("your_chips", 0)
            # 玩家当前已下注额
            player_current_bet = current_bet - call_amount
            # 最小 raise to 目标（优先使用引擎提供的精确值）
            min_raise_to = game_state.get("min_raise_to", current_bet + min_raise)

            if isinstance(amount, str):
                try:
                    amount = float(amount)
                except ValueError:
                    amount = min_raise_to

            logger.info(f"[{self.player_name}] [Standard Agent] Raise amount from LLM: {amount}, "
                        f"current_bet={current_bet}, min_raise={min_raise}, "
                        f"min_raise_to={min_raise_to}, player_current_bet={player_current_bet}")

            # 如果 LLM 给出的金额看起来是"额外投入"而非"raise to"，进行修正
            # 判断依据：如果 amount < current_bet 且 current_bet > 0，
            # 则 LLM 可能给的是额外投入量，需要转换为 raise to
            if amount > 0 and amount < current_bet and current_bet > 0:
                logger.info(f"[{self.player_name}] Converting amount {amount} from 'extra chips' "
                            f"to 'raise to': {player_current_bet + amount}")
                amount = player_current_bet + amount  # 转换为 raise to

            # 如果 raise_to <= current_bet，说明实际上是 call 而非 raise
            if amount <= current_bet and call_amount > 0 and "call" in valid_actions:
                action = "call"
                amount = 0
            elif amount < min_raise_to:
                # 强制提到最小 raise to
                logger.info(f"[{self.player_name}] Raise amount {amount} below min_raise_to "
                            f"{min_raise_to}, forcing to {min_raise_to}")
                amount = min_raise_to

            # 检查是否超过筹码（raise to 需要投入 amount - player_current_bet）
            chips_needed = amount - player_current_bet
            if action == "raise" and chips_needed >= your_chips:
                action = "all_in"
                amount = 0

        return {
            "action": action,
            "amount": int(amount) if action == "raise" else 0,
            "reasoning": reasoning,
            "thinking": thinking,
        }
