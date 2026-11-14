# Codex 内置任务接口（开发候选，协议 1）

权威进度台账仍在原工作区 `development/CODEX_NATIVE_GENERATION_PLAN.md`，本文件仅定义接口。未发布；现有 1.4.17/1.4.18 安装引擎不支持这些命令。

`python factory.py tasks OPERATION` 从标准输入读取 JSON。所有接口禁止自动调用任何生成器。只有 Agent 获得明确的本次生产指令后，才可领取、预留并调用当前会话真实可用的内置工具。创建批次不是执行授权。没有工具或没有可定位结果时保留任务，不回退 API。

## 共享组装和渠道

`assemble` 增加 `generation_route: "api" | "codex_native"`。缺省为 api；渠道纳入组装幂等校验，批次不能改渠道。原 category/count/phone/seed/services/source 等参数沿用共享实现，不从历史推断号码。

API plan/start/resume/retry、worker 和自动恢复入口拒绝内置批次。内置计划不读取 API 配置，不探测模型或密钥。

## 已实现公共入口

- `native-instance {}`：只读返回当前实际执行引擎、数据根、资产根、版本、安装标志和 instance_id。该命令只说明当前进程所绑定实例，不代表自动发现了正式安装；Agent 不得拿开发引擎冒充安装版。实例 ID 绑定规范化数据路径；迁移数据路径需要重新明确绑定。
- `native-discover {}`：只读查询 Windows 当前用户/机器卸载登记，或检查显式 install_roots（最多十个绝对路径）和 data_roots；返回安装引擎/版本/解释器及接口存在性，新安装启动会原子保存 .runtime/native-instance.json，发现接口只读匹配该描述与当前引擎；也可读取本用户标准资料根的该单个描述文件，不扫描任务或图片。不选择实例、不猜资料目录、不启动安装。选中后必须通过该安装自身解释器和 factory.py 验证 native-instance，缺接口的旧版明确不支持。调用安装解释器时必须显式设置已核对的 FACTORY_DATA_HOME；未绑定直接拒绝，不能在 engine 目录创建任务。开发实例 execution_kind=development，不冒充正式安装。
- `native-plan`：category、batch、instance_id，及 groups/unit_ids；校验冻结快照、清单、号码和范围，返回逐单元冻结提示词、原图数、成品图数、剩余调用上限和 plan_sha256。没有授权副作用。delivery_count 是所选单元涉及的成品位置数；只选三拼的一份素材时不会扩大生成范围，其他冻结素材未齐则仅保存原图，不宣称该成品完成。
- `native-authorize`：计划参数加 scope、plan_sha256、max_tool_calls、authorization=`execute_native_selected_units`。保存独立范围，scope 与单元不可重绑；一个单元只能属于一个范围，避免换名字重置用户更低的上限。
- `native-claim`：category/batch/instance_id/scope/unit，返回领取 claim 和单元冻结提示词。已领取、未知结果、待回填不能重新领取，无租约自动过期。
- `native-reserve`：同上加 claim。调用工具前必须成功落盘。仅 `new_reservation=true` 允许随后执行一次工具调用；重复请求返回 false，须查询并恢复，不能再次调用。总计和每单元计数保存在同一原子状态文件。
- `native-outcome`：同上加 outcome=`uncertain` 或 `confirmed_failure` 和非空 evidence。仅明确无返回图片的失败才允许剩余额度内重试；超时本身不是失败证据。禁止写凭据。已有结果的回填不会走该失败接口。
- `native-status`：category/batch/instance_id，返回持久状态；查询不重置计数。
- `native-cancel`：同上加 authorization=`cancel_native_batch`；保留原图及计数，拒绝迟到回填和新调用。

范围参数示例（值须从实际实例和计划获取，不能直接复制占位值执行）：

```json
{"category":"road_rescue","batch":"BATCH_ID","instance_id":"INSTANCE_ID","groups":[1],"unit_ids":["g0001_u01"],"scope":"USER_SCOPE_ID","max_tool_calls":2,"plan_sha256":"PLAN_SHA","authorization":"execute_native_selected_units"}
```

计数表示工具调用次数，不是 API POST、平台内部请求或收费账单。每单元最多两次且受冻结范围总上限约束。取消、断线、重启、未知结果不退额度。成功保存与质量批准分开。

## 原图回填和本地恢复接口

`native-register`：传递 category/batch/instance_id/scope/unit/claim，加 file（明确绝对路径）、sha256、source_kind（tool_return/manual_saved/synthetic_test）及可选 tool_result_id。有真实 ID 才填写，不编造。先保存返回绑定，再验证文件；文件失败保留为待核对，禁止改成失败重生。同摘要的另一个明确文件可以用于恢复，无需按最新文件猜测。已登记 tool_return 的文件失效后，手动恢复保留原 source_kind/tool_result_id/摘要，额外传 handoff=manual_saved，记录 manual_recovery；不能以另一个来源覆盖原证据。

`native-ingest`：同一绑定参数，无新授权/预算。原图先写临时区并保留 prepared 收据，再不可变发布工作原图、写收据和入共享原图库。恢复可使用暂存证据，不需要再次调用工具。receipt.provider=codex_native，不伪造 API key/model/POST 收据。synthetic_test 或显式 synthetic=true 标记模拟素材不可自动复用；所有新图未审核。

`native-materialize`：category/batch/instance_id/scope，可加 groups/unit_ids（或单 unit）收窄原范围，仅已有原图的本地处理。复用共享冻结渲染器、三拼源顺序、当前版本/历史及交付队列。排版失败保留原图；发布前再检查删除、取消、当前版本变化，拒绝迟到覆盖。已完成且已打包的组重复恢复不重新进入队列。

`native-recover`：相同参数，只恢复当前明确选中范围已登记返回结果及本地处理，不调用生成器。未知且未登记来源的单元继续保留未知状态。

面板选择文件导入仅针对已预留且待回填单元，标记 manual_saved；它是降级路径，不是自动取得工具图片的验证证据。API 单图重组/补生成入口同样拒绝内置批次，防止隐式换渠道；本地排版/历史选择继续共享。

单元流程 pending → claimed → awaiting_result → raw_saved → rendering → completed；失败为 failed，结果未知或返回待保存为 uncertain，取消为 cancelled。完整本地链路已用合成数据验证；真实内置输出路径、视觉审核和安装版联调仍待 N6。


## 安装更新互斥（P1 审核修复，2026-11-15）

两处更新服务入口均将原生活动加入原有 API 活动判断；不把原生记录伪装成 API job。

- 未取消批次的 `awaiting_result` 阻止安装：这是已经预留且尚未登记结果的工具调用。不能按时间推断结束或退还调用额度；中断后应按实际证据登记 `uncertain`，或明确取消。
- `pending`、`claimed` 尚未开始工具调用；`uncertain`（含返回文件待人工恢复）、`failed`、`raw_saved`（等待本地排版）、`completed`、`cancelled` 不单凭状态阻止安装。
- 回填/登记等短写入完整持有 `.runtime/task-admin.lock`；更新器获取同一锁后再次检查活动，之后才写 `installing.json`。原生写入口在锁内重新检查安装标记，安装先胜出则拒绝写入。
- 排版和恢复在管理锁内检查安装标记并建立 `.runtime/native-writes/<随机ID>.lock`，随后释放管理锁做长工作，直到所有操作完成或抛错才释放进程锁。进程仍存活时，即使批次被取消/删除，更新仍被阻止。更新先获得锁则不能建立新的写入保护或开始排版。恢复包含回填和排版的整个阶段。
- `rendering` 的持久文本不是永久活动证据；检查上述活进程写入锁，兼容原 `native-render.lock`。进程已退出的遗留锁和遗留 rendering 状态不阻塞安装，也不重置原图/调用记录；需要恢复时仍走原有公共流程。无法读取或损坏的活动记录保守拒绝安装，须先诊断，不能据此宣布空闲。

这些检查约束本应用的自动更新入口；不能保证外部用户手动启动安装器时的进程行为。真实安装版自动更新联调仍属于 N6。


### 真实内置返回尺寸（2026-11-15 源码联调修复）

实际 image_gen 返回 941×1672 等尺寸，不能沿用 API 必须 1024×1536 的响应校验。native-ingest 使用独立原生适配：先核验来源/摘要/解码/64MB 与 4000 万像素上限，要求至少 512×512 且宽高比 0.5—1.0；原始返回字节不可变归档，保留真实 source_returned_size、source_sha256。共享渲染器的工作 PNG 采用已有 Lanczos cover-crop 到 1024×1536，封面靠上、详情居中，并记录 normalization_mode/anchor；不是伪称工具原生返回固定尺寸。API save_task_raw 尺寸门槛不变。异常尺寸保留已登记来源和已占调用，不重新生图。真实原图与适配后的成品均须视觉核对；不把裁切后的文件当原始工具证据。
