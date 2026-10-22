# 稳定版本归档审查

2026-10-22。本页覆盖初次归档与合并前日期测试修复。业务算法、Prompt、固定数据、金标和模型结果不变；日期修复仅在测试层替换机器实时时钟断言，新增固定时钟边界用例。没有模型请求、合并 main、推送或修改仓库可见性。

## 合并前日期修复与最新验证

在 `docs/archive-deepseek-be-results` 的 `3f8c0fdfe00d17a5d68b1ab2fab79cd946f7d2e7` 上最小修改。只改 `tests/test_paid_preflight_guards.py`、README、TEST_REPORT 和本页；最终提交以 Git 记录为准。其余 9 个候选文件本轮没有变化，全部 13 个候选文件已经重新审查。

- 原时区用例改用固定 UTC 时刻转换上海时区，仍验证 Windows 时区数据可用，不再断言机器“今天”必须是授权日。
- 新增 6 个固定时刻用例，直接进入原脚本 `main()` 日期门禁，只 monkeypatch 该模块的 `datetime`。上海时间前一日拒绝、2026-10-22 的起止边界允许、2026-10-23 零点拒绝、2026-10-24 和 2027-01-01 拒绝。没有修改 `be.DATE` 或加入命令行/环境变量的日期覆盖入口。
- 允许日期以“到达后续公开数据检查”为断言；在那里注入主动停止。过期日期必须在该检查之前停止。两者预期退出码均为 1，分别表示测试主动阻断和真实日期阻断，不将它们误称为完成收费任务。另断言 Key 读取、文件写入、HTTP 和 suite 调用均未发生，临时目录为空。
- 日期/时区单独回归：**7 passed、3 deselected，0.20 秒**。完整离线回归：**100 passed、0 failed、0 skipped，48.15 秒**；比之前 94 项多 6 个日期边界样例，不是增加模型质量样本。实际 XML：仓库外 `.publication-preflight-20261022/archive-offline-2e51aab4ec22/pytest.xml`。
- 完整回归沿用仅允许本机测试 TCP、阻断外网及真实 Ollama 端口的包装器，外网尝试 0；没有执行 DeepSeek 或 Qwen。Ruff、PowerShell 包装器静态语法检查、Diff 检查通过。13 个候选文件中的 61 个本地 Markdown 引用均有效；提交前扫描全部本地 refs 可达的 10 个提交、131 个 blob 及 13 个工作区候选文件，凭据模式未命中，无运行数据、LFS 指针或二进制资源。模式扫描不保证不存在未知格式秘密，外部 URL/远端对象未重验。21 个真实 B/E 原件哈希未变，历史失败正文保留。
- 收费 Python 脚本、预检 Python 脚本、PowerShell 入口及 RequestGate 与 `3f8c0fd` **逐字一致**；真正执行仍读取机器上海时区当前日期，过期阻断未放宽，现有 run-id 不得复用。日期测试不再依赖实际今天，覆盖的未来日期包括 2026-10-23、2026-10-24 及 2027 年；未更改操作系统时钟。
- 当前本地 main 是归档分支祖先，具备本地 fast-forward 拓扑条件；远端实时 main 仍需正式同步前 fetch 核对。本轮没有访问或修改远端。

**公开待办仍保留：** 本地可达历史有 2 个作者/提交者邮箱身份，其中 1 个不是 GitHub noreply。已只输出数量和类型，未展示邮箱值。公开前需本人确认历史邮箱可公开；本轮不自行改写作者身份或 Git 历史。GitHub 平台侧资源检查仍沿用此前未验证边界，本次修复不等于完成 Public 授权。

## 真实 Git 关系

| 引用 | 核对时提交 | 与本地 main 的关系 |
|---|---|---|
| `main` / 本地 `origin/main` | `f3b5c496020e680dabdffceb04622791e20af136` | 相同；本轮不移动 |
| `experiment/research-quality-improvement` | `a53aaec47fa8f0bcd201ca99ffba788889142a1a` | main 后 3 个提交；保留 Qwen 撤回报告、B/E 工具及测试索引 |
| `audit/publication-safety-preflight` | `e358a05770cfc57a566153e6312b4d1b1d05f0e9` | 前述实验分支后 1 个预检提交；也是 B/E 真实执行代码 |
| `docs/archive-deepseek-be-results` | `e358a05` → 归档 `3f8c0fd` → 本次本地修复提交 | 审核分支后追加归档文档与确定性测试；没有失败候选业务代码 |
| `docs/finalize-public-readme` | `edff140b94dfbf1582a4b10757c691853bfaea9f` | main 的祖先 |
| `feat/deepseek-provider` | `f807062651e6803f7434004af8b8cbe70a0f5f54` | main 的祖先 |

origin 地址为 `https://github.com/qianmu233/research-pilot.git`。本轮重新执行 `git ls-remote --symref origin HEAD refs/heads/* refs/tags/*` 未成功：受限环境 Schannel 凭据错误，正常用户只读重试遇连接重置，按当时 DNS 地址连接仍超时。**本轮远端实时 main、分支及标签状态未验证**；表中 origin/main 是本地跟踪引用，不能当作刚刚 fetch 的结果。没有因此改配置、关闭 TLS 校验或推送。

审查范围为本地 main 到当前归档分支的完整差异及该分支可达本地 Git 对象，不是 GitHub 平台侧 Actions/Artifacts/Release/Pages 的重新审查。

## 候选文件与纳入理由

| 文件 | main 之外的内容与结论 |
|---|---|
| `README.md` | 更新 DeepSeek 已验证范围，链接真实结果，保留模型差异和限制；启动、架构和技术栈不变 |
| `TEST_REPORT.md` | 新增当前验收摘要；保留此前历史正文及失败记录 |
| `docs/DEEPSEEK_BE_RESULTS_20261022.md` | B/E 请求、用量、六条结论支持性、Qwen 对照、状态限制及 21 份本地原件哈希 |
| `docs/QUALITY_QWEN_20261022.md` | 保留失败实验、C 退化和撤回证据；不把该候选写成稳定功能 |
| `docs/DEEPSEEK_BE_PREFLIGHT.md` | 历史门禁和离线测试记录；只加当前结果导航，不回写旧实验 |
| `docs/STABLE_VERSION_REVIEW_20261022.md` | 本次完整版本范围、安全结论、测试证据及后续命令 |
| `.env.example` | 仅补充演示 DSN/本地接口边界注释和已知模型限制；不添加真实凭据或改变配置值 |
| `scripts/deepseek_be.py` | 固定 B/E、公共 SHA、端点/请求/字节/预算门禁、失败停止与独立 run-id；作为受控验收工具归档 |
| `scripts/deepseek_http_a.py` | 仅提取相同的公开载荷检查方法供 B/E 覆盖；原 A 行为和旧测试保持 |
| `scripts/preflight_deepseek_be.py` | 不读 Key 值，使用合成凭据+MockTransport检查 SDK，仅读本地缓存/只读 SQL；不发送模型请求 |
| `scripts/run-deepseek-be-once.ps1` | 默认只预检，付费需双开关和用户 SecureString；不继承旧 Key，不覆盖已有 run-id；保留作已执行实验的入口证据，不是再次调用授权 |
| `tests/test_quality_deepseek_be.py` | 8 项离线公共载荷、TCP Mock、失败停止、非法引用、预算和持久化合约 |
| `tests/test_paid_preflight_guards.py` | 10 项字节上限、并发计数、记账失败零网络、固定时区及 6 个日期边界回归；日期测试已确定性修复 |

完整 diff 中 `research_pilot/`、`benchmarks/`、`tests_real/`、依赖与锁文件没有变化。Qwen 候选只曾在忽略目录保留快照，撤回后没有出现在上述提交中；没有“为了通过”修改旧断言、检索金标或生产路由。

### 不应直接带入稳定版的内容

- 失败 Qwen 候选：移除 assess 请求中 plan 的业务改动及对应候选测试；B/E 不改善而 C 退化，已撤回，当前 Git 差异中不存在，禁止从忽略目录重新复制。
- `data/`、SQLite、API 原始响应、模型权重、`.env` 和本地审计辅助脚本/测试证据：保持忽略或仓库外，不加入提交。报告只归档公开事实、摘要及哈希。
- 不能把离线 Mock、检索 Recall、两条真实样例或手工来源复核改写为全面质量/自动事实验证成功。

### 工具限制与处理状态

1. `budget.json` 保存 dry-run 计划的静态 mode/authorization 标签；本次真实授权与请求由用户记录、账本和事件支持。建议将来仅修正新运行元数据并补无网络测试，不改旧结果。
2. 原 `test_windows_paid_date_path_has_working_timezone_data` 曾把当前日期与固定 `be.DATE` 相等作为断言，存在过期后错误失败的问题。**本次已在测试层修复**：固定时区转换独立于今天，日期允许/拒绝分支用固定时钟验证，过期不再导致测试本身错误失败。实际脚本授权日期未延长，门禁没有放松；详见本页最新验证。
3. 脚本付费日期与价格固定到 2026-10-22，现有 run-id 已占用；它们是一次性实验归档入口，不是可随意改 ID/日期再次运行的通用入口。冻结业务版本无需再次付费或解决全部模型差异。

原日期测试阻塞项已修复并通过完整离线回归；13 个候选文件可以进入稳定版本审查。静态 budget 标签继续作为非阻塞归档限制保留，不回写历史实验，不额外运行模型。

## 前次归档验证（保留当时结果）

- 既有 B/E 21 个证据文件只读核对，7 次 HTTP/usage/模型事件、任务/API/预算表一致，B 9 个/E 7 个检查点连续且最终状态一致，重开计数 4→4、3→3。原件前后 SHA256 未变。
- 归档前运行 `pytest tests -q --tb=short --junitxml=<独立审计目录>/pytest.xml`：**94 passed、0 failed、0 skipped，47.70 秒**。Python 包装器先移除子进程模型凭据、关闭下载/外部 tracing，并拒绝非 loopback TCP 和真实 Ollama 11434 端口；外网尝试 0。包含本地脚本化 HTTP、真实 BGE/PgVector/SQLite，不含 `tests_real/` 或收费模型。
- XML 留在仓库外 `.publication-preflight-20261022/archive-offline-adf7cb41b219/pytest.xml`；没有复用或覆盖真实运行目录。数据库已在本地监听，不启动/停止容器，不删除集合或数据库。
- `python -m ruff check research_pilot tests tests_real scripts`、`git diff --check`：通过。5 份归档文档的 56 个本地 Markdown 引用均存在；外部 URL 本轮未发请求重验。
- 提交前扫描本地全部 refs 可达的 9 个提交、126 个 blob，以及本次 5 份文档：私钥、供应商/GitHub Token、AWS Key ID 模式未命中，没有二进制/LFS 指针或已跟踪运行目录。新增差异没有内部绝对路径；业务/金标/真实模型测试/依赖未变，历史 TEST_REPORT 与预检正文、Qwen 报告字节核对通过。不读取真实环境配置，不输出候选凭据原文；模式扫描不等于绝对不存在秘密，也不覆盖未知远端对象。
- 未重新检查 GitHub 实时提交和平台侧资源，未运行模型、重新训练、确认实际账单或更改公开性；没有重验历史远端模型资源下载。

## 审核后命令建议（本轮均未执行）

日期测试修复已经完成。本轮停在本地提交，等待用户确认同步；之后先在可正常访问 GitHub 的终端复核远端与完整差异。不要直接合并旧失败候选或自动 cherry-pick 未审核内容。

```powershell
git fetch origin main
git status --short
git log --oneline --graph --decorate main origin/main docs/archive-deepseek-be-results
git diff --stat main..docs/archive-deepseek-be-results
git diff main..docs/archive-deepseek-be-results -- research_pilot benchmarks tests_real
```

确认工作区干净、审核通过且远端 main 仍是归档分支祖先后，可使用下列 PowerShell fast-forward；任一步失败就停止，不 force、不自动改成其它合并方式。这些同步命令本轮没有执行：

```powershell
git fetch origin main
if ($LASTEXITCODE -ne 0) { throw 'Fetch failed; stop.' }
if (git status --porcelain) { throw 'Working tree is not clean; stop.' }
git merge-base --is-ancestor origin/main docs/archive-deepseek-be-results
if ($LASTEXITCODE -ne 0) { throw 'Remote main has diverged; review before merging.' }
git switch main
if ($LASTEXITCODE -ne 0) { throw 'Switch failed; stop.' }
git merge --ff-only origin/main
if ($LASTEXITCODE -ne 0) { throw 'Local main cannot fast-forward; stop.' }
git merge --ff-only docs/archive-deepseek-be-results
if ($LASTEXITCODE -ne 0) { throw 'Archive cannot fast-forward; stop.' }
git push origin main
if ($LASTEXITCODE -ne 0) { throw 'Push failed; stop and review.' }
```

若 main 或远端演进导致不能 fast-forward，应重新审查并走正常 PR。当前仅准备本地归档提交，不承诺远端合并安全已经验证。

结论：ResearchPilot 的工程 MVP 和本次真实模型样例可以冻结，转入简历与面试；保留 Qwen 限制和 DeepSeek 未测范围。日期测试问题已解决，本地具备 fast-forward 合并条件；正式同步仍需用户确认与远端 fetch 核对，公开前仍需确认历史邮箱等隐私待办。不需要继续调业务 Prompt 或新增收费实验。
