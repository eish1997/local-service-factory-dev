# 本地生活服务图片工厂

本仓库维护源码、Windows 软件与项目规则的统一发布流程。当前为迁移开发候选，尚未切换公开或发布新版本。

- 安装使用：迁移上线后从本仓 Releases 的软件 v 标签下载 LocalServiceFactory-版本-setup.exe。GitHub Source code ZIP 只是源码，不是安装包。
- 当前可用软件与旧下载：[旧软件仓](https://github.com/eish1997/local-service-factory-releases/releases/latest)。旧规则仓保留历史与过渡入口。
- 规则以 rules-递增版本标签独立发布，通过签名 release-index.json 发现；更新规则通常不需要重装软件，最低兼容版本由清单约束。
- [开发与 Git 同步](development/README.md) · [迁移与完整上线清单](development/REPOSITORY_MIGRATION.md) · [执行台账](development/UNIFIED_REPOSITORY_EXECUTION_PLAN.md)
- [Agent 入口](AGENTS.md) · [完整帮助](HELP.md) · [统一任务接口](TASK_WORKFLOW.md)
- [工厂 skill](.agents/skills/road-rescue-factory/SKILL.md) · [软件发布](.agents/skills/factory-release-installer/SKILL.md) · [规则发布](.agents/skills/factory-release-rules/SKILL.md)

源码推送不自动发布或生图。客户数据、API 凭据、签名私钥、图片和任务历史不进入仓库。仓库公开不代表已选择开源许可证。
