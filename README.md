# DSH plugins for KDE

给 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 用的 **KDE 桌面自动化插件**：
让 agent 像用 Windows UI Automation 一样，通过无障碍接口（AT-SPI2）读取窗口控件树、按名称点击与输入。

| 内容 | 说明 |
|---|---|
| **[dsh-plugin-kde-uia/](dsh-plugin-kde-uia/README.zh.md)** | 插件本体（中文说明 · [English](dsh-plugin-kde-uia/README.md)） |
| [kde-uia/](kde-uia/README.md) | 底层 Python 客户端库 + 命令行工具 |
| [WORKFLOW.md](WORKFLOW.md) | 开发记录：这一版是怎么一步步做出来的 |
| [dsh-plugin-kde-uia/MAINTENANCE.md](dsh-plugin-kde-uia/MAINTENANCE.md) | 维护说明：能承诺什么、接手方式、发布流程 |

## 快速开始

```bash
# 1) 在 KDE 桌面里装依赖（Arch Linux）
sudo pacman -S python-gobject at-spi2-core qt6-tools kconfig xdotool wmctrl spectacle

# 2) 安装 Python 客户端
sudo mkdir -p /opt/dsh
sudo cp -r dsh-plugin-kde-uia/python /opt/dsh/kde-uia
sudo chown -R "$USER" /opt/dsh/kde-uia
PYTHONPATH=/opt/dsh/kde-uia python3 -m kde_uia doctor

# 3) 把插件装进 DSH
dsh plugin --profile desktop add file:<本仓库的绝对路径>/dsh-plugin-kde-uia
```

装好后 agent 就能调用 `kde_uia_windows`、`kde_uia_tree`、`kde_uia_click` 等工具。

## 状态

这是一个学生利用课余时间做的小项目，**尚未在真实的 KDE 桌面上验证过**。
使用前建议先看 [CHANGELOG 的验证状态表](dsh-plugin-kde-uia/CHANGELOG.md#verification-status)，
以及 [使用前的小提示](dsh-plugin-kde-uia/README.zh.md#使用前的小提示)。

## 许可

MIT
