# Zotero PDF2zh × Codex

在 Windows 上从 Zotero 右键生成中英双语 PDF，使用已登录的官方 Codex CLI 和自己的 ChatGPT 订阅。打开桌面「Zotero 全文翻译」会启动本机后端；退出 Zotero 时，本次后端和翻译进程一起退出。PDF 的待译片段会发送到 OpenAI，使用量计入自己的订阅。

![自编单页论文的真实双语输出，英文在左、中文在右](docs/bilingual.png)

## 安装

1. 准备 Windows x64、Zotero **10.0.8**、64 位 CPython **3.12.10** 和官方 Codex CLI **0.169.0-alpha.11.1**。在终端执行 `codex login`，选择 ChatGPT 账户，然后运行 `codex login status`。本版验证模型为 `gpt-6.2-sol`。[Codex 登录说明](https://developers.openai.com/codex/auth/)
2. 打开本项目 [Releases](https://github.com/caohh2077-netizen/zotero-pdf2zh-codex/releases)，下载同一版本的 Windows ZIP、`SHA256SUMS` 和 `build-source.json`。用下方命令校验，再解压到自己的目录。首次准备约 330 MB 的 Python wheels 和约 352 MB 的字体、布局模型等资源，另需官方 Server 与 XPI；预留 4 GB 空间。
3. 从解压目录运行 `.\Install.ps1 -PrepareOnly`。在 Zotero「工具 → 插件」中安装准备好的 `managed\downloads\zotero-pdf-2-zh.xpi` 并启用。退出 Zotero，再运行 `.\Activate.ps1` 和 `.\Use-Codex.ps1`。后者配置 PDF2zh 的服务、语言和双语选项，并保存这些选项的旧值。已启用 v4.1.8 的用户可在 Zotero 关闭时直接运行 `.\Install.ps1`，然后运行 `.\Use-Codex.ps1`。
4. 双击桌面「Zotero 全文翻译」。在 PDF 或其父条目上右键，选择 **PDF2zh → PDF2zh: 翻译PDF**。译文会作为新附件放回条目。最小化可继续翻译，退出 Zotero 会取消未完成的任务。

**获取指定 Codex 版本。** 已安装 Codex 桌面端的用户可用 `codex --version` 核对版本。也可从官方发布页下载 `codex-x86_64-pc-windows-msvc.exe`，用 `Get-FileHash` 对照 SHA-256 `a473edef0d52c4ffa067060ddd48a3d85720a3256cbd0510aab71d406f3af744`，将文件命名为 `codex.exe`。从该目录运行 `.\codex.exe login`，然后给安装脚本传 `-CodexPath` 和此文件的完整路径。[下载官方 Windows CLI](https://github.com/openai/codex/releases/tag/rust-v0.169.0-alpha.11.1)

```powershell
Get-FileHash .\zotero-pdf2zh-codex-0.1.0-windows-x64.zip -Algorithm SHA256
# 与同一 Release 的 SHA256SUMS 对照。安装 GitHub CLI 的用户还可以核验构建来源：
gh attestation verify .\zotero-pdf2zh-codex-0.1.0-windows-x64.zip --repo caohh2077-netizen/zotero-pdf2zh-codex
```

默认安装在 `%LOCALAPPDATA%\Zotero-PDF2zh-Codex`。使用现有目录时，给 **准备、激活及首次配置** 传相同的 `-InstallRoot`。自定义路径示例：

```powershell
.\Install.ps1 -PrepareOnly -InstallRoot 'D:\APP\Zotero-PDF2zh' -PythonPath 'D:\APP\Python\python.exe' -ZoteroPath 'D:\APP\Zotero\zotero.exe' -CodexPath (Get-Command codex.exe).Source
.\Activate.ps1 -InstallRoot 'D:\APP\Zotero-PDF2zh' -PythonPath 'D:\APP\Python\python.exe'
.\Use-Codex.ps1 -InstallRoot 'D:\APP\Zotero-PDF2zh' -PythonPath 'D:\APP\Python\python.exe'
```

也可在 Zotero 手动设置 `pdf2zh_next`，在**翻译服务文本框**输入 `clitranslator`，设置 `en → zh-CN`、双语、QPS 1 和线程 1。使用系统已有的代理设置。独立打开的 Codex 桌面继续由用户控制。每个片段都启动一次 CLI，长文耗时及配额随片段数增加。

若 Windows PowerShell 限制本地脚本，可以从解压目录直接运行同一 Python 入口，例如 `python -I src/manage.py prepare`、`python -I src/manage.py activate`、`python -I src/manage.py use-codex`。自定义安装目录通过 `--root` 指定。

## 更新与恢复

- `Doctor.ps1` 核对 Zotero、插件、CLI 和 ChatGPT 登录，显示当前语言。更换 Codex 安装路径后可重新准备版本，或在 PATH 上提供匹配的官方 CLI。
- `Set-Language.ps1 -Source en -Target de` 配置翻译命令，随后把 Zotero 的目标语言也改成 `de`。上游的通用 CLI 接口只传文本，两个位置需要一致。
- `Update.ps1 -Version 版本号` 从本仓库官方 Release 校验和准备版本。`Rollback.ps1` 选择上一个可用版本。`Use-Codex.ps1 -Restore` 可恢复此前保存的 PDF2zh 选项。如果更换过 XPI，在插件管理器中恢复矩阵对应的版本。
- `Candidate.ps1 -Profile 测试配置绝对路径` 创建测试入口，使用 `18890`；在该 Zotero 测试配置中将 PDF2zh 后端地址设为 `http://127.0.0.1:18890`。日常服务只监听 `127.0.0.1:8890`。上游版本变化不会自动改动运行环境。

## 开发者复现

```powershell
git clone --branch v0.1.0 https://github.com/caohh2077-netizen/zotero-pdf2zh-codex.git
cd zotero-pdf2zh-codex
.\scripts\Bootstrap-Dev.ps1
.\scripts\Test.ps1 -Suite Offline
.\scripts\Test.ps1 -Suite Lifecycle
.\.venv-dev\Scripts\python.exe -X utf8 scripts/offline_pdf.py
```

`offline_pdf.py` 首次运行需准备上游资源，可用 `--asset-profile 已有engine-data目录` 复用经过摘要校验的文件。翻译部分使用假 CLI，CI 不需要个人登录。测试覆盖文本契约、配置保留、错误和超时、端口占用及进程树回收。实际测试记录与维护流程见 [验收记录](docs/release.md) 和 [维护说明](docs/maintenance.md)。

**English.** Install the tested Windows components, sign in with `codex login` using ChatGPT, then run `Install.ps1 -PrepareOnly`. Enable the verified upstream XPI. Close Zotero, run `Activate.ps1` and `Use-Codex.ps1`, then use the desktop shortcut and the PDF2zh context menu. The original PDF is retained. Each user needs their own eligible subscription.

本项目使用 AGPL-3.0。原版插件及后端来自 [guaguastandup/zotero-pdf2zh](https://github.com/guaguastandup/zotero-pdf2zh)，文本接口来自 [PDFMathTranslate-next](https://github.com/PDFMathTranslate-next/PDFMathTranslate-next)，排版由 [BabelDOC](https://github.com/funstory-ai/BabelDOC) 提供。官方软件及其运行资源按各自许可从来源下载。测试论文为本项目自编，文本与夹具生成的样本采用 CC0。
