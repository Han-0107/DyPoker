# 🃏 LLM Texas Hold'em Poker

利用大语言模型(LLM)玩德州扑克的项目。**扑克引擎**和**LLM决策**完全分离部署。

## 📁 项目结构

```
LLMPoker/
├── poker_engine/          # 🎴 扑克引擎模块（独立，无LLM依赖）
│   ├── card.py            #   牌和牌组
│   ├── evaluator.py       #   牌力评估器（判断牌型、比较大小）
│   ├── player.py          #   玩家模型
│   └── game.py            #   游戏主逻辑（发牌、下注、摊牌）
│
├── llm_agent/             # 🤖 LLM Agent模块（独立，通过API与引擎交互）
│   ├── agent.py           #   LLM决策代理 + 随机代理
│   └── prompt_builder.py  #   Prompt构建器
│
├── server/                # 🌐 游戏服务器（FastAPI REST API）
│   └── poker_server.py    #   HTTP API服务器
│
├── tests/                 # ✅ 测试
│   └── test_poker_engine.py
│
├── config.py              # ⚙️ 配置文件
├── main.py                # 🚀 主入口（多种运行模式）
├── run_distributed.py     # 🔀 分离部署启动脚本
├── requirements.txt       # 📦 依赖
└── README.md              # 📖 说明文档
```

## 🏗️ 架构设计

```
┌─────────────────────┐     HTTP/REST API     ┌─────────────────────┐
│                     │◄────────────────────►  │                     │
│   Poker Engine      │                        │   LLM Agent         │
│   (Game Server)     │  GET /game/state       │   (Decision Client) │
│                     │  POST /game/action     │                     │
│  - 发牌             │                        │  - 调用LLM API      │
│  - 下注逻辑          │                        │  - 构建Prompt       │
│  - 牌力评估          │                        │  - 解析LLM响应      │
│  - 判断输赢          │                        │  - 提交动作         │
│                     │                        │                     │
└─────────────────────┘                        └──────────┬──────────┘
                                                          │
                                                          │ LLM API
                                                          ▼
                                               ┌─────────────────────┐
                                               │  LLM Service        │
                                               │  (Ollama/OpenAI/    │
                                               │   DeepSeek/...)     │
                                               └─────────────────────┘
```

**核心理念：**
- **Poker Engine** 不知道也不关心玩家决策来自LLM还是人类
- **LLM Agent** 不知道也不关心扑克规则，只负责看状态做决策
- 两者通过 **REST API** 解耦，可以独立部署在不同机器上

## 🚀 快速开始

### 1. 安装依赖

```bash
cd LLMPoker
pip install -r requirements.txt
```

### 2. 运行模式

#### 模式A: 本地一体化运行（推荐先试这个）

不需要HTTP服务器，直接在本地运行LLM对局：

```bash
# LLM vs 随机代理（不需要LLM服务也能运行）
python main.py local --preset llm_vs_random --hands 5

# 2个LLM对战（需要先启动Ollama等LLM服务）
python main.py local --preset 2player --hands 10 --model llama3.1:8b

# 使用OpenAI
python main.py local --preset 2player --provider openai --model gpt-4o-mini --api-key YOUR_KEY

# 使用DeepSeek
python main.py local --preset 2player --provider openai --model deepseek-chat \
    --api-url https://api.deepseek.com/v1/chat/completions --api-key YOUR_KEY
```

#### 模式B: 分离部署（服务器 + Agent客户端）

**终端1 - 启动游戏服务器：**
```bash
python main.py server --port 8000
```

**终端2 - 创建游戏并启动Agent：**
```bash
# 使用curl创建游戏
curl -X POST http://localhost:8000/game/create \
  -H "Content-Type: application/json" \
  -d '{"players": [{"name": "Alice", "chips": 1000}, {"name": "Bob", "chips": 1000}]}'

# 开始一手牌
curl -X POST http://localhost:8000/game/start

# 启动Agent
python main.py agent --name Alice --server http://localhost:8000 --model llama3.1:8b
```

**终端3 - 启动另一个Agent：**
```bash
python main.py agent --name Bob --server http://localhost:8000 --model llama3.1:8b
```

#### 模式C: 一键分离部署

自动启动服务器 + 多个Agent：
```bash
python run_distributed.py --num-players 3 --num-hands 20 --model llama3.1:8b
```

### 3. API 接口

| 端点 | 方法 | 描述 |
|------|------|------|
| `/game/create` | POST | 创建游戏 |
| `/game/start` | POST | 开始新一手牌 |
| `/game/state` | GET | 获取游戏状态 |
| `/game/action` | POST | 提交动作 |
| `/game/summary` | GET | 获取游戏摘要 |
| `/game/history` | GET | 获取历史记录 |
| `/game/players` | GET | 获取玩家信息 |

## 🤖 支持的LLM

| 提供商 | 配置 |
|--------|------|
| **Ollama** (本地) | `--provider ollama --model llama3.1:8b` |
| **OpenAI** | `--provider openai --model gpt-4o-mini --api-key KEY` |
| **DeepSeek** | `--provider openai --model deepseek-chat --api-url https://api.deepseek.com/v1/chat/completions --api-key KEY` |
| **自定义** | `--provider custom --api-url YOUR_URL` |

## ✅ 运行测试

```bash
cd LLMPoker
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
