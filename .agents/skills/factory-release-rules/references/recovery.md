# 规则发布中断与冲突

先定位已保存计划版本、原 `base_sha`、payload 和精确 `rules-<版本>` Release。`.runtime/private` 中旧脚本含固定版本/Release ID，只是历史证据，不是可直接复用的公共入口。

1. 上传/创建 Release 请求超时，先 GET 精确 tag 和 assets；读取本地状态及相关发布进程。有效 `rules.zip` 和 `manifest.json` 不重复上传，不创建同名 Release，不覆盖同名不同摘要资源。
2. 所有资源按大小、摘要和 Ed25519 签名核对；必须对应原计划。CLI 可用于补传缺失资产，GitHub connector 可用于带 SHA 的 Contents 更新；connector 没有二进制 Release 上传能力时使用已登录的 gh/原协议。不把登录 Chrome 当成 gh 凭证。
3. 只在本次 Release 完整且签名正确后公开。无凭证下载 ZIP 和 manifest，按现有 `protocol.verify`、`unpack`、`validate_business` 复核，不能只信 GitHub asset digest。
4. 更新指针前重新读取 `release-index.json`：若已是本版且完整签名 payload 相同，说明失联 PUT 已成功，补记本地 remote_head 即可；若 SHA 仍等于计划 base_sha，则以该 SHA 比较交换。首版不存在时才使用 create；禁止强制覆盖并发更新。
5. SHA 已变为其他版本时停止发布本计划，保留本次 Release。先维护端 sync，检查并发变化，重新生成更高版本计划并重新验证；不要删除已公开版本或把旧 payload 强推为最新版。
6. 指针和公开资源一致后完成隔离 consumer 同步验收，更新维护端基准与记忆。ZIP/签名/同步失败保持旧活动版本，不手工改活动指针。

网络使用已有系统代理。旧进程 PATH 缺 gh 时，仅加 `<local-path>` 到本次 PATH；Python urllib 读取系统代理，CLI 可在本次进程设置 HTTPS_PROXY。不展示 token，不新配中转，不改系统代理。读请求至多三次有界重试；写请求失联先读取状态再决定补做。一次恢复最多两种已知可信传输方式，仍失败则保留计划、草稿和当前指针，报告阻塞点。
