# 首次真机实测报告 — Plasma 6 / Wayland（2026-10-31）

0.1.0 发布时写明「还没在真实 KDE 桌面上跑过」。这份报告是第一次**真实环境**验证，
由仓库作者在一台实际的 Plasma 6 Wayland 桌面上完成，结论和每个失败项都可复现。

- 对应版本：**0.1.1**（客户端 `kde_uia` 与插件同步升版）
- 测试日期：2026-10-31
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

## 结论速览

| 能力 | 结果 |
|---|---|
| `kde_uia_doctor` 六项检查 | ✅ 全部通过 |
| 窗口列表（AT-SPI + kdotool 合并） | ✅ 通过 |
| 元素树 `tree` / `find` / `info` | ✅ 通过 |
| 按无障碍动作语义点击 + 状态回读 | ✅ 通过 |
| 截图 | ✅ 通过（spectacle） |
| 窗口激活 / 最小化 / 关闭 / 缩放 | ✅ 通过（仅 XWayland 窗口，见限制） |
| `kde_uia_keys` / `kde_uia_type`（按键注入） | ❌ **未通过**：接口返回成功，但事件未送达应用 |
| 0.1.0 客户端在真机上开箱即用 | ❌ 失败（10 处缺陷，见 CHANGELOG） |

> **一句话：读、找、点、截图、控制窗口可用；键盘输入在这台 Wayland 机器上不可用。**

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

### 5. 按键（❌ 未通过）

```
$ press {"key": "shift+F10"}
{"ok": true, "backend": "atspi", "kind": "key", "combo": "shift+F10"}
```

接口报告成功，但行为验证不成立：在 Gwenview 里发送 `n`（下一张）或 `F2`（主菜单）
后，窗口标题与控件树都不变；在 DSH 应用里发送 `F9`/`ctrl+v` 也没有任何界面反应。
`Atspi.generate_keyboard_event()` 返回 `True`，事件在本机 KWin 上被丢弃。

## 这台机器上各项输入路径的真实状态

| 路径 | 状态 |
|---|---|
| XTest（`xdotool`，X11 常规做法） | ❌ 原生 Wayland 下为空操作 |
| `kdotool` 0.3.0 | ❌ **没有 `key`/`click`/`type` 子命令**（只有窗口类命令） |
| KWin 脚本桥（`org.kde.kwin.Scripting`） | ❌ 6.8.2 中 `loadScript` 返回 id、`isScriptLoaded` 为 true，但脚本**从不执行** |
| `/KWin` 的 `org.kde.KConfig` | ❌ Plasma 6 不导出该接口 |
| `Atspi.generate_keyboard_event` | ⚠️ 返回成功，事件未送达（本机 KWin） |
| `Atspi.Action` 语义动作 | ✅ 可用（Qt 控件的 Press/Toggle） |
| `EditableText` 直接写入文本 | ⚠️ 不依赖键盘，但仅在应用暴露可编辑元素且接口可用时有效 |
| `ydotool`（AUR，`/dev/uinput`） | 未安装；需 `input` 组 + 常驻 `ydotoold`，涉及安全边界，未擅自启用 |
| XDG 远程桌面门户 `RemoteDesktop` | KDE 侧已实现，需用户授权；可作为后备方案 |

**结论：在当前这类「原生 Wayland + 无输入权限」的环境里，键盘注入不是本插件能靠自身代码解决的。**

## 这次实地测试顺带发现的 0.1.0 缺陷

全部已在 0.1.1 修复，详见 [CHANGELOG](../dsh-plugin-kde-uia/CHANGELOG.md#011--2026-10-31)：

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

## 尚未验证

- Plasma 5.x / X11 会话
- 其他发行版（Debian/Ubuntu/Fedora）与系统 Python 版本
- 多显示器、分数缩放下的坐标换算
- `ydotool` 或远程桌面门户作为键盘后端（尚未接入）
- WSL/SSH 传输的真实桌面往返（0.1.0 已在 WSL 验证过，0.1.1 未回归）

如果这些在你的机器上跑通了（或失败了），欢迎在 issue 里附上 `kde_uia_doctor` 输出与
本报告的对照结果。
