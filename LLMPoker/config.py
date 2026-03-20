"""
配置文件 - 项目所有可配置项（仅支持本地 vLLM 部署）
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict


@dataclass
class LLMConfig:
    """LLM配置（本地 vLLM）"""
    model: str = "/research/d7/gds/yhhan25/.cache/modelscope/hub/models/Qwen/Qwen3-32B"
    temperature: float = 0.7
    max_retries: int = 3
    tensor_parallel_size: int = 1     # GPU并行数
    gpu_memory_utilization: float = 0.9
    max_model_len: int = 4096
    lora_paths: Optional[List[str]] = None  # 可选 LoRA 适配器目录列表

    @classmethod
    def qwen3_32b(
        cls,
        model_path: str = "/research/d7/gds/yhhan25/.cache/modelscope/hub/models/Qwen/Qwen3-32B",
        tensor_parallel_size: int = 1,
        gpu_memory_utilization: float = 0.9,
        max_model_len: int = 4096,
        lora_paths: Optional[List[str]] = None,
    ) -> "LLMConfig":
        """快速创建本地Qwen3-32B vLLM配置"""
        return cls(
            model=model_path,
            temperature=0.7,
            tensor_parallel_size=tensor_parallel_size,
            gpu_memory_utilization=gpu_memory_utilization,
            max_model_len=max_model_len,
            lora_paths=lora_paths,
        )


@dataclass
class PlayerConfig:
    """玩家配置"""
    name: str
    chips: int = 1000
    agent_type: str = "llm"  # "llm", "random", "human"
    llm_config: Optional[LLMConfig] = None


@dataclass
class GameConfig:
    """游戏整体配置"""
    small_blind: int = 5
    big_blind: int = 10
    num_hands: int = 20           # 总共玩多少手
    seed: Optional[int] = 42     # 随机种子，None则完全随机
    players: List[PlayerConfig] = field(default_factory=list)

    @classmethod
    def default_2player(cls) -> "GameConfig":
        """默认2人对局配置"""
        llm = LLMConfig.qwen3_32b()
        return cls(
            players=[
                PlayerConfig(name="LLM_Alice", chips=1000, agent_type="llm", llm_config=llm),
                PlayerConfig(name="LLM_Bob", chips=1000, agent_type="llm", llm_config=llm),
            ],
            num_hands=20,
        )

    @classmethod
    def llm_vs_random(cls) -> "GameConfig":
        """LLM vs 随机代理"""
        llm = LLMConfig.qwen3_32b()
        return cls(
            players=[
                PlayerConfig(name="LLM_Player", chips=1000, agent_type="llm", llm_config=llm),
                PlayerConfig(name="Random_Bot", chips=1000, agent_type="random"),
            ],
            num_hands=50,
        )

    @classmethod
    def human_vs_llm(
        cls,
        n_ai: int = 3,
        human_name: str = "You",
        chips: int = 1000,
        num_hands: int = 20,
        model_path: str = "/research/d7/gds/yhhan25/.cache/modelscope/hub/models/Qwen/Qwen3-32B",
        tensor_parallel_size: int = 1,
    ) -> "GameConfig":
        """人类 vs LLM 对局"""
        llm = LLMConfig.qwen3_32b(
            model_path=model_path,
            tensor_parallel_size=tensor_parallel_size,
        )
        players = [
            PlayerConfig(name=human_name, chips=chips, agent_type="human"),
        ]
        ai_names = ["Alice", "Bob", "Charlie", "Diana", "Eve", "Frank",
                     "Grace", "Hank", "Ivy", "Jack"]
        for i in range(n_ai):
            players.append(PlayerConfig(
                name=ai_names[i] if i < len(ai_names) else f"AI_{i+1}",
                chips=chips,
                agent_type="llm",
                llm_config=llm,
            ))
        return cls(players=players, num_hands=num_hands)

    @classmethod
    def multi_player(cls, n: int = 4) -> "GameConfig":
        """多人对局"""
        llm = LLMConfig.qwen3_32b()
        players = [
            PlayerConfig(
                name=f"LLM_Player_{i+1}",
                chips=1000,
                agent_type="llm",
                llm_config=llm,
            )
            for i in range(n)
        ]
        return cls(players=players, num_hands=30)

    @classmethod
    def qwen3_32b_game(
        cls,
        n: int = 6,
        chips: int = 1000,
        num_hands: int = 5,
        tensor_parallel_size: int = 2,
        model_path: str = "/research/d7/gds/yhhan25/.cache/modelscope/hub/models/Qwen/Qwen3-32B",
    ) -> "GameConfig":
        """Qwen3-32B 多人对局"""
        llm = LLMConfig.qwen3_32b(
            model_path=model_path,
            tensor_parallel_size=tensor_parallel_size,
        )
        player_names = ["Alice", "Bob", "Charlie", "Diana", "Eve", "Frank",
                        "Grace", "Hank", "Ivy", "Jack"]
        players = [
            PlayerConfig(
                name=player_names[i] if i < len(player_names) else f"Player_{i+1}",
                chips=chips,
                agent_type="llm",
                llm_config=llm,
            )
            for i in range(n)
        ]
        return cls(players=players, num_hands=num_hands)
