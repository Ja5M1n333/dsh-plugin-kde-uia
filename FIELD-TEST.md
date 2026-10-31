# 首次真机实测报告 — Plasma 6 / Wayland（2026-10-31）

0.1.0 发布时写明「还没在真实 KDE 桌面上跑过」。这份报告是第一次**真实环境**验证，
由仓库作者在一台实际的 Plasma 6 Wayland 桌面上完成，结论和每个失败项都可复现。

- 对应版本：**0.1.3**（三轮实测：0.1.1 首次跑通 / 0.1.2 修复 activate 与文本 / 0.1.3 读出网页正文）
- 测试日期：2026-10-31（0.1.2、0.1.3 同日追加）
- 测试者：仓库作者（本人），机器为用户自用主机

## 环境

| 项 | 值 |
|---|---|
| 发行版 | Arch Linux（Nyarch 定制发行版，`ID=arch`） |
| 桌面 | KDE Plasma 6.8.2，**Wayland** 会话（XWayland 在 `:1`） |
| 窗口管理器 | KWin 6.8.2（`kwin_wayland`） |
| Python | 3.14.8（发行版 `/usr/bin/python3`） |
| PyGObject / AT-SPI | 3.58.1 / at-spi2-core 2.62.1 |
| 无障碍 | `org.a11y.Status.IsEnabled = true` |
| 窗口管理工具 | `kdotool` 0.3.0（AUR，已装）、`qdbus6`、`kwriteconfig6` |
| 截图后端 | `spectacle`（`grim`、`xdotool`、`wmctrl` 未安装） |
| DSH | 0.2.0-rc.2（Desktop 44） |

## 结论速览（v0.1.3）

| 能力 | 结果 |
|---|---|
| `kde_uia_doctor` 六项检查 | ✅ 全部通过 |
| 窗口列表（AT-SPI + kdotool 合并） | ✅ 通过 |
| 元素树 `tree` / `find` / `info` | ✅ 通过 |
| 按无障碍动作语义点击 + 状态回读 | ✅ 通过 |
| 截图 | ✅ 通过（spectacle） |
| 窗口激活 / 最小化 / 关闭 / 缩放 | ✅ 通过（0.1.2 修复 `window-op` 后） |
| `kde_uia_keys` / `kde_uia_type`（按键注入） | ✅ 通过，**需 `ydotool`**（0.1.2 新增后端） |
| **读取网页正文（不用截图）** | ✅ 通过，`tree-text`（0.1.3 新增） |
| 终端内容 | ⚠️ 部分：Konsole 报告 7181 字符但只提供约 2591 |

> **一句话：读、找、点、打字、截图、控制窗口全部可用；读网页正文靠 `tree-text`，不靠 OCR。**

### 三次迭代分别解决了什么

| 版本 | 解决的问题 |
|---|---|
| 0.1.1 | 客户端 10 处 PyGObject / Plasma 6 缺陷，让读树、点击、截图可用 |
| 0.1.2 | `kde_uia_activate` 的 `window-op` 报错；所有文本读取返回空；新增 `ydotool` 输入后端 |
| 0.1.3 | 新增 `tree-text` 与 `tree --include_text`：网页正文终于能读 |

## 复现命令

在桌面会话里执行（客户端源码目录 `dsh-plugin-kde-uia/python` 或安装后的 `/opt/dsh/kde-uia`）：

```bash
export PYTHONPATH=/opt/dsh/kde-uia
python3 -m kde_uia doctor
python3 -m kde_uia windows
python3 -m kde_uia find --text "显示缩略图" --window Gwenview
python3 -m kde_uia click --text "显示缩略图" --strategy atspi
python3 -m kde_uia screenshot -o /tmp/shot.png
python3 -m kde_uia press F2          # 在 Wayland 上：接口成功，但应用不会响应
```

## 原始结果

### 1. `doctor`（全部通过）

```
[+] display          kde / wayland / display=:1
[+] atspi            atspi initialised; 23 registered applications
[+] window-tree      7 accessible windows
[+] window-backend   KdotoolBackend: 7 windows
[+] input            available: atspi, kdotool, dbus
[+] screenshot       available: spectacle, import, xwd, portal, kwin, drm
```

### 2. 窗口列表

AT-SPI 窗口带 `uia:` 引用，kdotool 窗口带 KWin 窗口 id，两者合并返回。
两个 Gwenview 窗口以前会得到**同一个** `uia:1:gwenview:0`，现在靠实例后缀区分：

```
  uia:1:gwenview:0:8   1366x696+0+0   gwenview   屏幕截图_20261031_182007.png - ... — Gwenview
  uia:1:gwenview:0:20  1366x696+0+0   gwenview   屏幕截图_20261031_182510.png - ... — Gwenview
  {7ce2b66c-...}       1366x724+0+0   deepseek-harness   安装 dsh-plugin-kde-uia 插件 — DeepSeek Harness
```

引用可以往返解析：

```
resolve uia:1:gwenview:0:8  -> '屏幕截图_20261031_182007.png - 1496x854 - 71%  — Gwenview'
resolve uia:1:gwenview:0:20 -> '屏幕截图_20261031_182510.png - 1496x854 - 71%  — Gwenview'
```

### 3. 窗口内 `find` + 语义点击

```
$ find {"window": "...182510.png - 1366x724 - 83%  — Gwenview", "match": "exact", "role": "check box"}
count: 6
  uia:1:gwenview:0/0/0/2/1/1/1:20   显示缩略图
  uia:1:gwenview:0/0/0/2/1/1/4/0:20 适合视图
  uia:1:gwenview:0/3/3:20           浏览
  uia:1:gwenview:0/3/4:20           查看

$ click {"ref": "uia:1:gwenview:0/0/0/2/1/1/1:20", "strategy": "atspi"}
backend: atspi  ->  states: []      （点击前未勾选）
再次回读              ->  states: ['checked']   ✅
```

再点一次回到未勾选，确认是真实切换而不是显示噪声。

### 4. 截图

```
path=/tmp/field-shot.png  width=1366  height=768  backend=spectacle
```

### 5. 按键（✅ 通过，需 `ydotool`）

0.1.1 时按键接口返回成功但事件被丢弃。0.1.2 接入 `ydotool` 后实测：

```
$ echo lag-test-one      ← 由 kd_uia_type 逐字送入
lag-test-one             ← 回车由 kde_uia_keys 送入，命令真的执行了
```

注意：`ydotool` 用 Linux 键码注入，会被**输入法**影响。拼音激活时敲英文 URL 会得到汉字，
需要先切到 `keyboard-us`（或改用剪贴板粘贴）。

### 6. 读取网页正文（✅ 通过，0.1.3 新增）

目标：不截图、不用 OCR，用插件读出 `platform.deepseek.com/usage` 的余额。

**关键发现：正文不在 `document web` 节点里**（那里只有 1 个占位字符），而是分散在下级
`section` 节点，只能通过 Text 接口逐节点读取。

`tree-text` 一次调用返回 57 行：

```
充值余额        ¥5.97   CNY
累计消费金额     ¥99.27
本期消费金额     ¥41.47
API 请求次数     3,920
Tokens          546,407,414
deepseek-flash  3,836 次 / 543,799,825 tokens
deepseek-v4-pro 84 次 / 2,607,589 tokens
```

这是本项目"让 agent 读窗口而非看截图"目标的核心证据。

## 这台机器上各项输入路径的真实状态

| 路径 | 状态 |
|---|---|
| XTest（`xdotool`，X11 常规做法） | ❌ 原生 Wayland 下为空操作 |
| `kdotool` 0.3.0 | ❌ **没有 `key`/`click`/`type` 子命令**（只有窗口类命令） |
| KWin 脚本桥（`org.kde.kwin.Scripting`） | ❌ 6.8.2 中 `loadScript` 返回 id、`isScriptLoaded` 为 true，但脚本**从不执行** |
| `/KWin` 的 `org.kde.KConfig` | ❌ Plasma 6 不导出该接口 |
| `Atspi.generate_keyboard_event` | ⚠️ 返回成功，事件未送达（本机 KWin）；已降为兜底 |
| `Atspi.Action` 语义动作 | ✅ 可用（Qt 控件的 Press/Toggle） |
| `EditableText` 直接写入文本 | ⚠️ 不依赖键盘，但仅在应用暴露可编辑元素且接口可用时有效 |
| `ydotool`（AUR，`/dev/uinput`） | ✅ **可用**（0.1.2 起为首选后端）：需 `/dev/uinput` 可写 + 常驻 `ydotoold` |
| XDG 远程桌面门户 `RemoteDesktop` | KDE 侧已实现，需用户授权；可作为后备方案 |

**结论：原生 Wayland 下，键盘注入必须走 `ydotool`（内核级输入）。** 插件会检测 `ydotoold` 自动启用。

## 三轮实测累计发现的缺陷

0.1.1 修复了以下 10 处，详见 [CHANGELOG](../dsh-plugin-kde-uia/CHANGELOG.md#011--2026-10-31)：

1. `diagnose` 用了 `child_count()`，PyGObject 是 `get_child_count()`
2. 状态读取用 `get_state_set()`，PyGObject 是 `.states`（导致"树是空的"）
3. KWin 脚本桥在 Plasma 6 不可用（`org.kde.KConfig` 不存在、脚本不执行）
4. Qt 对无值控件返回未初始化 double（`6.9e-310`）
5. 带 `role`/`name` 的窗口内搜索先对窗口框过滤，永远搜不到
6. 同一应用多实例的引用冲突
7. 未注册为 AT-SPI 客户端，子节点未预取
8. 动作接口 `get_action_count()`/`do_action(0, name)` 与实际 API 不符
9. spectacle 截图路径把 `_require_png()` 传了两个参数；`import` 缺 `-silent`
10. 输入只走 xdotool/kdotool，在原生 Wayland 上完全没有可用路径

## 三轮实测逐条记录（时间顺序）

### 第一轮 · 0.1.1：插件能不能加载

| 观测 | 结果 |
|---|---|
| 在 DSH 插件页启用 | 报 `TypeError: Cannot read properties of undefined (reading 'validate')`，条目从未激活 |
| 原因 | `Config` 是普通 JSON Schema（加载器需要 Standard Schema 的 `~standard.validate`）；`apply()` 返回了对象（cordis 视为 setup promise） |
| 修复 | `Config` 改用 schemastery；`apply()` 返回 `undefined`，teardown 走 `ctx.effect()` |
| 验证 | 真实加载器下 13 个 `kde_uia_*` 工具注册成功，自检输出 `desktop automation ready` |

### 第二轮 · 0.1.2：agent 直接驱动工具

| 工具 | 观测 |
|---|---|
| `kde_uia_doctor` | 六项全过（21 个应用、6 个无障碍窗口、5 个 kdotool 窗口） |
| `kde_uia_windows` | AT-SPI 与 kdotool 窗口正确合并 |
| `kde_uia_tree`（Konsole） | 工具栏、按钮、`actions=Press` 全部读出 |
| `kde_uia_find` / `info` | 命中准确，字段完整 |
| `kde_uia_activate` | ❌ 报 `unknown op 'window-op'` → 修复后 ✅ |
| `kde_uia_type` | ❌ 返回成功但终端无输入 → 接 `ydotool` 后 ✅ |

`ydotool` 实测（第一次成功）：

```
$ echo ydotool-ok     ← ydotool 直接注入
ydotool-ok            ← 回车同样生效
```

**踩坑记录：** 默认 `-d 20` 会丢字符（`echo` 变成 `keco`），改成 `-d 40 -H 40` 后一字不差。

### 第三轮 · 0.1.3：读用量页（本次任务）

| 步骤 | 做法 | 结果 |
|---|---|---|
| 找窗口 | `kde_uia_windows` | 定位 Firefox |
| 激活 | `kde_uia_activate`（0.1.2 修复项） | ✅ |
| 聚焦地址栏 | `ydotool key ctrl+l` | ✅ |
| 输入 URL | `ydotool type` | ✅ 需先切英文输入法 |
| 回车 | `ydotool key Enter` | ✅ 页面标题变为 `DeepSeek 开放平台` |
| 直接读 `document web` | `Atspi.Text.get_text` | ❌ 只有 1 个占位字符 |
| 向下遍历 `section` | 逐节点 Text 读取 | ✅ 88 个文本节点 |
| `tree-text` 一次调用 | 新操作 | ✅ 57 行纯文本 |

**读出的真实数据（`platform.deepseek.com/usage`）：**

```
充值余额        ¥5.97   CNY
累计消费金额     ¥99.27
本期消费金额     ¥41.47   （09/17 - 10/17）
API 请求次数     3,920
Tokens          546,407,414
deepseek-flash  3,836 次请求 / 543,799,825 tokens
deepseek-v4-pro 84 次请求 / 2,607,589 tokens
```

### 踩坑与教训（写给未来的自己）

1. **`document web` 永远读不到正文。** 它只有占位符，真正内容在 `section` 里。
   第一版只读 `document web` 就下结论"网页正文读不了"，是方法错，不是能力不足。
2. **输入法会改写键盘输入。** 拼音激活时敲英文 URL 得到 `普拉提佛人民。的哦配色恶口。com/usage`。
   正确做法：先切 `keyboard-us`，或改用剪贴板。
3. **接口返回成功 ≠ 真的送达。** 本机 `Atspi.generate_keyboard_event` 返回 `True` 但事件被丢弃；
   `ydotool` 首次也返回 0 却丢了字符。**必须用行为验证**（读回文本或截图）。
4. **截图可以做最后兜底，但不该是首选。** 插件的价值就在于用结构读窗口；
   先 `find`/`info`/`tree-text`，读不到再截图。
5. **别用截图代替 `tree-text`。** 同样读余额，截图要 1 张图，`tree-text` 只要 57 行文本。

## 尚未验证

- Plasma 5.x / 纯 X11 会话
- 其他发行版（Debian/Ubuntu/Fedora）与系统 Python 版本
- 多显示器、分数缩放下的坐标换算
- XDG 远程桌面门户（`RemoteDesktop`）作为输入后端
- WSL/SSH 传输在 0.1.2/0.1.3 上的回归（0.1.0 曾在 WSL 验证过）
- 非 Firefox 浏览器（Chromium 系）的 `document web` 文本暴露情况

## 如何复现本次结果

```bash
# 1) 环境（Arch + Plasma 6 Wayland）
sudo pacman -S python-gobject at-spi2-core qt6-tools kconfig spectacle
yay -S kdotool ydotool
ydotoold --socket-path=$XDG_RUNTIME_DIR/.ydotool_socket --socket-perm=0600

# 2) 客户端
export PYTHONPATH=/opt/dsh/kde-uia
python3 -m kde_uia doctor

# 3) 读一个网页（不用截图）
python3 -m kde_uia tree-text --window Firefox --depth 16 --max-chars 20000
```
