# dsh-plugin-kde-uia

**让 DeepSeek Harness 的 agent 像用 Windows UI Automation（UIA）一样操控 Linux KDE 桌面。**

> 🐟 这是一个学生利用课余时间做的小项目，目前还没能在真正的 KDE 桌面上测试过。
> 如果你决定试试看，可以先了解一下它目前的成熟度，再按自己的情况判断是否合适。
> 详见 [使用前的小提示](#使用前的小提示)。

[English](README.md) | 中文 · [安全声明](SECURITY.md) · [维护说明](MAINTENANCE.md) · [更新日志](CHANGELOG.md) · [工具清单](docs/tools.md) · [架构](docs/architecture.md) · [协议](docs/protocol.md) · [Arch Linux 指南](docs/arch-linux.md)

---

## 关于作者

- 作者是一名学生，平时上课、写作业，能用电脑的时间不太多，所以更新节奏会比较慢，
  如果暂时没有回应，多半只是没空，还请见谅。
- 这个插件的代码是和一个 DeepSeek Harness（DSH）的 agent 一起写出来的。作者本人对 AT-SPI、
  KWin 脚本这些细节也还在慢慢学习，所以如果哪里写得不够好，很欢迎有经验的朋友帮忙指正。
- 作者会看 Issues，有空的时候也会尽量回复；不过回复和更新的速度实在不太好保证。
  想快速上手的话，下面的「故障排查」加上 `kde_uia_doctor` 的输出，已经覆盖了大部分常见情况。
- 如果这个插件对你有用，作者会很高兴。也欢迎提 PR，或者分享一下你的使用环境。

> 一句话：**代码是和 AI 一起写出来的，维护是一个学生挤课余时间在做，谢谢理解 m(_ _)m**

### 使用前的小提示

- 这个插件是用**学校的电脑**做的，最初也是给自己后面在自己的电脑（**Nyarch Linux + KDE**）上用；
  顺手放到 GitHub 上，更多是留个存档，也许能帮到有类似需求的人。
- 它到现在还没有在真正的 KDE 桌面上跑通过，所以遇到一些小问题是很可能的；
  在很极端的情况下，它对界面的操作也可能碰到你并不想改动的部分。
  使用之前，建议先读一下 [SECURITY.md](SECURITY.md) 和下面的「目前的状态」，再按自己的判断决定。
- 如果它现在的成熟度还不适合你，或者你对可能存在的风险不太放心，
  **先不用、或者观望一段时间，都是完全可以理解的选择**，作者也会尊重你的决定。
- Fork 和二次修改都很欢迎（MIT 协议本身也允许）；只是不太建议直接用在生产环境或主力机上，
  如果条件允许，先在虚拟机或专门的用户会话里试会更稳妥一些。
- 万一真出了问题，作者恐怕既没有能力、也负不起相应的责任（LICENSE 里写的也是这个意思）。
  所以使用前请记得备份重要数据。

> 一句话：**这是一个学生用学校电脑给自己做的小工具，用不用、怎么用，还是请你按自己的情况来判断。**

### 目前的状态：还没在真正的 KDE 上跑过

这个版本目前还没有在真实的 KDE Plasma 桌面上运行验证过。开发和测试都在一台 Windows 主机上完成，
Linux 侧只有一个没有装 KDE 和 PyGObject 的 WSL 服务器。所以：

- 已经验证的：工具声明能用 DSH 自己的 `defineTool` 编译、JSON Schema 校验、真实 DSH 模块加载、
  WSL 传输全链路，以及带引号、中文、`$(…)` 的参数往返。
- **还没验证的**：AT-SPI 元素树与点击、KWin 脚本桥接、Wayland 下的输入、截图后端。
  这部分是按文档和代码逻辑推演出来的，还没有实际跑通过。

完整对照表见 [CHANGELOG › Verification status](CHANGELOG.md#verification-status)。
如果你第一次跑通了，愿意在 issue 里留一句结果的话，会非常有帮助。

---

## 功能边界

这个插件的目标很单一：**让 agent 用"可访问名称 + 元素树"操作 KDE 应用，而不是靠猜坐标和 OCR 截图。**
它把 Windows UIA 的概念映射到 Linux 的 AT-SPI2 无障碍总线：

| Windows UIA 概念 | 本插件 / 客户端 |
|---|---|
| `AutomationElement.RootElement` + `TreeWalker` | `kde_uia_windows`、`kde_uia_tree` |
| `FindFirst` / `FindAll` + 条件 | `kde_uia_find`（role / name / text / states / attributes） |
| `RuntimeId` | `uia:1:<应用名>:<子节点索引路径>` 引用 |
| `InvokePattern` / `TogglePattern` | `kde_uia_click`（优先执行无障碍 action） |
| `ValuePattern` | `kde_uia_set_value`、`kde_uia_type` |
| `WindowPattern` | `kde_uia_activate`（激活/关闭/最小化/最大化/移动/缩放） |
| 合成键盘与鼠标 | `kde_uia_keys`、`kde_uia_type`、`kde_uia_click`、`kde_uia_scroll` |
| 屏幕捕获 | `kde_uia_screenshot` |

底层分别使用：**AT-SPI2** 读取元素树并执行语义动作；**KWin 脚本**在 Wayland 与 X11 上管理窗口；
**xdotool / kdotool** 完成指针与键盘输入。插件本身只做三件事：把工具声明交给 DSH 的工具注册表、
把一次调用变成一次安全的跨环境命令、把 JSON 结果翻译成给模型看的文本。

### 明确不做的事

- 不做 OCR、不做视觉识别（截图是给你/模型查看的，不参与定位）。
- 不读取 `/dev/fb0` 或任何需要提升权限的 DRM 后端（文档里有，默认不执行）。
- 不修改系统设置、不安装软件、不使用 `sudo`、不联网。
- 不提供 AT-SPI 事件流式的"监听"接口（等待通过轮询 `kde_uia_wait_for` 完成）。

## 环境要求

**主要面向 Arch Linux + KDE Plasma 6**（Wayland 或 X11）开发与验证。其它发行版也能用，
只是包名不同，见下面表格。

| 位置 | 要求 |
|---|---|
| DSH 宿主机 | 任意系统：同一台 Linux 桌面上就是 `runtime: local`；Windows 上通过 **WSL** 或 **SSH** 到达桌面 |
| Linux 桌面 | KDE Plasma 5.x / 6.x（Wayland 或 X11），用户已登录图形会话 |
| Python | 3.9+，需要 **PyGObject** 与 **libatspi typelib**（必须用发行版包，不能用 pip 安装） |
| 无障碍 | 会话内已启用（`org.a11y.Status.IsEnabled = true`） |
| 窗口控制 | `qdbus6` + `kwriteconfig6`（KWin 脚本），或 `xdotool` + `wmctrl`（X11） |
| 输入（可选） | `xdotool`（X11）、`kdotool`（Wayland） |
| 截图（可选） | `spectacle`（Plasma）、`grim` / `import` |

Arch Linux（一行装好，包名已核对）：

```bash
sudo pacman -S python-gobject at-spi2-core qt6-tools kconfig xdotool wmctrl spectacle
# Wayland 下的原始输入注入（kdotool 只在 AUR，官方源里没有）：
yay -S kdotool
```

`kconfig` 是最容易漏的一个：少了它，KWin 脚本拿不到命令，插件会退化到较弱的 X11/AT-SPI 后端。
完整步骤与验证清单见 [docs/arch-linux.md](docs/arch-linux.md)。

Debian / Ubuntu / KDE neon：

```bash
sudo apt install python3-gi gir1.2-atspi-2.0 at-spi2-core qdbus-qt6 kconfig-cli xdotool wmctrl spectacle
```

Fedora：`sudo dnf install python3-gobject at-spi2-core qt6-qttools kf6-kconfig xdotool wmctrl spectacle`

## 安装

### 1. 在 Linux 环境里安装 Python 客户端

插件自带客户端副本（`python/` 目录），一次 `cp` 即可。`/opt/dsh/kde-uia` 是插件默认优先探测的位置：

```bash
# 在 KDE 桌面 / WSL 发行版里执行
sudo mkdir -p /opt/dsh
sudo cp -r <插件目录>/python /opt/dsh/kde-uia
sudo chown -R "$USER" /opt/dsh/kde-uia

PYTHONPATH=/opt/dsh/kde-uia python3 -m kde_uia doctor
```

`doctor` 会逐项列出显示、AT-SPI、窗口后端、输入、截图能力，并对每个失败项给出具体修复命令；
它不启动任何东西。

Windows 宿主机上通过 WSL 做同样的检查：

```powershell
wsl -e bash -lc "PYTHONPATH=/opt/dsh/kde-uia python3 -m kde_uia doctor"
```

### 2. 把插件装进 DSH profile

以下任一方式均可，不会改动其他配置：

```bash
# a) 本地目录
dsh plugin --profile desktop add file:<绝对路径>/dsh-plugin-kde-uia

# b) 在插件目录里
cd dsh-plugin-kde-uia && dsh plugin --profile desktop add .

# c) 压缩包
dsh plugin --profile desktop add ./dsh-plugin-kde-uia-0.1.0.tgz
```

插件的 `package.json` 声明了 `"dsh": { "bundle": { "patch": "./cordis.patch.yml" } }`，
DSH 的插件管理器据此知道它如何向 profile 贡献配置行（`cordis.patch.yml` 中的 `- insert:` 条目）。

### 3. 选择运行时（只有 SSH 或自定义路径时才需要）

默认 `runtime: auto` 对 **Windows + WSL** 与 **Linux 宿主机**开箱即用。需要覆盖时，编辑 profile
的 `cordis.patch.yml`（`$DSH_HOME/profiles/desktop/cordis.patch.yml`）：

```yaml
# 通过 Windows 自带 OpenSSH 连接另一台机器上的 KDE 桌面：
- id: tool-kde-uia
  config:
    runtime: ssh
    sshHost: user@kde-box
    remotePath: /opt/dsh/kde-uia          # 第 1 步拷贝到的位置
    # sshIdentity: C:\Users\me\.ssh\id_ed25519

# 或指定某个带图形会话的 WSL 发行版：
- id: tool-kde-uia
  config:
    runtime: wsl
    wslDistribution: Ubuntu-24.04
    remotePath: /opt/dsh/kde-uia

# 只读部署：完全不注册点击/输入/按键/滚动/激活类工具：
- id: tool-kde-uia
  config:
    readOnly: true
```

| 配置项 | 默认值 | 含义 |
|---|---|---|
| `runtime` | `auto` | `auto` \| `wsl` \| `ssh` \| `local` |
| `wslDistribution` | `''` | WSL 发行版，留空用默认 |
| `remotePath` | `''` | Linux 内客户端目录；留空则依次探测 `/opt/dsh/kde-uia` 与检出目录 |
| `remotePython` | `python3` | Linux 内的解释器（必须带 PyGObject；绝不使用 Windows 的 Python） |
| `wslCommand` | `''` | 显式指定 `wsl.exe` 路径 |
| `sshHost` | `''` | `runtime: ssh` 时的 `user@host` |
| `sshIdentity` | `''` | 私钥（Windows 路径会被自动转换） |
| `sshOptions` | `[]` | 额外的 `ssh -o` 选项 |
| `timeoutMs` | `120000` | 单次调用超时预算 |
| `readOnly` | `false` | 只注册只读工具 |
| `doctorOnLoad` | `true` | 插件挂载时做一次离线自检并记录结果 |
| `executable` | `''` | 高级：用该命令启动 `kde_uia` 客户端，而不是内置 Python 路径 |

未知配置键会被忽略（新 README 可以先行描述旧版本尚未实现的键）；类型错误的取值会在加载时失败并指名该键。

改完 profile 后 DSH 会自动重载（HMR）或需要重启。之后让 agent 调用 `kde_uia_doctor` 就能看到到底哪一项可用。

## 使用：agent 的工作循环

```
kde_uia_windows                                    -> { "Dolphin" [dolphin] id 0x03a00007 active? }
kde_uia_tree   { "window": "Dolphin" }             -> tool bar 'mainToolBar'
                                                      push button 'New Tab' actions=click uia:1:dolphin:0/1/0
                                                      entry 'Path' value="/home/me"        uia:1:dolphin:0/3
kde_uia_find   { "text": "New Tab", "actionable": "button", "window": "Dolphin" }
kde_uia_click  { "ref": "uia:1:dolphin:0/1/0" }
kde_uia_keys   { "key": "ctrl+l" }
kde_uia_type   { "text": "trash:///", "submit": true }
kde_uia_wait_for { "selector": { "text": "Trash", "window": "Dolphin" }, "timeout_s": 5 }
kde_uia_screenshot { "window": "Dolphin", "output": "/tmp/dolphin.png" }
```

`kde_uia_tree` 是"地图"，`kde_uia_click`/`kde_uia_activate` 用 ref 定位。ref 是**路径**，窗口内容变化后
需要重新 `tree`/`find`；插件会明确返回 `INVALID_REF` 并提示重取，而不是静默点错。

不依赖 DSH 也能直接用客户端（脚本、CI、其他 harness）：

```bash
export PYTHONPATH=/opt/dsh/kde-uia
kde-uia windows
kde-uia tree --window Dolphin --depth 5
kde-uia click --text "Save" --role push-button
kde-uia screenshot --window Dolphin -o /tmp/dolphin.png
```

插件同时自带一个运维 CLI，它与工具使用完全相同的传输路径（适合在 DSH 宿主机上、尚未加载插件时排查部署）：

```bash
node dsh-plugin-kde-uia/lib/cli.js doctor --runtime wsl --remote-path /opt/dsh/kde-uia
node dsh-plugin-kde-uia/lib/cli.js windows
node dsh-plugin-kde-uia/lib/cli.js call kde_uia_find --json '{"text":"Save","window":"Dolphin"}'
```

全部工具与 CLI 命令见 [docs/tools.md](docs/tools.md)，插件与客户端之间的 JSON 协议见
[docs/protocol.md](docs/protocol.md)。

## DSH 版本兼容性

| 插件版本 | DSH 运行时 | 状态 |
|---|---|---|
| 0.1.0 | `@deepseek-ai/dsh` **0.2.0-rc.2**（Desktop 44 / `primary-runtime` `0.2.0-rc.2`） | 针对该版本开发与测试 |
| — | 其他 `0.2.0-rc.*` | 预期可用，未逐版本验证 |
| — | 其他版本 | 不支持；DSH 会拒绝加载不兼容的 peer |

`package.json` 中对 DSH 的 peer 依赖刻意写成**精确版本**（`"0.2.0-rc.2"`）：插件建立在 DSH 的
文档化扩展点（`ctx.tools.register`、`defineTool`、`dsh.bundle.patch`、`ctx.shell`）之上，而 DSH 仍处于
pre-stable 阶段，给一个范围等于给出无法用发布说明兑现的承诺。DSH 升级后：

1. 先尝试启用——DSH 会在导入前报告不兼容的 peer；
2. 若能加载且 `node --test "tests/**/*.test.js"` 全部通过（测试会用你本机安装的 DSH 中**真实的**
   `defineTool` 编译每个工具 schema），基本说明可以跟随升级；
3. 否则把插件回退到 `dsh-plugin-kde-uia@0.1.0`。

所有与兼容性相关的变更都会写入 [CHANGELOG.md](CHANGELOG.md) 的 **Compatibility** 小节。

## 安全声明

完整威胁模型见 [SECURITY.md](SECURITY.md)，要点：

- **能力范围**：能向传输所到达的 KDE 会话发送点击、键入与按键，等于该桌面用户能在 GUI 里做的一切。
  请把它当作"远程遥控工具"，而不是只读观察器。
- **不提权**：从不使用 `sudo`、不以 root 运行。以桌面用户身份访问会话总线与无障碍总线。
- **不拼接任意 shell**：工具参数经 JSON（base64）传给固定命令；插件只会提交由自己逐项引用转义的
  argv 组成的固定 `bash -lc` 包装，绝不把调用方拼出的 shell 字符串交给 bash。
- **不联网**：没有遥测、没有外部端点、不上传任何数据；唯一的网络流量是你自己配置的 `ssh`/`wsl` 传输。
- **只读开关**：`readOnly: true` 会把所有会改变桌面状态的工具从 agent 的工具集中移除。
- **落盘位置**：`/opt/dsh/kde-uia/.runtime/`（每次调用的参数/结果文件，调用结束即删除）、
  `/tmp/kde-uia/`（KWin 脚本桥接）、`~/.local/share/kwin/scripts/kde-uia-window-probe.js`
  （KWin 探测脚本）、以及你用 `kde_uia_screenshot` 指定保存的 PNG。

## 已知限制

- **AT-SPI 覆盖取决于工具包**：Qt/KDE 应用树完整；未启用无障碍的应用（部分 Electron/Java/xterm、
  关掉了 `GTK_MODULES` 的 GTK 应用）可能只暴露一个节点；个别输入框没有 editable-text 接口，会退回
  合成按键输入。
- **ref 是路径不是哈希**：控件增删会让之前取到的 ref 失效，报错会明确提示重新获取；长流程建议用
  `text`/`role` 匹配。
- **Wayland 输入**：`xdotool` 只能看到 XWayland 窗口。Wayland 下请安装 `kdotool`（KWin 脚本）或使用
  `atspi` 策略；`kde_uia_doctor` 会报告当前可用项。
- **截图**：`kwin`（阴影缓冲）与 `spectacle` 可直接截取窗口且无弹窗；XDG portal 每次都会弹出系统授权
  对话框，因此只有显式指定时才会使用。
- **不做 `/dev/fb0` 回退**：直接读帧缓冲需要设备权限，文档中列出但不会自动执行。
- **Windows 主机路径**：从 Windows 走 SSH 时必须显式设置 `remotePath`（插件无法猜测检出目录在远端的位置）；
  WSL 路径会自动转换（`C:\x` → `/mnt/c/x`）。
- **一个 profile 一个桌面**：运行时只指向单一会话/发行版/主机。
- **暂无事件流**：等待通过轮询完成；AT-SPI 事件流只在客户端内部用于名称/角色缓存。

## 故障排查

| 现象 | 处理 |
|---|---|
| `kde_uia_doctor` 报 *client not reachable* | 完成第 1 步：把 `python/` 拷到 WSL/SSH 的 `/opt/dsh/kde-uia` |
| `ATSPI_UNAVAILABLE` | `sudo apt install python3-gi gir1.2-atspi-2.0 at-spi2-core`，并以桌面用户身份运行 |
| `ACCESSIBILITY_DISABLED` | 在 KDE 系统设置 → 辅助功能中启用无障碍，然后重启目标应用 |
| 有窗口但看不到控件 | 应用没有暴露元素树，先用 `kde_uia_tree --depth 1` 确认 |
| *No window backend* | `sudo apt install qdbus6`（KWin 脚本）或 `xdotool wmctrl`（X11） |
| Wayland 下点击无效 | 安装 `kdotool`，或给 `kde_uia_click` 传 `"strategy": "atspi"` |
| 所有截图都失败 | `sudo apt install spectacle`（Plasma）或 `grim` |
| DSH 拒绝加载插件 | DSH 版本不匹配，见 [DSH 版本兼容性](#dsh-版本兼容性) |

## 开发

```bash
# Node 侧（工具声明、运行时、插件、文档）——不需要安装 DSH：
cd dsh-plugin-kde-uia
node --test "tests/**/*.test.js"        # 45 个测试；若本机存在 DSH，会用其真实 defineTool 编译全部工具
node scripts/smoke-dsh-load.mjs C:\HARNESS\resources\app.asar
                                         # 真机校验：cordis 形状、defineTool、JSON Schema 与参数校验
KDE_UIA_SMOKE_WSL=1 node --test tests/integration.test.js
                                         # 真实 wsl.exe → Python 客户端传输检查

# Python 侧（库 + CLI）：
cd ../kde-uia && PYTHONPATH=src python3 -m unittest discover -s tests   # 46 个测试
bash scripts/dev-smoke.sh

# 一次跑完（在 WSL 中执行，Windows 方法见脚本头部说明）：
bash dsh-plugin-kde-uia/scripts/run-all-tests.sh

# 提交前保持内置客户端同步：
bash scripts/sync-python.sh && bash scripts/sync-python.sh --check
```

Python 客户端的权威源码在 [`kde-uia/`](kde-uia)（也可单独 `pip install ./kde-uia`）；
`dsh-plugin-kde-uia/python/` 是逐字节一致的副本，保证插件可以一次 `cp` 安装。

### 类型模板（给未来的接手者）

`types/index.ts` 是用 TypeScript 写成的**插件形状模板**：它声明了 `name` / `inject` /
`Config` / `apply` 的签名，以及本插件用到的 Cordis 扩展点（`ctx.tools.register`、`ctx.shell`）。
它不参与运行，只为让下一位接手者（可能是人，也可能是 AI）不必靠猜。批量检查用：

```bash
npm run check:ts     # 需要先 npm install（typescript + @types/node）
```

## 发布到 GitHub

仓库根目录是 `Github-Upload/`（里面放着 `kde-uia/`、`dsh-plugin-kde-uia/` 和同步脚本）。
上传步骤、注意事项与一键脚本见 [README.md](README.md) 的「Development」与
[MAINTENANCE.md](MAINTENANCE.md)；作者不是专业的，上传过程也会写得很傻瓜。

## 许可证

MIT，见 [LICENSE](LICENSE)。
