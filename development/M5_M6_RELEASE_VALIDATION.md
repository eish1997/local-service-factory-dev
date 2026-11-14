# M5—M6 上线验收（2026-11-14）

统一仓库：https://github.com/eish1997/local-service-factory-dev 。软件与规则产物来源均为 `207df6261c300979e02f2760337192b499e6229c`；规则索引提交 `50d12f50c84e51a0de24e40f58b299713f24b1a5`。后续文档及维护工具修正不改变已发布构建来源。

## 发布结果

| 内容 | 实际结果 |
| --- | --- |
| 新软件 | [v1.4.18](https://github.com/eish1997/local-service-factory-dev/releases/tag/v1.4.18)，Release 445317583 |
| 旧仓过渡 | [v1.4.18](https://github.com/eish1997/local-service-factory-releases/releases/tag/v1.4.18)，Release 445320552 |
| 新规则 | [1794662868654979100](https://github.com/eish1997/local-service-factory-dev/releases/tag/rules-1794662868654979100)，40 文件、9 业务，min_app 1.4.18 |
| 旧规则下界 | 1793435166580719500；旧仓保留该兼容版本 |
| 软件大小 / SHA256 | 133102339 / `bf177fcc7fbfdb79f585499078c4b660e01aec9b7340d67a57d830e8ba6da28f` |
| 规则 ZIP SHA256 | `68b44fb0bdbd4c765fb597d7ca4b6da1a9f84054bfb76450d1ffce2bce12daa8` |
| 信任链 | 沿用 release-2026-09；Ed25519 公开验签通过；安装器没有 Authenticode 身份签名 |

新旧软件 Latest 均为 v1.4.18，规则不占软件 Latest；发布后锁已释放。新旧四类附件分别匿名下载后逐字节相同。下载证据与本地构建目录分开保存，没有用本地包冒充网络下载。旧 1.4.17 完整安装包仍可匿名下载且原签名/摘要一致。

## 端到端证据

证据均在原工作区 `.runtime/repository-migration/`，不上传客户数据或运行目录。

| 验收 | 证据与结果 |
| --- | --- |
| 源码公开与来源 | anonymous-source.json；匿名精确提交文件逐字节匹配。build-provenance.json 绑定 207df626，packaged-engine-audit.json 的 143 引擎文件一致 |
| 真实首次安装 | NSIS /currentuser 退出 0；实际安装 resources 上 bootstrap 两项通过；安装 ASAR 与构建 ASAR 相同 |
| 新使用端 | consumer-sync-first/second.json：独立 Python、无维护凭据，updated→current |
| 双仓一致 | dual-repository-byte-equality.json；两 public-download 目录保存安装器、blockmap、latest.yml、签名清单 |
| 真实旧版本 | old-client-identity.json：实际安装版 1.4.17、packaged=true、旧软件/规则源；非伪造版本适配器 |
| 旧源发现和下载 | 旧程序原 IPC 更新处理器、真实 electron-updater 完成下载与验签，随后状态 ready；旧规则同时同步为原兼容版本 |
| 任务保护 | old-client-active-gate.json：隔离运行任务夹具使实际 before-quit 监听器返回“后台仍有任务，本次退出不安装更新” |
| 真实升级 | 原程序 app.quit→electron-updater→NSIS；安装后 expected=actual=1.4.18，recovered=false，installing 标志清除 |
| 新源请求 | upgraded-client-check/second-check.json：实际升级程序软件 current、新仓规则 updated→current |
| 数据保留 | upgrade-preservation-result.json：隔离私有配置、冻结规则/额度占用记录、任务及原图证据逐字节相同 |
| 恢复入口 | 原 ASAR 备份字节一致；backup-recovery-identity.json 证明 previous-app 中真实 1.4.17 可启动并初始化；已验证安装器保留 |
| 失败保留 | consumer-offline-evidence.json：实际 CLI 断网失败、指针不变；既有精确签名/损坏下载/兼容回退测试通过 |
| 下一版本 | updates.test.js 共 8 项通过，含合成 1.4.19 发现；没有为了验收发布空版本 |
| Git 索引 | 规则发布后受保护同步实际快进至 50d12f50；后续维护提交保持 release-index.json 原字节 |
| 旧入口说明 | 旧软件/规则 README 增加统一入口，保留全文和历史附件；旧仓未归档、未删除 |

## 验证隔离偏差与修复

本机同时存在机器级正式安装和用户级测试安装。首次 NSIS 仅用 /D 不足以隔离：它选择机器级模式并迁移程序目录。已用原 1.4.17 安装器恢复原机器级程序位置，退出 0；随后明确 /currentuser 后真实安装成功。

真实旧版退出升级时，验证启动器仅附加 /currentuser 和明确测试目录，仍调用原 updater 的真实进程启动与 NSIS。安装器自动重启没有继承测试环境，短暂使用默认资料目录并同步新规则；发现后立即停止该测试程序，用原 1.4.17 公共 bootstrap/sync 恢复原兼容规则 1793435166580719500，并纠正软件诊断状态。新增规则历史和事件证据保留，没有删除客户数据或任务。不能将这次恢复描述为所有元数据逐字节回滚。

最终升级程序以明确测试环境手动启动，安装结果与新源检查均通过；所以本次证明的是实际旧包、原更新器和真实 NSIS 的用户级迁移，不宣称无人值守自动重启的资料隔离或所有机器级部署均已验收。后续本机验收必须在独立 Windows 用户/虚拟机中运行，或预先控制安装范围及禁止安装器自动重启，再显式传入隔离环境。

## 交付边界与恢复

- 本机 Windows 的首次安装、旧源升级、新源同步已完成；全新 Windows 虚拟机、其他 Windows 配置及真实下一版本安装不在已取得的证据内。
- 没有付费生图、归档/删除旧仓、强推或改签名信任链；禁用的整套 factory safety 未运行。
- 安装失败保留已验安装器及 previous-app；正式用户降级需明确处理安装范围，不能直接使用本次测试脚本。
- 错误规则仍以更高版本发布已验证旧内容，禁止降低远端索引；本次未人为制造错误线上版本来演练回退。
- 完整上线清单见 REPOSITORY_MIGRATION.md，过程和失败记录见 UNIFIED_REPOSITORY_EXECUTION_PLAN.md。M7 不在本次执行范围，不声称所有用户已经升级。
