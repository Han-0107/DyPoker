"""
LLM Agent - 利用本地 vLLM 部署的大语言模型进行德州扑克决策的模块

支持 Multi-Agent 协调决策：
  - LLMAgent: 标准策略 Agent (SFT/GRPO 训练)
  - OpponentAnalyzer: 对手策略分析 Agent
  - Coordinator: 多 Agent 协调器
"""

from .agent import LLMAgent
from .prompt_builder import PromptBuilder
from .opponent_analyzer import OpponentAnalyzer, StrategyType, OpponentStats
from .coordinator import Coordinator

__all__ = [
    "LLMAgent",
    "PromptBuilder",
    "OpponentAnalyzer",
    "StrategyType",
    "OpponentStats",
    "Coordinator",
]
