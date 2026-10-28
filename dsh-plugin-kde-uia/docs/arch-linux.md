# Arch Linux 专属安装与验证

本项目**主要面向 Arch Linux + KDE Plasma 6** 开发和验证。下面的命令都按 Arch 写；其它发行版的对应包名见文末。

## 1. 装依赖（一行）

```bash
sudo pacman -S python-gobject at-spi2-core qt6-tools kconfig xdotool wmctrl spectacle
```

每个包负责什么：

| 包 | 提供 | 为什么需要 |
|---|---|---|
| `python-gobject` | `python3 -c "import gi"` | 访问 AT-SPI 的 Python 绑定 |
| `at-spi2-core` | `Atspi-2.0.typelib`、`libatspi.so`、无障碍总线 | 元素树与语义动作的来源 |
| `qt6-tools` | `/usr/bin/qdbus6` | 调用 KWin 的 D-Bus 接口 |
| `kconfig` | `/usr/bin/kwriteconfig6`、`/usr/bin/kreadconfig6` | 把命令交给 KWin 脚本（**最容易漏**） |
| `xdotool` | 鼠标/键盘注入（X11 与 XWayland） | 坐标点击、打字 |
| `wmctrl` | 窗口枚举（X11 后端） | `--backend x11` 时 |
| `spectacle` | 截图 | `--strategy spectacle` |

可选：

```bash
# Wayland 下的原始输入注入（不在官方源，AUR 才有）
yay -S kdotool
# 或者预编译版
yay -S kdotool-bin
```

> ⚠️ `kdotool` **只在 AUR**。没有 AUR 助手的话，也可以 `cargo install kdotool`。

## 2. 无障碍开关

```bash
# 建议设为全局启用，否则部分 Qt 应用不暴露控件树
gsettings set org.gnome.desktop.interface toolkit-accessibility true
# 或者：系统设置 → 辅助功能 → 启用
```

## 3. 装客户端并自检

```bash
sudo mkdir -p /opt/dsh
sudo cp -r dsh-plugin-kde-uia/python /opt/dsh/kde-uia
sudo chown -R "$USER" /opt/dsh/kde-uia

PYTHONPATH=/opt/dsh/kde-uia python3 -m kde_uia doctor
```

`doctor` 每项都会给出**Arch 的包名**，照着装即可。全绿之后再装 DSH 插件。

## 4. 装 DSH 插件

```bash
dsh plugin --profile desktop add file:/绝对路径/dsh-plugin-kde-uia
```

在 Arch 上这是 `runtime: local`（DSH 和桌面在同一台机器），不需要 WSL 或 SSH。

## 5. 最小验证流程

```bash
export PYTHONPATH=/opt/dsh/kde-uia

kde-uia windows                        # 应能看到 Dolphin / Konsole 等
kde-uia tree --window Konsole --depth 4 # 控件树，带 uia: 引用
kde-uia click --text "新建标签页" --role push-button
kde-uia press ctrl+shift+t
kde-uia screenshot --window Konsole -o /tmp/konsole.png
```

如果 `windows` 空、`tree` 只有一层：先跑 `kde-uia doctor`，再看
[故障排查](README.zh.md#故障排查)。

## 6. 本仓库已知未验证项（诚实说明）

- **没有在真实 Arch + Plasma 上跑过完整流程。** 测试是在 Ubuntu 24.04 的 WSL（无 KDE、无 PyGObject）
  和一台 Windows 主机上完成的：验证了传输、JSON 协议、工具注册、真实 DSH 模块加载、错误路径。
- **KWin 脚本桥接**（`/Scripting` + `kconfig`）只做了逻辑与失败路径验证，没有在真实 KWin 上跑过。
- **Wayland 下的坐标点击**依赖 `kdotool`，同样未在真机验证。

第一次在你自己的 Arch 上跑通后，请在 issue 里留一句结论，能帮后面的人省很多时间。

## 其它发行版对照

| 需要 | Arch | Debian/Ubuntu | Fedora |
|---|---|---|---|
| PyGObject | `python-gobject` | `python3-gi` | `python3-gobject` |
| AT-SPI typelib | 含在 `at-spi2-core` | `gir1.2-atspi-2.0` | 含在 `at-spi2-core` |
| `qdbus6` | `qt6-tools` | `qdbus-qt6` | `qt6-qttools` |
| `kwriteconfig6` | `kconfig` | `kconfig-cli` | `kf6-kconfig` |
| 截图 | `spectacle` | `spectacle` | `spectacle` |
