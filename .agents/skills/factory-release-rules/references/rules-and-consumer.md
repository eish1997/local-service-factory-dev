# 数据范围及使用端验收

公共入口均为 `python factory.py rules <操作>`，JSON 从 stdin 输入。返回顶层 `ok` 和 `data`，保存/读取 data，不把整段响应当成发布请求。发布计划位于 `.runtime/updates/release_plans/<版本>/`，包含 `plan.json`、`payload.json`、`rules.zip`、validated 文档。

当前实现的 `PROJECTS` 固定八业务，`allowed_files()` 当前导出 36 文件；读取当前代码/配置判断数量，不能为满足用户新类别而绕过白名单或私密检查。

- `distribution/rules-fields.json` 定义字段范围。程序排除电话、凭证、私有路径、只读确认历史和参考来源。人工复核变化文件与包成员，不能打印整个包或私有字段值。
- `prompt_template_storefront.md` 是参考说明，不会整篇直接拼进生成提示词；可执行模板扩展仅来自当前支持的配置和占位符。
- 当前计划将 `min_app` 设为维护代码的 `app_version`，另检查 `engine_major` 和 `rules_schema`。例如维护代码升级后生成计划会要求新版软件，即使修改看似仅文案。发布前说明这个实际兼容门槛；不手工篡改已签名 payload 或假设旧软件能加载。
- 文件级 SHA256、ZIP 总摘要、解压大小、成员路径和私密字段检查均需通过。签名清单和最新指针使用现有 Ed25519 协议。
- 新任务使用活动规则，旧任务/批次保留冻结版本，历史目录不清理。使用端隐藏记录也不能因规则更新重新出现。

使用端测试要在新的隔离目录运行，不能指向生产用户 workspace，也不能把维护私钥/gh token 传入验证进程。使用独立 Python 和当前兼容引擎，将 `FACTORY_DATA_HOME` 设为测试目录，stdin `{}` 依次执行两次 `rules sync`，只输出状态、版本和校验摘要。`active_rules.json` 与对应 `rules/<版本>/manifest.json` 一致，首次 updated 后第二次 current 才算同步/重复检查通过。维护端未设置 FACTORY_DATA_HOME 时仅返回 available，不证明使用端激活成功。

生成独立 stage 需用户构建授权；仅发布规则时优先复用兼容、已验证的现有独立引擎/runtime，不顺带构建新安装包。如果没有可复用的独立环境，可用维护引擎在隔离 consumer 模式验收，并如实记录环境差异。
