/**
 * maling_node_compat.cjs —— 码铃（MaLing）内置 SillyTavern 的 Node 运行时兼容补丁
 * ===========================================================================
 *
 * 用法（由 tavern_backend.py 注入，不需要人工调用）：
 *
 *     node --require <本文件绝对路径> server.js --port ... --dataRoot ...
 *
 * ---------------------------------------------------------------------------
 * 一、这个文件解决什么问题
 * ---------------------------------------------------------------------------
 *
 * Node v22.22.2 的 `fs.cpSync()` 在 **非 ASCII 路径** 下递归复制**目录**时，
 * 会以 **静默硬崩溃** 收场：进程直接被 NTSTATUS 异常终止，stdout / stderr 没有
 * 任何错误输出，`try/catch` 也抓不到。实测退出码为
 * `0xC0000005`（3221225477，ACCESS_VIOLATION）或 `0xC0000409`（3221226505，
 * STACK_BUFFER_OVERRUN），具体码取决于崩溃点。
 * 上游 issue：nodejs/node#54476。
 *
 * 只要**工程根含中文（或方括号等非 ASCII 字符）**就会命中 —— 安装路径形如
 * 「盘符:\中文目录\」时必现；中文用户的 `%APPDATA%`（内置 ST 的数据目录所在）
 * 同样可能命中（此时表现为"静默不复制"，比崩溃更隐蔽）。所以这不是"某个用户的
 * 环境特例"，而是中文 Windows 用户下的必现问题。
 *
 * ---------------------------------------------------------------------------
 * 二、为什么必须在 Node 层修，而不能在 Python 层绕
 * ---------------------------------------------------------------------------
 *
 * SillyTavern 源码里 `fs.cpSync` 共 **12 处、分布在 7 个文件**：
 *
 *     src/users.js:401 / 403 / 411 / 413 / 466 / 522   用户数据迁移（单文件 + recursive 目录）
 *     src/endpoints/content-manager.js:173             内容包播种（recursive, force:false）
 *     src/endpoints/characters.js:1086                 角色改名时迁移 chats 目录（recursive + filter）
 *     src/endpoints/extensions.js:366                  扩展目录搬移（recursive, force:true）
 *     src/transformers.js:108                          模型缓存迁移（recursive, force:true）
 *     src/endpoints/secrets.js:414                     secrets 备份（单文件，无 options）
 *     src/endpoints/sprites.js:281                     精灵图上传落盘（单文件，无 options）
 *
 * Python 侧"预先预置内容"最多只能绕开 content-manager 那 1 处，其余 11 处照样崩。
 * 因此只能从 `fs` 层根治。
 *
 * ---------------------------------------------------------------------------
 * 三、实测触发条件（用本仓库 _internal/pi_runtime/node.exe v22.22.2 逐项验证）
 * ---------------------------------------------------------------------------
 *
 *     src 路径       dest 路径      recursive   结果
 *     ---------------------------------------------------------------------
 *     纯 ASCII       纯 ASCII       true        正常（本补丁直接走原生实现）
 *     含非 ASCII     纯 ASCII       true        崩溃 0xC0000005
 *     纯 ASCII       含非 ASCII     true        **静默不复制**（不报错，比崩溃更危险）
 *     含非 ASCII     含非 ASCII     true        崩溃 0xC0000005 / 0xC0000409
 *     含非 ASCII     ——             单文件      正常
 *     含非 ASCII     含非 ASCII     true + filter  正常（Node 的 filter 走慢路径，恰好绕开 bug）
 *
 * 请特别注意第 3 行：dest 含非 ASCII 时不是崩溃，而是 **静默丢数据**。所以
 * "只在 src 非 ASCII 时才接管"是不够的 —— **任一路径含非 ASCII 都必须接管**。
 *
 * 另外实测确认：`[` `]` 这类 ASCII 符号单独出现不会触发；真正触发的是码位 ≥ 0x80
 * 的字符（中文、é、西里尔、emoji 均触发）。
 *
 * ---------------------------------------------------------------------------
 * 四、策略
 * ---------------------------------------------------------------------------
 *
 * 1. 保存原生 `fs.cpSync`；
 * 2. 替换为一个包装：
 *      - src 与 dest **都是纯 ASCII** → 直接调用原生实现，与上游行为逐字节一致，
 *        不引入任何偏差（绝大多数路径走这条快路径）；
 *      - 否则 → 走本文件实现的 **Unicode 安全同步递归复制**
 *        （readdirSync / mkdirSync / copyFileSync / statSync —— 这组原语已实测在
 *          非 ASCII 路径下工作正常）；
 * 3. 首次触发安全实现时打印一行日志，便于验证补丁真的生效。
 *
 * ---------------------------------------------------------------------------
 * 五、边界与已知不覆盖
 * ---------------------------------------------------------------------------
 *
 * - **不修改 SillyTavern 源码**：`vendor/sillytavern/` 保持逐字节不变。本补丁只在
 *   进程启动时替换内存里的 `fs` 模块方法，磁盘上的 ST 一个字节都没动。这也是
 *   AGPL-3.0 合规上最干净的形态（原样捆绑，未构成派生修改）。
 * - 覆盖 ST 实际用到的选项子集：`recursive` / `force` / `filter`，以及单文件复制。
 *   另外顺带实现了 `errorOnExist` / `preserveTimestamps` / `dereference` /
 *   `verbatimSymlinks`，语义对齐实测到的原生行为。
 * - **符号链接**：ST 的 12 处调用点均不涉及符号链接，此处按"逐字复制链接"处理
 *   （对相对链接即原生默认语义）；未实现原生在 `verbatimSymlinks:false` 下把
 *   链接目标重写为相对目标路径的行为。这是有意的取舍，不影响 ST。
 * - **不覆盖 `fs.promises.cp`**：它背后是同一个 bug（走同一套内部 cp 实现），
 *   但 ST 全仓库无调用点。QA 已扫过 ST 源码 **+ 整个 `node_modules`（18,823 个文件）**，
 *   确认 `promises.cp` 与 `fs.cp` 当前均为空，所以现在安全。
 * - **不覆盖 `fs.cp`**（回调版）：同上，ST 无调用点。
 *
 * ⚠️ **升级 SillyTavern 后必须重新扫描三种形态**：
 *
 *     grep -rn "cpSync\|promises\.cp\|[^a-zA-Z]cp(" vendor/sillytavern/src \
 *                                                  vendor/sillytavern/server.js
 *
 *   本补丁只接管 `fs.cpSync`。如果新版本 ST 开始用 `fs.promises.cp` 或 `fs.cp`
 *   （两者有同样的非 ASCII 崩溃问题），**补丁会静默失效** —— 表现为启动期
 *   无声崩溃或静默丢数据，且没有任何报错。届时需要把本文件的包装同步扩展到
 *   这两个入口（可复用同一个 `safeCpSync` 实现，异步版包一层 Promise 即可）。
 *   另外也要复核 12 处调用点的**选项组合**是否仍在本文件支持的子集内。
 * - 其他文件类型（FIFO / socket / 设备文件）与原生一致：静默跳过，不报错。
 *
 * @see https://github.com/nodejs/node/issues/54476
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { fileURLToPath } = require('url');

// ---------------------------------------------------------------------------
// 常量与状态
// ---------------------------------------------------------------------------

/** 纯 ASCII 判定：全部码位 < 0x80。非 BMP 字符（emoji）以代理对出现，同样会被判为 false。 */
const ASCII_ONLY_RE = /^[\u0000-\u007F]*$/;

const LOG_PREFIX = '[maling-node-compat]';

/** 首次触发安全实现时打日志，只打一次（避免刷屏）。 */
let fallbackLogged = false;

// ---------------------------------------------------------------------------
// 基础工具
// ---------------------------------------------------------------------------

/** 把 PathLike 统一成字符串（string / Buffer / URL）。 */
function toPathString(p) {
    if (typeof p === 'string') return p;
    if (Buffer.isBuffer(p)) return p.toString('utf8');
    if (p instanceof URL) return fileURLToPath(p);
    return String(p);
}

function isAsciiOnly(s) {
    return ASCII_ONLY_RE.test(s);
}

/** 构造带 `code` 的错误，形似 Node 原生 fs 错误（ST 的 catch 会读 code / message）。 */
function makeError(code, message) {
    const err = new Error(message);
    err.code = code;
    return err;
}

/** 目标不存在返回 null，其余异常照常抛出。 */
function lstatOrNull(p) {
    try {
        return fs.lstatSync(p);
    } catch (e) {
        if (e && e.code === 'ENOENT') return null;
        throw e;
    }
}

/**
 * 判断 child 是否位于 parent 之内（按路径段比较，避免 `/a/b` 与 `/a/bc` 误判）。
 * 两个入参都应已 resolve 成绝对路径。
 */
function isInside(parent, child) {
    const rel = path.relative(parent, child);
    return rel !== '' && !rel.startsWith('..') && !path.isAbsolute(rel);
}

// ---------------------------------------------------------------------------
// Unicode 安全同步递归复制
// ---------------------------------------------------------------------------

/** 归一化 cpSync 的 options，默认值与原生一致（force 默认 true，recursive 默认 false）。 */
function normalizeOptions(options) {
    const o = (options && typeof options === 'object') ? options : {};
    return {
        recursive: o.recursive === true,
        force: o.force !== false,                 // 原生默认 true
        errorOnExist: o.errorOnExist === true,
        preserveTimestamps: o.preserveTimestamps === true,
        dereference: o.dereference === true,
        verbatimSymlinks: o.verbatimSymlinks === true,
        filter: typeof o.filter === 'function' ? o.filter : null,
    };
}

/**
 * 复制一个条目（文件 / 目录 / 链接）。src 与 dest 必须已是字符串。
 *
 * 调用顺序严格对齐原生：**先 filter，再 stat**（实测：src 不存在时若 filter 返回
 * false 则不报错，返回 true 才抛 ENOENT）。
 */
function copyEntry(src, dest, opts, isRoot) {
    if (opts.filter && !opts.filter(src, dest)) {
        return;                                   // 整棵子树跳过
    }

    const st = opts.dereference ? fs.statSync(src) : fs.lstatSync(src);

    if (st.isSymbolicLink()) {
        copySymlink(src, dest, opts);
        return;
    }

    if (st.isDirectory()) {
        if (!opts.recursive) {
            throw makeError(
                'ERR_FS_EISDIR',
                `Recursive option not enabled, cannot copy a directory: ${src}`);
        }
        if (isRoot && isInside(path.resolve(src), path.resolve(dest))) {
            // 防无限递归：不拦的话 readdirSync 会读到自己刚创建的 dest，栈溢出
            throw makeError(
                'ERR_FS_CP_EINVAL',
                `Cannot copy ${src} to a subdirectory of self ${dest}`);
        }
        copyDirectory(src, dest, opts);
        return;
    }

    if (st.isFile()) {
        copyRegularFile(src, dest, st, opts);
        return;
    }

    // FIFO / socket / 设备文件：与原生一致，静默跳过。
}

function copyDirectory(src, dest, opts) {
    const destStat = lstatOrNull(dest);
    if (destStat && !destStat.isDirectory()) {
        throw makeError(
            'ERR_FS_CP_DIR_TO_NON_DIR',
            `Cannot overwrite non-directory ${dest} with directory ${src}`);
    }
    if (!destStat) {
        // recursive:true 顺带创建缺失的父目录（与原生一致）
        fs.mkdirSync(dest, { recursive: true });
    }

    for (const entry of fs.readdirSync(src)) {
        copyEntry(path.join(src, entry), path.join(dest, entry), opts, false);
    }

    // 实测原生 cpSync 在递归复制目录时 **不保留** 目录的 mode / mtime，
    // 此处保持一致，不做额外 chmod / utimes —— 与上游行为零偏差优先。
}

function copyRegularFile(src, dest, st, opts) {
    const destStat = lstatOrNull(dest);
    if (destStat) {
        if (destStat.isDirectory()) {
            throw makeError(
                'ERR_FS_CP_NON_DIR_TO_DIR',
                `Cannot overwrite directory ${dest} with non-directory ${src}`);
        }
        if (!opts.force) {
            if (opts.errorOnExist) {
                throw makeError(
                    'ERR_FS_CP_EEXIST',
                    `Target already exists: cp returned EEXIST (${dest} already exists) ${dest}`);
            }
            // 实测原生：force:false 且目标已存在 → **静默跳过，不抛错**
            return;
        }
    } else {
        // 实测原生：目标的父目录不存在时会自动创建
        fs.mkdirSync(path.dirname(dest), { recursive: true });
    }

    // copyFileSync 覆盖时截断，且在 Windows 上会连同源文件的只读属性一起复制
    // （实测：源 0o444 → 目标 0o444），与原生 cpSync 行为一致，无需额外 chmod。
    fs.copyFileSync(src, dest);

    if (opts.preserveTimestamps) {
        try {
            fs.utimesSync(dest, st.atime, st.mtime);
        } catch {
            // 时间戳是尽力而为，失败不影响复制结果
        }
    }
}

/**
 * 符号链接：逐字复制链接本身（相对链接即原生默认语义）。
 * 有意未实现原生 `verbatimSymlinks:false` 下"把链接目标重写为相对目标路径"的行为
 * —— ST 的 12 处调用点均不涉及符号链接，见文件头"边界"。
 */
function copySymlink(src, dest, opts) {
    const target = fs.readlinkSync(src);
    const destStat = lstatOrNull(dest);

    if (destStat) {
        if (!opts.force) {
            if (opts.errorOnExist) {
                throw makeError(
                    'ERR_FS_CP_EEXIST',
                    `Target already exists: cp returned EEXIST (${dest} already exists) ${dest}`);
            }
            return;
        }
        // symlinkSync 遇到已存在的路径会 EEXIST，先清掉（只删链接本身，不跟进去）
        fs.rmSync(dest, { force: true });
    } else {
        fs.mkdirSync(path.dirname(dest), { recursive: true });
    }

    // Windows 下不传 type 时 Node 会自行探测 file / dir
    fs.symlinkSync(target, dest);
}

/** Unicode 安全入口：只在任一路径含非 ASCII 时被调用。 */
function safeCpSync(src, dest, options) {
    copyEntry(src, dest, normalizeOptions(options), true);
}

// ---------------------------------------------------------------------------
// 安装补丁
// ---------------------------------------------------------------------------

/** 原生实现（快路径直通）。 */
const nativeCpSync = fs.cpSync;

function malingCpSync(src, dest, options) {
    let srcStr;
    let destStr;
    try {
        srcStr = toPathString(src);
        destStr = toPathString(dest);
    } catch {
        // 路径形态无法识别（极罕见）→ 交回原生，不做猜测
        return nativeCpSync(src, dest, options);
    }

    if (isAsciiOnly(srcStr) && isAsciiOnly(destStr)) {
        // 快路径：与上游逐字节一致，不引入任何偏差
        return nativeCpSync(src, dest, options);
    }

    if (!fallbackLogged) {
        fallbackLogged = true;
        process.stderr.write(
            `${LOG_PREFIX} cpSync fallback used: ${srcStr} -> ${destStr}\n`);
    }

    return safeCpSync(srcStr, destStr, options);
}

fs.cpSync = malingCpSync;

// 供自验脚本直接 require 使用；`--require` 加载时 module.exports 会被丢弃，
// 不影响补丁本身。
module.exports = {
    malingCpSync,
    nativeCpSync,
    safeCpSync,
    isAsciiOnly,
    toPathString,
};
