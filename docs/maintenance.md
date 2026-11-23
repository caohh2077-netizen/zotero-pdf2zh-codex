# 维护、复现和回滚

`compat/upstream.lock.toml` 同时固定上游标签、源码提交、官方 XPI 与 Server 文件的 SHA-256。`locks/windows-x64-py312.txt` 固定 Windows x64 的 141 个 wheels。BabelDOC 的锁定 wheel 含布局模型、字体、CMap 及分词资源的 SHA3-256 目录，安装时逐个验证，包括从旧安装复用的文件。

1. 运行 `python scripts/check_upstream.py`，或查看每周 GitHub Actions 的只读报告。若同一标签的资产被替换，先人工核对发布记录。为候选版本建独立分支，显式更新兼容清单和必要代码。
2. 在一个新 Python 3.12.10 x64 虚拟环境中解析、测试新依赖，使用 `scripts/lock_wheels.py` 生成对应平台的 wheel 哈希清单，审阅差异。安装器只从清单取包。更新翻译专用 CLI 时，在 `[codex_cli]` 中同时更新官方版本、Windows x64 资产名、压缩包和解压后 EXE 的 SHA-256。验证禁用工具的参数、ChatGPT 登录、账户限额、临时会话、输出事件结构及真实单页翻译。
3. 使用 `Install.ps1 -PrepareOnly`。候选目录在 `managed/releases` 下以版本及源摘要标识。创建独立 Zotero 配置和文献目录，安装清单中的 XPI，指向 `127.0.0.1:18890`。运行 `Candidate.ps1 -Profile 路径` 并使用测试快捷方式。保留日常配置与 `8890` 服务用于回退。
4. 离线测试、真人单页、退出回收、重启、端口冲突均通过后，运行 `Activate.ps1`。当前版本、前一版本和待切换状态保存在 `managed/state`。更新期间的代码、配置、可写翻译缓存与产物都在各自的版本目录中。首次迁移保存平铺版 `legacy` 入口及原有快捷方式备份。
5. 回滚时先正常退出 Zotero，运行 `Rollback.ps1` 并核对 `Doctor.ps1` 和匹配的 XPI。处理中断时，从同一版本包重新运行准备步骤，只有存在就绪标记的目录可以成为活动版本。迁移操作无需修改 Zotero 文献数据库。
6. 从已提交的源代码运行 `python scripts/build_release.py`。发布任务使用标签对应的 Windows runner 执行测试，生成 ZIP、`SHA256SUMS`、源提交记录和 GitHub 构建证明。构建只读公开目录，打包前扫描凭据格式。使用 GitHub 的 Release 和仓库标签关联同一源码。

故障诊断按顺序检查 `Doctor`、`/health` 和 `managed/state/adapter-events.jsonl`。日志通过 `fragmentId` 和 `attempt` 关联同一片段的各次调用。`end.final` 为真时才确定该段的最终结果。`ZPC_LOGIN` 需要在本机重新登录；`ZPC_QUOTA` 请检查订阅额度；`ZPC_NETWORK` 请检查连接和本机系统代理；`ZPC_FORMAT` 表示回答为空或格式占位符异常。修复后运行 `Doctor.ps1` 再试。个别片段失败时，上游可能保留原文，因此验收要抽查新附件的页面内容。

## 翻译专用 Codex CLI

已验证的可执行文件位于 `managed/tools/codex/<版本>/codex.exe`。模型列表、逐段翻译和可选的进程复用实验均从安装根目录定位该文件。日常翻译沿用当前用户的 ChatGPT 登录状态；部署和诊断时才检查完整文件摘要。桌面版更新、应用目录改名和系统 PATH 变化都不会改变翻译使用的路径。

首次安装会校验并缓存官方 Windows x64 压缩包，然后校验解压后的 EXE 才原子替换目标。`Doctor.ps1` 可利用缓存修复程序；缓存也损坏时重新下载官方发行物。离线安装可在准备阶段传入 `-AssetDir` 或 `-CodexPath`。切换到新版时，安装器也会修正兼容旧版本中已经失效或指向 WindowsApps 的路径，供回退使用。各 CLI 版本的可执行文件可以并存。

Windows 测试会模拟原桌面目录消失、PATH 出现不同 CLI、压缩包或 EXE 校验失败，以及断网从缓存恢复。干净账户的安装测试直接下载官方 CLI，执行 `--version`，再验证重复准备能修正陈旧设置并复用已经验证的程序。

## 学科领域验收

在候选槽的专用测试库中，运行下列命令。缓存顺序验证使用未翻译过该样稿的候选槽。两次术语对照的模型、强度和输入一致，默认 Sol/xhigh、10 个 Worker。48 份输出写到新目录的 blind.jsonl，独立的 key.json 只在锁定评分后查看。对有歧义的词请结合源句核对，分别报告改善与退步。

~~~powershell
& "$slot\runtime\Scripts\python.exe" -I -X utf8 scripts/acceptance_v2.py --port 18890 --tessdata "$slot\tessdata" --work .work/subject-pdf --cases subjects
& "$slot\runtime\Scripts\python.exe" -I -X utf8 scripts/subject_study.py --settings "$slot\settings.json" --live --out .work/subject-study
~~~

## 0.2 前后端及实验复现

源码在固定的上游提交上构建。运行 `python scripts/build_frontend.py --out rebuilt.xpi` 会校验源码归档，应用 `scripts/build_frontend.py` 和 `compat/frontend/codex.ts` 中的改动，执行 `npm ci`、TypeScript 检查和上游打包，再固定 ZIP 成员顺序和时间。用 `Get-FileHash rebuilt.xpi` 对照兼容清单的 `xpi_sha256`。服务端及翻译器的定点改动见 `src/patch_runtime.py`。源文件摘要或替换位置不匹配时，候选安装会中止。

复用实验 B 在每个片段启动新的临时线程，同一文档内可重用空闲进程。正常翻译默认走 A。Windows 的命名事件为每个正在运行或空闲待用的 Codex 翻译进程保留名额，同一用户跨文档合计最多 20 个。等待名额的时间计入排队。独立测试配置可在启动后端前设置当前 PowerShell 会话的 `$env:ZPC_EXPERIMENT='app-server'`。关闭该测试实例后清除环境变量。两组基准使用相同的合成短句，记录本机在途峰值、成功数、墙钟时间与工作集。只在自己的订阅账户上执行真实基准。

```powershell
$slot = '已安装候选版本的绝对路径'
& "$slot\runtime\Scripts\python.exe" -I -X utf8 scripts/benchmark_fragments.py --settings "$slot\settings.json" --live --count 40 --workers 1 10 20 --out benchmark.jsonl
& "$slot\runtime\Scripts\python.exe" -I -X utf8 scripts/acceptance_v2.py --port 18890 --tessdata "$slot\tessdata" --work .work/acceptance-v2
& "$slot\runtime\Scripts\python.exe" -I -X utf8 scripts/offline_partial.py --slot "$slot"
```

`GET /api/codex/capabilities` 提供账户模型与强度。异步提交返回 taskId，`/api/tasks` 与 `/api/history` 的 `fragments` 给出阶段、分子、分母、失败数及调用数。向 `/api/codex/tasks/<taskId>/cancel` 发 POST 可取消该文件。用于诊断的事件只含标识、选项、结果类别和计时。
