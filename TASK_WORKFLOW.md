# Agent 与看板统一任务入口

适用：今后新建的内容组和批量任务。用户要求“组装”“生成”“组装并生成”“继续”时，优先使用以下公共入口。看板只调用同一入口，不另建组装和生成规则。旧任务根据原任务类型继续原恢复流程。

所有普通操作读取标准输入中的 JSON，返回 `{ "ok": true, "data": ... }`；失败返回 `ok:false` 和具体原因。源标记仅用于记录，不改变逻辑。不要通过底层模块绕过任务授权或预算。

## 组装与查看（不调用生图）

创建新批次必须显式传入 count 和 phone（有效 11 位手机号），不能从历史业务配置自动补齐。看板手机号输入默认空白，点击组装即确认本批次输入；Agent 必须使用用户指定给本批次的号码。批次 ID 含手机号，显示名称为“手机号 · N 组”；号码同时冻结进提示词与 snapshot.batch_contact。旧批次不改名或迁移，界面可从其保存的 phone 字段显示号码。

- `python factory.py tasks projects`：输入 `{}`，读取八个业务、组结构与缺少电话等阻塞原因。
- `python factory.py tasks assemble`：输入 `{"category":"road_rescue","count":100,"phone":"用户指定给本批次的11位手机号","seed":1401,"source":"agent","request_id":"本次唯一标识"}`。count 为完整组数，范围 1–100；seed 可省略，由系统随机生成并保存。标识只允许英文字母、数字、下划线和连字符。
- `python factory.py tasks batches`：输入 `{"category":"road_rescue"}`。
- `python factory.py tasks view`：输入 `{"category":"road_rescue","batch":"返回的批次ID","offset":0,"limit":20,"include_prompts":true}`。offset 从 0 开始，最多一次读 100 组；列表可设置 include_prompts:false。
- `python factory.py tasks legacy-group`：输入业务与正整数 group；只读已登记来源，不补写历史信息。

批次由 batch.json、snapshot.json、manifest.json、groups/ 组成。组装时固化当前目录和业务配置，使用整组纯构建器；不改活动生产清单，不消耗正式组号。Agent 与看板同参数和种子的提示词及结构应相同，随机图片像素不保证一致。

## 当前新任务模型（2026-09-30）

用户确认共享新任务默认采用 tinysnow / gpt-image-2-4k，medium，请求2560x3840。Agent与看板的tasks plan/start使用同一配置，并冻结raw_contract。沿用既有双尺寸方案：只接受2336x3520或2352x3520响应，保存原始字节和尺寸证据，转换为1024x1536工作图，现有成品尺寸不变；不宣称返回源图为原生3840像素。旧任务模型与许可不改写，配置变化时原任务继续会明确阻止，须由Agent核对原冻结配置，不得重建预算。旧category命令仍按原显式profile规则运行，不能直接继承新的共享默认值。

密钥弹窗显示渠道tinysnow、已保存数量和每行保存状态；替换输入留空保留该槽位。状态栏并发位于请求与最后更新之间。顶部任务记录中的模型为历史任务实际模型，非当前默认模型。

共享计划的 max_workers 等于有效去重槽位数，不设十路上限；实际派发还受待生成数、余额隔离和跨任务槽位锁约束。共享 worker 每个生成单元最多两次总请求，任务总预算为本次计划待生成数的两倍；普通失败不会因全局“最多两次重试”说明获得第三次请求。续接与 retry 都受原剩余次数和预算约束，不能保证每种失败可再次调用 API。连续三次 API 异常触发停止并保存结果，已发出的请求仍需收尾。

## 生成与继续

先调用 `python factory.py tasks plan`，输入 category、batch、groups（例如 `[1,3]`），获取明确的目标数量、可复用数量、模型、Key 槽位、请求上限、blocks 和 plan_sha256。必须让用户在按钮区域或对话中知道对应的执行范围与模型。准备提示词、检查和本次开发不构成生图授权。

已有明确且范围一致的生产指令时，直接调用 `python factory.py tasks start`，输入相同 category/batch/groups，以及：

- source: `agent`；看板固定写 `dashboard`。
- request_id: 本次执行的唯一标识；不确定是否成功时重用原标识。
- plan_sha256: 计划返回值，不自行伪造。
- authorization: `execute_selected_groups`，是依据用户明确指令填写的机器声明，不再让用户重复确认付费。

该操作创建一次性许可与任务并启动后台进程。请求数量、单图次数、清单、模型和 Key 槽位均绑定；任务关闭窗口后继续。缺少 API、电话、固定服务文案或必需视觉审核能力时返回原因，不绕过。

“组装并生成 N 组”按 assemble → plan → start 调用；必须先形成可追溯批次。已经组装好的批次直接 plan/start，禁止启动时重新抽取变量。

`python factory.py tasks resume` 输入 category、batch、task，恢复同一任务。已完成任务返回原结果，不请求图片。预算耗尽、参数变化、不确定的已付费请求、下载失败或不适合重试的错误需要 Agent 处理；不得借新 request_id 重建预算。

`tasks pause` 使用相同任务定位，请求暂停后续调度，已发出的请求继续保存结果。`tasks retry` 只调度可恢复的失败单元，不请求尚未开始的单元；继续整个剩余任务仍用 resume。两者均保留原许可、已用次数和预算。

## 文件与审核

### 与看板共用的维护操作

- `tasks delete`：输入 category、scope（project/batch/group/image）、必要的 batch/group/position，以及 authorization:delete_selected。项目删除额外要求 confirmation 精确为“删除<登记项目名称>项目”。界面/Agent 必须明确说明不可从应用找回，不能把开发要求当作实际删除授权。运行中任务阻止删除。项目专属配置、批次、图片被删除，跨业务共享模板和代码不属于删除范围。组和图片删除保留不可执行的审计标识；不提供恢复入口。
- `tasks replacement-prepare`：输入 category、batch（历史汇总为 legacy）、group、position、request_id，仅为目标交付图片重新抽取提示词，形成独立隐藏修订批次。三拼图片包含三个生成单元。再对返回批次 plan/start（groups:[1]），仍需明确生产指令。失败保留旧图，成功替换原位置并记录新提示词、原规则快照与关联任务。历史批次需已有本业务确认号码；不能从图片推测电话。准备操作不产生付费请求。
- `tasks keys-view`：返回已配置渠道、槽位标签及版本，不返回密钥原文。`tasks keys-save` 使用 channel、revision、rows；每行可填 value 或 keep_slot（保存原槽位）。只允许既有可信渠道，新增渠道仍走 Agent 设置流程。不要在聊天或日志中暴露密钥；用户可使用标题栏密钥按钮填写。配置写入本机私有渠道文件与现有 .env，Agent 和看板共用；运行时不允许换密钥池。
- 顶部全局并发显示 current/limit，上限等于有效去重密钥数，不设固定行数或并发数上限。共享任务使用跨进程槽位锁，避免不同任务同时占用同一 Key。批次内部不再显示 Key 空闲条。
- “已有图片与待交付”入口已收为“历史批次”，新旧都按批次/组/图片呈现；原文件位置不强制迁移。

- 批次目录：prompts/library/<category>/<batch>/。
- 任务：tasks/<task>/task.json、license.json、events.jsonl；许可范围与使用计数独立保存，先预留请求计数再调用 API。
- 原图与成品：output/<category>/library/<batch>/group_XXXX/；原图收据校验提示词和文件哈希。
- URL 响应使用已有私有下载凭据机制，不在日志中写密钥或签名地址。
- 新图片进入原看板待交付文件的 pending_library_groups 分区，以批次和组号共同定位；不与旧 pending_groups 混用。
- 生成成功不等于审核通过。共享叠字/三拼处理保留验证记录；拒绝的图片不可自动批准。
- 商务 KTV 的无人值守视觉审核尚未接通，因此两个入口都阻止后台付费生产。它的 Agent 实时视觉样片流程仍是单独能力，不能冒充统一后台任务。
- ChatGPT 内置生图同样属于 Agent 专属途径，用户明确选用时单独说明，不用它来替换看板 API 任务。

## 验证要求

相关测试采用工作区内独立目录和注入的模拟图片响应，测试钩子不通过公共 CLI/IPC 暴露。不要为验证此功能发起真实付费生成。禁止任何 dry-run 与整个 tests.test_factory_safety 模块。提示词逻辑修改后运行 factory.py audit。


## 资产路径、打开目录与图片打包（2026-09-30）

所有 Agent 新任务（包括单独标记的内置生图保存操作）先读取 `python factory.py tasks assets-view`，不要假定图片都在代码目录的 output。看板标题栏文件夹按钮弹出目录选择并调用同一 assets-save。公共配置为 `.runtime/asset_settings.json`，新批次的 batch.json.asset_root 固定该根目录；旧批次缺省绑定原 output，已有任务/批次不搬迁。图片存放于 `<资产路径>/<业务>/library/<批次>/group_XXXX/`；提示词、许可与密钥依然留在工厂配置位置。

- `tasks assets-view` 输入 `{}`：返回当前默认路径和历史根目录，纯读取。
- `tasks assets-save` 输入 `{"path":"用户指定的绝对目录"}`：检查目录与写权限，原子保存；无需重启 Agent。只在用户指定目录后调用。
- `tasks open-folder` 输入 category、scope(project/batch/group/image)，以及范围对应的 batch/group/position：返回准确的资产目录，图片占位使用所在组目录。看板随后交给系统打开。
- `tasks package` 输入 `{"category":"业务ID","batch":"批次ID或legacy","groups":[1,3],"destination":"用户选择的绝对目录"}`：省略 groups 为整个批次；只包含成品图片并保留业务/批次/组目录，不包含 raw、提示词、审核证据或密钥。缺图拒绝并提示组号。文件名唯一不覆盖已有压缩包；每份小于既有 1GB 上限，必要时分成多个独立 ZIP。校验全部 ZIP 后返回 paths，并记录 `.runtime/asset_exports/`。这是图片导出，不改变审核结论，也不自动清除待交付队列；正式交付仍按原审核和归档流程执行。

看板右键项目/批次/组/图片可打开目录，右键批次/组可打包；任务功能栏 Lucide archive 图标打包当前勾选的组。每次打包通过系统对话框手动选择目的目录，取消不写文件。渲染页不能绕过选择窗口直接提交保存路径。


## 软件更新与项目规则发布

维护者 GitHub 为 eish1997，仓库为 local-service-factory-releases 和 local-service-factory-rules。详细配置、公共命令与发布步骤见 distribution/README.md。发布新版安装包用 factory-release-installer，项目规则/变量/提示词数据用 factory-release-rules；本机 skill 位于 .agents/skills/。日常规则编辑不自动上传。“发布新版安装包”涵盖必要构建、验证及软件上传；“仅构建”不授权上传；项目规则发布不顺带构建安装包。不得将整个项目目录推送至公开仓库。

公共 `factory.py rules sync/release-plan/publish/rollback` 与 `updates status/check/setup/release-plan/publish` 接收 JSON 标准输入。rules sync 在维护端只检查，不覆盖本地修改；使用端应用经过签名、摘要、字段白名单、兼容性和八业务组装检查的完整数据包。远端冲突先同步并重新规划。发布凭证仅维护端环境或 gh 本地登录；签名私钥仅.runtime/private，不打印、不分发。

使用端安装路径与用户数据分离，任务仍通过同一factory.py入口调用内置Python。新批次snapshot.rules_version记录实际规则版本；旧任务使用原版本目录和冻结提示词，找不到原版本则明确停止。软件安装标志存在时，Agent也不能组装、启动或续接任务。通用模板段落存 configs/prompt_templates.json，默认为空，不改变原有提示词；版本刷新对后续组装生效。

开发期间不得自动打包/上传。2026-09-30 已正式发布软件 1.3.1 和规则 1790730656981293500，完成真实公开下载/签名、隔离使用端规则同步、NSIS 安装及更新模块验收。更新验收含低版本测试适配器和已公开核验的安装缓存复用，不等同于真实旧版整机迁移；全新 Windows 虚拟机未验收，暂无 Authenticode 证书。后续版本仍依据当次明确指令发布，当前版本以配置和远端核对为准。
