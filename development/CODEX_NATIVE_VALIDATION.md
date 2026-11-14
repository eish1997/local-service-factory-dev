# Codex 内置生成：本地候选验证与真实联调清单

本候选基于 main/3d8f7006cc82d157cbc9f3bf65f88b81408b9af3，未提交、未构建、未安装、未推送或发布。唯一进度台账仍是原工作区 development/CODEX_NATIVE_GENERATION_PLAN.md。本文件是验证索引和后续联调清单，不能替代该台账。

最新状态：N6 源码面板真实商务 KTV 一组（7张、7次调用）链路已通过，含实际自动文件交接与恢复；发现的尺寸问题已修复。详见文末 N6 源码真实联调节。正式图片质量批准和安装版联调仍未完成。

## N0—N5 初始历史证据及范围

以下 N0—N5 初始验证数据位于 `.runtime` 隔离目录，使用 Pillow 合成色块并标记模拟；该历史阶段真实调用为零。后续 N6 的七张真实工具图片另存 codex-native-n6，证据不可混用。

| 要求 | 证据 |
| --- | --- |
| 渠道与旧批次 | tests/test_native_tasks.py：旧数据缺渠道仍 API；同请求 ID 不得换渠道；native 的 plan/start/resume/retry/worker 拒绝 API 入口；组装和计划不读 API 配置 |
| 两种创建入口 | Agent/dashboard 冻结清单和快照一致；真实 Electron 表单经共享 IPC assemble，生成内置批次；API 表单仍创建 API 批次且没有任务 |
| 独立授权/调用上限 | 同一单元只能属于一个冻结 scope；范围低上限及两次单元上限同时生效；未知结果/失败/取消不退款；并发 claim 和 reserve 各只有一个执行许可 |
| 文件绑定 | instance/category/batch/group/unit/route/snapshot/prompt/claim/hash/source 明确绑定；未知文件不扫描，摘要不同和旧 claim 拒绝；同摘要回填幂等；注册后的文件缺失可用明确手动交接恢复，保留真实来源字段 |
| 原图与恢复 | 合成原图通过共享原图库归档，provider=codex_native，未审核；原图写入后收据写入前故障可在源文件删除后由暂存证据恢复；返回但无效的图片保留待核对 |
| 成品和队列 | 单张和完整 7 原图→5 成品链路，三拼源 caption 顺序断言；使用共享图版历史及未打包交付队列；重复恢复不新增历史、打包后不重新入队 |
| 包内当前版本 | 完整组导出 ZIP 五张，逐文件与当前成品相同；保留原图和版本 |
| 失败与迟到 | 原图成功但排版失败只重做本地处理；取消发生在渲染之后、发布之前时拒绝迟到成品；删除组、改变快照拒绝回填 |
| 文字和审核 | 商务 KTV 内置单元实际渲染保留本次电话、不打印场景标题；三拼使用冻结角色顺序；合成图不自动 approved |
| 实际 UI | 原工作区 .runtime/codex-native-validation/ui-acceptance/ui-report.json、ui-results-report.json；创建、稳定实例指令、原图/成品数量、同实例 CLI 回填后的真实卡片刷新、API 表单回归 |
| 手动降级入口 | ui-manual-r3-report.json：真实渲染器、IPC、磁盘处理；单元为 manual_saved，调用计数不增加。系统文件选择结果由测试注入，未宣称实际 Windows 文件选择器人工操作通过 |
| 现有安装 | native-discover 读取真实安装登记，1.4.17/1.4.18 均缺新接口；没有启动或改写它们；发现多个候选不自动选择资料根 |

截图 native-create-verified.png、native-instruction-verified.png、native-result-verified.png、native-manual-r3.png 位于上述 UI 证据目录。复制指令窗已实际查看截图并修正空白高度及初始滚动位置。

验证中发现并保留：首次 Electron 沙箱访问拒绝，结束该测试进程后经正常审批运行隔离验证；第一次 API 按钮文字断言早于异步表单完成，改为等待真实完成后通过；维护 Git 副本不带历史 prompts 文件，直接 audit 缺文件退出。维护候选审计脚本与生产根脚本文本相同（换行编码不同），只读挂载已有历史数据后 AUDIT_OK 10000；原公共 factory.py audit 同样通过。没有为审计重新组装生产批次。

整套 tests.test_factory_safety 按仓库约束未运行。没有 Authenticode/安装器检查，因为本目标不构建安装包。

## N6 真实联调前的必要输入

1. 用户明确业务、需要生成的原图数量或精确单元范围、本次手机号和文案；创建不视为生图授权。
2. 明确目标安装实例和资料目录。多实例先选择，不能自动使用开发根。当前旧安装缺接口，须另行授权带新接口的隔离安装候选；若需要构建由 N7 获得相应授权。
3. 说明本次是否允许实际安装，以及隔离 Windows 用户/虚拟机方案、数据备份和回退路径。不能复用之前发生隔离偏差的默认用户资料来试装。
4. 确认本会话真实存在内置工具，不读订阅令牌、不模拟登录 API、不改用收费 API。缺工具或额度就保留任务。

## N6 验证步骤与通过证据

- 用该安装自身 Python 和 factory.py 获取 native-instance，记录版本/引擎/数据根/资产根/安装标志；确认 panel 与 Agent 指向同一 instance_id。
- 从面板创建一批；另从聊天用本次参数创建同类批次。确认双方可见、号码及冻结提示词一致，没有 API worker 或密钥探测。
- native-plan 展示原图数、最终成品数、范围上限、已有素材与未知/耗尽单元。将用户更低上限冻结到 scope；领取单元、持久 reserve 后才调用工具一次。
- 保存真实工具返回 ID（有才记录）、明确文件与该单元映射。证明本地输出来自该工具返回，而非猜缓存最新文件。若仅有图片展示、无可定位文件，记录自动交接未通过；只以 manual_saved 降级导入，不宣传自动接入成功。
- 登记来源、回填、排版后在实际安装面板查看卡片；比对原图/成品/历史/队列。三拼核对源顺序和 caption；封面无详情标题；商务 KTV 无场景标题。
- 人工检查真实图片类别、场景、电话及服务词；门头招牌号码与本次号码相同且清晰。保存完成不能当 approved。
- 在受控范围模拟关闭面板/聊天、未知返回和本地排版中断；恢复没有第二次工具调用，原图及既有历史保持。检查手动保存的真实系统文件选择流程。
- 导出交付包核对当前版本，保存校验和及截图；未完成部分仍未完成，不用合成样本冒充通过。

## N7 另行授权后的发布清单

- 先关闭 N6 待验项，或在发布说明准确标注未验证范围；不得声称所有真实链路通过。
- 核对源码差异、依赖、未提交修改和安全扫描；按授权提交推送、版本元数据、必要构建和签名检查。
- 在明确隔离实例检查新安装和旧版升级：旧任务默认 API，许可和计数、原图、历史和资料路径不变；新接口存在且实例定位准确。
- 再执行授权范围内的软件发布；规则仅有内容变化时独立发布。保留旧仓过渡和回退链路，不自动删除旧仓。


补充完成审查：安装启动代码新增原子实例描述，真实安装入口未显式绑定 FACTORY_DATA_HOME 时拒绝执行；新描述发现/身份一致性单测通过，既有离线暂存引擎的两项初始化/升级保留测试通过。此为源码函数与隔离暂存验证，不是新安装包联调。新增排版期间删除批次不会重建状态文件、已完成工作原图缺失时从暂存证据免费恢复、两个公共 CLI 进程领取竞争、用户收窄 groups 时不回填其他已授权组等测试。全部仍为本地合成或只读数据。


最终验收：24 项新增 NativeTasks 测试通过（52.458 秒，原工作区 .runtime/codex-native-validation/native-tests-completion.log）。实际 UI 四份报告（ui-report、ui-results-report、ui-manual-r3-report、ui-visual-report）均无 errors；主界面、新建表单、指令窗和手动导入截图均实际核对。隐藏窗口曾返回空帧或旧帧，保留失败证据后通过关闭后台节流、invalidate 和明确捕获选项重绘验证，不凭“PNG 有效”推断当前界面。三拼缺素材准确显示已保存 2/3，不误报已完成。

源差异、逐文件摘要与完成矩阵分别保存在原工作区 .runtime/codex-native-validation/N0-N5-review.patch、candidate-files.json 和 completion-audit.json。Git HEAD 未改变，没有提交推送。源码候选可供审阅，实际工具与安装体验尚未完成 N6。


## P1 审核修复验收（2026-11-15）

修复两处更新入口遗漏 codex_native：dashboard/main.js 接入 dashboard/tasks.js 的独立活动检测，保留原 API job/进程判断。tools/task_native.py 为锁外排版与恢复增加管理锁内准入及进程写入锁，短回填继续全程持有管理锁。具体状态定义见 CODEX_NATIVE_CONTRACT.md 的“安装更新互斥”。

本次源码/测试修改：dashboard/main.js、dashboard/tasks.js、tools/task_native.py、tests/test_native_tasks.py、dashboard/tests/updates.test.js；新增 dashboard/tests/update-fixture.js，仅供测试复用真实更新服务与桩安装器。契约和本文同步更新。

| 验收项 | 当前证据 |
| --- | --- |
| 原生调用活动拒绝安装，转人工核对后允许 | Python public dispatch reserve/outcome → 独立 Node 更新服务 before-quit；API job 数仍为 0，原生活动被识别；额度保持 1 |
| 回填与更新竞争 | 实际 ingest 不可变原图发布阶段尝试更新，管理锁阻止安装；回填完成后允许 |
| 排版与更新竞争 | 实际 materialize 锁外渲染时，API job 为 0、管理锁已释放，但活进程写入锁阻止安装；完成后允许 |
| 取消、删除、异常与退出 | 排版期间取消仍受写入锁保护，退出后允许；模拟批次记录删除时独立写入锁仍有效；真实子进程 os._exit 留下锁，已退出进程不永久阻塞 |
| 更新先胜出 | 两次检查之间新启动的原生调用被锁内复查识别；安装标记先落盘后，authorize/claim/reserve/register/ingest/outcome/cancel/materialize/recover 均拒绝且状态字节不变；排版准入竞争不进入 renderer |
| 不永久阻塞 | pending/claimed/uncertain/failed/raw_saved/completed/cancelled、无活进程的遗留 rendering 不单凭状态阻止安装；awaiting_result 必须按实际证据结束或取消，不能超时退款 |
| API 保持 | 原更新器活动 API 测试与 monitor 6 项通过；共享幂等/篡改、非连续选择/继续/预算 2 项通过 |

本次通过：原生模块 29 项（110.624 秒）＋随后新增崩溃遗留锁 1 项（3.227 秒），更新服务 14 项，monitor 6 项，共享 API 指定回归 2 项（12.832 秒）。四个相关 JS 文件语法检查通过。证据在原工作区 .runtime/codex-native-validation/p1-native-tests.log、p1-native-crash-test.log、p1-updates-tests.log、p1-monitor-tests.log、p1-api-regression.log。

验证过程的失败已修正：Node --test 在沙箱内 spawn EPERM，当前 Node 也不支持 --test-isolation=none，改为直接 node 测试文件运行相同 node:test 用例；新断言最初因保护函数尚不存在失败；Python 新方法最初放在 __main__ 后导致未发现，后又修正了测试中局部导入函数的 patch 位置。没有删除断言或放宽安装拒绝条件。更新器安装、下载、签名/文件内容均使用隔离夹具，不执行安装器、不访问网络；复用真实 createService/事件处理和 Python 回填/排版。未新增 UI 布局，先前 UI 截图仅为前一阶段证据，不冒充本次安装联调。

N0—N5 本地开发与审核修复完成；N6 真实生图、真实工具文件交接、实际安装版更新/升级互斥联调仍待验收，不能宣称全部完成。未运行 dry-run 或整套 tests.test_factory_safety；未修改生产数据、真实生图、构建安装包、提交推送或发布。


## N6 源码面板真实联调（2026-11-15，安装项暂缓）

用户选择“先用源码面板测试，安装联调暂缓”；已授权商务 KTV 一组、任意测试手机号、其余默认。此次使用 13800000000，面板实际创建 1 组 7 原图/7 成品，默认本地服务词来自公共 overlay-text：商务宴请、派对聚会。店名听光等来自冻结默认模板，不追加历史号码或额外业务事实。范围 g0001_u01—g0001_u07，总上限 14，实际仅 7 次内置 image_gen 调用，每单元 1 次；没有收费 API 调用、未知重试或按质量追加生成。

资料根为原工作区 .runtime/codex-native-n6/profile/workspace；instance_id=c9169dcb124f3b28d420febc5420852d4c896e2d449808d5c885b4accce6a805。批次 batch_13800000000_20261114T184411_5716bc6297（批次标识含 UTC 时间，本地面板显示 2026/11/15）。面板复制指令、Agent 公共 native-instance、重启面板 IPC 的 ID 三者一致；execution_kind=development，不能冒充正式安装。

实际链路：Electron 真实表单/renderer/IPC 创建 → native-plan/authorize/claim/reserve 持久预留 → 七次真实内置工具 → 各次 output_hint 明确的唯一 PNG 文件路径 → native-register/ingest/materialize → 七张卡片载入。没有扫描缓存或按最新文件选择，没有人工保存/选择导入，没有生成器桩或合成图片；没有编造 tool_result_id。此次自动文件交接实际通过（当前会话证据，不保证所有宿主都提供路径）。

第一张真实回填暴露尺寸兼容缺陷：941×1672 被共享 API 原图保存拒绝为“预期1024×1536”。保留已返回文件和调用记录；tools/task_native.py 增加仅原生使用的原始字节归档/工作副本归一化，API 校验不放宽。随后无需重生即完成该图和其余图片。新增 tests/test_native_tasks.py 非 API 尺寸用例覆盖 941×1672、1086×1448，原图字节完全保留、七图流程可排版、API 仍拒绝同样尺寸；全部 31 项原生测试通过（88.491 秒）。候选摘要因修复已更新，旧 P1 审核摘要仅对应修复前版本。

两次实际 native-recover：调用数仍为7，七张成品 SHA256 与全部 image-history 返回逐项不变，任务全 completed，pending/blocked 均为0。真实面板重启后7张 naturalWidth=1024、naturalHeight=1536；选中1组后生成按钮禁用、交付按钮可用。未实际打包或清除交付队列。源码验证入口只在独立 profile 内运行，测试壳模式关闭，未把真实导入标为 synthetic；自动规则联网调度由外部测试入口抑制，未改变产品源代码。

实际像素检查：7张原图和7张本地成品均已查看，号码及默认服务词清晰，商务KTV不叠场景标题，封面招牌号码可读。此为源码链路和文字检查通过；不宣称正式质量审核通过。电视歌词字形、局部手指遮挡、组内人物/布局连续性及照片感仍需评判，全部保留未审核状态；22项质量检查记录保留 not_fully_verified，不编造视觉模型版本/正式评分，也不因这些问题追加调用。

证据（原工作区）：.runtime/codex-native-n6/evidence/ 中每单元 prompt/request/reservation/tool-output/tool-binding、initial-plan、latest-state、real-recovery-verification、size-compatibility-finding、visual-review、native-tests-after-size-fix.log；profile/workspace/ui-report.json 为创建证据，real-ui-results.json 为最终真实面板证据，real-seven-result.png 为已实际查看截图。UI 自动化首次在批次异步加载完成前点击、随后错误等待已完成组的禁用按钮弹窗，两份失败报告保留；修正为等待实际批次并核对选中完整组后的完成态，没有修改产品行为来通过测试。

当前结论：N0—N5 本地开发与修复完成；N6 的源码真实生成→自动回填→排版→面板→恢复/历史链路通过。N6 安装版同实例与真实更新互斥按用户选择暂缓，严格图片质量批准仍未通过；N7 构建/安装/提交推送/发布均未执行。本轮没有修改正式安装或生产任务，也没有运行禁用测试命令。


## N6 隔离安装与真实更新验收（2026-11-15）

用户后续明确允许隔离本地提交、构建和安装测试，仍不推送、不发布。复用已有7张真实图片，本轮真实生图0次。隔离副本 .runtime/codex-native-n6/source 无远端；冻结候选提交6e6ec14、1.4.20隔离配置b422040、1.4.21版本提交1efb4f4。n6-runtime/n6-config、独立appId/GUID/产品名/固定资料目录和本机feed仅在隔离副本，不进入产品候选。

- 1.4.20真实NSIS /currentuser安装成功。包内Python、面板与native-instance.json均指向同一测试资料根；真实面板显示7张已生成图片。1.4.21经真实electron-updater下载、测试Ed25519签名与SHA256验证，保留安装器及previous-app原始ASAR备份。旧blockmap缺失，实际走全量下载回退。
- 真实包内before-quit处理器在awaiting_result、回填admin锁、排版native写租约期间均不安装。为可控观察前三项通过事件触发，工作阶段通过屏障暂挂真实函数；没有伪装成生成中的真实工具请求。独立合成夹具批次batch_13800000000_20261114T191920_9c5e6e2870只预留1次，实际工具调用0，来源synthetic_test，不能与原7次真实调用合并统计。
- 夹具完成后实际app.quit触发真实NSIS 1.4.20→1.4.21，自动重启后install-result expected/actual均1.4.21、recovered=false、安装标记已清理。实际安装标记出现时claim/register/ingest/materialize/recover全部拒绝新写入，见install-first-race.json。
- 升级后公共native-recover成功；原任务完整状态、7次计数、7个原始返回字节/工作原图摘要、7个成品摘要和7份完整历史均保持。安装版截图与面板IPC核对7图/同实例通过。正式<local-path> Files/road-rescue-dashboard 1.4.19的exe/app.asar/config摘要保持；未操作正式用户资料。
- 复跑更新14项、传输5项、bootstrap2项通过；两版独立stage各3036个运行时文件摘要一致、9项目公共入口通过。产品逻辑未新增变更，复用31项原生及既有API回归证据，整套test_factory_safety按约束未运行。安装包Authenticode为NotSigned。

证据：原工作区 .runtime/codex-native-n6/installed-evidence 的build-provenance对应两版artifacts、post-upgrade-verification.json、update-backup-verification.json、install-first-race.json、各probe/ui回执及日志；profile/workspace/.runtime/n6-control/installed-1-4-20.png和installed-1-4-21.png均实际查看。七图源码真实证据继续保留在evidence。安装前资料备份和程序备份保留；隔离应用与本机feed已停止，没有在途生成/构建/安装。

结论：N0—N5本地开发与修复完成；N6真实生成链路、隔离安装同实例和真实NSIS更新互斥已通过。严格图片质量批准仍待验，因此不称全部验收完成。公开下载链路、正式身份安装升级、全新Windows/机器级安装均不在本轮证明范围；临时测试签名与本机feed不冒充公开发行。N7正式发布未执行，隔离候选不可直接发布。下一步为图片质量验收和正式发布候选审阅；推送/发布仍需明确授权。


## 正式发布候选 1.4.22（2026-11-15）

用户明确“图片验收通过，同意授权”，本组图片记为用户验收通过；不伪造自动视觉评分，也不追加生图。N6功能链路与用户图片验收闭合。授权正式候选审阅、源码推送、构建和软件发布；规则无内容变化不重复发布。

正式候选从维护副本生成，保留原应用身份local.roadrescue.dashboard、原产品名和release-2026-09公钥；不包含隔离n6-runtime/n6-config、本机feed、测试公钥或固定个人资料路径。正式版本1.4.22避开本地隔离版本。复用同一产品代码的原生31项、API定向回归、真实七图和隔离NSIS证据；正式打包另核对来源、独立运行与公开资源。正式用户级/机器级整机迁移、全新Windows未重新验证，不将隔离身份测试称为正式身份覆盖升级。
