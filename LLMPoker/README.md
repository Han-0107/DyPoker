# 🃏 LLM Texas Hold'em Poker

利用本地部署的大语言模型 (vLLM) 玩德州扑克的项目。模型在本地 GPU 上运行，自动检测并选择空闲显卡。

## 📁 项目结构

```
LLMPoker/
├── main.py                    # 🚀 主入口 — 运行 LLM 德州扑克对局
├── config.py                  # ⚙️ 游戏与模型配置
│
├── poker_engine/              # 🎴 扑克引擎模块（纯游戏逻辑，无 AI 依赖）
│   ├── card.py                #   牌和牌组
│   ├── evaluator.py           #   牌力评估器（判断牌型、比较大小）
│   ├── player.py              #   玩家模型
│   └── game.py                #   游戏主逻辑（发牌、下注、摊牌）
│
├── llm_agent/                 # 🤖 LLM Agent 模块
│   ├── agent.py               #   LLM 决策代理
│   ├── human_agent.py         #   人类玩家交互代理（终端交互）
│   ├── prompt_builder.py      #   Prompt 构建器（PokerBench 风格）
│   └── vllm_provider.py       #   vLLM 本地推理引擎封装
│
├── utils/                     # 🔧 工具模块
│   ├── gpu_utils.py           #   GPU 自动检测与选择
│   ├── pokerbench_utils.py    #   PokerBench 数据解析工具
│   ├── markdown_logger.py     #   Markdown 游戏日志记录器
│   └── console_display.py     #   终端美化输出
│
├── training/                  # 📚 模型训练模块
│   ├── train_pokerbench.py    #   Stage 1: SFT 微调（PokerBench 数据集）
│   ├── train_grpo_phh.py      #   Stage 2: GRPO 强化学习（phh-dataset）
│   ├── phh_parser.py          #   PHH 对局文件解析器
│   └── grpo_trainer.py        #   GRPO 训练核心逻辑（奖励、优势计算）
│
├── tests/                     # ✅ 测试
│   ├── test_poker_engine.py   #   扑克引擎单元测试
│   └── test_pokerbench_utils.py # 数据工具测试
│
├── checkpoints/               # 💾 训练好的模型检查点
├── result/                    # 📊 游戏结果输出
├── requirements.txt           # 📦 依赖
└── README.md
```

## 🏗️ 架构设计

```
┌─────────────────────────┐          ┌─────────────────────────┐
│     Poker Engine        │          │      LLM Agent          │
│                         │  游戏状态  │                         │
│  - 发牌                 │─────────►│  - 构建 Prompt           │
│  - 下注逻辑             │          │  - 调用本地 vLLM 模型     │
│  - 牌力评估             │◄─────────│  - 解析 LLM 响应          │
│  - 判断输赢             │  动作决策  │  - 返回动作              │
│                         │          │                         │
│                         │          └────────────┬────────────┘
│                         │                       │ 本地推理
│                         │                       ▼
│                         │          ┌─────────────────────────┐
│                         │          │   vLLM Engine (本地GPU)  │
│                         │          │   Qwen2.5 / Qwen3 / ... │
│                         │          └─────────────────────────┘
│                         │
│                         │          ┌─────────────────────────┐
│                         │  游戏状态  │     Human Agent 🎮      │
│                         │─────────►│                         │
│                         │          │  - 终端美化展示游戏状态    │
│                         │◄─────────│  - 接收用户键盘输入       │
│                         │  动作决策  │  - 验证操作合法性         │
└─────────────────────────┘          └─────────────────────────┘
         │
         ▼
┌─────────────────────────┐
│     Utils               │
│  - GPU 选择             │
│  - Markdown 日志        │
│  - 终端美化输出          │
└─────────────────────────┘
```

**核心特性：**
- **纯本地推理** — 通过 vLLM 加载模型，无需外部 API
- **自动选 GPU** — 启动时自动检测空闲显存，选择最优 GPU
- **多人对局** — 支持 2-10 人德州扑克
- **🎮 人机对战** — 交互模式支持人类玩家 vs LLM AI
- **模块解耦** — 扑克引擎与 LLM 决策逻辑完全分离
- **两阶段训练** — SFT (PokerBench) → GRPO (phh-dataset 胜者策略)

## 🧠 训练流水线

```
 ┌─────────────────┐         ┌──────────────────────┐         ┌─────────────────┐
 │   Stage 1: SFT  │         │   Stage 2: GRPO      │         │    Inference     │
 │                 │         │                      │         │                 │
 │  PokerBench     │────────►│  phh-dataset         │────────►│  main.py        │
 │  (solver最优解)  │  LoRA   │  (人类专家胜者策略)    │  LoRA   │  (vLLM 对局)    │
 │                 │ adapter │                      │ adapter │                 │
 │ train_pokerbench│         │ train_grpo_phh.py    │         │                 │
 └─────────────────┘         └──────────────────────┘         └─────────────────┘
```

| 阶段 | 数据来源 | 方法 | 目标 |
|------|----------|------|------|
| **Stage 1: SFT** | PokerBench (solver 最优解) | Supervised Fine-Tuning (LoRA) | 学习基本决策格式与 solver 策略 |
| **Stage 2: GRPO** | phh-dataset (10K+ 真实对局) | Group Relative Policy Optimization | 学习胜者人类专家的实战策略 |

## 🚀 快速开始

### 1. 安装依赖

```bash
cd LLMPoker
pip install -r requirements.txt
```

### 2. 运行对局

```bash
# 默认6人100手
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

### 🎮 3. 人机对战模式

加上 `--human` 参数即可以人类玩家身份加入对局，与 LLM AI 进行德州扑克对战！

```bash
# 1个人类 + 5个AI（默认6人）
python main.py --human

# 1个人类 + 3个AI（共4人）
python main.py --human --players 4

# 自定义你的名称
python main.py --human --name "玩家1"

# 20手牌，2000初始筹码
python main.py --human --hands 20 --chips 2000

# 使用自定义模型和4卡并行
python main.py --human --model /path/to/model --tp 4
```

**交互模式下的操作方式：**

轮到你行动时，终端会展示完整的游戏状态（你的手牌、公共牌、各玩家筹码等），并列出可选操作：

| 操作 | 输入 | 说明 |
|------|------|------|
| 弃牌 | `fold` 或 `1` | 放弃本手牌 |
| 过牌 | `check` 或 `2` | 不加注（无人加注时） |
| 跟注 | `call` 或 `3` | 跟当前最高注 |
| 加注 | `raise` 或 `4` | 加注（需输入加注总额） |
| 全下 | `all_in` 或 `5` | 押上全部筹码 |

- 支持 **编号** 或 **名称** 输入（大小写不敏感）
- 加注时需输入总额，输入 `all` 可直接全下
- 每手牌结束后按 Enter 继续，输入 `q` 退出
- 按 `Ctrl+C` 随时中断游戏

**`main.py` 参数说明：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--human` | `false` | 🎮 加入一个人类玩家（替换第一个AI） |
| `--name` | `You 🧑` | 人类玩家的显示名称 |
| `--players` | `6` | 玩家总数 (2-10) |
| `--hands` | `5` | 总手数 |
| `--chips` | `1000` | 初始筹码 |
| `--small-blind` | `5` | 小盲注 |
| `--big-blind` | `10` | 大盲注 |
| `--model` | LoRA checkpoint | 本地模型路径 |
| `--tp` | `1` | Tensor Parallel GPU 数 |
| `--gpu-util` | `0.9` | GPU 显存利用率 |
| `--max-model-len` | `10000` | 最大序列长度 |
| `--seed` | `40` | 随机种子 |
| `--log-level` | `INFO` | 日志级别 |
| `--lora` | `None` | 可选 LoRA 适配器路径（可重复指定） |

### 3. SFT 微调（Stage 1）

```bash
python -m training.train_pokerbench \
  --model Qwen/Qwen2.5-7B-Instruct \
  --output-dir ./checkpoints/sft-qwen2.5-7b \
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

### 4. GRPO 强化学习（Stage 2）

```bash
python -m training.train_grpo_phh \
    --sft-model Qwen/Qwen2.5-7B-Instruct \
    --sft-adapter ./checkpoints/sft-qwen2.5-7b \
    --output-dir ./checkpoints/grpo-qwen2.5-7b \
    --phh-data-dir ../phh-dataset/data \
    --epochs 2 \
    --bf16
```

#### 保守更新策略

| 参数 | GRPO 值 | vs SFT | 说明 |
|------|---------|--------|------|
| Learning Rate | `5e-6` | SFT `2e-4` (↓40x) | 极低学习率防止遗忘 |
| KL 系数 β | `0.1` | — | 惩罚偏离 SFT 策略 |
| LoRA rank | `8` | SFT `16` (↓2x) | 更少可训练参数 |
| Gradient Clip | `0.5` | SFT `1.0` (↓2x) | 防止梯度爆炸 |

#### 奖励函数设计

| 生成 vs 专家 | 奖励值 | 说明 |
|-------------|--------|------|
| 精确匹配 (raise amount ±30%) | `+1.0` | 动作类型+金额均匹配 |
| 精确匹配 (raise amount ±50-100%) | `+0.7` | 金额大致正确 |
| 语义相似 (check↔call, raise↔all_in) | `+0.5` | 方向一致 |
| 错误方向但合法 JSON | `-0.3` | 如 fold vs raise |
| 无法解析 | `-1.0` | 格式错误 |

### 5. 使用训练好的模型对局

训练完成后，可以直接用训练好的模型运行对局。根据训练阶段不同，有以下几种使用方式：

#### 方式一：仅使用 SFT 模型

SFT 训练会输出一个 LoRA adapter 目录（如 `./checkpoints/sft-qwen2.5-7b`）。使用时需要指定**基座模型 + LoRA adapter**：

```bash
# 基座模型 + SFT LoRA adapter
python main.py \
    --model Qwen/Qwen2.5-7B-Instruct \
    --lora ./checkpoints/sft-qwen2.5-7b \
    --players 6 --hands 50
```

如果 SFT 训练时使用了 `--merge-lora` 合并了权重，则可以直接指定合并后的模型目录：

```bash
# 已合并的 SFT 模型（无需 --lora）
python main.py \
    --model ./checkpoints/sft-qwen2.5-7b/merged \
    --players 6 --hands 50
```

#### 方式二：使用 SFT + GRPO 模型

GRPO 训练在 SFT 基础上进一步优化。GRPO 的输出同样是一个 LoRA adapter，需要叠加在**已合并 SFT 的基座模型**上：

```bash
# 基座模型 + SFT adapter + GRPO adapter（叠加两个 LoRA）
python main.py \
    --model Qwen/Qwen2.5-7B-Instruct \
    --lora ./checkpoints/sft-qwen2.5-7b \
    --lora ./checkpoints/grpo-qwen2.5-7b \
    --players 6 --hands 50
```

如果 GRPO 训练时 SFT adapter 已合并入基座（默认行为），则只需指定 GRPO adapter：

```bash
# 基座模型（已含 SFT）+ GRPO adapter
python main.py \
    --model Qwen/Qwen2.5-7B-Instruct \
    --lora ./checkpoints/grpo-qwen2.5-7b \
    --players 6 --hands 50
```

GRPO 训练会自动保存评估表现最好的模型到 `best/` 子目录，推荐优先使用：

```bash
# 使用 GRPO 最佳检查点
python main.py \
    --model Qwen/Qwen2.5-7B-Instruct \
    --lora ./checkpoints/grpo-qwen2.5-7b/best \
    --players 6 --hands 100
```

#### 方式三：使用完全合并的模型

如果 GRPO 训练时指定了 `--merge-lora`，会在 `merged/` 目录生成完整模型，可以直接加载（无需任何 `--lora`）：

```bash
python main.py \
    --model ./checkpoints/grpo-qwen2.5-7b/merged \
    --players 6 --hands 100
```

#### 快速对比不同模型

```bash
# 原始基座模型（无微调）
python main.py --model Qwen/Qwen2.5-7B-Instruct --output ./result/base.md

# SFT 模型
python main.py --model Qwen/Qwen2.5-7B-Instruct --lora ./checkpoints/sft-qwen2.5-7b --output ./result/sft.md

# SFT + GRPO 模型
python main.py --model Qwen/Qwen2.5-7B-Instruct --lora ./checkpoints/grpo-qwen2.5-7b/best --output ./result/grpo.md
```

> 💡 **提示**：对局结果会保存为 Markdown 文件（默认 `./result/game.md`），可以方便地对比不同模型的表现。

### 6. GPU 自动选择

启动时会自动检测所有 GPU 的空闲显存，选取最空闲的卡：

```
  🔍 GPU 自动选择结果:
     GPU 2: 79.2 GiB 空闲 ✅ 选中
     GPU 3: 79.2 GiB 空闲 ✅ 选中
     GPU 0: 52.8 GiB 空闲
     GPU 1:  7.7 GiB 空闲
  🎯 CUDA_VISIBLE_DEVICES=2,3
```

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
