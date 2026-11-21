Persona + Memory Schema v1

这是把原项目的 5 层 Persona 与 Memory 结构化后的第一版数据模型。

现在先不要改原项目

先把这个 schema 保存下来，作为后续重构的“数据合同”。

下一阶段会：

1. 定义统一 Message 数据结构；
2. 把微信/QQ解析结果统一成 Message；
3. 让 LLM 只负责填 Persona/Memory 字段；
4. 用 JSON Schema 校验 LLM 输出；
5. 再进入真正的聊天运行时。

与原项目的对应

Persona：

• Layer 0 → layer0_rules
• Layer 1 → identity
• Layer 2 → speech_style
• Layer 3 → emotional_pattern
• Layer 4 → relationship_behavior

Memory：

• 原项目的关系记忆维度 → core_facts / timeline / shared_experiences / conflicts / happy_memories / breakup / inside_jokes

注意：

• 这是 v1，不代表最终商业版数据库结构。
• 目前不加入向量数据库、账号、支付等内容。
• 不把 LLM 的自由文本当作系统状态；后续代码会负责校验。