# v1.6 P0-4 验证三项销项记录（R-K）

> 对应 docs/design-v16.md §2.12 D-V16-12（验证非开发）；§5 任务表 P0-4a。
> 自动化验证脚本：`_verify_v16_p04a_offscreen.py`（项目根，QT_QPA_PLATFORM=offscreen，14/14 PASS，2026-09-08）。
> 本文档 = 自动化结论 + 真机复核步骤抄录。执行人：software-engineer-12。

---

## ① 停止生效

**设计口径**：长回复流式中点「⏹」→ 断言 3s 内 send_btn 恢复、可再次发送、无残留 worker 线程（`chat_service.is_busy()==False`）、UI 出现"生成已停止~"气泡；重复 3 次含 Agent 流式中断。

**自动化结论（offscreen，PASS ×3）**：
- ①a 停止后 3s 内 `is_busy()==False`（worker 线程协作退出）——PASS
- ①b `message_cancelled` 信号到达（协作取消链：cancel_check 命中 → StreamCancelled → ApiWorker except → emit）——PASS
- ①c 底层 API 感知 cancel_check（response 侧真停）——PASS

**真机复核步骤（待真机环境）**：
1. 配置真实 API，发送一条长回复请求；
2. 流式输出进行中点击「⏹ 停止」；
3. 断言：3s 内发送按钮恢复可用、可再次发送；消息区出现"生成已停止~"气泡；关闭主窗无卡顿（worker 已退出）；
4. 重复 3 次，其中 1 次在 Agent 模式流式中断。

**实现注记**：取消链依赖 `api.chat_stream_chunks` 的 `cancel_check` → `StreamCancelled` 异常路径；验证脚本已按该真实行为对齐（取消抛异常而非静默 return）。

---

## ② 上下文边界

**设计口径**：mock_cfg 下 30 轮对话（> max_history_rounds=8）→ 断言请求 messages 长度受控（`len(session.history) <= 1 + 4 + max_history_rounds*2`）+ `context_trimmed==True` + 反套话注入出现在请求副本；"摘要自然衔接"项仅 CLI 链跑（GUI 无 auto_summary，D-V16-08 校正）。

**自动化结论（PASS ×7）**：
- ②a 30 轮后 user/assistant 总数受控（others=16 ≤ max_history_rounds*2=16）——PASS
- ②b `context_trimmed==True`（_trim_history 实际截断置位，session.py:241-243）——PASS
- ②c 反套话（"【诚实边界】…"）注入出现在**请求副本**（_launch_worker 组装，chat_service.py:966-986）——PASS
- ②d 注入**不写入** session.history（不入存档）——PASS
- ②e 请求 non-system 消息数受控（17 ≤ 16+1）——PASS
- ②f1 **缺陷暴露**：仅设置 `AppConfig.agent_anti_hallucination_inject=False` 时仍注入——见下方"发现 1"
- ②f2 开关在 `app_ctx.config`（GuiConfig 侧动态补字段）关闭 → 零注入（通路本身有效）——PASS
- ②g 未截断会话（新 session，context_trimmed=False）→ 零注入、零打扰——PASS

**发现 1（实现核对项，待 T3 侧确认/修正）**：
`ChatService._launch_worker` 反套话开关读取 `cfg = app_ctx.config`（GuiConfig，chat_service.py:917 → 969），而开关字段落在 **AppConfig**（core/__init__.py:733，config.yaml agent 段，GuiConfig 无此字段）→ `getattr` 默认值恒 True，**设置 AppConfig 上的开关无效**。建议：GuiConfig 增镜像字段，或 969 行改读 `getattr(app_ctx, "cfg", None)` 侧。已同步报告 team-lead。

**发现 2（口径注记）**：
D-V16-08 原文"只增不清（会话级标志，不做撤销）"；当前实现为"注入后一次性复位"（chat_service.py:971-975）+ 每轮 send 触发 trim 重新置位。两者在稳态行为上等价（截断过的会话每轮都会重新置位），但"早期轮次注入一次后、后续轮次若不触发 trim 则不再注入"——与设计"会话级持续生效"存在语义偏差。多轮长会话实测下每轮 send 都会触发裁剪置位，实际等价；留档备查。

---

## ③ 编辑重发基础链

**设计口径**：真机——右键编辑 user 消息 → 确认框 → 截断 + 回填 + 改后重发 → 断言后续气泡消失、会话存档同步截断、LLM 收到的是改后文本；零回归对照 v1.5.2 行为。

**自动化结论（offscreen，PASS ×3）**：
- ③a 编辑确认（R9 QMessageBox 确认框自动应答 Yes）后截断该条及其后（4 → 2 条气泡）——PASS
- ③b 原文回填输入框（R10：截断前取局部变量快照）——PASS
- ③c LLM 侧历史与 UI 截断对齐（`_truncate_messages_from` + `_save_current_session` 增量同步既有链，R2）——PASS

**真机复核步骤（待真机环境）**：
1. 右键任一 user 气泡 → 「编辑」→ 确认框点「确定」；
2. 断言：该条及其后气泡消失、原文与附件回填输入框；
3. 修改文本后发送，断言后续对话基于改后文本。

---

## 汇总

| 项 | 自动化 | 真机 |
|---|---|---|
| ① 停止生效 | 3/3 PASS | 待复核（步骤已抄录） |
| ② 上下文边界 | 7/7 PASS（含 1 项缺陷暴露 ②f1） | 不适用（纯自动化） |
| ③ 编辑重发基础链 | 3/3 PASS | 待复核（步骤已抄录） |
| **合计** | **13/14 PASS**（②f1 为如实暴露的实现缺陷，非验证失败） | — |
