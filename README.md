# DSH plugins for KDE

这里放的是给 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 用的 KDE 桌面自动化插件。

| 内容 | 说明 |
|---|---|
| [dsh-plugin-kde-uia/](dsh-plugin-kde-uia/README.zh.md) | 插件本体：让 agent 像用 Windows UI Automation 一样操作 KDE 桌面（中文说明） |
| [dsh-plugin-kde-uia/README.md](dsh-plugin-kde-uia/README.md) | English documentation |
| [kde-uia/](kde-uia/README.md) | 底层 Python 客户端库 + CLI |

> 目前是学生自用项目，**尚未在真实 KDE 桌面上验证过**，详见 [维护说明](dsh-plugin-kde-uia/MAINTENANCE.md)。

## 快速开始

```bash
dsh plugin --profile desktop add file:/绝对路径/dsh-plugin-kde-uia
