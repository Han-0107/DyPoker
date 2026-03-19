# 🃏 LLM Texas Hold'em Poker

利用本地部署的大语言模型 (vLLM) 玩德州扑克的项目。模型在本地 GPU 上运行，自动检测并选择空闲显卡。

## 📁 项目结构

```
LLMPoker/
├── poker_engine/          # 🎴 扑克引擎模块
│   ├── card.py            #   牌和牌组
│   ├── evaluator.py       #   牌力评估器（判断牌型、比较大小）
│   ├── player.py          #   玩家模型
│   └── game.py            #   游戏主逻辑（发牌、下注、摊牌）
│
├── llm_agent/             # 🤖 LLM Agent模块
│   ├── agent.py           #   LLM决策代理 + 随机代理
│   ├── prompt_builder.py  #   Prompt构建器
│   └── vllm_provider.py   #   vLLM 本地推理引擎封装
│
├── tests/                 # ✅ 测试
│   └── test_poker_engine.py
│
├── withdrawn/             # 📦 已废弃模块
│   └── main.py            #   旧版主入口（预设模式，已废弃）
│
├── config.py              # ⚙️ 配置文件
├── gpu_utils.py           # 🎯 GPU自动检测与选择
├── main.py       # 🚀 主入口（完整参数控制）
├── requirements.txt       # 📦 依赖
└── README.md
```

## 🏗️ 架构设计

```
┌─────────────────────────┐          ┌─────────────────────────┐
│     Poker Engine        │          │      LLM Agent          │
│                         │  游戏状态  │                         │
│  - 发牌                 │─────────►│  - 构建Prompt            │
│  - 下注逻辑             │          │  - 调用本地vLLM模型       │
│  - 牌力评估             │◄─────────│  - 解析LLM响应           │
│  - 判断输赢             │  动作决策  │  - 返回动作              │
│                         │          │                         │
└─────────────────────────┘          └────────────┬────────────┘
                                                  │
                                                  │ 本地推理
                                                  ▼
                                     ┌─────────────────────────┐
                                     │   vLLM Engine (本地GPU)  │
                                     │   Qwen3-14B / 32B / ... │
                                     └─────────────────────────┘
```

**核心特性：**
- **纯本地推理** — 通过 vLLM 加载模型，无需外部 API
- **自动选GPU** — 启动时自动检测空闲显存，选择最优 GPU
- **多人对局** — 支持 2-10 人德州扑克
- **模块解耦** — 扑克引擎与 LLM 决策逻辑完全分离

## 🚀 快速开始

### 1. 安装依赖

```bash
cd LLMPoker
pip install -r requirements.txt
```

### 2. 运行对局

使用 `main.py` 启动对局，支持完整参数控制：

```bash
# 默认6人5手
python main.py

# 4人10手
python main.py --players 4 --hands 10

# 9人10手
python main.py --players 9 --hands 10

# 4卡并行，调整显存利用率
python main.py --tp 4 --gpu-util 0.85

# 自定义模型
python main.py --model /path/to/model --tp 2

# 指定GPU（跳过自动检测）
CUDA_VISIBLE_DEVICES=2,3 python main.py --players 4 --hands 10

# 使用 LoRA 适配器
python main.py --model /path/to/base --lora /path/to/adapter
```

**`main.py` 参数说明：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--players` | `6` | 玩家数量 (2-10) |
| `--hands` | `5` | 总手数 |
| `--chips` | `1000` | 初始筹码 |
| `--small-blind` | `5` | 小盲注 |
| `--big-blind` | `10` | 大盲注 |
| `--model` | Qwen3-14B | 本地模型路径 |
| `--tp` | `2` | Tensor Parallel GPU 数 |
| `--gpu-util` | `0.9` | GPU 显存利用率 |
| `--max-model-len` | `4096` | 最大序列长度 |
| `--seed` | `40` | 随机种子 |
| `--log-level` | `WARNING` | 日志级别 (`DEBUG` / `INFO` / `WARNING` / `ERROR`) |
| `--lora` | `None` | 可选 LoRA 适配器路径（可重复指定） |

### 3. 使用 PokerBench 进行微调

我们提供了 `train_pokerbench.py` 脚本，使用 HuggingFace `datasets/trl/peft` 对模型做 LoRA 微调，支持 QLoRA 四比特加载。

快速示例（单卡小样本）：

```bash
python train_pokerbench.py \
  --model Qwen/Qwen2.5-7B-Instruct \
  --output-dir ./checkpoints/pokerbench-qwen2.5-7b \
  --max-train-samples 8000 \
  --epochs 0.5 \
  --batch-size 1 \
  --grad-accum-steps 4 \
  --lr 5e-5 \
  --max-seq-len 768 \
  --lora-r 8 \
  --lora-alpha 16 \
  --lora-dropout 0.1 \
  --save-steps 1000 \
  --logging-steps 50
```

提示：`--merge-lora` 会将 LoRA 权重合并回基模，便于与 vLLM 直接加载；否则输出的即为 LoRA 适配器目录（可通过 `--lora` 传给 `main.py` 使用）。

### 3. GPU 自动选择

启动时会自动检测所有 GPU 的空闲显存，选取最空闲的卡：

```
  🔍 GPU 自动选择结果:
     GPU 2: 79.2 GiB 空闲 ✅ 选中
     GPU 3: 79.2 GiB 空闲 ✅ 选中
     GPU 0: 52.8 GiB 空闲
     GPU 1:  7.7 GiB 空闲
     ...
  🎯 CUDA_VISIBLE_DEVICES=2,3
```

如果你已手动设置了 `CUDA_VISIBLE_DEVICES`，自动选择会跳过，尊重你的设置。

## ✅ 运行测试

```bash
python -m pytest tests/ -v
```

## 🎯 扑克引擎支持的牌型

| 牌型 | 英文 | 等级 |
|------|------|------|
| 皇家同花顺 | Royal Flush | 9 |
| 同花顺 | Straight Flush | 8 |
| 四条 | Four of a Kind | 7 |
| 葫芦 | Full House | 6 |
| 同花 | Flush | 5 |
| 顺子 | Straight | 4 |
| 三条 | Three of a Kind | 3 |
| 两对 | Two Pair | 2 |
| 一对 | One Pair | 1 |
| 高牌 | High Card | 0 |
