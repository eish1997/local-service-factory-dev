# 三仓库合并为一个公开仓库：开发执行文档

日期：2026-11-14。状态：M0—M6 已完成（真实用户级验证范围见验收说明）。新仓已公开，软件 1.4.18 与规则已发布，旧仓过渡发布完成；M7 不在本次授权内。

本文是本次迁移唯一的任务台账和接续入口。后续执行直接更新本文状态、证据和下一步。大日志保存到本地 `.runtime/repository-migration/`，不进入源码仓库。

## 1. 目标与设计决策

用户已选择：源码、安装包、项目规则合并到一个公开 GitHub 仓库。保留软件和规则两条独立更新通道；推源码不自动发布，发布规则不要求重装软件。

默认沿用 `eish1997/local-service-factory-dev`，保留历史，本次不额外改名。名称中的 `-dev` 不影响公开分发。

| 内容 | 统一仓库中的位置 |
| --- | --- |
| 源码、规则源文件、Agent 指引、项目 skills | 保留现有目录结构 |
| 安装包、blockmap、latest.yml、software-manifest.json | `v版本号` Release |
| rules.zip、manifest.json | `rules-递增整数版本号` Release |
| 当前规则入口 | 默认分支根目录的签名 release-index.json |
| GitHub Latest | 只指向已验证的软件版本 |
| 旧仓库 | 保留过渡入口和历史下载，停止日常新功能发布 |

修正此前讨论的标签方案：不使用 `app-v`，继续沿用 `v`。当前软件发布代码按 v 前缀解析版本，保持兼容可减少修改。规则版本不从 1 重新编号。

排除项：业务提示词重构、生图、修改客户任务和额度、清理生产数据、重做旧图片、搬迁所有历史附件、新建下载服务、默认开启 CI 自动发布。公开仓库不等于替用户选择开源许可证，不擅自增加 LICENSE 或修改第三方声明。

## 2. 授权与执行约定

当前用户已明确授权 M5—M6：提交推送、公开、必要构建、双仓过渡发布与真实升级验证。禁止生图、删除/归档旧仓和强推。历史检查点保留当时授权与事实，不覆盖当前授权。

- 仅授权本地开发：执行 M0—M4，准备可审阅差异和上线清单；不据此构建或发布。
- 明确授权完整合仓、公开和过渡发布：继续 M5—M6，已授权步骤无需逐项再次确认。
- M7 归档另有收尾条件；永久删除仓库、改写历史和强推不属于默认动作。
- 文档中的任务列表不是新的生产或发布授权。发生自动审批拒绝时报告具体动作和原因，不误报为用户未授权。

后续按 agent-dev-loop 执行：先读 AGENTS.md、agent_memory/current_state.md 和本文，再读当前切片文件；一个切片验收后更新台账，继续依赖就绪项。不擅自启动子 Agent 或无限后台任务。

项目限制保持：不运行任何 dry-run；不运行整个 tests.test_factory_safety；测试按短模块或明确方法串行，限时且限制输出；不递归扫描生产输出、历史 manifests 或 Codex 日志。发布继续使用公共 `python factory.py updates/rules` 接口，不另建旁路上传器。

## 3. 已核实基线和未验证项

以下是规划时事实，不代表迁移验收已经完成。执行前必须重新核对。

| 项目 | 已记录基线 |
| --- | --- |
| 源码目录 | F:/AI/FZ/road_rescue_image_factory5_260928；不是 Git 工作树 |
| 最近开发副本 | .runtime/github-dev-20261114；复用前核对状态和归属 |
| 最近核对的 main 提交 | 001706a7b1f3e63a98bcedd659203d3dc41335c2 |
| 本地软件版本 | 1.4.17；下一版本在执行时核对远端后确定 |
| 软件仓库 | eish1997/local-service-factory-releases |
| 规则仓库 | eish1997/local-service-factory-rules |
| 更新地址配置 | distribution/update-config.json 的 software_repo、rules_repo |
| 软件发现 | update-service.js 读取 Latest 的签名清单，electron-updater 使用 software_repo |
| 软件发布 | software_release.py 使用 v 标签、software-publish-lock，验证后设置 Latest |
| 规则发布 | rule_updates.py 使用 rules 标签、make_latest=false 和索引 Contents SHA 比较更新 |
| 规则发现 | raw HEAD / Contents API 读取同一份签名 release-index.json |
| 维护端规则基准 | .runtime/updates/remote_head.json；发布计划 base_sha 来自它 |
| 构建配置 | dashboard/package.json 单独保存 publish 目标 |

尚未验证：完整 Git 历史公开安全性、远端当前变化、本机匹配私钥、旧客户端整机升级、共仓下 electron-updater 完整行为。此前推源码时的脱敏检查不能替代公开历史审查。

此前整组预算测试长时间未返回而被停止，不记为通过；本次不要重跑无关生图任务测试。

主工作区目前缺少两个发布 skill 入口，最近 Git 副本内存在 factory-release-installer 和 factory-release-rules。执行时核实有效位置，保留开发副本独有文件；无法读取时按 distribution/README.md 相同公共命令处理，不能猜测旧机器路径。

## 4. 不可破坏的约束

1. 客户数据、真实号码、API 凭据、签名私钥、生产许可、图片及运行日志不进入公开仓库。扫描报告只记录路径、提交和问题类型，不打印秘密。
2. 用户匿名下载即可使用，不植入 GitHub token，不要求用户登录 GitHub。
3. 沿用原 Ed25519 信任链。缺匹配私钥就阻塞发布，不生成新密钥冒充旧身份。
4. 规则 URL 属于签名 payload；变更 URL 必须重新签名，不能复制旧签名后替换地址。
5. 规则不抢 Latest；错误 Latest 必须安全拒绝，不当成软件版本。签名、摘要、最低软件版本验证不能被跳过。
6. 规则版本严格递增；同版本内容不静默覆盖；回退内容也使用更高版本号。
7. 安装身份、用户目录、私有配置、旧任务冻结规则、原图、许可和请求计数保持不变。有任务时不安装更新。
8. 下载或验证失败保留当前可用程序和规则；保留旧下载与恢复入口。
9. release-index.json 是受跟踪发布文件，源码导出没有它不表示应删除，普通推源码不能覆盖它。
10. 构建快照、源码 SHA、签名清单、附件摘要和发布记录可追溯；发布标签绑定明确的提交。

## 5. 文件修改清单

| 文件／模块 | 修改或核对内容 |
| --- | --- |
| distribution/update-config.json | 两个 repo 改统一仓库，保留字段兼容和原公钥 |
| dashboard/package.json、package-lock.json | publish 地址、版本及锁文件元数据一致 |
| dashboard/tools/build-installer.js | 构建前核对包和引擎的仓库、owner、版本；保留 publish never |
| tools/software_release.py | 同仓初始化去重、Latest 类型检查、标签提交、发布锁恢复、受控过渡发布目标 |
| tools/rule_updates.py | 新仓首次索引、仓库身份绑定、旧缓存防误用、版本下界、签名 URL 和 CAS |
| dashboard/update-service.js | 共仓 feed、错误 Latest、清单与包不一致时保留旧版 |
| tools/update_protocol.py | 仅按真实需要调整，不扩大允许域名或绕过签名 |
| tools/runtime_paths.py、tools/stage_distribution.py | 核对配置来源、冻结规则和包内配置，不无故重构 |
| development/export_source.py | 核对保留独有文件及索引的流程，修正生成的旧三仓库说明 |
| tests/test_rule_updates.py、test_update_transport.py、test_release_robustness_review.py | 精确增加迁移与故障测试 |
| dashboard/tests/updates.test.js、installed-bootstrap.test.js | 更新发现、失败保留、任务保护、安装引导兼容 |
| AGENTS.md、开发／发布 README、三个相关 skills | 更新公开单仓约定，保留历史发布事实与旧链接 |
| 统一仓库 README | 软件下载安装、规则说明，区分安装包与 GitHub 源码压缩包 |

这是已知实现边界，允许补充范围内的真实依赖并记录理由；不借迁移扩展业务功能。

## 6. 权威任务台账

状态：todo、doing、verifying、blocked、done。规划不计作实现完成。

| ID | 切片 | 依赖 | 状态 | 完成证据 |
| --- | --- | --- | --- | --- |
| M0 | 现场核对与公开审查 | 无 | done | 3 提交/464 blobs、远端元数据、签名身份与差异归属已审阅；见检查点 |
| M1 | 统一配置与构建约束 | M0 | done | 配置/构建前检查 2 项 Node 测试及初始化 2 项 Python 测试通过 |
| M2 | 共仓发布与故障恢复 | M1 | done | 故障、CAS、来源和双顺序共仓测试通过，见检查点 |
| M3 | 旧版过渡和规则初始化 | M2 | done | 双仓/恢复、初始化、版本竞争及旧规则兼容隔离测试通过 |
| M4 | 开发同步、文档与离线验收 | M1—M3 | done | Git 同步/导出/源码看板/验收矩阵/补丁已验证，见最终交付 |
| M5 | 构建与新仓上线准备 | M4＋完整上线授权 | done | 207df626 构建、公开、软件/规则发布、真实 NSIS 和匿名 updated→current 已通过 |
| M6 | 过渡发布与真实升级验收 | M5 | done | 双仓匿名验签/逐字节一致、真旧版升级、新源 updated→current、任务保护/数据保留/备份恢复及源码再推送保留索引通过 |
| M7 | 旧仓库归档 | M6＋收尾条件 | todo | 待执行 |

### M0：现场核对与公开审查

- 核实三个仓库 owner、可见性、默认分支、SHA、当前版本和发布锁；只读必要元数据，不下载所有历史安装包。
- 检查生产源码与 Git 副本修改归属，获取远端更新；保留其他电脑／对话修改，不在生产根目录初始化 Git。
- 按 factory-push-source 导出脱敏快照并三方比较，复用合适开发副本，不按时间戳整目录覆盖。
- 对待公开的全部可达分支、标签和历史提交做本地有界扫描；分类处理客户信息、密钥、大文件等命中，不能误删合成测试号码或公开哈希。
- 检查远端附件与自动化配置。发现问题保存路径／提交级清单，不自动强推清洗历史。
- 验证私钥是否匹配既有公钥，秘密不进入聊天或日志。

验收：保存当前基线、公开审查结论和阻塞清单。只有审查通过才允许实际切换公开。

### M1：统一配置与构建约束

- software_repo、rules_repo 同指统一仓库，保留两个配置字段。
- 包与引擎的 owner、repo、version 一致；不一致在正式构建前失败。
- setup 两字段同仓时只处理一次，不在普通初始化中自动修改可见性。
- 保留 v／rules 标签规则、应用身份、安装目录和数据目录。

验收：隔离配置正确解析两个入口；配置不一致被拒绝；测试不改生产配置和用户数据。

### M2：共仓发布与故障恢复

- 规则固定 make_latest=false；软件资源公开下载及签名全部验证后才设置 Latest。
- 软件发布先验证 Latest 标签类型与版本；错误类型明确报错，不自动修复远端。
- 发布前记录源码 SHA，统一仓库 Release 标签绑定该 SHA；已存在标签／附件先比对，不覆盖不明内容。
- 保留原子发布锁；尽可能在加锁前完成前置校验；中断后先核对远端附件与锁，不重放不明确的写请求。
- remote_head 和发布计划绑定 owner/repo，旧仓 base_sha 不能用于新仓；保留旧记录，不以清空历史模拟新发布。
- 索引仍做 SHA 比较交换；并发代码提交不丢失，竞争规则发布不能共同推进同一旧基准。

验收：软件／规则两种发布顺序都正确；错误 Latest、重复标签、并发和上传中断不损坏当前通道。

### M3：旧版过渡和规则初始化

安装包内的未来更新源与本次上传目的地必须分开。过渡包始终内置新地址，上传旧仓时不能把包内地址改回旧仓。

- 在公共 updates 接口内设计受控过渡目标，只允许已记录的新旧软件仓库；先记录拟增参数再实现测试，不绕过公共命令上传。
- 同一构建产物双仓分发；安装包、blockmap、latest.yml、软件签名清单逐字节一致。保持旧 updater 可识别的命名、公钥和应用身份。
- 新仓首次缺少索引仅在显式迁移流程处理；403、网络错误、坏签名不等于空仓库。
- 验证旧规则索引，以其版本为下界发布更高的新版本；新 URL 重新签名，不用同版本号替换旧缓存内容。
- 核对 min_app；如果规则要求新软件，旧规则仓保留兼容入口，旧软件先升级后读取新规则。
- 新仓两条通道可用后，才推进旧软件仓 Latest 到过渡版，避免用户升级后进入空通道。
- 不搬全部历史附件；记录新旧当前入口、版本、摘要和源码关系。

验收：模拟旧版从旧源发现过渡包，新安装配置指向新源；空索引可受控初始化；旧冻结任务和规则仍可读取。

### M4：开发同步、文档与离线验收

- release-index.json 由发布流程维护，源码导出／合并不得覆盖、删除有效签名索引。
- 规则发布通过 Contents API 产生远端代码提交；发布后同步本地 Git，干净时快进，有改动时保留并合并，不自动 stash/reset/强推。
- 更新相关 skills，去掉“源码必须私有”和固定三仓库要求；新约定优先于旧技能偏好。
- 更新 README 和 Agent 指引，旧发布记录保留旧链接；新增迁移说明。
- 执行下节矩阵中的必要离线检查。仅当实际修改提示词／批次逻辑时运行 factory.py audit，不为仓库地址迁移重跑无关生产审计。

验收：必要离线检查通过，交付差异、拟发布版本、目标仓库、构建与迁移清单。仅授权开发时在此交付，不称迁移上线完成。

### M5：构建与新仓上线准备

- 复核授权和最新源码；公开审查后有新增修改就补增量审查。
- 新软件版本必须高于本地及新旧远端软件版本，本文不固定下一版本号。
- 从固定源码快照按 staging／NSIS 公共流程构建；构建不自动上传，记录摘要、公钥 ID 和源码 SHA。
- 检查包内配置、独立 Python、隔离启动及私密数据排除；源码提交与实际构建快照一致。
- 准备完成后将目标仓库公开，不同时改名；匿名验证可访问。
- 发布统一仓库软件和迁移规则，分别遵守原有公开下载验证后推进指针的顺序。

验收：新仓匿名下载、验签及两条更新入口可用；此阶段失败不推进旧仓入口。

### M6：过渡发布与真实升级验收

- 新仓已可用后，把相同软件产物发布到旧软件仓；旧分发仓标签使用其实际有效提交，在发布记录中关联真实源码 SHA，不能假造旧仓不存在的源码提交。
- 使用隔离 Windows 或明确授权的测试安装，从真实旧安装版经旧源升级。启动新的 unpacked 程序不能代替旧版整机升级证据。
- 确认升级后请求实际走新仓；规则首次 updated，再次 current；签名、摘要、版本一致。
- 对合成数据或已授权副本核对用户配置、旧任务、冻结规则、原图和请求计数不变，不执行付费生图。
- 用夹具测试下一版软件发现；不为测试制造空版本发布，缺少真实下一版升级证据时明确说明。
- 如更改看板源码，重启开发看板核对实际加载版本，不停止其他生产 worker。
- 更新旧仓 README 迁移入口、当前状态与最终证据，保留兼容下载。

验收：新用户安装、旧用户升级、新规则同步三个真实入口成功。缺真实旧版测试环境时记待验收，不以单测冒充迁移完成。

### M7：旧仓库归档

- 前提：M6 通过，无待恢复发布／回滚，用户授权覆盖归档并接受旧仓仅保留历史下载。
- 无可靠用户版本统计时不声称所有用户已升级；保留过渡包让长期离线用户仍可升级。
- 归档前后匿名验证旧下载入口；不删除仓库或客户端旧数据。
- 条件未满足则待办，不妨碍统一仓库承担后续日常发布。

## 7. 验收矩阵

| 编号 | 场景 | 标准 | 层级 |
| --- | --- | --- | --- |
| V01 | 同仓配置与构建一致性 | 两通道正确，不一致提前失败 | 本地测试 |
| V02 | 软件／规则交错发布 | 规则不抢 Latest，软件发现正常 | 模拟＋公开读回 |
| V03 | 错误 Latest、包与清单不一致 | 拒绝错误包，保留旧版 | Node 测试 |
| V04 | 新仓无索引、旧缓存存在 | 受控初始化，不误用旧仓 SHA | Python 测试 |
| V05 | 并发规则发布／代码提交 | CAS 正确，代码与索引保留 | Git/API 模拟 |
| V06 | 上传超时、缺附件、残留锁 | 先核对再恢复，不提前推进指针 | 故障注入 |
| V07 | 换 URL、坏签名、不兼容规则 | 重新签名；不合法输入不激活 | Python 测试 |
| V08 | 双仓过渡包 | 四类资源摘要一致，包内新地址 | 实际公开下载 |
| V09 | 旧软件升级 | 从旧源成功升级，后续请求新源 | 真实安装 |
| V10 | 新使用端 | 匿名安装与同步，updated→current | 隔离使用端 |
| V11 | 有任务、离线、下载失败 | 不强制安装，当前版本和数据保留 | 精确测试＋实际验证 |
| V12 | 迁移后再次推源码 | 不覆盖签名索引或远端发布提交 | Git 隔离验证 |
| V13 | 旧历史入口 | 保留并可下载 | 匿名读取 |

现有入口：tests.test_rule_updates、tests.test_update_transport、tests.test_release_robustness_review，以及 dashboard/tests/updates.test.js、installed-bootstrap.test.js。执行前核对实际方法和依赖，选择小范围串行运行；不要把尚未实现的测试名当作现成命令。

每次记录工作目录、解释器版本、命令、时限、退出码和输出上限。环境权限问题先诊断，测试超时保留失败现场；不无限等待、不删测、不放宽断言。禁用整套 factory safety。

公开命令仍为 `python factory.py updates release-plan/publish` 和 `rules release-plan/publish/sync`，通过 JSON 标准输入传参。过渡目标参数在 M3 实现和测试后才能使用，本文不提供可误触发上线的整段命令。

## 8. 回退和中断恢复

| 失败位置 | 处理 |
| --- | --- |
| 敏感历史审查不通过 | 不公开，保存问题清单，不自动改写历史 |
| 本地开发／构建失败 | 保留记录，旧用户继续使用旧仓 |
| 新仓上传不完整 | 保留草稿、锁和摘要，核对后恢复，旧入口不推进 |
| 新仓已上线但未桥接 | 旧用户不受影响，修复后再继续 |
| 桥接后安装故障 | 使用已验证安装器和 previous-app 恢复；修复通常发更高版本，不假定可自动降级 |
| 新规则错误 | 保留旧活动规则，以更高版本发布已验证旧内容 |
| Git 冲突 | 保留源码和索引后合并，不强推或覆盖整目录 |
| 公开后发现资料问题 | 停止继续发布并处理；改回私有不能保证撤回外部副本 |

恢复先核对 Latest、索引 SHA、草稿、发布锁和已上传资源摘要，再决定下一步。写请求结果不明确时先查远端，不重复创建版本掩盖中断。

## 9. 检查点、记录与完成定义

每个切片追加：ID／状态、源码 SHA 或差异、目标仓库、修改文件、测试与退出码、证据路径、失败分类、未完成项和下一条具体动作。大日志不贴入正文，秘密不写入可导出文档。

当前检查点：

- 已完成：M0—M6；双仓发布、实际用户级旧版升级、新源同步和恢复入口已验收，维护提交 2b0d10f 已推送，远端签名索引逐字节保持。
- M7 不在本次授权中；旧仓保留。完整真实证据和测试隔离边界见 Git 副本 development/M5_M6_RELEASE_VALIDATION.md。
- 构建、软件/规则发布均已退出；没有在途上传。
- 接续：日常源码/软件/规则继续使用统一仓库；M7 不执行。未来安装验证优先独立 Windows 用户/虚拟机，准确保留本次验证边界。

M0—M4 通过只能报告开发完成；M5—M6 通过且必要端到端证据齐全，才可报告迁移上线完成。M7 条件不足可以待办，但必须说明旧仓仍用于过渡／历史，不声称物理上只剩一个仓库。

最终交付：统一仓库地址、源码提交、软件与规则版本及链接、双仓过渡包摘要、真实升级证据、未验证限制、旧仓状态和恢复入口。

## 10. 后续执行提示

以下提示供后续发起任务，本身不触发执行。

本地开发：

> 使用 agent-dev-loop，按 development/UNIFIED_REPOSITORY_EXECUTION_PLAN.md 完成 M0—M4 的开发与验证。先核对工作区、远端基线和已有修改，复用合适 Git 副本；每个切片验收后更新本文并继续依赖就绪项。不构建安装包、不公开仓库、不发布。交付可审阅差异、验证结果和完整上线清单。

完整迁移：

> 完整执行上述合仓计划，包括已选公开仓库、必要安装包构建、新旧仓库过渡发布与真实升级验证。已授权步骤不重复询问，保护客户数据与历史产物，真实阻塞记录原因并继续独立可推进项。旧仓库暂不归档或删除。

## 11. 依据

- AGENTS.md、distribution/README.md、development/README.md。
- distribution/update-config.json、tools/software_release.py、tools/rule_updates.py、tools/runtime_paths.py、dashboard/update-service.js、dashboard/tools/build-installer.js。
- [GitHub Releases 官方接口](https://docs.github.com/en/rest/releases/releases)：实际执行时复核 make_latest、target_commitish 行为。

### 执行检查点 2026-11-14 / M0 doing

- 当前授权覆盖 M0—M4 本地实现和验证，覆盖第 2 节原“仅规划”状态；不授权推送、构建、公开或发布。
- 根目录非 Git 工作树；复用 `.runtime/github-dev-20261114`，工作树干净，origin 为预期开发仓库；fetch 后 HEAD 与 origin/main 均为 `001706a7b1f3e63a98bcedd659203d3dc41335c2`。本地可达 3 个提交，无标签。
- 沙箱 fetch 因凭据辅助程序权限和网络代理失败；提升权限 fetch 成功。gh 查询开发仓库返回不可解析，需继续核对 API 身份，不能据此断言仓库不存在。两个分发仓库只读查询成功，均 PUBLIC/main。
- 已运行 `python development/export_source.py --destination .runtime/repository-migration/source-baseline`，退出 0，389 文件。比较报告 `.runtime/repository-migration/source-comparison.json`：5 个差异文件及新增执行计划；尚未覆盖 Git 副本，独有发布 skills 保留。
- 下一步：逐项审阅上述差异归属，完成全部可达历史的有界敏感信息扫描、远端版本/锁/自动化和签名身份核对，再进入 M1。M0 尚未验收，M1—M4 未实现。

### M0 审查进展（第二检查点）

- 上一轮属于实质进展：完成导出与基线比较；本轮继续历史审查，未重复导出。
- 已扫描全部本地可达 3 提交、464 个唯一 blob，报告 `.runtime/repository-migration/history-audit.json`。未命中凭据格式、私钥头或超过 2 MB 的 blob；电话号码候选只出现在测试文件及运行依赖锁中，仍需上下文分类，不能据此宣称完整公开审查通过。
- 原签名私钥通过内存挑战签名及既有配置公钥验证（matched）；未记录私钥或签名内容。
- 远端只读核对：软件 Latest `v1.4.17`，规则最新记录 `rules-1793435166580719500`，均非草稿/预发布；软件发布锁 ref 返回 404。未进行远端写入。
- 已审阅导出差异：renderer/icons.js 与 index.html 只有空白变化，门头模板仅换行差异；导出 README 会减少 Git 副本已有入口，保留副本版本。development/README.md 的计划入口需后续合并。
- 当前无在途扫描进程（会话 14368 已退出 0）。下一步：分类电话候选、核实开发仓 API 身份与远端自动化/附件元数据；完成 M0 结论后推进 M1。当前仍为 M0 doing。

### M0 验收与 M1 开始

- Git 凭据与 gh 当前凭据可见范围不同；使用既有 Git 凭据只读核实统一仓库 PRIVATE/main。远端只有 main，无标签、工作流和 Release，见 remote-audit.json。没有切换账号、保存凭据或修改可见性。
- 审阅 phone-context.json 的 235 处上下文：测试参数/断言与依赖 SHA256，不作为客户清单删除。扫描结论限于已获取的全部可达源码历史；未来新增提交/附件公开前须复查。
- M0 本地验收通过。M1 在 `.runtime/github-dev-20261114` 实现；生产根目录配置保持当前可用通道。版本仍 1.4.17，后续正式发布需选更高版本。

### M1 实现检查点

- Git 副本的 software_repo/rules_repo 与 dashboard publish 均已改统一仓库；未修改生产根目录当前更新配置。包/锁文件版本均 1.4.17，无需改依赖锁。
- 新增纯函数 build-config.js，在正式构建调用前验证公钥、界面/引擎/锁文件版本、owner/repo 与双通道一致性；保留 publish never。setup 同仓去重，保持不自动修改可见性。
- `node .runtime/github-dev-20261114/dashboard/tests/build-config.test.js` 退出 0，2 测试通过（正常配置及 7 类不一致）。`node --test` 曾因沙箱 spawn EPERM 失败；直接运行同一 node:test 文件通过，不涉及构建。
- M1 仍 doing：下一步补 setup 去重/私有仓拒绝测试并复核公共配置解析，然后进入 M2。新增文件尚未提交，git diff 与未跟踪文件共同构成审阅候选。

### M1 验收 / M2 第一切片

- `python -m unittest tests.test_repository_migration` 在 Git 副本运行，初始化两项隔离测试通过，验证同仓去重和私有仓无写入。结合前次 Node 构建配置检查，M1 验收通过。
- M2：软件 Latest 严格要求正式 vX.Y.Z；检查提前到加锁前。重复标签/Release 拒绝盲目重传；创建 Release 明确绑定读取到的提交 SHA 并禁止推进 Latest。完整来源 SHA/构建关联及中断恢复仍待实现，不把当前前置检查当作 M2 完成。
- 新增 Latest 正常/规则标签/缺前缀/草稿/预发布/相同与更高版本测试，当前 migration 模块 3 测试通过，退出 0，Python 3.14；无网络写入或安装包构建。
- 一次指定工具 workdir 的只读检查调用未返回（functions cell g15:25）；后续从根目录显式 Push-Location 运行正常。该调用仅含 status/read/search，无变更。下轮先核对该句柄，不据此重启任何生产进程。
- 下一步：补充发布流程故障注入与来源 SHA 绑定，再实现 remote_head/plan 的仓库身份约束和 M3 受控迁移入口。

### M2 仓库绑定切片

- rule_updates 的 remote_head、release-plan 与 rollback plan 增加 repository owner/repo。迁移前的无身份缓存及其他仓库缓存明确拒绝，不删除/清空旧记录，不使用旧 SHA 生成新计划；sync 写入当前身份。
- publish 在签名前验证计划归属及精确规则下载 URL，防止签名旧仓 URL 后向新仓发布。CAS 继续使用原 Contents SHA，发布失败不推进索引。
- Git 副本运行 `python -m unittest tests.test_repository_migration`：4 测试通过；`python -m unittest tests.test_rule_updates.RuleUpdates.test_publish_cas_and_rollback_are_explicit_and_assets_first`：1 测试通过（12.905 秒），退出 0。首次新增测试因系统临时目录 ACL 失败，改为仓库 .runtime 隔离夹具后通过，保留失败事实。
- M2 尚待：软件源码/构建关联、发布锁恢复与上传故障测试；M3 需提供显式空索引迁移和旧版本下界，不能把当前拒绝旧缓存当成初始化功能完成。
- 只读 cell g15:25 本轮重新查询仍未返回；没有据此重复启动或停止生产作业。测试会话 70082 已正常退出。

### M2 软件故障与来源记录切片

- 新增软件发布隔离故障测试：错误 Latest 无远端写入；上传超时/公开下载损坏保持锁且不推进 Latest；成功路径先验证附件再推进 Latest/释放锁。3 项通过。
- 构建脚本加入干净源码提交检查，成功后生成 build-provenance.json（源码 SHA、版本、仓库、三类附件摘要）；发布计划验证该记录，签名清单携带 source_sha，发布检查目标仓中存在该提交，Release 绑定记录中的 SHA 而非临时分支头。
- 修复构建进程异常/被中断时 status 为 null 被误判成功的问题。未运行构建脚本或生成安装包；测试只使用隔离伪附件。
- `python -m unittest tests.test_repository_migration` 7 测试通过，退出 0。仍需 Node 来源记录测试、构建暂存内容与源码一致性核对、锁恢复入口和规则故障测试；M2 尚未验收。
- 下一步先补来源记录篡改/缺失测试，再继续中断恢复和 M3。旧包缺少新来源记录时明确拒绝，不能把既有安装包伪装成本次统一仓库构建。

### M2 发布恢复切片

- 公共 `python factory.py updates recover` 接收与 release-plan 相同的 directory，默认只读核对发布锁/标签源码、Latest、四类附件名称、下载摘要和签名清单；返回 recoverable/blocks。不重新上传附件、不删除不明草稿。
- 明确 `authorization=finalize_software_recovery` 且回传匹配 source_sha/files 时，仅对完全核验的公开版本完成 Latest 指针及锁释放；若 Latest 已成功设置，只释放所属锁。草稿/缺标签/外来锁保留并报告阻塞。
- 软件锁现在绑定构建 source_sha，避免恢复时误用并发源码提交的分支头。发布创建仍依赖 Git ref 原子冲突防竞争。
- 新增草稿/外来锁无写入、只读检查、明确恢复仅 PATCH/DELETE 的测试；migration 模块共 9 测试通过，退出 0。没有实际调用远端恢复命令。
- M2 仍 doing：来源记录缺失/篡改、暂存源码关联、规则上传中断和重复标签测试待补；M3 受控过渡与初始化仍未实现。下一步继续闭合这些测试与实现边界。

### M2 构建暂存来源闭环

- 正式暂存入口要求干净 Git 提交，在暂存结束记录 source_sha 与引擎全部文件摘要；通用 stage_engine 导出函数不增加构建副作用。构建前后核对暂存 SHA 和完整文件清单，拒绝新增/改写文件；与构建后附件摘要记录一起形成来源证据链。
- `node .runtime/github-dev-20261114/dashboard/tests/build-provenance.test.js`：2 项通过，验证错 SHA、改写/新增文件、缺附件及摘要记录。未调用构建器。
- `python -m unittest tests.test_repository_migration.ProvenanceTests`：1 项通过，验证缺来源文件、无效 SHA、错版本/仓库、篡改摘要及构建后附件变化均拒绝。
- 本轮仅修改开发副本，生产配置保持原通道。M2 仍需规则中断/重复标签与客户端错误 Latest 回归；之后推进 M3 显式迁移和过渡上传目标。当前没有构建或发布作业。

### M2 客户端回归及导出缺陷修复

- 发现基线开发副本既存导出缺陷：脱敏 Windows 盘符正则误匹配 https 的 s:/ 及 JavaScript Error: 文本，造成 update-service 更新 URL 损坏及 installed-runtime、renderer/ui、renderer/actions 的源码截断。此问题不是本轮仓库地址变更导致；此前 mock 响应未覆盖真实请求 URL。
- 修复开发副本 export_source.clean_text 的盘符前边界；只从生产源码恢复上述四个确认损坏文件并重新脱敏，没有覆盖其他开发改动。四文件 node --check 通过。
- updates.test.js 新增配置 URL、有效签名规则清单误占 Latest、updater 版本不匹配测试；共 7 测试通过，涵盖原有摘要/签名/任务保护/旧版备份行为。新 ExportBoundaryTests 1 项通过，验证 URL/JavaScript 保留及真实 Windows 路径脱敏。
- 该导出修复是 M4 的必要依赖，提前处理以保证 M2 客户端代码有效。M4 仍需全量导出源码语法及历史损坏范围复核；原始生产目录导出器尚未同步，后续交付时明确差异来源。
- M2 仍待规则发布上传中断、重复标签测试；之后推进 M3。所有测试离线，无安装包构建或远端写入。

### M2 规则发布故障切片

- 规则发布加写入前重复 tag/Release 检查；草稿创建及公开转换都显式 make_latest=false。公开 rules.zip 摘要和 manifest.json 签名/payload 全部一致后才 Contents CAS 更新索引。
- `python -m unittest tests.test_repository_migration.RuleFailureTests` 通过：重复标签无写入、上传超时/公开清单不一致不 PUT 索引、不推进 Latest、不改本地 remote_head。
- `python -m unittest tests.test_rule_updates.RuleUpdates.test_publish_cas_and_rollback_are_explicit_and_assets_first` 通过（13.698 秒），验证新检查未破坏显式发布、递增回退及 CAS 冲突。退出均 0，使用隔离夹具和模拟网络。
- M2 复核尚缺规则 Release 的明确 source_sha 关联及两种交错发布顺序的组合证据；后续完成后再标 done，不用单通道测试替代整体验收。
- M3 拟新增公共参数：updates release-plan/publish/recover 的 target，仅接受 unified/legacy-software；包内配置仍为统一仓库。rules release-plan 的 migration_from_legacy=true 仅在新仓索引确实不存在时启用，以已验签旧仓版本为严格下界，并保存迁移证据；403/网络/坏签名必须失败。参数尚未实现，不可用于上线。

### M2 规则源码关联

- 新规则 release-plan 要求干净提交并在导出前后复核 SHA，plan/payload 均写 source_sha；发布前验证源提交存在于目标仓库，Release target_commitish 绑定它。
- 递增回退复用原内容的 source_sha，缺源码关联的历史计划拒绝自动回退，需审阅后重新准备；不编造历史来源。
- migration 模块 12 测试及规则发布/CAS/回退单方法通过，退出 0（后者 7.998 秒）。夹具显式提供合成源码身份与远端提交，网络调用均模拟。
- 下一步补共仓交错发布组合证据与 M2 整体复核，然后进入 M3 已记录的 target/migration_from_legacy 参数实现。仍未构建或发布。

### M2 验收 / M3 开始

- tests.test_repository_interleaving 使用同一有状态 GitHub 模拟仓库执行两个实际发布函数的两种顺序，验证 Latest 始终为 v 软件、规则索引独立推进、标签绑定来源和软件锁释放。1 测试（2 顺序）通过，退出 0。结合前述故障/CAS/来源/客户端证据，M2 本地验收通过；真实公开读回仍属于 M5—M6。
- M3 开始接入 target=unified/legacy-software；旧目标仅允许已记录 owner/仓库。包内配置和签名清单仍绑定新仓源码；旧分发仓标签绑定其自身明确分支 SHA（它没有源码历史），双仓清单仍应逐字节一致。
- 过渡目标实现尚待验证，尤其旧仓恢复标签核对与新通道 readiness 门槛；不得把参数视为已上线可用。下一步补这些检查及双仓伪附件测试。

### M3 通道前置检查与显式规则迁移

- legacy-software 发布前和推进 Latest 前核对新仓软件 Latest、签名清单及三类附件逐字节摘要，并读取验签后的新仓规则索引、确认新 URL/规则包摘要。新通道未就绪时拒绝旧仓推进。
- 修复旧仓锁错误引用新仓源码 SHA（该对象未必存在）：过渡锁/标签绑定旧仓明确提交，签名清单保留新仓 source_sha；recover 区分两种提交身份并核对新通道。
- 变更后 migration + interleaving 两模块共 13 测试通过，退出 0；此回归覆盖统一仓路径，过渡专属测试待补，不能据此宣称双仓验证完成。
- rules release-plan 已接入 migration_from_legacy=true：限定维护端和记录的新旧仓，先核对目标仓可访问且无索引，再读取验签旧索引；保存旧 envelope/版本下界到新计划，保留原 remote_head。版本必须严格更高；发布再次核对旧仓下界。403/网络异常直接传播，不能当空索引。
- 显式迁移实现尚未运行专属测试。下一步验证空索引/已存在/403/坏签名/版本不递增/旧缓存保留，以及过渡附件一致性。M3 仍 doing，无远端写入。

### M3 初始化验证

- 新增 tests.test_rule_migration.RuleMigrationTests，使用生成的隔离 Ed25519 测试密钥及真实签名验证路径。2 测试通过（5.881 秒）：旧版本 200 时拒绝 199/200、接受 201 并改用新 URL，原 remote_head 字节保持；目标已有索引、403、网络超时、坏签名均拒绝。
- 修正迁移计划 api_called 标志（显式初始化确实执行只读网络查询）。普通离线计划保持原标志。
- 复核发现过渡恢复新增路径有未定义 envelope 引用和 PATCH 缩进错误，已改为保存并复用验签 envelope，仅在 Latest 尚未是目标版本时 PATCH。RecoveryTests 两项回归通过。
- M3 尚需完整双仓分发/过渡恢复及新通道缺失拒绝测试、发布时旧仓版本推进测试。下一步以同一组伪附件跑实际双仓发布函数，校验四类资源逐字节相同和目标白名单。

### M3 双仓过渡发布与恢复验证

- 按最新检查点恢复，保留现有全部修改。git status 显示已记录的 M1—M3/导出修复候选及测试，未重做已验收切片。
- 旧只读 functions cell g15:25 返回 stale host generation，句柄已失效。只读进程检查最初被 ACL 拒绝，提升权限后成功且未发现本次相关 Python/Node 测试进程；没有停止/重启其他作业。
- 新增 tests.test_transition_publish，2 测试通过（0.025 秒）：实际 release_plan/publish/recover 对两个有状态模拟仓库运行；新通道缺失时零写入；软件包/blockmap/latest.yml/签名清单四类资源逐字节一致；旧仓标签和锁绑定其提交，新仓源码仍在清单中；Latest 已更新但锁残留时恢复仅 DELETE，不重传或再次 PATCH。
- 同模块验证 target 白名单及 owner 限制，配置始终保留统一仓库。网络全部模拟，使用隔离伪附件，未构建/上传/发布。
- M3 仍待发布时旧仓版本推进、旧冻结任务/规则兼容的针对性验证及全切片复核；M4 尚未完成。下一步补这些证据，再整理源码同步、文档和上线清单。

### M3 验收 / M4 开始

- 新增发布前旧仓版本推进测试：旧版本从 200 推进到 202，既有 201 迁移计划拒绝，全部远端调用为 GET。通过（4.453 秒）。
- 修复统一仓库无缓存时普通计划绕过显式初始化的问题：release-plan 无基准拒绝；publish 新仓空索引且无 migration 证据也拒绝。新增无缓存测试通过，export 未调用。
- 旧规则兼容：test_offline_upgrade_preserves_old_and_compatible_signed_rules 通过（14.436 秒）；test_signed_install_atomic_failures_and_new_prompt_version 通过（11.265 秒），包括原任务冻结规则继续使用旧版本、签名/损坏/离线失败保留当前规则。仅隔离模拟生图，无 API 请求。
- 发布/CAS/回退单方法在最新防护下通过（7.106 秒）；该通用测试使用独立 test/rules 仓库，统一仓初始化由专属迁移测试覆盖。测试会话均已退出，无在途测试。
- 结合双仓四资源一致/恢复和初始化证据，M3 本地验收通过；真实旧客户端安装、实际匿名下载及升级仍留 M5—M6，不以模拟替代。
- 下一步 M4：索引保护与 Git 同步流程、README/Agent/skills 单仓约定、导出全量语法复核、验收矩阵及完整上线清单。当前源目录仍保留线上配置，迁移实现位于复用 Git 副本，未构建/公开/发布。

### M4 同步保护与上线清单

- 新增 development/sync_repository.py：fetch 后仅干净且无分叉时快进；未提交修改/分叉报告 review_required，保持现场，不 stash/reset/clean/push。合并由审阅后的明确本地提交执行，流程见 development/REPOSITORY_MIGRATION.md。
- 新增本地 Git 集成测试：规则发布索引提交快进保留；本地脏修改阻止自动合并且字节保留；明确提交后合并远端，源码与新版索引均保留。沙箱首次失败已定位为 Git sh CreateFileMapping Win32 error 5，提升权限在隔离本地仓库重验通过（2.544 秒），不涉及 GitHub。
- 新增迁移说明及完整 M5—M6 上线检查清单，覆盖授权/审查/版本/构建来源/签名/双通道/双仓/真实升级/任务保护/回滚/Git同步/旧仓保留。
- M4 尚需更新 README、AGENTS 与三项 skills，修正导出器生成旧三仓说明，执行导出语法与最终验收矩阵。当前不标完成，下一步继续文档和导出验证。

### M4 文档与导出验证

- 更新开发副本 README、development/README、distribution/README、AGENTS 及 factory-push-source / factory-release-installer / factory-release-rules，明确单仓两通道、签名索引保护、来源 SHA、过渡参数和授权边界；公开不擅选许可证。README 区分安装包和 Source code ZIP，并保留旧下载入口。
- 修正导出器生成的固定三仓/技能数量说明。distribution README 从原源码经修复后的脱敏器恢复既存损坏历史链接，保留历史事实。
- 导出 `.runtime/repository-migration/final-export-review` 成功，409 文件，退出 0；仅脱敏源码快照，不是安装包。
- export-verification.json：229 个 Python 文件 AST、41 个 JavaScript 文件 node --check 全部通过；三项依赖完整性元数据逐字节相同；release-index.json 未导出，合并必须保留目标索引。未递归扫描生产输出。
- M4 尚需最终差异复核、必要离线测试矩阵与可审阅补丁交付。下一步核对全部候选文件、文档链接及测试实际覆盖，发现缺口继续修复，不能将导出成功等同目标完成。

### M4 最终离线验证进展

- 本次候选统一 LF 后 git diff --check 退出 0；test_update_transport 5 项通过。
- installed-bootstrap 旧测试依赖旧机器路径和八业务断言。核实本机已有 Python 嵌入运行时可复用，建立仅测试用 migration-bootstrap/engine（当前源码脱敏快照）及 python Junction，未构建安装包/安装依赖；当前九业务对应全列表 9、隐藏一个后 8，修正过期断言。
- 沙箱下 Node spawnSync 明确 EPERM，提升权限后 installed-bootstrap.test.js 2 项通过（8.373 秒），验证首次离线初始化、后续私有配置保留、升级旧证据保留及兼容内置规则刷新。不是 NSIS 安装或客户整机升级证据。
- M4 仍需最终验收矩阵、可审阅补丁以及候选完整性/文档复核。尚未标完成，未构建/公开/发布。

### M4 验收矩阵与补丁候选

- 新增 development/MIGRATION_VALIDATION.md，逐项映射 V01—V13 本地证据与上线阶段未执行条件；更新开发副本当前入口。test_incompatible_and_tampered_archive_rejected 通过（0.672 秒）。
- 生成 35 文件候选清单及 M0-M4-review.patch（.runtime/repository-migration）。最初自建文本 diff 因原文件末尾无换行导致 corrupt patch；改用 Git 原生 diff（含新增文件）后，独立临时 index 上 git apply --cached --check 退出 0，未暂存真实工作树。
- 候选清单保存文件 SHA256 和补丁 SHA256。补丁会在最终台账更新后重新生成，当前版本不是最终冻结交付。
- 下一步完成最终候选复核、文档/skills 引用与必要实际源码看板检查，并冻结补丁与证据清单；M4 仍 verifying，不提前声称全部完成。

### M4 实际源码看板检查发现缺口

- 用现有 Electron 启动当前 Git 副本 main.js 的隔离测试窗口，独立数据目录、TEST 模式禁用自动更新；已退出，无生产操作。report.json 确认加载副本 renderer/index.html、九业务、无脚本/console 错误。
- 截图人工检查未通过：顶部图片缺失且布局异常。开发副本 dashboard/branding 只有 SVG，生产源码还有 PNG/ICO；导出器未复制二进制静态资源。不能用 DOM/语法通过代替视觉验收。
- 证据在 .runtime/repository-migration/dashboard-check/report.json 与 screenshot.png。下一步修复明确静态资源白名单及检查样式实际加载/尺寸，重启隔离看板复验后再冻结补丁。M4 仍未完成。

### M4 静态资源修复与复验

- 看板图标缺失根因为旧导出脱敏破坏 SVG xmlns；恢复品牌及本地 Lucide SVG。CSS 与原源码逐字相同，不引入无关布局重构。新增 PNG/ICO 精确静态资源导出白名单，凭据扫描只跳过这两个已知二进制资源。
- 初次 SVG 定位遍历未及时返回，已停止并改为 branding/logo.svg 与 renderer/vendor/lucide/*.svg 的明确范围；未读取/输出生成任务内容。
- 重启隔离 Electron 后截图确认品牌、窗口按钮、侧栏与新建/刷新图标显示正常；report 无加载/console 错误，九业务正常。此前所谓布局异常主要是图标缺失造成的操作区空白，CSS 未变。
- StaticAssetTests 通过（0.137 秒），逐项验证 SVG namespace 和品牌文件头；修复后新导出 static-assets-export 成功，412 文件，退出 0。下一步核验导出资源字节、刷新最终补丁与矩阵，M4 尚未冻结交付。

### 最终交付：M0—M4 完成（2026-11-14）

- 开发候选位于 `.runtime/github-dev-20261114`，基线 `001706a7b1f3e63a98bcedd659203d3dc41335c2`；未提交/推送，原生产根目录程序与配置未切换。复用了现有干净 Git 副本，保留独有技能和已审阅内容。
- 最新最终模块串行测试全部退出 0，命令/工作目录/时限/耗时及日志索引见 `.runtime/repository-migration/final-test-results.json`。原有相关精确测试、Node、Git 和隔离实际看板证据见前述切片及 MIGRATION_VALIDATION.md。
- 最新导出验证 export-verification-final.json：229 Python、41 JavaScript、21 SVG，通过；品牌 PNG/ICO 及依赖完整性元数据逐字节一致，文档引用无缺失。源码看板截图确认修复后的图标/九业务正常。
- 审阅差异 `.runtime/repository-migration/M0-M4-review.patch`，候选文件及 SHA256 见同目录 candidate-files.json；使用独立索引对原基线检查补丁可应用，不改变真实暂存区。
- 完整上线/回退清单：开发副本 development/REPOSITORY_MIGRATION.md。验收矩阵：development/MIGRATION_VALIDATION.md。所有 M5—M7 项目明确留待授权和真实证据，不把本地测试称为迁移上线。
- 未构建安装包、未公开仓库、未发布、未推送、未付费生图。未运行禁用命令和整套 factory safety。生产数据、旧下载与运行任务均未改动。

### M5 恢复与发布前复核（2026-11-14）

- 用户本次明确授权 M5—M6 的提交推送、统一仓库公开、必要构建、新旧仓过渡发布及真实升级验证，无需逐项重复确认；继续禁止生图、旧仓归档/删除和强推历史。
- 对照 candidate-files.json，58 个候选摘要未变化。远端 fetch 成功，统一源码仍 001706a7/main/PRIVATE，无 Latest/锁；旧软件 1.4.17、旧规则 1793435166580719500，无软件发布锁。详情 m5-remote-baseline.json。
- 412 个受跟踪/候选源码文件及提交消息的凭据格式/私钥/禁止产物路径扫描无命中，历史基线未变化，沿用并复核 M0 的完整可达 blob 和号码上下文审查。报告 m5-candidate-audit.json；公开动作尚未执行。
- 准备版本 1.4.18，package/lock/engine 元数据一致，build-config 2 测试通过。Node 22.20.0、Python 3.14；F盘约12GB空余、C盘约73GB，需控制构建副本数量。现有 Electron/electron-builder 和 Python运行时可检查后复用。
- 本轮尚无构建/上传作业，没有远端写入。下一步完成候选公开/构建审查和依赖一致性核验，提交明确文件、推送并复核 SHA，再按上线顺序推进。

### M5 提交前检查

- Electron 37.10.3、electron-builder 26.15.3、electron-updater 6.8.9 已安装版本与候选 lock 完全匹配，允许复用现有 node_modules。Python独立运行时复用前仍需核对锁与实际包版本。
- 版本更新新增 package-lock.json 差异，属于明确审阅的 1.4.18 元数据变更；其他候选仍在已审阅 58 文件范围。迁移模块 13 项测试通过（0.102 秒）。
- 准备将上述候选及执行文档作为单个源码提交，随后推送已核实 origin/main。当前未改变仓库可见性，未上传安装包。

### M5 源码提交与推送审批受阻

- 本地提交完成：207df6261c300979e02f2760337192b499e6229c，59 个明确候选文件，提交后工作树干净。保留原历史，未强推。
- 普通 git push origin main 两次被自动审批拒绝，命令未执行。第一次理由引用 M0—M4 旧授权；第二次称最新 goal 授权仅视为助手转述，未见可信用户消息。已通过问题请求用户普通回复确认，没有改用其他上传方式绕过。
- 本地源提交和测试证据均保留；远端仍未确认收到新提交，可见性未改，安装包未构建。此条先记录于生产根目录权威文档，Git 副本仍保持干净以便后续构建绑定源码。
- 下一步等待远端写入审批所需明确回复，同时可继续本地运行时/依赖核对。目标保持 active，尚未达到 blocked 条件。

### M5 本地运行时核验与暂存尝试

- 在等待远端写入确认期间未重试 push。旧 1.4.17 安装包 SHA256 与已保存发布证据一致；具备后续隔离真实旧版升级测试的本地产物，尚未执行安装。
- Python ZIP 摘要匹配官方固定规格，现有运行时 33 个核心文件逐字节一致；24 个依赖版本匹配锁。RECORD 检查 2960 文件，8 个命令行启动器缺失，其余无命中，因此选择从已校验 ZIP 和离线 wheelhouse 重新安装依赖，不盲目复用不完整 runtime。
- 已启动一次本地 stage_distribution（build-1.4.18），离线 pip --require-hashes；会话 30419 已退出 1。错误是系统 Temp/pip-target 目录 WinError 5，未联网、未生成安装包。日志 stage-1.4.18.log，失败暂存保留。
- 下一步使用工作区内明确 TMP/TEMP 新目录重新暂存到新目标，避免权限问题；继续等待普通用户回复解除远端写入自动审批拒绝。目标仍 active。

### M5 阻塞检查点：审批无法识别 goal 授权

- r2 暂存仍因 pip 临时目录 WinError 5 失败；已诊断并在经审批的本地离线执行中完成 r3，stage_exit=0，来源 SHA 为 207df626。失败目录均保留，不覆盖。
- build-1.4.18-r3 已安装锁定 24 依赖，独立引擎检查成功；该实际暂存上的 installed-bootstrap 两项测试通过（6.033 秒）。复用已核对版本的 node_modules Junction，真实工作树仍干净。
- NSIS 构建命令被自动审批拒绝，未执行；拒绝理由为“未见可信用户授权，--confirm-build不能替代确认”。与此前两次 push 拒绝同属 goal 授权不被审批识别的问题，未绕过。
- 同一阻塞跨连续三轮仍存在，且本地必要准备已完成；无构建/上传在途作业。后续依赖实际构建/推送/公开，需用户普通消息明确确认。目标标 blocked，而非完成或暂停。
- 接续：收到确认后先核对本地提交/暂存、远端 SHA/版本/锁，再执行 push 与本地 build-installer；禁止重复上次已成功暂存，不删除旧仓或重写历史。

### M5 授权恢复、源码公开与安装包构建

- 用户通过确认问题明确回复“确认授权继续 M5—M6”，前述审批阻塞已解除；提交 207df6261c300979e02f2760337192b499e6229c 已正常推送并核对远端 SHA，无强推。
- NSIS 构建已完成，build-provenance.json 存在且绑定该源码，三项附件摘要由公共 updates release-plan 验证。安装器 133102339 字节，SHA256 bf177fcc7fbfdb79f585499078c4b660e01aec9b7340d67a57d830e8ba6da28f。构建进程已退出；没有 Authenticode 证书（NotSigned），不混同 Ed25519 更新签名。
- 统一仓库已实际公开（认证 GET private=false）。匿名 API 配额耗尽返回 403，随后匿名 raw.githubusercontent.com 精确提交 package.json 下载成功并逐字节匹配，证据 anonymous-source.json。未重放公开写请求。
- 新旧仓库 v1.4.18 Release 与锁均不存在；旧 Latest 保持 v1.4.17。已保存 software-plan-1.4.18.json，尚未发布。正在隔离目录执行实际新 NSIS 安装；后续新仓软件/规则发布、旧仓过渡及真实旧版升级仍待验收。

### M5 安装验收偏差与恢复（尚未发布）

- 第一次真实 NSIS 验证仅指定 /S 与 /D，未指定 /currentuser；发现 HKLM 已有 E:\Program Files\road-rescue-dashboard 的 1.4.17 后，测试进入自动提权分支。父进程已停止，子进程受权限保护不能结束，已请求用户取消。
- 用户回复后核对发现子进程已完成安装：HKLM 卸载记录变为 1.4.18 并指向 nsis-fresh-1.4.18，原 E 盘程序目录不存在。首次安装父句柄退出 -1，不将其记录为完整通过。此为隔离参数遗漏导致的实际程序安装迁移，不能声称原安装未变。
- 已启动经过先前摘要核对的原 1.4.17 安装器，/S /allusers /D=E:\Program Files\road-rescue-dashboard，恢复原程序位置。会话 39587 在途，用户端 UAC 允许待确认。此恢复不操作客户 workspace；尚需核实实际结果。
- 规则迁移计划已生成（未上传）：1794662868654979100，旧签名下界 1793435166580719500，40 文件/9 业务，min_app 1.4.18。后续复用该计划，不重建。
- 新仓与旧仓均未执行 publish。下一步先核验恢复，再以明确 /currentuser 的用户级隔离安装完成真实验证；恢复未确认前不推进发布。

### M5 安装恢复完成与新仓发布在途

- 原 1.4.17 恢复安装会话 39587 退出 0；HKLM 卸载记录及 E 盘 app.asar 均恢复，未发现遗留安装器进程。原用户 workspace 路径仍存在；没有修改其内容，未做无法证明的完整前后数据一致性断言。
- 明确 /currentuser 后隔离 NSIS 会话 15975 退出 0，HKCU 指向 nsis-user-1.4.18，HKLM 仍为原路径 1.4.17。实际安装 resources 上 bootstrap 两测试通过（8.403 秒），引擎 143 文件与来源清单完全一致。
- 以隔离 fresh-profile 启动真实安装版，已生成 initialized 状态及 bundled 活动规则；启动 PID 57968，仅测试模式不自动更新、不生图。窗口未出现在可访问 UI 清单中，尚不标记安装版视觉验收完成。
- 新仓软件 updates publish 已启动，会话 9670，日志 software-publish-unified.log；必须先核对该会话/远端，禁止盲目重放。规则计划已保存且未上传；旧仓过渡未开始。

### M5 完成 / M6 真实升级验证

- 新仓软件 Release 445317583（v1.4.18），旧仓过渡 Release 445320552；两次公共 publish 均退出 0。新仓规则 1794662868654979100 已发布，首次匿名使用端同步 updated，第二次 current。软件与规则均源自 207df626，原签名信任链保留。
- 新旧四附件已分别匿名下载到 public-download-local-service-factory-dev / public-download-local-service-factory-releases，验签/摘要通过；不是本地拷贝缓存。
- 规则 Contents 提交 50d12f50c84e51a0de24e40f58b299713f24b1a5 已通过受保护同步工具快进；索引受跟踪保留。
- 实际发布发现返回链接仍引用创建草稿时的 untagged URL，已修正维护端返回稳定 v/rules 标签链接。另修复 skill 匿名下载 helper 历史脱敏损坏 URL，并补 source_sha 与过渡 target 验证；新仓真实下载缓存复核通过，transition 两测试通过。以上是发布后维护工具修正，不改变已发布 1.4.18 产物来源。
- 真实旧版进程 55032 经本机调试只读确认 packaged=true、1.4.17、旧仓配置及独立数据路径。通过其原 IPC 更新处理器执行检查，使用真实 electron-updater 下载；会话 47276 在途。没有替换更新模块或伪造版本。

### M6 真实升级与恢复验收（2026-11-14）

- 真旧版 1.4.17 经原 IPC/原 updater 从旧源下载验签后 ready；活动任务夹具触发真实 before-quit 保护，不安装。暂停夹具后 app.quit 启动真实 NSIS，额外仅限定 /currentuser 与测试目录保护机器级安装。
- 自动重启未继承测试环境，发现默认资料目录规则被同步为新版本后立即停止测试进程。原 1.4.17 公共 bootstrap/sync 均退出 0，默认规则恢复 1793435166580719500；软件诊断恢复 1.4.17 idle，新增历史/事件元数据保留。不能声称元数据逐字节回滚。
- 随后显式隔离启动实际升级程序，expected=actual=1.4.18、recovered=false，安装标志清除；实际软件 current，新源规则 updated→current。隔离配置、冻结任务/额度记录、原图证据与任务文件全字节保持，见 upgrade-preservation-result.json。
- previous-app 的原 ASAR 字节一致；实际备份 1.4.17 可独立启动初始化，已退出。原机器级程序保持 1.4.17。两次隔离偏差及修复已纳入公开验收说明与发布 skill，后续优先独立 Windows 用户/虚拟机，不复用默认资料目录。
- 实际独立 CLI 断网拒绝同步且指针未变；未来 1.4.19 使用夹具测试，不发布空版本。Node 8 测试通过，首次沙箱 spawn EPERM 保留日志；维护端规则 CAS/回退单方法通过（7.721 秒）。
- 新旧四附件匿名下载逐字节一致，旧 1.4.17 安装包仍可完整匿名下载、原签名和摘要一致。旧两仓 README 已更新统一入口且保留历史全文，未归档/删除。
- M6 尚待最终维护提交正常推送、签名索引保持及远端状态复核；不重构安装包，不覆盖已发布附件。

### M5—M6 最终验收关闭

- 维护提交 2b0d10ff99e8acda742ed23ce5f634f5b986d361 已正常推送，API 核对远端 main 相同；release-index.json 与规则发布提交逐字节相同，blob SHA 662edf3cd502acc9c690069fbcdad7c85fe274ab。
- final-remote-audit.json：双软件 Latest=v1.4.18、均无锁；新规则=1794662868654979100、旧规则=1793435166580719500；三仓公开且均未归档；新软件/规则 tag 均绑定真实构建来源 207df626。
- 最终进程核对无测试安装器/看板在途；原机器级正式安装仍为 1.4.17，默认兼容规则为旧版 1793435166580719500。测试隔离两次偏差和恢复、无人值守/全新 Windows 未验范围完整保留，不抹去失败。
- M5—M6 按本文实际用户级测试范围验收完成；下一版仅夹具验证，没有伪造新发布。M7 不执行，不声称所有用户已升级。最终文档维护不重新打包、不更换已发布资源。
- 交付见 development/M5_M6_RELEASE_VALIDATION.md、REPOSITORY_MIGRATION.md；完整可审阅 Git 差异保存为原工作区 .runtime/repository-migration/M0-M6-review.patch。

### 2026-11-15 后续日常发布：1.4.19

- 用户明确要求执行推送、打包发布及规则发布检查；两个旧仓继续保留，不执行删除。复用统一仓库 Git 副本，远端基线 0edb646、工作树干净，新旧 Latest 均 1.4.18，无锁、无 1.4.19 草稿。
- 修正 development/README.md 与 distribution/README.md 中私有/待迁移旧文字，版本元数据统一为 1.4.19。build-config 两项通过，提交 5dc6e7ba0a7b9df12abc911908f984783d92ca79 已推送并核对远端 SHA。
- rules sync 成功；公共 release-plan 版本 1794673072733071700，changed_files=[]，9 业务验证通过。规则内容无变化，按发布 skill 不重复上传，现有有效规则仍为 1794662868654979100，未推进 min_app。计划作为未发布证据保留。
- 新 stage-1.4.19 从已验证 Python ZIP 和哈希锁定离线 wheelhouse 暂存成功，stage_exit=0；两项独立 bootstrap 测试通过（8.077 秒）。本次不改更新器/安装布局，复用 M6 已验证链路，避免再次触及本机正式安装。
- 构建会话 17536 在途，证据 .runtime/release-20261115/build.log；检查该会话和 build-provenance 后再发布，不重复构建。无在途上传。

### 2026-11-15 构建验收 / 软件发布在途

- 1.4.19 构建退出 0，安装器 133103647 字节，SHA256 5acdd78105e787d28f9495f05a558529724d4e2f5596738950958446f82c4c34；build-provenance 绑定 5dc6e7b，143 个包内引擎文件摘要一致。没有 Authenticode 证书，仍使用原 Ed25519 信任链。
- updater、installed-runtime、main、Python 规格和运行依赖锁与 M6 验证源码完全相同。此次无安装布局/客户端更新逻辑改动，复用已有真实安装链路证据；未执行本机安装/自动重启。
- 本版独立 Python 的全新匿名使用端规则 sync：updated→current，仍为 1794662868654979100。规则计划 changed_files=[]，未重复发布。
- 公共 updates publish 会话 94416 在途，发布计划 software-plan.json 与日志 publish.log 位于 .runtime/release-20261115。必须核对实际远端状态/句柄后继续；不能重放不明确上传。

### 2026-11-15 日常发布完成

- 软件 1.4.19 已发布到统一仓库，Release 445425290，公共 publish 退出 0，完整公开下载摘要及原 Ed25519 签名验证通过；再次 GET 确认 Latest=v1.4.19、无发布锁，四资源齐全。构建来源为 5dc6e7ba0a7b9df12abc911908f984783d92ca79。
- 安装器 133103647 字节，SHA256 5acdd78105e787d28f9495f05a558529724d4e2f5596738950958446f82c4c34；独立匿名清单再验签通过，证据 .runtime/release-20261115/validation.json。无 Authenticode 证书。
- 规则 40 文件没有变化，公共计划 changed_files=[]，没有发布重复规则或提高 min_app。规则仍为 1794662868654979100，本版独立匿名使用端 updated→current 通过。
- 本次复用未改变的已验收安装链路，没有安装/启动正式程序，没有生图、删除/归档旧仓或重写历史。旧软件仓继续提供 1.4.18 过渡包；旧用户可先迁移到 1.4.18，再从统一仓库更新到 1.4.19，或直接下载新版。没有所有用户升级统计，旧仓继续保留。
- 构建、发布和验证作业均已退出；正在将本条发布结果及入口文档提交同步，签名索引必须保持不变。
