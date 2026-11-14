# M0—M4 验收证据与交付边界

基线：001706a7b1f3e63a98bcedd659203d3dc41335c2。候选为该提交上的本地差异，尚未提交或推送。生产根目录保留原更新配置；迁移实现位于 .runtime/github-dev-20261114。

| 要求 | 本地证据 | 上线阶段仍需 |
| --- | --- | --- |
| V01 同仓配置/构建一致性 | build-config.test.js 2 项；build-provenance.test.js 2 项；ProvenanceTests | 正式构建并核验包内配置 |
| V02 两种发布顺序 | test_repository_interleaving 对实际发布函数的两顺序状态模拟 | 公开读回 |
| V03 错误 Latest/包不一致 | updates.test.js 7 项；LatestTests/SoftwareFailureTests | 实际 updater 源验证 |
| V04 新仓空索引/旧缓存 | RuleMigrationTests：显式迁移、旧缓存保留、403/坏签名/版本下界 | 真实新仓初始化 |
| V05 CAS/并发代码 | RuleUpdates 精确 publish_cas 方法；test_repository_sync 本地 Git | 发布后远端源码同步 |
| V06 中断/缺附件/残留锁 | SoftwareFailureTests、RecoveryTests、RuleFailureTests、TransitionTests | 核对真实锁/附件后恢复 |
| V07 URL/签名/min_app | RuleMigrationTests 真实 Ed25519；RuleUpdates 不兼容/损坏拒绝 | 新 URL 重新签名及公开验签 |
| V08 双仓过渡 | TransitionTests 四类伪附件逐字节相同、受控目标、空新源拒绝 | 同一实际构建双仓下载摘要 |
| V09 旧软件升级 | 过渡路径模拟、installed-bootstrap 隔离初始化 | 真实 Windows 旧安装版升级，未执行 |
| V10 全新使用端 | installed-bootstrap 两项，RuleUpdates updated/current 路径 | 匿名真实安装及规则同步 |
| V11 有任务/离线/失败 | updates.test.js；RuleUpdates 冻结任务和离线升级精确方法 | 实际安装保护与回退演练 |
| V12 再次源码同步 | test_repository_sync 快进/脏修改/分叉后合并保留索引 | 正式发布后的实际同步 |
| V13 旧入口 | 旧软件/规则只读元数据已核对；代码与文档保留入口 | 上线前后匿名历史附件下载 |

执行限制：未运行任何 dry-run、整套 tests.test_factory_safety 或无关生图预算测试。test_release_robustness_review 是生产图片/修订测试模块，经检查不属于仓库迁移变更面，未重跑。没有调用生产 API、构建安装包、推送、改变可见性或发布。

环境：Windows PowerShell、Python 3.14、Node 本机运行时。测试按短模块/精确方法串行，工具输出封顶；关键退出码与耗时记录在执行台账。系统临时目录/Node spawn/Git sh 映射权限失败保留记录，改用仓库隔离目录或经许可的隔离测试执行；未改断言掩盖失败。

导出验证：412 文件脱敏快照，229 Python AST、41 JavaScript 语法、21 SVG namespace 通过；三项完整性元数据逐字节保留；签名 release-index.json 不由导出器复制。git diff --check 通过。测试运行目录仅在 .runtime，客户数据不参与。

M0—M4 的开发完成不等于上线完成。完整上线、恢复和旧仓收尾清单见 REPOSITORY_MIGRATION.md；M5—M7 保持未执行。缺实际安装/公开下载证据的项目不得标为迁移上线完成。

最终源码看板：隔离 Electron 加载当前副本，九业务显示、无 console/load 错误，已人工检查修复后截图。最终短模块结果和候选摘要见原工作区 .runtime/repository-migration/final-test-results.json 与 candidate-files.json。
