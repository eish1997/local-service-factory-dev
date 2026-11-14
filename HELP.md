# 图片内容工厂｜当前帮助

适用于多业务本地生活服务图片工厂。当前登记八个业务：道路救援、开锁、家电维修、管道疏通、宠物托运、货车救援、KTV、商务KTV；具体可用能力和阻塞项以 `python factory.py tasks projects`、对应 plan 为准。系统可扩展其他类别，但不能跳过登记、配置或发布白名单检查。

## 完整工作流

1. **创建或了解项目**：先查看业务及组结构；新类别使用 `new-project-guide` 和主skill的项目引导，确认类别、首图/详情参考、组结构和服务词。只分析参考不等于生产授权，不从参考猜电话或经营事实。
2. **参考与规则调优**：Agent 分析参考，维护业务变量和规则；手机随手拍真实感、场景事件链和去同质化遵循 AGENTS.md。看板变量只读。修改后本地验证；视觉样片需要对应生成授权，商务KTV既有单样片约定另行适用。
3. **选择图片目录**：读取 `tasks assets-view`；用户选定目录后 `assets-save`。新批次保存该路径，旧图片不自动搬迁。
4. **免费组装新批次**：明确完整组数1–100和本批次11位手机号，调用 `tasks assemble`。看板输入框同样必填且默认不沿用历史号码。保存组卡片、冻结提示词/结构/配置；组装不调用生图API。
5. **查看并选择**：`tasks batches/view` 查看批次及提示词，选择部分组或整批。Agent与看板使用相同数据。组装完成后不在启动时重新抽变量。
6. **核对计划**：`tasks plan` 返回待请求、可复用、模型/尺寸、Key槽位、预算、blocks和哈希。当前共享默认tinysnow/gpt-image-2.5-flare、medium、1024x1536。密钥已不在 Adobe 原生4K 分组，不再默认请求 gpt-image-2-4k。实际任务以plan和冻结配置为准。
7. **执行生成**：用户明确指定范围的生产指令后，`tasks start` 使用相同选择、计划哈希和机器授权标记；不要求第二次付费确认。已有可信渠道不重复确认信任，新中转必须先明确授权。密钥只在本机密码表单/私有配置填写。
8. **后台执行与恢复**：任务关闭看板后仍可继续；用同一保存任务 `resume/pause/retry`，不重建预算。有效去重Key数决定共享并发，无固定10路上限，实际受待请求数量及槽位锁约束。单生成单元最多2次总请求，总计最多计划待生成数的2倍；不可恢复错误、下载失败或预算耗尽交Agent核对，不能盲目重POST。
9. **审核与修改**：生成成功不等于批准。实际查看原图/文字/电话、成品完整性和重复度；拒绝结果保持拒绝。单图修订用 `replacement-prepare` 建立独立小任务，明确授权后plan/start；失败保留原图，成功才替换。商务KTV与其它项目一样，由看板和 Agent 共用 tasks plan/start；不再因缺少自动视觉审核而阻止开始。
10. **导出成品**：`tasks package` 按用户选择目录导出批次/组，完整性校验并按小于1GB分包，不含原图/私密配置，保留图片。导出不等于审核通过，也不自动清队列。旧category任务正式交付使用原 `package-category-groups`，不要混用组ID。
11. **日常维护**：Agent与看板共享 `tasks delete/keys-view/keys-save/open-folder`。项目删除需精确确认短语，运行任务阻止删除；开发授权不等于实际删除授权。不能在聊天显示API密钥。
12. **发布更新**：软件改动用“发布新版安装包”调用 `factory-release-installer`，涵盖版本、独立运行构建、验收、签名和GitHub发布；仅打包不上传也可明确指定。项目规则、变量和提示词数据用“发布项目规则”调用 `factory-release-rules`，脱敏校验后独立发布。日常编辑不自动发布。当前软件1.3.1与规则1790730656981293500已发布，未来以远端核对为准；使用端软件启动/每6小时检查、无任务退出后安装，规则独立同步，旧批次保持冻结版本。

## 命令与入口

公共命令为 `python factory.py ...`；`run.py` 是 business-ktv 短别名，不是另一套生成程序。共享 tasks/rules/updates 接收标准输入JSON，接口字段见 [TASK_WORKFLOW.md](TASK_WORKFLOW.md)。生产授权见 [PRODUCTION_AUTHORIZATION.md](PRODUCTION_AUTHORIZATION.md)。发布细节及验收边界见 [distribution/README.md](distribution/README.md)。

看板提供业务/批次/组/图片、执行信息、暂停继续、密钥表单、资产路径和成品导出；不显示秘密或绕过许可。Agent负责只读变量之外的规则维护、异常核对和明确区分的内置ChatGPT生图能力。内置生图不能静默替换看板API任务。

查看状态先读 [agent_memory/current_state.md](agent_memory/current_state.md)，再读对应任务，不能从历史“当前下一步”自动启动。测试只用隔离目录和模拟响应，禁止dry-run及整个tests.test_factory_safety模块。修改提示词逻辑/批次数据后运行factory.py audit。

## 旧任务续接参考

此前category固定10路、自适应升档、模型迁移、特殊重试、旧组号和具体任务示例完整保存在 [旧帮助快照](agent_memory/archive/HELP_before_agent_review_20260930.md)。仅在用户明确继续对应旧任务时结合其原许可和计划使用；这些不是新任务默认值，也不携带新的执行授权。
