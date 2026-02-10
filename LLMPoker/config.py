"""
配置文件 - 项目所有可配置项
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict


@dataclass
class ServerConfig:
    """游戏服务器配置"""
    host: str = "0.0.0.0"
    port: int = 8000


@dataclass
class LLMConfig:
    """LLM配置"""
    provider: str = "ollama"          # "ollama", "openai", "custom", "vllm"
    model: str = "llama3.1:8b"        # 模型名称或本地路径
    api_url: str = "http://localhost:11434/api/chat"  # API地址
    api_key: Optional[str] = None     # API密钥（OpenAI等需要）
    temperature: float = 0.7
    max_retries: int = 3
    # vLLM专用参数
    tensor_parallel_size: int = 1     # GPU并行数
    gpu_memory_utilization: float = 0.9
    max_model_len: int = 4096

    @classmethod
    def ollama(cls, model: str = "llama3.1:8b") -> "LLMConfig":
        """快速创建Ollama配置"""
        return cls(
            provider="ollama",
            model=model,
            api_url="http://localhost:11434/api/chat",
        )

    @classmethod
    def openai(cls, model: str = "gpt-4o-mini", api_key: str = "") -> "LLMConfig":
        """快速创建OpenAI配置"""
        return cls(
            provider="openai",
            model=model,
            api_url="https://api.openai.com/v1/chat/completions",
            api_key=api_key,
        )

    @classmethod
    def deepseek(cls, model: str = "deepseek-chat", api_key: str = "") -> "LLMConfig":
        """快速创建DeepSeek配置"""
        return cls(
            provider="openai",
            model=model,
            api_url="https://api.deepseek.com/v1/chat/completions",
            api_key=api_key,
        )

    @classmethod
    def qwen3_32b(
        cls,
        model_path: str = "/research/d7/gds/yhhan25/.cache/modelscope/hub/models/Qwen/Qwen3-32B",
        tensor_parallel_size: int = 2,
        gpu_memory_utilization: float = 0.9,
        max_model_len: int = 4096,
    ) -> "LLMConfig":
        """快速创建本地Qwen3-32B vLLM配置"""
        return cls(
            provider="vllm",
            model=model_path,
            api_url="",  # vllm本地调用，不需要API地址
            temperature=0.7,
            tensor_parallel_size=tensor_parallel_size,
            gpu_memory_utilization=gpu_memory_utilization,
            max_model_len=max_model_len,
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
    server: ServerConfig = field(default_factory=ServerConfig)
    small_blind: int = 5
    big_blind: int = 10
    num_hands: int = 20           # 总共玩多少手
    seed: Optional[int] = 42     # 随机种子，None则完全随机
    players: List[PlayerConfig] = field(default_factory=list)

    @classmethod
    def default_2player(cls) -> "GameConfig":
        """默认2人对局配置"""
        llm1 = LLMConfig.ollama()
        llm2 = LLMConfig.ollama()
        return cls(
            players=[
                PlayerConfig(name="LLM_Alice", chips=1000, agent_type="llm", llm_config=llm1),
                PlayerConfig(name="LLM_Bob", chips=1000, agent_type="llm", llm_config=llm2),
            ],
            num_hands=20,
        )

    @classmethod
    def llm_vs_random(cls) -> "GameConfig":
        """LLM vs 随机代理"""
        llm = LLMConfig.ollama()
        return cls(
            players=[
                PlayerConfig(name="LLM_Player", chips=1000, agent_type="llm", llm_config=llm),
                PlayerConfig(name="Random_Bot", chips=1000, agent_type="random"),
            ],
            num_hands=50,
        )

    @classmethod
    def multi_player(cls, n: int = 4) -> "GameConfig":
        """多人对局"""
        llm = LLMConfig.ollama()
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
