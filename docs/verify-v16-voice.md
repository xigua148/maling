# 码铃（MaLing）v1.6 语音细节 · 真机标定清单与验证留档

- 对应：design-v16.md D-V16-11 / prd-v16.md P1-1（R-K 销项：把"真机标定"从口头声明落成文档）
- 日期：2026-09-08
- 维护人：码铃 v1.6 开发（software-engineer-13）
- 状态：**自动化已验**（pytest 24 项全绿）+ **真机待验**（下表标定项需真机麦克风/扬声器环境）

---

## 1. 本批语音改动落点（自动化已验）

| 项 | 落点 | 自动化验证 |
|---|---|---|
| 软失败反馈 | `gui/voice_conversation.py` `_on_failed`：连续 3 次软失败（听不懂/静默）→ 提示"没听清，建议换个安静环境…"；6 次自动暂停；识别成功归零 | `test_v16_voice.py::TestSoftFailureFeedback` |
| 退出恢复缓冲（10min） | `stop()` 记录 `resume_cooldown_until`；`gui/proactive_scheduler.py` `PolicyState.external_cooldown_until` + `gates()` 返回 `resume_buffer`（计入四重闸，quiet 后、cap 前） | `TestResumeBuffer`（4 项） |
| 说话打断（barge-in） | speaking 期间挂识别 worker：用户开口 → 停 TTS + 「我在听~」+ 文本接续走发送链；回声防护 `_looks_like_echo`（识别文本与朗读文本子串/字符重叠 >60% 判回声，防扬声器外放自我打断）；打断中命中退出关键词 → 退出；识别失败静默重挂 | `TestBargeIn`（5 项）+ `TestEchoGuard` |
| 录音呼吸微提示 | `gui/widgets/handsfree_bar.py`：listening 态 QTimer 驱动 ● 透明度正弦波动（120ms/拍）；离开 listening 即停表（防常驻耗电）。无波形分析、无音频落盘（R-B） | `TestBreathingAnimation` |
| 角色音色同步 | `gui/tts.py` `TTSController`：订阅 `role_bridge.role_changed` → `apply_role_voice(role_id)`：`ROLE_VOICE_HINTS`（猫娘 +8 / 毒舌博士 -6 / 鲸鱼娘 -4 语速偏置，叠加设置页语速并钳位 0..100；可选 `voice` 关键词切引擎音色）；未收录角色偏置归零（跟随设置页），诚实降级 | `TestRoleVoiceSync`（4 项） |
| 语音与文字同会话 | 确认现状（v1.3 P2-2 起即如此）：`speech_ready` → `chat_panel._on_hf_speech_ready` → `_add_message_bubble`（唯一 user 渲染入口）+ `ChatService.send_message`——与打字同源同一 ChatService/同一会话历史 | `TestVoiceTextSameSession` |
| 停顿判断（现状说明） | 静默/听不懂属软失败：v1.6 起计数并反馈（3 提示 / 6 暂停），不打断退出通道；"不重复识别上一句"由 `_RecognitionWorker` 每轮独立起听、识别成功即消费发送、无结果缓存复用机制保证（现状即无重复发送问题） | 软失败链测试 + 代码通读 |

## 2. 真机标定清单（**真机待验**，逐项填"默认值 → 真机建议值 → 验证人"）

| # | 标定项 | 代码常量/落点 | 默认值 | 真机建议值 | 验证人 | 结论 |
|---|---|---|---|---|---|---|
| 1 | 打字/动鼠标打断灵敏度 | `voice_conversation._INTERRUPT_AGE_MS` | 450ms | 待填 | 待填 | 待验 |
| 2 | 打断轮询间隔 | `voice_conversation._INTERRUPT_POLL_MS` | 800ms | 待填 | 待填 | 待验 |
| 3 | 软失败提示阈值 | `voice_conversation._SOFT_NOTICE_AT` | 3 次 | 待填 | 待填 | 待验 |
| 4 | 软失败自动暂停阈值 | `voice_conversation._MAX_SOFT_FAILURES` | 6 次 | 待填 | 待填 | 待验 |
| 5 | 免提退出恢复缓冲时长 | `voice_conversation._RESUME_BUFFER_MIN` | 10 分钟 | 待填 | 待填 | 待验 |
| 6 | 回声防护重叠阈值 | `voice_conversation._looks_like_echo`（>60% 字符重叠判回声） | 0.6 | 待填（扬声器外放环境易误断则调低） | 待填 | 待验 |
| 7 | 呼吸动画节拍 | `handsfree_bar` setInterval | 120ms | 待填 | 待填 | 待验 |
| 8 | 角色语速偏置表 | `tts.TTSController.ROLE_VOICE_HINTS` | 猫娘+8 / 博士-6 / 鲸鱼娘-4 | 待填（听感为准） | 待填 | 待验 |
| 9 | 朗读截断长度 | `voice_conversation._try_speak_reply`（600 字截断） | 600 字 | 待填 | 待填 | 待验 |
| 10 | 麦克风增益/噪音场景 | SpeechRecognition adjust_ambient（voice_input 内） | 引擎默认 | 待填（安静室内/开放工位各测一轮） | 待填 | 待验 |

## 3. 真机验证步骤（R-K 销项用）

1. **打断**：免提开启 → 码铃朗读长回复中直接开口说新内容 → 断言 TTS 立即停、状态条闪「我在听~」、新内容被发送；重复 3 次含一次说「暂停」。
2. **回声**：外放音量 70% 场景朗读 → 断言无自我打断（回声防护生效）；若误断记录到上表 #6 调阈值。
3. **恢复缓冲**：免提用完退出 → 立即放置 ≥idle_minutes 空闲 → 断言 10 分钟内无主动问候、之后恢复。
4. **软失败**：安静朗读无意义音节 6 次 → 断言第 3 次出现提示、第 6 次自动暂停且退出通道不受影响。
5. **角色音色**：切猫娘/毒舌博士/鲸鱼娘 → 断言语速听感有差异；切自建角色 → 语速回到设置页值。
6. **停顿体验**：正常对话中句间停顿 1–2 秒 → 断言不抢话、不重复发送上一句。

## 4. 诚实边界（R-K）

- 本表"自动化已验"均为逻辑层断言（mock 识别 worker / mock TTS），**不等于**真机听感验收；
- barge-in 依赖 SpeechRecognition 单路 worker，真机回声抑制效果依赖 #6 阈值标定，未标定前外放大音量场景可能出现误打断/漏打断；
- 角色音色 `voice` 关键词切换依赖系统已装中文语音包，缺包时诚实降级为仅语速偏置。
