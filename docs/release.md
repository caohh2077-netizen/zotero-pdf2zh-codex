# 0.1.0 Windows x64

Zotero 10.0.8、PDF2zh 4.1.8、Python 3.12.10、pdf2zh-next 2.10.2、BabelDOC 0.7.1、Codex CLI 0.169.0-alpha.11.1。用户使用自己的 ChatGPT 登录和订阅额度。

2026-11-18 在独立 Windows Zotero 配置中，从 PDF2zh 右键菜单翻译了一页自编的温度研究。该文献从一个附件变为两个，新附件标记为 `clitranslator-dual`。实测包含 4 次成功的 Codex 片段调用；单次约 30–36 秒。成品为一页左右对照，中文保留 12 个样品、23.5 摄氏度、引用 [1] 及公式 x = 2。导入前后原 PDF 的 SHA-256 相同。README 中配图为本次实际输出。

在 `18890` 上重复启动保持同一后端 PID。启动第二次翻译并观察到 Codex 及所属进程树，最小化后正常退出测试 Zotero。退出后记录的 11 个进程全部释放，端口停止监听。独立进程保护、外部端口占用及重新创建 Job 的场景另有 Windows 自动测试。离线整页测试使用真实排版引擎与假译文，不依赖 ChatGPT 凭据。

日常快捷方式在 `127.0.0.1:8890` 上通过同样的启停测试。翻译中退出后，记录的 11 个进程全部释放，再次启动与退出均成功。测试用 Zotero 重新启动后也完成了第二份双语 PDF。切回旧版时，原桌面快捷方式恢复后的 SHA-256 与切换前一致，随后重新启用了 Codex。

GitHub 托管的 Windows 2022 环境在含中文及空格的目录完成首次安装、重复安装与离线双语 PDF 验收。安装时验证了 182 个字体、布局及分词资源。另用 README 指向的官方独立 Codex 可执行文件，在同一 ChatGPT 账户上将合成句子译为“我们测量了 12 个样品 [1]。”。[Windows 验收工作流](https://github.com/caohh2077-netizen/zotero-pdf2zh-codex/actions/workflows/test.yml)

下载 Windows ZIP 后按 README 安装。此版本使用上游通用 CLI，切换语言时需同步设置 Zotero 和适配器。
