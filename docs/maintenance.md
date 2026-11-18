# 维护、复现和回滚

`compat/upstream.lock.toml` 同时固定上游标签、源码提交、官方 XPI 与 Server 文件的 SHA-256。`locks/windows-x64-py312.txt` 固定 Windows x64 的 141 个 wheels。BabelDOC 的锁定 wheel 含布局模型、字体、CMap 及分词资源的 SHA3-256 目录，安装时逐个验证，包括从旧安装复用的文件。

1. 运行 `python scripts/check_upstream.py`，或查看每周 GitHub Actions 的只读报告。若同一标签的资产被替换，先人工核对发布记录。为候选版本建独立分支，显式更新兼容清单和必要代码。
2. 在一个新 Python 3.12.10 x64 虚拟环境中解析、测试新依赖，使用 `scripts/lock_wheels.py` 生成对应平台的 wheel 哈希清单，审阅差异。安装器只从清单取包。Codex CLI 版本变化时，验证禁用工具的参数、ChatGPT 登录、账户限额、临时会话、输出事件结构及真实单页翻译，再把该版本加入清单。
3. 使用 `Install.ps1 -PrepareOnly`。候选目录在 `managed/releases` 下以版本及源摘要标识。创建独立 Zotero 配置和文献目录，安装清单中的 XPI，指向 `127.0.0.1:18890`。运行 `Candidate.ps1 -Profile 路径` 并使用测试快捷方式。保留日常配置与 `8890` 服务用于回退。
4. 离线测试、真人单页、退出回收、重启、端口冲突均通过后，运行 `Activate.ps1`。当前版本、前一版本和待切换状态保存在 `managed/state`。更新期间的代码、配置、可写翻译缓存与产物都在各自的版本目录中。首次迁移保存平铺版 `legacy` 入口及原有快捷方式备份。
5. 回滚时先正常退出 Zotero，运行 `Rollback.ps1` 并核对 `Doctor.ps1` 和匹配的 XPI。处理中断时，从同一版本包重新运行准备步骤，只有存在就绪标记的目录可以成为活动版本。迁移操作无需修改 Zotero 文献数据库。
6. 从已提交的源代码运行 `python scripts/build_release.py`。发布任务使用标签对应的 Windows runner 执行测试，生成 ZIP、`SHA256SUMS`、源提交记录和 GitHub 构建证明。构建只读公开目录，打包前扫描凭据格式。使用 GitHub 的 Release 和仓库标签关联同一源码。

故障诊断按顺序检查 `Doctor`、`/health` 和 `managed/state/adapter-events.jsonl`。该日志仅包含时间、错误类别与耗时。`ZPC_LOGIN` 需要在本机重新登录；`ZPC_QUOTA` 请检查订阅额度；`ZPC_NETWORK` 请检查连接和本机系统代理；`ZPC_FORMAT` 表示回答为空或格式占位符异常。修复后运行 `Doctor.ps1` 再试。个别片段失败时，上游可能保留原文，因此验收要抽查新附件的页面内容。
