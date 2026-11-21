# 前任.skill — 产品需求文档（PRD）

## 产品定位

前任.skill 是一个运行在 Claude Code 上的 meta-skill。
用户通过对话式交互提供原材料（聊天记录 + 照片 + 手动描述），系统自动生成一个可独立运行的前任 Persona Skill。

## 核心概念

### 两层架构

| 层 | 名称 | 职责 |
|----|------|------|
| Part A | Relationship Memory | 存储事实性记忆：共同经历、日常模式、争吵甜蜜档案 |
| Part B | Persona | 驱动对话行为：说话风格、情感模式、关系行为 |

两部分可以独立使用，也可以组合运行。

### 运行逻辑

```
用户发消息
  ↓
Part B（Persona）判断：ta会怎么回应？什么态度？用什么语气？
  ↓
Part A（Memory）补充：结合共同记忆，让回应更真实
  ↓
输出：用ta的方式说话
```

### 进化机制

```
追加原材料 → 增量分析 → merge 进现有 Skill
对话纠正 → 识别修正点 → 写入 Correction 层
版本管理 → 确认纠正写回时自动备份；其余更新手动跑 version_manager → 支持回滚
```

## 用户旅程

```
用户触发 /create-ex
  ↓
[Step 1] 基础信息录入（3个问题，除花名外均可跳过）
  - 花名/代号
  - 基本信息（在一起多久、分手多久、职业等）
  - 性格画像（MBTI、星座、性格标签、主观印象）
  ↓
[Step 2] 原材料导入（可跳过）
  - 微信聊天记录导出
  - QQ 聊天记录导出
  - 社交媒体截图
  - 照片
  - 直接粘贴/口述
  ↓
[Step 3] 自动分析
  - 线路 A：提取关系记忆 → Memory
  - 线路 B：提取性格行为 → Persona
  ↓
[Step 4] 生成预览，用户确认
  - 分别展示 Memory 摘要和 Persona 摘要
  - 用户可直接确认或修改
  ↓
[Step 5] 写入文件，立即可用
  - 生成 exes/{slug}/ 目录
  - 包含 SKILL.md（完整组合版）
  - 包含 memory.md 和 persona.md（独立部分）
  ↓
[持续] 进化模式
  - 追加新文件 → merge 进对应部分
  - 对话纠正 → patch 对应层
  - 版本存档（确认纠正写回时自动备份；导入等其他更新不会自动备份，需手动执行 tools/version_manager.py --action backup）
```

## 安全边界

1. **仅用于个人回忆与情感疗愈**
2. **不主动联系真人**
3. **不鼓励不健康执念**
4. **数据仅本地存储**
5. **Layer 0 硬规则**保证不说前任绝不可能说的话

## 数据源支持矩阵

| 来源 | 格式 | 提取内容 | 优先级 |
|------|------|---------|--------|
| 微信聊天记录 | txt（WeChatMsg）/ JSON（留痕） | 完整对话、语气词、回复模式 | ⭐⭐⭐ |
| QQ 聊天记录 | txt / mht | 完整对话 | ⭐⭐⭐ |
| 照片 | JPEG/PNG + EXIF | 时间线、地点（需装 Pillow） | ⭐⭐ |
| 朋友圈/微博截图 | 图片（仅归类，内容靠 Claude 读图） | 公开人设、兴趣 | ⭐⭐ |

> 格式说明（与代码对齐）：微信解析器只接受 `wechatmsg_txt` / `liuhen_json` / `auto`
> （见 `tools/wechat_parser.py` 的 `SUPPORTED_FORMATS`），**csv / html / sqlite 暂不支持**。
> 社交媒体没有自动抽取逻辑：`tools/social_parser.py` 只把目录里的文件归类并输出前 5000 字文本，
> 截图内容依赖 Claude 的读图能力，人设提取由提示词完成。
| 口述/粘贴 | 纯文本 | 主观记忆 | ⭐ |

## 文件结构

```
exes/
  └── {slug}/
      ├── SKILL.md          # 完整组合版，可直接运行
      │                     # 触发词: /{slug}
      ├── memory.md         # Part A：关系记忆
      │                     # 触发词: /{slug}-memory
      ├── persona.md        # Part B：人物性格
      │                     # 触发词: /{slug}-persona
      ├── meta.json         # 元信息
      ├── versions/         # 历史版本存档
      └── memories/         # 原始材料存放
          ├── chats/
          ├── photos/
          └── social/
```
