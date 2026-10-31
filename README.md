# DSH plugins for KDE

给 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 用的 **KDE 桌面自动化插件**：
让 agent 像用 Windows UI Automation 一样，通过无障碍接口（AT-SPI2）读取窗口控件树、按名称点击与输入。

| 内容 | 说明 |
|---|---|
| **[dsh-plugin-kde-uia/](dsh-plugin-kde-uia/README.zh.md)** | 插件本体（中文说明 · [English](dsh-plugin-kde-uia/README.md)） |
| [kde-uia/](kde-uia/README.md) | 底层 Python 客户端库 + 命令行工具 |
| **[FIELD-TEST.md](FIELD-TEST.md)** | **首次真机实测报告（Plasma 6 / Wayland，2026-10-31）** |
| [WORKFLOW.md](WORKFLOW.md) | 开发记录：这一版是怎么一步步做出来的 |
| [dsh-plugin-kde-uia/MAINTENANCE.md](dsh-plugin-kde-uia/MAINTENANCE.md) | 维护说明：能承诺什么、接手方式、发布流程 |
| [install.sh](install.sh) | 本机安装脚本（装客户端 + 把插件放进 DSH desktop profile） |

## 快速开始

```bash
# 1) 在 KDE 桌面里装依赖（Arch Linux）
sudo pacman -S python-gobject at-spi2-core qt6-tools kconfig spectacle
yay -S kdotool            # AUR，Wayland 下需要它来枚举/控制窗口

# 2) 安装 Python 客户端
sudo mkdir -p /opt/dsh
sudo cp -r dsh-plugin-kde-uia/python /opt/dsh/kde-uia
sudo chown -R "$USER" /opt/dsh/kde-uia
PYTHONPATH=/opt/dsh/kde-uia python3 -m kde_uia doctor

# 3) 把插件装进 DSH
dsh plugin --profile desktop add file:<本仓库的绝对路径>/dsh-plugin-kde-uia
```

装好后 agent 就能调用 `kde_uia_windows`、`kde_uia_tree`、`kde_uia_click` 等工具。

## 状态（v0.1.1，首次真机验证之后）

**已经在真实的 KDE Plasma 6.8.2 + Wayland 桌面上跑过。** 完整环境、原始输出和未通过项见
**[FIELD-TEST.md](FIELD-TEST.md)**。

| 能力 | 真机结果 |
|---|---|
| `kde_uia_doctor` 六项检查 | ✅ 全部通过 |
| 窗口列表 / 元素树 / `find` / `info` | ✅ 通过 |
| 按无障碍动作语义点击 | ✅ 通过（回读状态确认切换） |
| 截图（spectacle） | ✅ 通过 |
| 窗口激活 / 最小化 / 关闭 / 缩放 | ✅ 通过（kdotool，仅 XWayland 窗口） |
| **键盘输入（`kde_uia_keys` / `kde_uia_type`）** | ❌ **不可用**：接口返回成功，但事件未送达应用 |

### 为什么 0.1.0 开箱用不了

0.1.0 的客户端在真机上有 **10 处缺陷**（PyGObject 接口名不符、Plasma 6 的 KWin 脚本桥不可用、
窗口内搜索逻辑错误、引用冲突等），其中任何一处都足以让读树或点击失败。
0.1.1 把它们集中修在 `kde-uia/src/kde_uia/compat.py`，随包自动生效，逐条说明见
[CHANGELOG](dsh-plugin-kde-uia/CHANGELOG.md#011--2026-10-31)。

### 键盘输入的已知限制（未解决）

在「原生 Wayland + 无系统级输入权限」的机器上，本插件自带的所有输入路径都不可用：

- XTest（`xdotool`）在原生 Wayland 下是空操作；
- `kdotool` 0.3.0 **没有** `key`/`click`/`type` 子命令；
- KWin 6.8.2 不执行脚本（`loadScript` 返回 id、`isScriptLoaded` 为 true，脚本从不运行）；
- `Atspi.generate_keyboard_event()` 返回成功，但本机 KWin 丢弃了事件。

可用的替代方案都需要机器主人点头：**`ydotool`**（AUR，`/dev/uinput`，需要 `input` 组并常驻
`ydotoold`），或 **XDG 远程桌面门户**（`RemoteDesktop`，需要你在弹窗里授权）。
在此之前，建议用 `kde_uia_click`（语义动作）和 `kde_uia_set_value` 完成不依赖键盘的操作。

## 许可

MIT
