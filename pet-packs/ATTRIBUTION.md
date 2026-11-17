# 素材来源记录

上游项目：[PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet)。高清黄泉的绘制完成度和桌宠布局参考该项目的内置角色素材。上游代码及素材的原有声明保留，不由本文件另行授予许可。

## 原始 Codex 素材标识

- 黄泉：`acheron--lingxiaotian`
- 流萤：`firefly--lingxiaotian`
- 神里绫华：`kamisato-ayaka--lingxiaotian`

标识来自原始本地宠物的 `pet.json`，仅作为来源追溯；不据此推定作者身份或额外许可。原 `pet.json` 未提供单独的素材许可证字段。

## 本次适配

- 黄泉高清版：使用内置 imagegen 按角色基准重绘9组动作，每组6个姿态。原画、姿态网格、设计说明及完整提示词位于 `sources/acheron-hd/`。
- 流萤和神里绫华：从原有精灵图的标准9组动作裁取和转换为透明 VP9 WebM，保留原画外观与角色ID。
- 所有角色默认不显示，需在 dsh-pet 设置中主动选择显示位置；未纳入任何本机账号、收据、实时偏好或个人路径。
