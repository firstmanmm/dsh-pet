# 素材来源记录

上游项目：[PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet)。高清黄泉的绘制完成度和桌宠布局参考该项目的内置角色素材。上游代码及素材的原有声明保留，不由本文件另行授予许可。

## 原始 Codex 素材标识

- 黄泉：[`acheron--lingxiaotian`](https://github.com/legeling/awesome-codex-pet/tree/main/pets/acheron--lingxiaotian)
- 流萤：[`firefly--lingxiaotian`](https://github.com/legeling/awesome-codex-pet/tree/main/pets/firefly--lingxiaotian)
- 神里绫华：[`kamisato-ayaka--lingxiaotian`](https://github.com/legeling/awesome-codex-pet/tree/main/pets/kamisato-ayaka--lingxiaotian)

来源库为 [legeling/awesome-codex-pet](https://github.com/legeling/awesome-codex-pet)。2026-11-17 核对上述三个目录的 `submission.json`，均标注作者 [legeling](https://github.com/legeling)、`source_type: fan-art`、`license: CC BY-NC 4.0`。目录中的历史 `--lingxiaotian` 后缀保留作素材标识，署名以元数据为准。

原始素材遵循 [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) 及上游 [ASSETS-LICENSE.md](https://github.com/legeling/awesome-codex-pet/blob/main/ASSETS-LICENSE.md) 的说明，须保留署名和改动说明，限非商业使用；上游代码的 MIT 声明不替代素材许可。本次重绘参考了原角色素材，并不表示取得角色权利人的额外授权。

## 本次适配

- 黄泉高清版：使用内置 imagegen 按角色基准重绘9组动作，每组6个姿态。原画、姿态网格、设计说明及完整提示词位于 `sources/acheron-hd/`。
- 流萤和神里绫华：以原有头像为身份参考、高清黄泉为风格参考，使用内置 imagegen 重绘统一角色基准和9组动作，每组6个真实姿态，再按脚底或头部锚点配准并编码为透明 VP9 WebM。角色ID保持原状，源图、提示词及配准清单位于 `sources/firefly-hd/` 和 `sources/ayaka-hd/`。
- 后续动作修订：三套左右跑步各使用内置 imagegen 补画8姿态循环，完整提示词保存在对应源目录。待机复用同一底图，通过局部眼睑组合和微幅呼吸位移编码；原始生成图保留。复制待机的转身别名已删除，自动移动使用原生左右方向素材。
- 所有角色默认不显示，需在 dsh-pet 设置中主动选择显示位置；未纳入任何本机账号、收据、实时偏好或个人路径。
