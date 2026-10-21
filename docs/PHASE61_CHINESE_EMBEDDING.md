# Phase 6.1：官方中文 Embedding 与独立索引复测

日期：2026-10-20。使用原封不动的 Phase 6 数据、问题、金标及 0.5 阈值，对照英文模型、中文无指令、中文有指令。没有训练模型、修改金标、引入第二套数据库或调用聊天模型。

## 官方身份与加载

- 模型：`BAAI/bge-small-zh-v1.5`，官方仓库 revision **`7999e1d3359715c523056ef9478215996d62a620`**，模型卡 MIT。
- 该 commit 的官方文件列表没有 ONNX；因此没有采用 FastEmbed 注册的第三方中文 ONNX 转换，而是加载官方 `model.safetensors`。关闭 remote custom code，不加载 pickle 权重。
- 权重 SHA256：**`354763b9b1357bc9c44f62c6be2276321081ed2567773608c0d0785b61d5a026`**，95,827,648 bytes。官方六个模型/tokenizer/config 文件合计 96,377,581 bytes。
- 下载时，safetensors SHA256 对照官方 LFS 元数据，小文件按 Git blob 规则计算 SHA1 对照固定 commit 的 blob ID；核验记录保留于 `benchmarks/zh_retrieval_v1/results/official-zh-model-audit.json`。
- `research_pilot/embedding-zh.lock.json` 固定六份文件 SHA256；正常加载全部校验且仅用本地路径。旧英文模型、原模型清单和历史结果均保留。
- PyTorch **2.10.0+cpu**、Transformers **5.20.2**、safetensors **0.8.0**，其余旧向量依赖按原锁文件约束保留。新增 `requirements-chinese.lock`，CPU wheel 来源为 PyTorch 官方索引。
- CPU 两线程、float32、eval/inference mode；取 CLS 表示并 L2 归一化，输出 **512 维**。未使用 GPU 运行 Embedding。

依据：[官方模型卡与指令](https://huggingface.co/BAAI/bge-small-zh-v1.5)、[固定 commit 文件](https://huggingface.co/BAAI/bge-small-zh-v1.5/tree/7999e1d3359715c523056ef9478215996d62a620)。模型身份与下载指纹是本轮实际核验结果，不是仅凭名称声明。

## 查询、文档与索引隔离

保持默认 256-token 切片、32-token 重叠、Top-K=5、余弦距离 `<=>`、score=1-distance、阈值 0.5。所有 19 篇金标文档在两种中文配置中均为 19 个片段，没有因新 tokenizer 改变金标对应关系。

两种查询配置只有以下差别：无前缀；或仅给查询加 `为这个句子生成表示以用于检索相关文章：`。文档侧始终不加指令。两次索引的文档向量摘要完全一致：

```text
40e12240fc95acb1988a457e03a6e4b487bca40f2c8c448bc70e737be1f7d23a
```

旧表 `researchpilot_vector_chunks` 仍为 vector(384)。新表 `researchpilot_vector_chunks_512` 为 vector(512)，有独立 `researchpilot_vector_collections_512`，并记录官方文件指纹；模型/维度/指纹不一致直接拒绝。真实数据库测试验证向旧表插入 512 维会失败且旧数据不受影响。

结果限定同一模型物理表和 collection，按距离及稳定次序排序，再应用原阈值；不会通过标题、合成标识或金标过滤干扰资料。实际测试确认另一个集合即使保存相同正文也不能泄漏。去重仍按 locator + excerpt，来源元数据和完整片段保留。

已保留可检查索引：

| 配置 | 表 / collection | 正式文档/分片 |
|---|---|---:|
| 英文重测 | 384 表 / `phase61-en-v1` | 19/19 |
| 中文无指令最终 | 512 表 / `phase61-zh-noinstruction-v3` | 19/19 |
| 中文有指令 | 512 表 / `phase61-zh-instruction-v1` | 19/19 |

其他尝试的 v1/v2 collection 也保留并注明原因，没有删除旧索引。探针在指标查询之后导入、检查后仅删除其自己的临时记录，正式索引中没有残留探针。详见 `phase61-retained-indexes.json`。

## 新旧并排指标

数据 SHA256 始终为 `6b7975eb701d461fd712cef3acc0ab749d42498eca65fb75f67250be46d5475c`。16 有答案题进入文档级宏平均 Recall 和 MRR；4 个无答案题单独检查，4 题需要多文档。小集由开发助手标注、可人工检查，未经独立盲评。

| 指标 | 英文 384D | 官方中文无指令 512D | 官方中文有指令 512D |
|---|---:|---:|---:|
| Recall@3 | 0.53125 | **1.0** | **1.0** |
| Recall@5 | 0.53125 | **1.0** | **1.0** |
| MRR@5 | 0.51041667 | **0.96875** | **0.95833333** |
| 多文档全部金标覆盖@5 | 0/4 | **4/4** | **4/4** |
| 无答案零候选 | 0/4 | 1/4 | 1/4 |
| 无答案非空候选 | 4/4 | 3/4 | 3/4 |
| 全 20 题 top-5 中不相关候选数 | 90 | 59 | 60 |
| 原始文本 [UNK] token 比例 | 68.0146% | 1.7136% | 1.7136% |

无指令中文是本小集较好的默认候选，因此中文配置示例明确采用 false；不是宣称官方指令一般无效。未开展其他前缀/阈值搜索，没有利用此小集校准拒答阈值后再称独立验收。

[UNK] 比例按原始19正文+20问题计算，不含特殊 token 或新增查询指令，便于比较两个 tokenizer；不是指令模式完整推理输入的统计。

原始每题排序、分数、S#、真实 locator/doc_id/chunk_id/source_ref、配置、norm、包版本与耗时均保留：

- `results/phase61-en.json`
- `results/phase61-zh-noinstruction-final.json`
- `results/phase61-zh-instruction.json`

路径均相对于 `benchmarks/zh_retrieval_v1/`。原 Phase 6 的 baseline/final JSON 不变。

## 尚未成功的具体场景

- **Q01**：金标 D01（断电后检查点保留进度）仍没有排第一。无指令时 D02/D01 位于第 1/2，有指令时 D02/D17/D01 位于第 1/2/3。没有将 D02 添加到金标提高 MRR。
- **Q17 无答案价格问题**：无指令返回 D10（分片）score=0.5235；有指令仍返回 D10 score=0.5343。文档没有价格，不能据此回答收费金额。
- **Q18 无答案证书问题**：两种配置均返回 D12（任务状态），分数约 0.5354 / 0.5268；不能支持证书签发与轮换结论。
- **Q19 无答案实测性能问题**：无指令返回 D07/D13/D17/D12（约 0.5500/0.5490/0.5237/0.5102）；有指令返回 D07/D13/D17。这些相关技术定义不含一亿向量 QPS/P99 数据，错误证据暴露风险仍在。
- **Q20 天文问题**：两种中文配置均零候选。这是一个容易的不相关无答案样例，不能代表近主题拒答能力。

零候选不是唯一成功标准。返回相关主题候选是允许的，但必须明确未验证是否足以回答；真实聊天模型是否据此拒绝编造数字，仍要 Phase 7 实测。

## 候选数量与语义充分性的最小修复

原 assess 用来源数量输出 sufficient。现在数量只决定是否继续收集候选，不宣称完成语义验证。达到数量门槛的 trace 为 `assess:candidates_collected`；任务与报告 API 持久化返回 `evidence_status=unverified`，无候选为 no_evidence，尚未评估为 unassessed。旧检查点缺字段时保持 unassessed。

Mock 报告明确说明只是候选资料、尚未验证是否足以回答。任务 completed 仍只代表生成和引用语法处理完成。Q19 的真实图现在同时呈现 completed + unverified，而非把候选数量当答案可支持性。没有拿 benchmark 金标喂给生产工作流，也没有添加未经验证的语义规则或 LLM。消费者仍必须尊重该字段；本轮没有实现事实蕴含校验或证明最终答案正确。

## 性能与资源成本

同一 Windows 主机、CPU 两线程、每题 query 已在范数/排序诊断中预热后，计时真实 `search`（包括编码和本地 PgVector 往返）。每配置只有 20 题、单次测量；不是并发压测，不能外推 QPS。

| 本次测量 | 英文 ONNX | 中文无指令 safetensors | 中文有指令 safetensors |
|---|---:|---:|---:|
| 模型初始化（含框架导入） | 0.883s | 7.114s | 7.136s |
| 19 文档编码/入库 | 0.502s | 0.481s | 0.473s |
| 预热 search 中位数 | 9.23ms | 10.29ms | 14.19ms |
| 预热 search P95 | 10.38ms | 14.86ms | 20.20ms |
| 评测进程峰值 working set | 442.8MiB | 683.9MiB | 682.7MiB |

working set 由 Windows 本进程 API 获取，包括框架和恢复诊断创建的第二个模型实例，不是单份权重 RAM。中文权重约 91.4MiB，六个模型文件约 91.9MiB；CPU PyTorch wheel 下载约 113.7MB，已安装 torch 目录约 443.2MiB（未包含全部依赖）。CPU-only，没有为 Embedding 安装 CUDA wheel 或占用 GPU 推理。

## 自动化、失败与交付范围

最终 **39 passed，0 failed，0 skipped**（原 33 保留 + 6 新测试）；Ruff、pip check 通过。真实验证了模型、查询/文档前缀边界、归一化、物理维度拒写、集合隔离、指纹拒绝、候选非充分状态和 512D HTTP/图闭环。双模型清单打入实际 wheel。

第一次新评测在入库后、指标前因 pgvector.Vector 不能直接 np.asarray 转换而停止；已按真实驱动返回类型调用 to_numpy，失败日志/索引保留。首次完整无指令记录的尾标记检查只看第一片，中文 tokenizer 实际把探针切成两片；修复诊断为检查全部返回片段，最终两片完整、尾标记保留。没有把正常 token 切片当成模型截断错误。另有 wheel 的外部 pip cache 权限错误，以 --no-cache-dir 重试成功，未修改系统权限。

主要修改：vector.py、两模型锁清单、config/runtime/workflow/store/schema/api/model、benchmark.py、下载/评测脚本、requirements-chinese.lock、pyproject.toml、test_phase61_chinese.py、Compose 中文叠加与文档。没有重写图框架。新增 Docker 配置只做 config 校验，未重建/部署既有容器。

## 复现（显式选择中文，保留兼容默认）

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-chinese.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e '.[dev,chinese]'
.\.venv\Scripts\python.exe scripts/download_embedding.py --model BAAI/bge-small-zh-v1.5
.\.venv\Scripts\python.exe scripts/evaluate_zh_retrieval.py --model BAAI/bge-small-zh-v1.5 --label rerun-plain --collection new-zh-plain --keep-index --output data/phase61/rerun-plain.json
.\.venv\Scripts\python.exe scripts/evaluate_zh_retrieval.py --model BAAI/bge-small-zh-v1.5 --query-instruction --label rerun-instruction --collection new-zh-instruction --keep-index --output data/phase61/rerun-instruction.json
.\.venv\Scripts\python.exe -m pytest -q
```

须先启动现有专用 PostgreSQL。已有非空 collection/结果文件拒绝覆盖；重新测量用新名字。中文应用设置 `RESEARCH_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5`、`RESEARCH_EMBEDDING_QUERY_INSTRUCTION=false` 并重新导入资料。旧默认仍为英文，防止无提示更改既有索引；可用 `compose.zh.yaml` 叠加显式选择中文。只读 Phase 7 调查与资源建议见 `PHASE7_ENVIRONMENT_SURVEY.md`，当前等待用户确认后才执行。
