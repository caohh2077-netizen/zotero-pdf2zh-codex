# 0.1.0 Windows x64

Zotero 10.0.8、PDF2zh 4.1.8、Python 3.12.10、pdf2zh-next 2.10.2、BabelDOC 0.7.1、Codex CLI 0.169.0-alpha.11.1。用户使用自己的 ChatGPT 登录和订阅额度。

2026-11-18 在独立 Windows Zotero 配置中，从 PDF2zh 右键菜单翻译了一页自编的温度研究。该文献从一个附件变为两个，新附件标记为 `clitranslator-dual`。实测包含 4 次成功的 Codex 片段调用；单次约 30–36 秒。成品为一页左右对照，中文保留 12 个样品、23.5 摄氏度、引用 [1] 及公式 x = 2。导入前后原 PDF 的 SHA-256 相同。README 中配图为本次实际输出。

在 `18890` 上重复启动保持同一后端 PID。启动第二次翻译并观察到 Codex 及所属进程树，最小化后正常退出测试 Zotero。退出后记录的 11 个进程全部释放，端口停止监听。独立进程保护、外部端口占用及重新创建 Job 的场景另有 Windows 自动测试。离线整页测试使用真实排版引擎与假译文，不依赖 ChatGPT 凭据。

下载 Windows ZIP 后按 README 安装。此版本使用上游通用 CLI，切换语言时需同步设置 Zotero 和适配器。
