"""chat_panel.py 拆分方案（v1.4.8 建议，待执行）

当前问题：
- chat_panel.py 2600+ 行，职责过多
- 包含：消息气泡渲染、输入处理、会话管理、Agent 模式、任务模式、授权弹窗等

建议拆分为：
1. chat_panel.py (主容器，~500行)
   - ChatPanel 类：组合各子组件
   - 信号连接、布局管理
   
2. chat_bubbles.py (~400行)
   - UserBubble / AIBubble / SystemBubble 类
   - 气泡渲染、Markdown 渲染、代码高亮
   
3. chat_input.py (~300行)
   - ChatInput 类：输入框、发送按钮、模式切换
   - 快捷键处理、粘贴处理
   
4. chat_session.py (~400行)
   - SessionManager 类：会话列表、切换、持久化
   - 会话创建/删除/重命名
   
5. chat_agent.py (~300行)
   - AgentMode 类：Agent/任务模式管理
   - 授权弹窗、工具轨迹显示
   
6. chat_service.py (已存在，保持不变)
   - ChatService 类：消息收发、API 调用

拆分步骤：
1. 先为 chat_panel.py 补充 GUI 测试（如 pytest-qt）
2. 逐个提取子模块，每提取一个跑一次全量测试
3. 最后清理 chat_panel.py 中的冗余代码

风险：
- 信号/槽连接可能断裂
- 组件间数据传递需要重构
- 需要大量手动测试验证

建议：在下一个大版本（v1.5.0）执行，不在 v1.4.8 紧急修复中做。
"""
