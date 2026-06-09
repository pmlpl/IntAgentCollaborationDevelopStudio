# Agent CLI 安装指南（Windows）

Studio 编排的是 **终端里的 Agent CLI**（会弹 TUI 窗口），不是 Cursor 等 IDE。

检测本机已安装哪些：

```powershell
cd C:\Users\MOM\Desktop\IntAgentCollaborationDevelopStudio
python -m cli.studio agent list
python -m cli.studio agent status
```

在 Studio TUI 中点击 **「Agent 目录」**（快捷键 `A`）：**单击**查看说明，**双击**运行安装命令或打开 Agent TUI（API Key 在 Agent 窗口内自行配置）。

打开某个 Agent 的 TUI 测试：

```powershell
python -m cli.studio agent open opencode
python -m cli.studio agent open --all
python -m cli.studio agent open --position laowang --project 你的项目名
```

---

## BYOK 策略（只用第三方模型 / 无厂商订阅）

Studio 默认启用 **`agents.policy: byok_only`**（见 `config/platform.yaml`），只会调度标记为 **`byok: true`** 的 Agent：

| Agent | BYOK | 说明 |
|-------|------|------|
| **OpenCode** | ✅ | 75+ 提供商，DeepSeek / Ollama / OpenAI 兼容 |
| **Hermes** | ✅ | `config.yaml` 配置 provider |
| **Aider** | ✅ | `--model deepseek/...` 或 `ollama/...` |
| **Goose** | ✅ | 多 provider / 本地 |
| Claude Code | ❌ | 默认 Anthropic 订阅 |
| Codex | ❌ | ChatGPT Plus |
| Gemini CLI | ❌ | Google 账号 |

检测时会显示 **BYOK / 订阅** 与 **可用 / 禁用**：

```powershell
python -m cli.studio agent status
```

### 推荐岗位分配（已写入默认模板）

| 岗位 | Agent |
|------|-------|
| 技术主管 | opencode |
| 前端 / 移动 | opencode |
| 后端 / 小程序 | hermes |
| 测试审查 | aider |
| 桌面端 | goose |

### 第三方模型配置示例

**OpenCode**（首次运行按提示配置，或编辑用户配置中的 provider）：

```powershell
opencode
# 在 TUI 中选择 DeepSeek / OpenAI 兼容 / Ollama 等
```

**Hermes**（编辑 `%USERPROFILE%\.hermes\config.yaml` 或安装目录下的 provider 段）：

```yaml
# 示例：DeepSeek
providers:
  default: deepseek
```

**Aider**（环境变量或命令行）：

```powershell
$env:DEEPSEEK_API_KEY = "你的密钥"
aider --model deepseek/deepseek-chat
# 或本地 Ollama：aider --model ollama/deepseek-r1:8b
```

若将来恢复使用 Claude / Codex 等订阅 Agent，将 `config/platform.yaml` 中 `agents.policy` 改为 `all` 即可。

---

大多数用户无需改路径，按下方各 Agent 章节直接 `npm install -g` / `pip install` 即可：

| 类型 | 默认位置 |
|------|----------|
| npm 全局（claude / codex / opencode 等） | `%APPDATA%\npm` → `C:\Users\<你>\AppData\Roaming\npm` |
| Hermes（pip venv） | `%LOCALAPPDATA%\hermes\hermes-agent\venv` |

检测：`npm config get prefix` 应为 Roaming\npm；`where.exe claude` 应指向 C 盘。

---

## 可选：全部装到 D 盘（高级）

<details>
<summary>仅当 C 盘空间不足时再考虑（点击展开）</summary>

建议统一根目录，例如 `D:\Agents`：

```text
D:\Agents\
  npm-global\          ← npm 全局包装（claude / codex / gemini / opencode）
  python-venvs\
    studio-agents\     ← pip 虚拟环境（aider、hermes 等）
  bin\                 ← 手动解压的二进制（goose 等）
```

### 第一步：npm 全局改到 D 盘

**新开 PowerShell** 执行（只需做一次）：

```powershell
$npmGlobal = "D:\Agents\npm-global"
New-Item -ItemType Directory -Force -Path $npmGlobal | Out-Null

npm config set prefix $npmGlobal

# 写入用户 PATH（永久）
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$npmGlobal*") {
    [Environment]::SetEnvironmentVariable("Path", "$userPath;$npmGlobal", "User")
}

# 当前窗口立即生效
$env:Path = "$npmGlobal;" + $env:Path
```

之后所有 `npm install -g ...` 都会装到 `D:\Agents\npm-global`：

```powershell
npm install -g @anthropic-ai/claude-code @openai/codex @google/gemini-cli opencode-ai
```

验证：

```powershell
npm root -g          # 应显示 D:\Agents\npm-global\node_modules
Get-Command claude   # 应指向 D:\Agents\npm-global\claude.cmd
```

### 第二步：pip 类 Agent 用 D 盘虚拟环境

```powershell
$venv = "D:\Agents\python-venvs\studio-agents"
python -m venv $venv
& "$venv\Scripts\Activate.ps1"

pip install -U pip aider-chat hermes-agent

# 把 venv 的 Scripts 加入用户 PATH
$scripts = "$venv\Scripts"
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$scripts*") {
    [Environment]::SetEnvironmentVariable("Path", "$scripts;$userPath", "User")
}
$env:Path = "$scripts;" + $env:Path
```

验证：

```powershell
aider --version
hermes --version
```

> 以后要用 aider/hermes，可先 `& D:\Agents\python-venvs\studio-agents\Scripts\Activate.ps1`，或依赖上面已加入 PATH 的 `Scripts` 目录。

### 第三步：Goose 等 GitHub 二进制

从 [Goose Releases](https://github.com/aaif-goose/goose/releases) 下载 Windows 包，解压到 `D:\Agents\bin`，把该目录加入 PATH（方式同 npm-global）。

或用官方脚本指定目录（若脚本支持）后，把安装路径改到 `D:\Agents\bin`。

### 第四步：新开终端 + 检测

**必须新开 PowerShell**（或重启 Cursor 终端），再运行：

```powershell
python -m cli.studio agent status
```

应看到各 Agent 为 `[OK]`。

### 注意

| 项目 | 说明 |
|------|------|
| Node / Python 本体 | 仍可在 C 盘（nvm、官方安装器）；改的是 **包装命令和 venv** 的位置 |
| 已装在 C 盘的 | 见下方「从 C 盘迁移到 D 盘」 |
| Studio 检测 | 只检查命令是否在 **PATH** 里，不关心在 C 还是 D |

---

## 从 C 盘迁移到 D 盘（已装好的 Agent）

**不要直接剪切文件夹**（npm 包内路径、hermes 虚拟环境容易坏）。推荐：**C 盘卸载 → 改安装位置 → D 盘重装**。

你本机当前典型位置（供对照）：

| Agent | 现在在 C 盘的位置 |
|-------|------------------|
| claude / codex / opencode | `C:\Users\MOM\AppData\Roaming\npm\` |
| hermes | `C:\Users\MOM\AppData\Local\hermes\hermes-agent\venv\` |

目标目录（与上文一致）：`D:\Agents\`

### 一、迁移 npm 类（claude、codex、opencode、gemini 等）

```powershell
# 1. 记录已装的全局包（可选）
npm list -g --depth=0

# 2. 卸载 C 盘上的（按你实际装过的来）
npm uninstall -g @anthropic-ai/claude-code @openai/codex opencode-ai @google/gemini-cli codewhale

# 3. 把 npm 全局 prefix 改到 D 盘
$npmGlobal = "D:\Agents\npm-global"
New-Item -ItemType Directory -Force -Path $npmGlobal | Out-Null
npm config set prefix $npmGlobal

# 4. 更新用户 PATH：加入 D 盘，并去掉旧的 Roaming\npm（避免仍命中 C 盘）
$oldNpm = "$env:APPDATA\npm"
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$parts = $userPath -split ";" | Where-Object { $_ -and $_ -ne $oldNpm -and $_ -ne $npmGlobal }
$newPath = ($npmGlobal, ($parts -join ";")) -join ";"
[Environment]::SetEnvironmentVariable("Path", $newPath, "User")
$env:Path = "$npmGlobal;" + ($env:Path -split ";" | Where-Object { $_ -ne $oldNpm }) -join ";"

# 5. 在 D 盘重装
npm install -g @anthropic-ai/claude-code @openai/codex opencode-ai
# 需要时再装：npm install -g @google/gemini-cli

# 6. 验证路径
npm root -g                    # 应为 D:\Agents\npm-global\node_modules
Get-Command claude | Select-Object Source
```

### 二、迁移 Hermes（pip / 独立 venv）

Hermes 若装在 `AppData\Local\hermes\...`，建议在 D 盘新建 venv 重装：

```powershell
$venv = "D:\Agents\python-venvs\studio-agents"
python -m venv $venv
& "$venv\Scripts\Activate.ps1"
pip install -U hermes-agent

# PATH：加入 D 盘 Scripts，去掉 Local\hermes\...\Scripts（若曾手动加过）
$scripts = "$venv\Scripts"
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$hermesOld = "$env:LOCALAPPDATA\hermes\hermes-agent\venv\Scripts"
$parts = $userPath -split ";" | Where-Object { $_ -and $_ -ne $hermesOld -and $_ -ne $scripts }
[Environment]::SetEnvironmentVariable("Path", "$scripts;" + ($parts -join ";"), "User")

hermes --version   # 应指向 D:\Agents\python-venvs\studio-agents\Scripts\hermes.exe
```

确认 D 盘 hermes 正常后，可删 C 盘旧目录释放空间：

```powershell
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\hermes" -ErrorAction SilentlyContinue
```

### 三、迁移 Aider（若已用 pip 装在 C 盘）

```powershell
pip uninstall aider-chat -y
& D:\Agents\python-venvs\studio-agents\Scripts\Activate.ps1
pip install -U aider-chat
```

### 四、Goose（若已装）

Goose 若是 zip 解压到某目录，把整个文件夹 **复制** 到 `D:\Agents\bin`，更新 PATH 指向新目录，再删 C 盘旧目录即可（纯二进制，可搬）。

### 五、收尾

1. **关闭并重新打开** PowerShell / Cursor 终端  
2. 运行：

```powershell
python -m cli.studio agent status
where.exe claude codex opencode hermes
```

3. 若仍指向 `C:\Users\MOM\AppData\Roaming\npm\`，检查系统/用户 PATH 里是否还有旧的 `%APPDATA%\npm`，删掉后重开终端。

4. C 盘 `Roaming\npm` 在卸载且 PATH 已改后，可手动删除残留（先确认 `npm list -g` 为空）：

```powershell
# 谨慎：确认 D 盘已全部 OK 后再执行
# Remove-Item -Recurse -Force "$env:APPDATA\npm\node_modules" -ErrorAction SilentlyContinue
```

</details>

---

## 岗位 ↔ Agent 推荐对照

| 岗位 | 推荐 Agent | 特长 |
|------|-----------|------|
| 技术主管 | **claude-code** | 拆解、决策、复杂推理 |
| 前端 / 移动 | **gemini-cli** | UI、原型、多模态（有免费额度） |
| 后端 / API | **codex** 或 **hermes** | 快速写接口 / 配置与记忆 |
| 测试 / 审查 | **aider** 或 **opencode** | Git 安全提交 / 多模型审查 |
| 桌面 / 自动化 | **goose** | 脚手架、MCP 工作流 |

新建项目默认岗位已按上表配置（见 `core/project.py`）。已有项目请在 `positions.yaml` 里改 `agent:` 字段。

---

## 1. Claude Code（主管 · 已有可跳过）

```powershell
npm install -g @anthropic-ai/claude-code
claude --version
```

认证：按提示登录 Anthropic，或配置 `ANTHROPIC_API_KEY`。

---

## 2. OpenAI Codex（后端 · 你本机可能已装）

```powershell
npm install -g @openai/codex
codex --version
codex login
```

交互 TUI：直接运行 `codex`（不要加 `exec` 子命令）。

---

## 3. Gemini CLI（前端 · 推荐，免费额度）

```powershell
npm install -g @google/gemini-cli
gemini --version
```

首次运行 `gemini`，在 TUI 里选 **Sign in with Google**，或：

```powershell
$env:GEMINI_API_KEY = "你的Key"   # https://aistudio.google.com/apikey
gemini
```

---

## 4. Hermes（后端 / 文档 / 小程序）

```powershell
# 若已装过，跳过
pip install hermes-agent
hermes --version
hermes chat --tui
```

---

## 5. OpenCode（审查 / 多模型）

```powershell
npm install -g opencode-ai
opencode --version
opencode
```

支持在配置里切换 75+ 模型提供商（可接 DeepSeek、Claude、OpenAI 等）。

---

## 6. Aider（测试审查 · Git 原生）

```powershell
pip install -U aider-chat
aider --version
aider
```

需配置任一模型 API Key，例如：

```powershell
$env:DEEPSEEK_API_KEY = "你的Key"
# 或 OPENAI_API_KEY / ANTHROPIC_API_KEY 等，见 https://aider.chat/docs/llms/
aider
```

特点：每次改动自动 `git commit`，适合审查岗「可回滚」。

---

## 7. Goose（桌面 / 脚手架 / 自动化）

**PowerShell（官方）：**

```powershell
irm https://github.com/aaif-goose/goose/releases/download/stable/download_cli.ps1 | iex
goose --version
goose configure
goose session
```

**首次使用必须先 `goose configure`** 选择 model provider 并填入 API Key，否则 `goose session` 会报错退出。Studio Agent 目录在未配置时会自动打开 `goose configure`。

若 GitHub 超时，到 [Goose Releases](https://github.com/aaif-goose/goose/releases) 手动下 Windows 包，解压后将目录加入 PATH。

也可安装桌面版：<https://goose-docs.ai/docs/getting-started/installation>

---

## 一键批量安装（PowerShell）

复制整段执行（GitHub 不通时 gemini/claude/codex 的 npm 一般仍可用）：

```powershell
npm install -g @anthropic-ai/claude-code @openai/codex @google/gemini-cli opencode-ai
pip install -U aider-chat
python -m cli.studio agent status
```

Goose 需单独执行上一节的 `irm ...` 命令。

---

## 常见问题

### `agent status` 显示 `[--]`

表示命令不在 PATH。安装后 **新开一个 PowerShell** 再测。

### npm 装得上，但运行时要下 GitHub 二进制超时

与 CodeWhale 类似：npm 包装脚本装好了，Release 资源拉不下来。解决：

- 开代理后重试
- 或到该项目 GitHub Releases **手动下载 Windows exe**，加入 PATH

### Cursor 为什么不在列表里？

Cursor 是 **IDE**，不是 Studio 编排用的终端 Agent。请用本页 CLI 列表。

---

## 卸载

```powershell
npm uninstall -g @anthropic-ai/claude-code @openai/codex @google/gemini-cli opencode-ai
pip uninstall aider-chat
# Goose：删除安装目录并从 PATH 移除
```
