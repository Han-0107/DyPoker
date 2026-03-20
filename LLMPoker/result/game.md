# 🃏 Qwen3 德州扑克对局记录

| 项目 | 值 |
|------|------|
| 模型 | `pokerbench-qwen2.5-7b` |
| 玩家数 | 4 |
| 总手数 | 10 |
| GPU 并行 | 1 卡 |
| 时间 | 2026-03-20 20:06:38 |

---

## 🎴 第 1/10 手牌

**庄家:** You 🧑

| 玩家 | 筹码 | 状态 |
|------|------|------|
| You 🧑 | 1000 | ✅ 活跃 |
| Alice 🂡 | 995 | ✅ 活跃 |
| Bob 🂢 | 990 | ✅ 活跃 |
| Charlie 🂣 | 1000 | ✅ 活跃 |

- **Charlie 🂣**: 📞 跟注
  > 💭 Fallback: call (only 1 BB)

- **You 🧑**: 📞 跟注
  > 💭 Human player decision

- **Alice 🂡**: 📞 跟注
  > 💭 Fallback: call (good pot odds)

- **Bob 🂢**: ✋ 过牌
  > 💭 Fallback: check (free to see)

### 🃏 翻牌 (Flop)

**公共牌:** `8♥` `Q♥` `Q♦`

- **Alice 🂡**: ✋ 过牌
  > 💭 Fallback: check (free to see)

- **Bob 🂢**: ✋ 过牌
  > 💭 Fallback: check (free to see)

- **Charlie 🂣**: ✋ 过牌
  > 💭 Fallback: check (free to see)

- **You 🧑**: 🚫 弃牌
  > 💭 User interrupted

### 🃏 转牌 (Turn)

**公共牌:** `8♥` `Q♥` `Q♦` `K♣`

- **Alice 🂡**: ✋ 过牌
  > 💭 Fallback: check (free to see)

- **Bob 🂢**: ✋ 过牌
  > 💭 Fallback: check (free to see)

- **Charlie 🂣**: ✋ 过牌
  > 💭 Fallback: check (free to see)

### 🃏 河牌 (River)

**公共牌:** `8♥` `Q♥` `Q♦` `K♣` `9♦`

- **Alice 🂡**: ✋ 过牌
  > 💭 Fallback: check (free to see)

- **Bob 🂢**: ✋ 过牌
  > 💭 Fallback: check (free to see)

- **Charlie 🂣**: ✋ 过牌
  > 💭 Fallback: check (free to see)

### 📋 本手结果

**公共牌:** `8♥` `Q♥` `Q♦` `K♣` `9♦`

- 🏆 **Bob 🂢**: 赢得 **40** 筹码 — _两对 (Two Pair)_ [`8♣` `3♦`]

⏱️ 本手耗时: **207.6s**

**💰 当前筹码:**

| 排名 | 玩家 | 筹码 |
|------|------|------|
| 1 | Bob 🂢 | 1030 |
| 2 | You 🧑 | 990 |
| 3 | Alice 🂡 | 990 |
| 4 | Charlie 🂣 | 990 |

---

## 🏆 最终排名

| 排名 | 玩家 | 最终筹码 | 盈亏 |
|------|------|----------|------|
| 🥇 | Bob 🂢 | 1030 | +30 |
| 🥈 | You 🧑 | 990 | -10 |
| 🥉 | Alice 🂡 | 990 | -10 |
| 4 | Charlie 🂣 | 990 | -10 |

**🎉 冠军: Bob 🂢** (1030 筹码)

- ⏱️ 总耗时: 207.9 秒
- 📊 平均每手: 207.9 秒
