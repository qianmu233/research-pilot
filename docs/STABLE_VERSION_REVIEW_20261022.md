# 稳定版本归档审查

2026-10-22。本轮只整理已完成的验收与审查稳定版候选，不修改业务算法、Prompt、固定数据、金标或测试断言；没有模型请求、合并 main、推送或修改仓库可见性。

## 真实 Git 关系

| 引用 | 核对时提交 | 与本地 main 的关系 |
|---|---|---|
| `main` / 本地 `origin/main` | `f3b5c496020e680dabdffceb04622791e20af136` | 相同；本轮不移动 |
| `experiment/research-quality-improvement` | `a53aaec47fa8f0bcd201ca99ffba788889142a1a` | main 后 3 个提交；保留 Qwen 撤回报告、B/E 工具及测试索引 |
| `audit/publication-safety-preflight` | `e358a05770cfc57a566153e6312b4d1b1d05f0e9` | 前述实验分支后 1 个预检提交；也是 B/E 真实执行代码 |
| `docs/archive-deepseek-be-results` | 以 `e358a05` 新建，本次归档提交以 Git 为准 | 在审核分支上只追加文档；没有失败候选业务代码 |
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
| `tests/test_paid_preflight_guards.py` | 4 项字节上限、并发计数、记账失败零网络及 Windows 日期门禁；存在下述日期耦合限制 |

完整 diff 中 `research_pilot/`、`benchmarks/`、`tests_real/`、依赖与锁文件没有变化。Qwen 候选只曾在忽略目录保留快照，撤回后没有出现在上述提交中；没有“为了通过”修改旧断言、检索金标或生产路由。

### 不应直接带入稳定版的内容

- 失败 Qwen 候选：移除 assess 请求中 plan 的业务改动及对应候选测试；B/E 不改善而 C 退化，已撤回，当前 Git 差异中不存在，禁止从忽略目录重新复制。
- `data/`、SQLite、API 原始响应、模型权重、`.env` 和本地审计辅助脚本/测试证据：保持忽略或仓库外，不加入提交。报告只归档公开事实、摘要及哈希。
- 不能把离线 Mock、检索 Recall、两条真实样例或手工来源复核改写为全面质量/自动事实验证成功。

### 已发现的工具限制（本轮不改代码）

1. `budget.json` 保存 dry-run 计划的静态 mode/authorization 标签；本次真实授权与请求由用户记录、账本和事件支持。建议将来仅修正新运行元数据并补无网络测试，不改旧结果。
2. `test_windows_paid_date_path_has_working_timezone_data` 把当前日期与固定 `be.DATE` 相等作为断言；它在本次日期通过，**过期后会使完整 pytest 失败**。这是一次性实验门禁的日期耦合，不是业务回归。稳定版若保留整套工具，建议另行审核最小测试修正：时区可用性独立于当前日期，过期阻断用固定时钟单独测试；不能简单延长收费日期或放松付费授权。本轮未改断言，因此整分支合并仍需处理此项，不能称其已永久 CI 就绪。
3. 脚本付费日期与价格固定到 2026-10-22，现有 run-id 已占用；它们是一次性实验归档入口，不是可随意改 ID/日期再次运行的通用入口。冻结业务版本无需再次付费或解决全部模型差异。

文档与实验成果可以正式归档；将全部工具纳入长期稳定分支前，日期耦合测试须由后续单独审核处理。上述限制不否定已经完成的 B/E 真实验收。

## 本轮实际验证

- 既有 B/E 21 个证据文件只读核对，7 次 HTTP/usage/模型事件、任务/API/预算表一致，B 9 个/E 7 个检查点连续且最终状态一致，重开计数 4→4、3→3。原件前后 SHA256 未变。
- 归档前运行 `pytest tests -q --tb=short --junitxml=<独立审计目录>/pytest.xml`：**94 passed、0 failed、0 skipped，47.70 秒**。Python 包装器先移除子进程模型凭据、关闭下载/外部 tracing，并拒绝非 loopback TCP 和真实 Ollama 11434 端口；外网尝试 0。包含本地脚本化 HTTP、真实 BGE/PgVector/SQLite，不含 `tests_real/` 或收费模型。
- XML 留在仓库外 `.publication-preflight-20261022/archive-offline-adf7cb41b219/pytest.xml`；没有复用或覆盖真实运行目录。数据库已在本地监听，不启动/停止容器，不删除集合或数据库。
- `python -m ruff check research_pilot tests tests_real scripts`、`git diff --check`：通过。5 份归档文档的 56 个本地 Markdown 引用均存在；外部 URL 本轮未发请求重验。
- 提交前扫描本地全部 refs 可达的 9 个提交、126 个 blob，以及本次 5 份文档：私钥、供应商/GitHub Token、AWS Key ID 模式未命中，没有二进制/LFS 指针或已跟踪运行目录。新增差异没有内部绝对路径；业务/金标/真实模型测试/依赖未变，历史 TEST_REPORT 与预检正文、Qwen 报告字节核对通过。不读取真实环境配置，不输出候选凭据原文；模式扫描不等于绝对不存在秘密，也不覆盖未知远端对象。
- 未重新检查 GitHub 实时提交和平台侧资源，未运行模型、重新训练、确认实际账单或更改公开性；没有重验历史远端模型资源下载。

## 审核后命令建议（本轮均未执行）

先处理上面的日期耦合测试审核，再在可正常访问 GitHub 的终端复核远端与完整差异。不要直接合并旧失败候选或自动 cherry-pick 未审核内容。

```powershell
git fetch origin main
git status --short
git log --oneline --graph --decorate main origin/main docs/archive-deepseek-be-results
git diff --stat main..docs/archive-deepseek-be-results
git diff main..docs/archive-deepseek-be-results -- research_pilot benchmarks tests_real
```

确认工作区干净、工具问题已审核解决且远端没有冲突后，可选择正常 PR（优先）或本地 fast-forward；以下 fast-forward 任一步失败就停止，不 force、不自动改成其它合并方式：

```powershell
git switch main
git merge --ff-only origin/main
git merge --ff-only docs/archive-deepseek-be-results
git push origin main
```

若 main 或远端演进导致不能 fast-forward，应重新审查并走正常 PR。当前仅准备本地归档提交，不承诺远端合并安全已经验证。

结论：ResearchPilot 的工程 MVP 和本次真实模型样例可以冻结，转入简历与面试；保留 Qwen 限制和 DeepSeek 未测范围。完整工具集的长期稳定性还有日期测试这一明确待决项，不需要继续调业务 Prompt 或新增收费实验。
