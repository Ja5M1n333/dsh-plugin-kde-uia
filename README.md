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

> ## ⚠️ 这个插件很吃 token，用之前先看这里
>
> 实测教训：测试期间余额从 **¥5.97 掉到 ¥0**。不是插件有 bug，是**用法太奢侈**。
>
> **从便宜到贵的调用顺序：** `windows` → `find` → `info` → `tree --depth 4` → `tree-text`
>
> - `tree-text` **必须**带 `--window`/`--app`/`--ref`，否则会读整个桌面（最贵）
> - 能用 `find` + `info` 就不必用 `tree`；能 `tree --depth 4` 就不必用 `tree-text`
> - **不要为了"确认"反复读同一棵树**；也不要拿截图代替读结构
>
> 详见 [FIELD-TEST.md](FIELD-TEST.md) 与 [HANDOFF-GUIDE.md](HANDOFF-GUIDE.md)。

## 状态（v0.1.3，三轮真机验证之后）

**已经在真实的 KDE Plasma 6.8.2 + Wayland 桌面上跑过。** 完整环境、原始输出和未通过项见
**[FIELD-TEST.md](FIELD-TEST.md)**。

| 能力 | 真机结果 |
|---|---|
| `kde_uia_doctor` 六项检查 | ✅ 全部通过 |
| 窗口列表 / 元素树 / `find` / `info` | ✅ 通过 |
| 按无障碍动作语义点击 | ✅ 通过（回读状态确认切换） |
| 窗口激活 / 最小化 / 关闭 / 缩放 | ✅ 通过（0.1.2 修掉了 `window-op` 报错） |
| 截图（spectacle） | ✅ 通过 |
| **键盘输入（`kde_uia_keys` / `kde_uia_type`）** | ✅ 通过，**前提是装了 `ydotool`**（见下） |
| 网页正文文字 | ✅ 通过 `tree-text` / `tree --include_text` 读取（0.1.3 新增） |
| 终端内容 | ⚠️ 部分：Konsole 报告 7181 字符，实际只提供约 2591 字符 |

### 怎么用它读一个窗口（不用截图）

```
kde_uia_windows                                  # 先看有哪些窗口
kde_uia_find    { "window": "Firefox", "text": "余额" }   # 缩小范围
kde_uia_tree_text { "window": "Firefox" }        # 读整页文字（0.1.3）
kde_uia_tree    { "window": "Firefox", "include_text": true }  # 带文本的树
```

**关键**：不要只读 `document web`，它只有占位符；正文在下级 `section` 节点，
用 `tree-text` 一次读完。

### 这个插件的用途，以及它目前能做到哪一步

设计目标很明确：**让 agent 不靠截图、不看 OCR，直接"读"界面结构再按语义操作。** 实测边界：

- ✅ **结构级读取完全可用**：窗口、工具栏、按钮、菜单、标签页（连"42封未读"都在）、对话框、
  页面骨架（`article` / `heading` / `paragraph` / `list`）都是结构化文本。
- ✅ **内容级读取（0.1.3 起）**：网页正文通过 `tree-text` 可以读出来。实测用它读
  `platform.deepseek.com/usage`，一次调用得到 57 行文字，含 `充值余额 ¥5.97`、
  `API 请求次数 3,920`、`Tokens 546,407,414`。
- ⚠️ 终端尾部仍有限：Konsole 报告 7181 字符但只提供约 2591。

### 四个版本各自修了什么

| 版本 | 修掉的问题 | 怎么发现的 |
|---|---|---|
| **0.1.0** | —（从未在真机跑过，**不要使用**） | 按文档编写 |
| **0.1.1** | 插件从未激活：`Config` 是普通 JSON Schema（加载器要 `~standard.validate`）、`apply()` 返回对象（cordis 当作 setup promise）；另有客户端 10 处缺陷（PyGObject 接口名、KWin 脚本桥不可用、窗口内搜索失效、引用冲突……） | 第一次真机运行 |
| **0.1.2** | `kde_uia_activate` 恒报 `unknown op 'window-op'`；所有文本读取返回空串；新增 `ydotool` 输入后端 | 第一次由 agent 直接驱动工具 |
| **0.1.3** | 新增 `tree-text` / `kde_uia_tree_text` / `tree --include_text`，网页正文终于能读 | 真实任务：读余额 |

### 为什么 0.1.0 开箱用不了

0.1.0 的客户端在真机上有 **10 处缺陷**（PyGObject 接口名不符、Plasma 6 的 KWin 脚本桥不可用、
窗口内搜索逻辑错误、引用冲突等），其中任何一处都足以让读树或点击失败。
0.1.1 把它们集中修在 `kde-uia/src/kde_uia/compat.py`，随包自动生效，逐条说明见
[CHANGELOG](dsh-plugin-kde-uia/CHANGELOG.md#011--2026-10-31)。

0.1.2 又修了两处（`kde_uia_activate` 的 `window-op` 报错、所有文本读取返回空字符串），
并新增 `ydotool` 输入后端：见 [CHANGELOG 0.1.2](dsh-plugin-kde-uia/CHANGELOG.md#012--2026-10-31)。

0.1.3 新增 `tree-text` 操作与 `tree --include_text`：**网页正文现在能读了**，
见 [CHANGELOG 0.1.3](dsh-plugin-kde-uia/CHANGELOG.md#013--2026-10-31)。

### 键盘输入：需要 `ydotool`

原生 Wayland 下 XTest 无效、kdotool 没有输入命令、KWin 不执行脚本、AT-SPI 合成事件被丢弃——
所以插件把 `ydotool` 作为首选输入后端（检测到 `ydotoold` 时才启用，没装则保持原行为）：

```bash
yay -S ydotool                                   # AUR
# 让当前用户能写 /dev/uinput（ACL 或加入 input 组）
ydotoold --socket-path=$XDG_RUNTIME_DIR/.ydotool_socket --socket-perm=0600
```

实测：`echo lag-test-one` 逐字送达并执行成功。未装 `ydotool` 的机器上，键盘输入仍然不可用。

## 余额

> 💸 **请不要用这个插件烧余额。**
>
> 本插件每次调用都会把元素树/窗口列表写进上下文，**非常吃 token**。
> 实测期间作者的余额一路掉到了个位数（¥8 以下），一次多窗口遍历就能吃掉好几毛。
>
> - 能读结构就别读整棵树：先用 `kde_uia_find` 缩小范围，再 `kde_uia_info`
> - 不要对着同一个窗口反复 `tree`
> - 不要用截图来代替读取——那是最贵的做法
>
> 钱是作者自己的，请替作者心疼一下。（这条也算写给自己看的。）

## 许可

MIT
