# 码铃（MaLing）v2.5 增量架构设计 ——「记忆链路的正确性收口 + 三处能力补齐 + 配置路径根治」

- 版本：v2.5（承接 `docs/prd-v25.md`）
- 文档状态：**已实现并全量回归**（2451 passed / 1 failed 系既有环境问题，见 §5.3）
- 维护人：架构（高见远）
- 基线：`v2.3.1`（`version.json`，本版仍未定版号）
- 关联：`docs/design-v24.md`（上一版，记忆捕获链路修复）、`docs/design-v22.md`（酒馆，本版起标记弃用）
- **本文所有行号以改动后源码为准**

---

## 1. 范围与现状基线（先读我）

### 1.1 范围与来源

本版**没有新立项**，而是把三份既有材料合并执行：

| 来源 | 内容 |
|---|---|
| `docs/OPTIMIZATION_BACKLOG_v2.1.md` | 项目自己写的 10 条待办（其中与本版相关的是「死代码/双源主题」「裸 print」） |
| v2.4 实施期间的实测发现 | 6 条（见 §1.3） |
| 用户口头指示 | 加「话题提及注入」「话题完成检测」「词表外挂」；酒馆不再优化、逐步下线 |

### 1.2 ★ 既有测试硬约束（**不得推翻**）

| # | 约束 | 来源 | 本版如何满足 |
|---|---|---|---|
| B1 | 注入序位断言 `len(lines) == 5`（白天）且逐行前缀固定 | `test_v18_batch3.py::test_final_order` | 话题提及注入**追加在实体提及之后**作为「①b」；该场景无话题 → 零注入 → 计数不变 |
| B2 | 群聊三隔离（不写历史/不计亲密度/**不做记忆提取**） | `test_v17_batch4_f10.py::TestTripleIsolation`（R-J④⑤） | 未触及群聊路径 |
| B3 | `followup_score` 精确值、排序 tie-break 方向 | v2.4 §1.2 B1/B2 | 未触及 |
| B4 | `build_memory_context` 输出 ≤300 字符 | `test_v18_batch1.py` | 未触及该函数 |
| B5 | 测试数据隔离（共享知识 23） | — | 三个新测试文件全部 `tmp_path`；会话测试额外 `monkeypatch.chdir` + 打桩 `memory._memory_path` |
| B6 | R-A 无数值化 | — | 新增注入行为纯文本描述（「N 天前」「已经完成了」），无分数/计数 |

### 1.3 已核实的现状事实（逐条实测，作为改动依据）

| # | 事实 | 取证 |
|---|---|---|
| F1 | `MemoryManager` 全文件**无锁**；`_save()` 的临时文件名固定为 `path + ".tmp"` | 实读；`_save` 有 29 处调用点 |
| F2 | 双线程场景真实存在：`gui/main.py` 启动 `maid-diary` daemon 线程读记忆，主线程同时可能写 | `gui/main.py:452/495` |
| F3 | `session.py:392` `memory_mgr.from_dict(data["memory"])` 会用会话内快照**整体替换**全局记忆（`intimacy` 同款） | 实读 |
| F4 | `utils.py` 崩溃恢复路径有同款回放（`session.memory_mgr.from_dict(...)`） | 实读 |
| F5 | `update_topic_status`（`memory.py:528`）**全仓零调用**（连测试都没有） | `grep -rn` |
| F6 | `_VISION_NOTE_DEFAULT` / `_VISION_NOTE_UNSEEN` 定义了但**从未被引用**，实际代码走硬编码字符串 | `grep -rn` |
| F7 | `_ENTITY_RELATION_PRESETS` 在 `memory.py` 与 `page_memory_book.py` **各定义一份** | `grep -rn` |
| F8 | `page_memory_book.py:1247` 硬编码「14 天」，与 `_FOLLOWUP_MUTE_DAYS` 无绑定 | 实读 |
| F9 | `query_vision_memories` 末尾 `items[:limit] if ... else items[:limit]` 两分支等价（死分支 + else 写错） | 实读 |
| F10 | **7 处**裸相对 `config.yaml` 解析（`gui/main.py:119`、`gui/diagnostics.py:313`、`gui/pages/onboarding.py:78`、`core/__init__.py:1009`、`main.py:93/108`、`utils.py:308/368/386`、`helpers.py:245`） | `grep -rn` |
| F11 | 话题只有**通道①静态 top-3 快照**注入；实体/规则/影像/情绪都有提及命中注入，唯独话题没有 | 实读 `chat_service.py:1370-1400` |
| F12 | `C1 知识库` / `C2 待办` 的「GUI 零引用」结论**已过时**——GUI 已注册命令与提醒调度器 | `gui/main.py:95/98/231/234` |

### 1.4 ★ 落点校正（**诚实记录**）

1. **`docs/audit-功能真实性清单-2026-09-07.md` 的 C1/C2 已过时**：该审计判定两者「后端真实但 GUI 零引用」，但现版本 GUI 已接线（F12）。**按它办事会做无用功**——记录在此避免后续误用。
2. **「裸 print」这条不该机械替换**：清点后集中在 `gui/main.py:38-49`、`utils.py:160-216` 的**依赖缺失引导路径**——那时日志系统尚未初始化，`print` 是唯一能到达用户的通道。**保留不动是正确决策**，不是遗漏。真正的 lib 层裸 print 本轮未发现。
3. **`update_topic_status` 删除而非保留**：它「更新状态但不移动列表」，与 `complete_topic`（改状态 + 移入 archived）语义重叠且零调用。保留它只会让后续维护者误用它造出「active 里 status=completed」的脏状态。
4. **本版曾引入一个真 bug 并被测试当场捕获**：`_effective_patterns` 最初把外挂词表的 `completion`（纯字符串列表）当成 `(正则, 标签)` 二元组处理，导致该键完全失效。修复见 D-V25-06。
5. **Windows 并发写有硬限制**：唯一临时名解决了「交错写入」，但 `os.replace` 并发替换同一目标仍会抛 `WinError 5`（共享冲突）。这不是本版引入的，但并发写频率上升后被暴露——故加有界重试（D-V25-02）。

---

## 2. 架构决策（D-V25-01 ~ D-V25-08）

### D-V25-01 MemoryManager 进程内锁

`__init__` 增加 `self._lock = threading.RLock()`；`_load` 与 `_save` 全程持锁。

- **用 `RLock` 而非 `Lock`**：`_save()` 会被已持锁的路径再次调用（如 `complete_topic` 内部），普通 `Lock` 会自死锁。
- **只保证进程内**：跨进程（CLI + GUI 各持一个实例）仍靠 `.bak.1` 快照与原子 replace 兜底，不引入跨进程锁（无第三方依赖约束，R-F）。

### D-V25-02 原子写：唯一临时名 + 有界重试

`utils._atomic_write_json` 两处加固：

```python
tmp = "%s.tmp.%d.%d" % (path, os.getpid(), threading.get_ident())   # 唯一化
...
for attempt in range(5):                       # Windows 共享冲突重试
    try:
        os.replace(tmp, path); return
    except PermissionError as exc:
        last_exc = exc
        time.sleep(0.02 * (attempt + 1))
```

失败路径清理自己的临时文件（`except BaseException` → `os.remove(tmp)` → `raise`），不留垃圾。

### D-V25-03 死代码与常量单一事实源

| 动作 | 对象 |
|---|---|
| 删除 | `MemoryManager.update_topic_status`（F5，全仓零调用） |
| 接线 | `_VISION_NOTE_DEFAULT` 取代两处硬编码字符串（F6） |
| 去重 | `page_memory_book` 改为从 `memory` 导入 `_ENTITY_RELATION_PRESETS` 与 `_FOLLOWUP_MUTE_DAYS`，删本地副本、tooltip 改 f-string 绑定常量（F7/F8） |
| 修正 | `query_vision_memories` 去掉等价死分支，`limit=None` 正确返回全部（F9） |

### D-V25-04 话题完成自动检测

在 `extract_from_dialogue` 的话题提取之后追加一段：

```
若消息命中任一完成句式（搞定了/完成了/上线了/考完了/交付了…）
  则遍历 active 话题，**同时满足** subject 整串或 ≥2 字分词出现在消息里 → complete_topic(subject)
```

**核心守护（本决策最重要的一条）**：只说完成词而不点名话题时**绝不猜测**。用户说「今天搞定了好多事」而手里有「向量数据库」话题时，**不得**归档它。理由：误归档让用户的话题凭空消失，比漏归档严重得多（对齐 R-K 诚实边界与 R-I 删除即遗忘的严肃性）。

### D-V25-05 话题提及注入通道

补上双通道体系的最后缺口（F11）：

- **数据侧**：`MemoryManager.find_topics_by_name(text, limit)` —— 与 `find_entities_by_name` 对称，两点不同：
  1. 含空格话题按 ≥2 字分词补充命中（否则「学 Rust」在用户说「Rust」时永远唤不醒）
  2. `active` 与 `archived` **都搜**（归档话题被自然唤起正是本通道存在的理由）
  3. 返回**副本**（防调用方改到内部数据）
- **注入侧**：`gui/chat_service.py::build_topic_mention_injection`（纯函数，守卫式）→ 产出「【之前聊过】主人提过「X」（N 天前），已经完成了；…」，≤150 字符、每轮 ≤2 条。
- **序位**：作为「①b」紧随实体提及之后（提及类聚在一起），不改既有先后。

**匹配策略是刻意保守的**：只做整串子串 + 空白分词，**不做 CJK 前缀/模糊匹配**。因为这是每轮都跑的通道，误命中等于持续 prompt 污染（R-I payload 最小化）。宁可漏（用户换个说法就唤不醒），不可误。此口径由测试 `test_partial_cjk_prefix_does_not_match` 钉住。

### D-V25-06 提取词表外挂 JSON 热补

新增 `~/.maid_coder/memory_patterns.json`（与记忆文件同目录），支持四个键：

```json
{ "preference": [["正则", "类型"]], "topic": [["正则", "状态"]],
  "completion": ["完成词"], "emotion_keywords": {"分类": ["词"]} }
```

- **追加式合并**：外挂条目接在内置**之后**（正则按序首命中），内置优先级不受影响。
- **mtime 热补**：`(st_mtime_ns, st_size)` 变化才重载并缓存，改词表不必重启。
- **坏文件降级**：解析失败 / 类型不对 / 半截写入 → 静默只用内置（绝不因词表炸掉提取链）。
- **深拷贝隔离**：合并前对内置做 JSON 往返深拷贝，杜绝外挂数据污染内置表。
- **宽容 `completion` 的两种写法**：`["词"]` 与 `[["词"]]` 都接受（本版曾因把它当二元组处理而完全失效，见 §1.4-4）。

### D-V25-07 会话/崩溃恢复不再回放全局数据

`session.py::load` 与 `utils.py` 崩溃恢复路径**删除**对 `memory_mgr.from_dict` / `intimacy.from_dict` 的调用。

理由：`memory` 与 `intimacy` 都是**全局单例数据**（各有一个权威文件），而会话文件里嵌的那份是「存这个会话当时的快照」。加载旧会话会把快照整体替换全局数据（`from_dict` 内部还会 `_save()` 落盘），等于**用三周前的状态覆盖至今的全部记忆**——这是数据回退，不是恢复。

会话文件**仍保留这两个键**（存档价值：可人工查证当时状态），只是不再应用。

### D-V25-08 配置路径锚定应用根

`core/path_guard.py`（L0，无循环风险）新增：

```python
def resolve_app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent    # 打包：exe 所在目录
    return Path(__file__).resolve().parent.parent       # 源码：项目根

def resolve_config_path() -> Path:
    return resolve_app_root() / "config.yaml"
```

**注意与 `gui/main.py:12` 的 `BASE_DIR = sys._MEIPASS` 区分**：后者是**打包资源**目录（只读），本函数返回的是**用户可写的安装目录**，onedir 形态下两者不是同一位置。

**零迁移**：现有安装包里 `config.yaml` 就在 `maling.exe` 旁，故解析结果与改前一致；开发版同理（源码根）。

接线 10 处（F10 全部）；并加**源码扫描回归护栏** `test_no_bare_relative_config_path_left`——新增调用点若忘了用 `resolve_config_path`，该测试会红。

---

## 3. 文件清单

### 3.1 新增

| 文件 | 内容 |
|---|---|
| `docs/prd-v25.md` / `docs/design-v25.md` | 本文档对 |
| `tests/test_v25_config_path.py` | 应用根解析 + 原子写加固（11 例） |
| `tests/test_v25_memory_features.py` | 提及注入 / 完成检测 / 词表热补 / 不回放 / 锁与清理（39 例） |

### 3.2 修改

| 文件 | 改动 |
|---|---|
| `memory.py` | +`threading` 导入；+`_TOPIC_COMPLETION_PATTERNS` / `_PATTERNS_FILE` 常量；+`_lock` / `_patterns_cache` / `_patterns_stamp`；+`_patterns_path` / `_effective_patterns` / `find_topics_by_name`；`_load`/`_save` 加锁；`extract_from_dialogue` 与 `detect_emotion` 走 `_effective_patterns`；+完成检测段；删 `update_topic_status`；`_VISION_NOTE_*` 接线；`query_vision_memories` 去死分支 |
| `utils.py` | +`threading` 导入；`_atomic_write_json` 唯一临时名 + 重试 + 失败清理；`_ensure_config` / `_first_run_banner` / `path_guard` 转发改用 `resolve_config_path`；崩溃恢复不再回放 memory/intimacy |
| `session.py` | `load()` 不再回放 memory/intimacy |
| `core/path_guard.py` | +`resolve_app_root` / `resolve_config_path`（+`sys` 导入） |
| `core/__init__.py` | `save()` 兜底路径改 `resolve_config_path` |
| `gui/chat_service.py` | +`parse_iso_dt` 守卫导入；+`_TOPIC_MENTION_MAX` / `_TOPIC_MENTION_LINE_MAX`；+`build_topic_mention_injection`；注入链新增「①b」一行 |
| `gui/main.py` / `gui/diagnostics.py` / `gui/pages/onboarding.py` / `main.py` / `helpers.py` | 配置路径改 `resolve_config_path` |
| `gui/pages/page_memory_book.py` | 关系预设与静默天数改为从 `memory` 导入；tooltip 绑定常量 |
| `CHANGELOG.md` | v2.5.0 条目（含酒馆弃用记要） |

### 3.3 明确不动

| 对象 | 理由 |
|---|---|
| `docs/OPTIMIZATION_BACKLOG_v2.1.md` 的 P0 两项（`chat_panel.py` 3926 行拆分、1033 处宽泛 except） | 改动面极大，需独立立项与分批回归，**不在本版塞车**。本版只做其中可直接验证的小项（死代码/常量漂移） |
| `version.json` | 发布时由 `tools/build_release.py` 回填，手工改会破坏更新器 |
| `session.save/load` 的**相对文件名** | 又一处相对路径问题（`f"{safe_name}.json"` 落在工作目录）。修复涉及会话存储位置迁移，**风险高于收益**，本版只记录不修（见 §5.4） |
| `build_memory_context` | 300 字符预算与段序被测试钉死 |
| 酒馆相关一切 | 本版起**标记弃用**，只修不增 |

---

## 4. 为什么是这个范围

用户原话是「一、二全部能修的修，三、四可以加」。据此逐条判定：

| 条目 | 判定 | 理由 |
|---|---|---|
| 二-1 线程安全 | ✅ 做 | 改动小、风险真实且随写入频率上升 |
| 二-2 会话覆盖记忆 | ✅ 做 | 数据完整性，越晚修越可能真丢数据 |
| 二-3 死代码/常量漂移 | ✅ 做 | 低风险、可测试、减少后续误用 |
| 二-4 CLI/GUI 对称性审计 | ✅ 做（本轮范围） | 复扫确认：除 v2.4 已修的捕获链外，未发现第二处同类缺口；C1/C2 已过时（F12） |
| 二-5 配置路径 | ✅ 做 | 一次修掉一整类坑，且零迁移 |
| 三 话题提及注入 | ✅ 做 | 架构零阻力，价值最高 |
| 四 完成检测 | ✅ 做 | 最便宜的能力补齐 |
| 四 词表外挂 | ✅ 做 | 解锁「不改代码扩词表」 |
| 四 实体自动提议 | ⏸ 推迟 | v1.8 留的空壳钩子需要完整交互链（句式词表 → 尾部轻问 → 两键确认），1–2 天工作量，**应独立立项** |
| 四 评分权重校准 | ⏸ 推迟 | 需要真实话题分布数据（当前用户记忆仍为空），拍脑袋调参无依据 |
| 一 P0 两项 | ⏸ 推迟 | 见 §3.3 |
| 酒馆 T-20 记忆钩子 | ❌ 取消 | 酒馆弃用，不再投入 |

---

## 5. 测试与验收

### 5.1 新增测试（50 例）

| 文件 | 覆盖 |
|---|---|
| `test_v25_config_path.py`（11） | 源码/打包两种形态的应用根；**换工作目录不改变解析结果**；源码扫描护栏（禁止裸相对 config.yaml 回归）；原子写不留临时文件/失败清理/并发不交错 |
| `test_v25_memory_features.py`（39） | 提及检索（含归档、分词、副本、保守匹配口径）；注入构建器（格式/已完成标注/零命中/长度上限/异常不抛）；完成检测（正向 + **不点名不猜** + 无完成词不归档 + 参数化多句式）；词表热补（四个键各自生效、内置优先、坏文件降级、类型错容忍、mtime 重载、路径就近）；不回放（行为 + spy 双保险）；RLock 可重入；并发写文件可解析；死代码删除与常量接线 |

### 5.2 验收判据

- `py_compile` 全改动文件通过（共享知识 25）
- 新增 50 例全绿
- **全量回归零回归**

### 5.3 全量回归结果

```
1 failed, 2451 passed, 9 skipped in 242.72s
```

唯一失败 `test_v20_updater.py::test_enumerate_finds_own_process` 为**既有环境问题**（Windows venv 的 `python.exe` 重定向器使进程真实 image 路径不在被枚举盘符下），与本版无依赖关系——v2.4 已用三条证据确认（依赖模块零改动 / 单独跑即失败 / 测试自身 docstring 已说明），本版结论相同。

### 5.4 遗留（已记录，未修）

1. **`session.save/load` 用相对文件名**：会话落盘位置随工作目录漂移，与 D-V25-08 属同一类问题，但修复需迁移既有会话文件，风险高于收益。
2. **跨进程写仍无锁**：D-V25-01 只保证进程内。CLI 与 GUI 同时运行时的冲突由「唯一临时名 + replace 重试 + `.bak.1` 快照」三层兜底，但**末次写者胜出**语义不变。
3. **话题提及匹配偏保守**：用户换用同义词/简称时唤不醒（如「装修计划」↔「装修」）。若后续实测发现召回不足，再评估引入更宽的匹配——但那需要同时设计防误注入机制。

---

## 6. 红线对照

| 红线 | 实现对照 | 验证 |
|---|---|---|
| **R-A** 无焦虑 | 新增注入纯文本（「N 天前」「已经完成了」），无分数/计数/百分比；未新增任何 UI | 未新增 UI 触点 |
| **R-I** 本地与遗忘 | 词表外挂与记忆同目录（全本地）；提及注入走 `request_injections`（只活当轮、不入历史）；返回副本不改内部态 | `test_returns_copies_not_internal_objects` |
| **R-K** 诚实边界 | §1.4 记录三项落点校正与一处自引入 bug；§5.3 如实报既有失败；§5.4 列出未修项 | 本文 §1.4/§5.4 |
| **R-F** 零新增依赖 | 全为标准库（`threading` / `shutil` / `json`），无新三方包 | 无 requirements 变更 |
| **R-J④⑤** 群聊三隔离 | 未触及群聊路径 | 既有 `TestTripleIsolation` 未改且绿 |
| **共享知识 18** 读时迁移 | 外挂词表是**独立文件**，不进 `user_memory.json` schema | 无 schema 变更 |
| **共享知识 23** 测试隔离 | 新测试全部 `tmp_path`；会话测试 `chdir` + 打桩 `_memory_path` | 无真实目录读写 |
| **共享知识 25** 双绿 | `py_compile` + pytest | §5.2 |

---

*文档版本：v2.5a（2026-09-19）*
