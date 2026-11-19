# Zotero PDF2zh × Codex

在 Windows 的 Zotero 里右键一篇英文论文，用自己的 ChatGPT 账户生成左侧英文、右侧简体中文的双语 PDF。原文和译文都保存在文献库中。PDF 拆分和排版在本机完成，待译片段会通过 Codex 发给 OpenAI，使用量计入你的 Codex 额度。使用订阅翻译无需填写 API Key。

[下载 v0.3.1 Windows 安装包](https://github.com/caohh2077-netizen/zotero-pdf2zh-codex/releases/download/v0.3.1/zotero-pdf2zh-codex-0.3.1-windows-x64.zip) · [首次安装](#首次安装) · [翻译第一篇文献](#翻译第一篇文献) · [与上游的功能对比](#与上游的功能对比)

## 首次安装

适用于 **Windows x64、Zotero 10.0.8**，需要一个可使用 Codex 的 ChatGPT 账户。先在 Zotero 的「帮助 → 关于 Zotero」核对版本，并预留约 **4 GB** 磁盘空间。首次安装需要联网下载翻译引擎、字体和版面模型。[支持的版本](compat/upstream.lock.toml) · [Zotero 10.0.8 官方 Windows 安装包](https://download.zotero.org/client/release/10.0.8/Zotero-10.0.8_x64_setup.exe)

### 1. 下载 Python、插件和 Codex

已有 Python 的用户可先在 PowerShell 运行 `python -VV`。输出同时包含 `3.12.10` 和 `64 bit (AMD64)`，就可以跳过下表的 Python 安装。v0.3.1 安装器会核对完整版本号，包括末尾的 `.10`。

| 下载什么 | 接下来做什么 |
| --- | --- |
| [Python 3.12.10（64 位）](https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe) | 运行安装程序，勾选 **Add python.exe to PATH**，完成安装。 |
| [本项目的 Windows ZIP](https://github.com/caohh2077-netizen/zotero-pdf2zh-codex/releases/download/v0.3.1/zotero-pdf2zh-codex-0.3.1-windows-x64.zip) | 右键 ZIP →「全部解压」，放到一个准备长期保留的文件夹。打开能同时看到 `Install.ps1`、`compat`、`src` 的那一层。插件文件已包含在 `compat` 里。 |
| [官方 Codex CLI 0.169.0-alpha.11.1（Windows x64）](https://github.com/openai/codex/releases/download/rust-v0.169.0-alpha.11.1/codex-x86_64-pc-windows-msvc.exe) | 把下载的 `codex-x86_64-pc-windows-msvc.exe` 放在 **`Install.ps1` 旁边**。这是翻译时实际使用的程序，安装后请保留在原处。 |

<details>
<summary>核对下载文件的 SHA-256</summary>

在下载文件所在文件夹打开 PowerShell，运行 `Get-FileHash .\文件名 -Algorithm SHA256`，把「文件名」换成实际下载的文件名。Windows ZIP 的校验值见同版 `SHA256SUMS`，Codex 可执行文件的校验值为 `a473edef0d52c4ffa067060ddd48a3d85720a3256cbd0510aab71d406f3af744`。已安装 GitHub CLI 的用户还可以核验 ZIP 的构建来源。[本项目发布页](https://github.com/caohh2077-netizen/zotero-pdf2zh-codex/releases/tag/v0.3.1) · [Codex 官方发布页](https://github.com/openai/codex/releases/tag/rust-v0.169.0-alpha.11.1)

```powershell
gh attestation verify .\zotero-pdf2zh-codex-0.3.1-windows-x64.zip --repo caohh2077-netizen/zotero-pdf2zh-codex
```

</details>

### 2. 登录自己的 ChatGPT 账户

在刚才看到 `Install.ps1` 的文件夹中，点一下文件资源管理器的**地址栏**，输入 `powershell` 并回车。后面的命令都在这个窗口逐行执行。

```powershell
Rename-Item -LiteralPath .\codex-x86_64-pc-windows-msvc.exe -NewName codex.exe
python --version
.\codex.exe --version
```

后两条命令应分别显示 `Python 3.12.10` 和 `codex-cli 0.169.0-alpha.11.1`。接下来执行 `login`，在浏览器里用自己的 ChatGPT 账户登录。回到 PowerShell，运行 `login status` 应看到 `Logged in using ChatGPT`。[Codex 官方登录说明](https://developers.openai.com/codex/auth/)

```powershell
.\codex.exe login
.\codex.exe login status
```

### 3. 在 Zotero 安装插件

打开 Zotero 的 **工具 → 插件**，把解压目录里的 **`compat\pdf2zh-codex.xpi`** 拖进插件管理器，确认安装。看到 **PDF2zh 4.1.8.4** 已启用后，从 **文件 → 退出** 完全关闭 Zotero，以便安装程序写入翻译设置。

### 4. 安装翻译引擎，生成桌面快捷方式

回到刚才的 PowerShell。先运行第一条，等它完成后再运行第二条。

```powershell
python -I -X utf8 .\src\manage.py install --codex .\codex.exe
python -I -X utf8 .\src\manage.py use-codex
```

第一条会下载并校验依赖、激活后端，在桌面创建 **Zotero 全文翻译**。第二条显示 `PDF2zh now uses clitranslator.` 就表示已选好 **Codex（本机订阅）**，可以开始翻译。默认从英语译为简体中文，生成双语附件。后端的默认安装目录是 `%LOCALAPPDATA%\Zotero-PDF2zh-Codex`。

## 翻译第一篇文献

1. 双击桌面的 **Zotero 全文翻译**。如果 Zotero 已经打开，也可以直接双击这个快捷方式启动后端。
2. 第一次使用时，打开 **编辑 → 设置 → PDF2zh**。确认「翻译引擎」为 `pdf2zh_next`，「翻译服务」为 **Codex（本机订阅）**，在 `http://127.0.0.1:8890` 旁点 **检查连接**。默认模型是 **GPT-6.2-Sol / xhigh**。若提示账号不支持，点「刷新模型」，选择列表中可用的模型和思考强度。
3. 把一份英文 PDF 拖进「我的文库」，或选中已有的本地 PDF 附件。右键 PDF 或带附件的文献条目，选 **PDF2zh → 翻译PDF**。右下角会先显示版面分析，随后显示「已处理 / 总片段数」。
4. 完成后展开原文献条目，打开新增的双语 PDF。独立导入的 PDF 会在原分类中得到新附件。默认英文在左、中文在右，磁盘文件名末尾带有 `__gpt-6.2-sol__xhigh.pdf` 这样的标记。

最小化 Zotero 可以继续翻译。退出 Zotero 会停止本次后端及翻译子进程，进行中的翻译会取消。

![同一篇单页论文的实际输出，英文原文在左，中文译文在右](docs/bilingual.png)

## 与上游的功能对比

以下对照本项目实际采用的 **zotero-pdf2zh v4.1.8** 和 **本项目 v0.3.1 的 Codex 翻译模式**。Zotero 右键翻译、PDF 排版、双语附件和 OCR 的基础能力均来自上游。[上游项目](https://github.com/guaguastandup/zotero-pdf2zh) · [对照版本的说明](https://github.com/guaguastandup/zotero-pdf2zh/blob/5dd2eaf019f71266764c269bbd2104b559ae95cf/README.md)

| 对比项 | 上游 zotero-pdf2zh v4.1.8 | 本项目 Zotero PDF2zh × Codex v0.3.1 |
| --- | --- | --- |
| **平台与翻译引擎** | 提供 Windows、macOS、Linux 和 Docker 部署方式，可选 PDF2ZH 或 PDF2ZH Next | 已验证 Windows x64 和 Zotero 10.0.8，通过 PDF2ZH Next 调用本机 Codex CLI |
| **翻译服务与登录** | 可选 DeepSeek、OpenAI、Ollama 等服务，按服务配置账号、密钥或本机地址 | ✅ 新增「Codex（本机订阅）」，使用自己的 ChatGPT 账户 |
| **模型与思考强度** | 在各服务的 LLM 配置里选模型，按服务支持设置思考参数 | ✅ 直接读取当前 Codex 账户的模型列表，可选该模型支持的思考强度 |
| **学科与术语** | PDF2ZH Next 支持术语表及自动提取，具体取决于翻译服务 | ✅ 11 个学科预设或自定义名称，可预览包含领域和术语要求的首句，译文按领域分别缓存 |
| **进度与失败片段** | 提供后台任务、文件进度和百分比，个别失败段可能保留原文 | ✅ 显示已处理、重试中及最终失败的段数，自动补译临时失败的片段 |
| **并发与模型调用** | 已有 QPS 和 Worker 数设置，可按服务配额调整 | 默认 10 个 Worker，同一用户跨文档合计最多 20 个。跳过启动时的 `Hello` 试译 |
| **双语附件与命名** | ✅ 将译文作为新附件导入，支持双语排版和自动 OCR | ✅ 保留双语附件和自动 OCR，另在文件名标明实际模型和思考强度 |
| **启动与退出** | 单独启动翻译服务，也提供自建一键启动脚本的示例 | ✅ 双击「Zotero 全文翻译」同时启动 Zotero 和后端，退出 Zotero 时回收相关进程 |
| **更新与回退** | 发布配套 XPI 和 Server，支持检查上游更新 | 固定上游及依赖版本，插件与后端配对升级，可切回上一个已安装版本 |

**选择学科。** 在 PDF2zh 设置的「思考强度」下方选择「学科领域」。前两个预设依次是「人工智能、机器学习与具身智能」和「人工智能、机器学习」。也可以选「通用」或填写中英文学科名称。同一次右键提交的文献使用同一个领域。选定领域后，提示词以 `As a translator specializing in {field}, choose established terms in the target language that fit the context.` 开头，紧接着指定原文和目标语言。设置页会把 `{field}` 替换成实际名称供预览。通用模式以 `You are a scientific translator.` 开头。

**10 个 Worker 怎样翻译一篇论文？** 最多同时翻译 10 段。比如一个 Worker 做完第 1 段后，就可以接下一段。默认每个需要翻译的片段都会启动一个后台 Codex 进程，并用独立的临时对话翻译。QPS 控制每秒能发起多少次请求，Worker 数设为 0 时跟随 QPS，最多 20 个。

**再次翻译同一篇论文。** 原文、语言、模型、思考强度和提示词配置相同的片段可以直接取用本机已缓存的译文。学科首句更新后，对应领域的片段会按新提示词翻译。

**片段重试。** 断线、短期限流、服务端临时错误、空回复或格式校验失败时，插件会单独补译该段，最多补两次。通常分别等待 1 秒和 3 秒，限流时遵守服务端要求的更长等待时间。首次实际调用开始后的 10 分钟由所有尝试、等待和排队共用。浮窗显示正在重试的段数。若最终仍有失败，会提示「部分完成，N 个片段保留原文」。保持相同设置重新翻译原文，可以复用成功片段。登录、额度或模型问题会提示对应原因，通过现有校验的英文回复按成功处理。[并发实验与术语盲评结果](docs/release.md)

## 常见问题

- **找不到 Python 或 Zotero。** 安装 Python 后重新打开 PowerShell，再运行 `python --version`。若 Zotero 装在自选位置，在第 4 步 `install` 命令末尾加 `--zotero "你的 Zotero 文件夹\zotero.exe"`，替换为实际完整路径。
- **安装依赖时报 `WinError 206`（文件名或扩展名太长）。** 回到第 4 步的 PowerShell，用较短的目录重新安装。下面两条命令会将后端安装到自己用户目录下的 `ZPC` 文件夹。

  ```powershell
  python -I -X utf8 .\src\manage.py install --codex .\codex.exe --root "$env:USERPROFILE\ZPC"
  python -I -X utf8 .\src\manage.py use-codex --root "$env:USERPROFILE\ZPC"
  ```

- **插件已装好，右键没有翻译菜单。** 在「工具 → 插件」确认 PDF2zh 4.1.8.4 已启用，通过「Zotero 全文翻译」重开 Zotero，再选本机可以打开的 PDF 或带 PDF 附件的条目。
- **检查连接失败，或模型列表为空。** 先双击桌面翻译快捷方式，核对地址 `http://127.0.0.1:8890`。连接成功后若列表仍为空，再检查 `.\codex.exe login status` 并点「刷新模型」。安装后可在解压目录运行 `python -I -X utf8 .\src\manage.py doctor` 查看诊断结果。

<details>
<summary>已有安装、自选路径、更新和恢复</summary>

- 已安装匹配版本的 `codex.exe` 时，可直接使用它登录，并将第 4 步 `--codex` 后的路径改为该程序的完整路径。已启用上游官方 4.1.8 XPI 的用户可正常退出 Zotero，从第 4 步配对升级。
- 自选安装目录时，给第 4 步的两条命令都加上 `--root "D:\Apps\Zotero-PDF2zh"`。也可用发布包中的 PowerShell 入口 `Install.ps1 -PrepareOnly`、`Activate.ps1` 和 `Use-Codex.ps1`，三步使用同一个 `-InstallRoot`。
- 更新使用 `.\Update.ps1 -Version 版本号`，将版本号替换为目标 Release 的数字版本。需要回退时，先退出 Zotero，再运行 `.\Rollback.ps1`。`.\Use-Codex.ps1 -Restore` 可在 Zotero 关闭时恢复之前保存的翻译设置。
- 翻译其他语言时，在 Zotero 的 PDF2zh 设置中更改源语言和目标语言。单独测试新版本可用 `Candidate.ps1 -Profile 测试配置绝对路径` 建立测试快捷方式和 `18890` 端口。[维护和回滚说明](docs/maintenance.md)

</details>

<details>
<summary>从源码复现</summary>

以下命令在装有 Git 和 Python 3.12.10 x64 的 Windows 机器上运行。

```powershell
git clone --branch v0.3.1 https://github.com/caohh2077-netizen/zotero-pdf2zh-codex.git
cd zotero-pdf2zh-codex
.\scripts\Bootstrap-Dev.ps1
.\scripts\Test.ps1 -Suite Offline
.\scripts\Test.ps1 -Suite Lifecycle
.\.venv-dev\Scripts\python.exe -X utf8 scripts/offline_pdf.py
```

单页离线测试使用模拟 CLI。首次运行需准备上游资源，已有资源可通过 `--asset-profile` 复用。[Windows 验收工作流](https://github.com/caohh2077-netizen/zotero-pdf2zh-codex/actions/workflows/test.yml) · [构建、同步上游与回滚步骤](docs/maintenance.md)

</details>

**English quick start.** On Windows x64, use Zotero 10.0.8, Python 3.12.10 x64 and the pinned Codex CLI. Extract the Windows release ZIP, place the CLI beside `Install.ps1` as `codex.exe`, and sign in with `.\codex.exe login` using ChatGPT. Install `compat\pdf2zh-codex.xpi` through Zotero’s Plugins window and quit Zotero. From the extracted folder run `python -I -X utf8 .\src\manage.py install --codex .\codex.exe`, then `python -I -X utf8 .\src\manage.py use-codex`. Open the **Zotero 全文翻译** desktop shortcut and right-click a PDF to translate it.

本项目使用 AGPL-3.0。Zotero 插件与后端来自 zotero-pdf2zh，翻译引擎和排版分别来自 PDFMathTranslate-next 与 BabelDOC。运行资源依各自许可从原始来源下载，自编测试样稿采用 CC0。[许可证](LICENSE) · [zotero-pdf2zh](https://github.com/guaguastandup/zotero-pdf2zh) · [PDFMathTranslate-next](https://github.com/PDFMathTranslate-next/PDFMathTranslate-next) · [BabelDOC](https://github.com/funstory-ai/BabelDOC)
