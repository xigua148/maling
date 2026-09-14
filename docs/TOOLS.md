# 码铃 MaLing 工具手册

> v1.4.8 — 31 个 Agent 工具完整参考

## 工具分类总览

| 类别 | L0 只读（自动放行） | L1 修改（需授权） |
|------|---------------------|-------------------|
| 文件操作 | read_file, list_dir, file_search, file_info, hash_file | write_file, file_move, file_delete, file_append |
| Git | git_status, git_diff | git_commit |
| 代码执行 | — | run_python, run_command |
| 网络 | web_search, http_get | — |
| 系统 | system_info, get_datetime, env_var, list_processes | clipboard_write |
| 数据 | sqlite_query | — |
| 文本 | count_text, validate_json, validate_yaml, math_eval, regex_test, text_transform, base64_encode, base64_decode | — |
| 图片 | image_info | — |

---

## L0 只读工具

### read_file
读取文件内容（超长自动截断到 3000 字符）。
```json
{"path": "src/main.py"}
```

### list_dir
列出目录下文件和子目录。
```json
{"path": "."}
```

### file_search
在文件中搜索正则匹配的行（类似 grep）。
```json
{"path": "app.py", "pattern": "def \\w+", "max_lines": 50}
```

### file_info
获取文件元数据：大小、修改时间、创建时间。
```json
{"path": "data.json"}
```

### hash_file
计算文件哈希（md5/sha1/sha256）。
```json
{"path": "release.zip", "algorithm": "sha256"}
```

### web_search
联网搜索最新信息。
```json
{"query": "Python 3.13 新特性"}
```

### http_get
获取 URL 页面内容（纯文本，最大 10000 字符）。
```json
{"url": "https://httpbin.org/get", "max_chars": 5000}
```

### system_info
获取系统信息：OS、Python 版本、内存、磁盘等。
```json
{}
```

### get_datetime
获取当前日期时间。
```json
{"format": "%Y-%m-%d %H:%M:%S"}
```

### count_text
统计文本行数、单词数、字符数。
```json
{"text": "hello world\nsecond line"}
```

### validate_json / validate_yaml
验证 JSON/YAML 语法。
```json
{"text": "{\"key\": \"value\"}"}
```

### math_eval
安全计算数学表达式。
```json
{"expression": "2**10 + sin(pi/4)"}
```

### env_var
读取环境变量（只读）。
```json
{"name": "PATH"}
```

### list_processes
列出系统进程（按内存降序）。
```json
{"top_n": 20}
```

### sqlite_query
SQLite 只读查询（仅 SELECT）。
```json
{"db_path": "data.db", "query": "SELECT * FROM users LIMIT 10"}
```

### regex_test
测试正则匹配。
```json
{"pattern": "\\d+", "text": "abc123def456", "flags": "i"}
```

### text_transform
文本变换（upper/lower/title/sort/unique/reverse/lines_count）。
```json
{"text": "hello\nworld\nhello", "operation": "unique"}
```

### base64_encode / base64_decode
Base64 编解码。
```json
{"text": "Hello World"}
```

### image_info
获取图片元数据（需 Pillow）。
```json
{"path": "photo.png"}
```

---

## L1 修改工具（需授权）

### write_file
创建或覆写文件（自动备份 .bak）。
```json
{"path": "output.txt", "content": "hello world"}
```

### file_move
移动/重命名文件。
```json
{"src": "old.txt", "dst": "new.txt"}
```

### file_delete
删除文件（不可恢复）。
```json
{"path": "temp.txt"}
```

### file_append
追加内容到文件末尾。
```json
{"path": "log.txt", "content": "new log entry\n"}
```

### git_commit
暂存全部改动并提交。
```json
{"message": "fix: 修复登录逻辑"}
```

### run_python
在 AST 沙箱内执行 Python 代码（不能访问文件系统/网络）。
```json
{"code": "print(sum(i*i for i in range(10)))"}
```

### run_command
执行白名单命令（仅 python/python3/pytest/node）。
```json
{"command": "python tests/test_utils.py", "cwd": "."}
```

### clipboard_write
复制文本到系统剪贴板。
```json
{"text": "已复制的内容"}
```

---

## 安全说明

- **L0 工具**：只读操作，自动放行，无需用户授权
- **L1 工具**：修改操作，需要用户授权
  - 目标在 workspace 内 → 自动放行
  - 目标在 workspace 外 → 弹出授权对话框
  - 无确认渠道 → 拒绝（fail-safe）
- **run_command**：仅放行 python/python3/pytest/node 白名单解释器
- **sqlite_query**：仅允许 SELECT，禁止修改操作
- **run_python**：AST 沙箱，禁止 import os/subprocess 等
