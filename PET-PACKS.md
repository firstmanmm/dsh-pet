# Codex 自定义宠物包

本分支为上游 [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet) 添加三套独立宠物素材，沿用上游的文件宠物机制。

| 种类 ID         | 角色     | 素材                  | 动作数量 |
| --------------- | -------- | --------------------- | -------- |
| `codex-acheron` | 黄泉     | 高清 2D Q 版重绘      | 9        |
| `codex-firefly` | 流萤     | 原 Codex 像素素材适配 | 9        |
| `codex-ayaka`   | 神里绫华 | 原 Codex 像素素材适配 | 9        |

黄泉由统一角色基准生成 54 张姿态图，再裁切、配准并编码；待机带眨眼停留节奏。所有动画为 640×360 VP9-alpha WebM，包含待机、左右跑动、挥手、跳跃、失落、等待、工作和检视。工作状态映射沿用 dsh-pet 的六档协议。

![黄泉高清角色](sources/acheron-hd/character-master.png)

## 安装

先安装并运行 dsh-pet。从本仓库根目录执行，要求 Node.js 22 或更高版本：

```sh
# 预览安装计划，不写入用户目录
node tools/install-codex-pets.mjs --dry-run

# 安装全部三种角色
node tools/install-codex-pets.mjs

# 只安装黄泉；自定义 DSH_HOME 时显式指定目录
node tools/install-codex-pets.mjs codex-acheron --dsh-home /path/to/.dsh
```

目录默认使用 `$DSH_HOME`，未设置时为当前用户的 `~/.dsh`。安装结果遵循上游格式：

```text
$DSH_HOME/dsh-pet/pet/
├── codex-acheron-config.jsonc
├── codex-acheron-avatar.png
└── codex-acheron-animation/*.webm
```

安装器先校验清单中的路径与 SHA256，再执行复制。首次安装的角色默认不显示；打开 **DeepSeek Harness 左下角头像 → 设置 → 桌宠配置**，选择对应种类，将显示位置设为“仅桌面”或“两者都显示”，然后保存。只想显示新角色时，将内置宠物设为“都不显示”。

更新已有素材时使用：

```sh
node tools/install-codex-pets.mjs codex-acheron --overwrite
```

相同素材会跳过；不同素材在未指定 `--overwrite` 时拒绝覆盖。更新前备份将受影响的旧素材，已有角色配置始终保留。安装后通过桌宠右键菜单“重载配置”应用新素材。

## 从原画重建黄泉动画

需要 Python 3、Pillow、ffmpeg 和 ffprobe。图片生成使用内置 imagegen；原画、9 张动作网格及完整提示词均保存在 `sources/acheron-hd/`。

```sh
python tools/prepare-hd-pet.py inspect --image sources/acheron-hd/idle-sheet.png --columns 3 --rows 2
python tools/prepare-hd-pet.py build --manifest sources/acheron-hd/animation-manifest.json --out temp/acheron-hd
```

脚本仅处理真实生成的姿态帧，使用清单中的统一缩放、脚底或腰部配准及停留时间。输出包括透明视频、联系表与逐帧检查结果；重复构建应使用新的输出目录。生成后将视频同步到对应 `pet-packs/<id>/animations/` 并更新素材清单中的哈希。

为保留跑动时飘开的长发，黄泉绘制范围允许延伸到画框 x=160..480；脸部保留在原点击区内。基础动作覆盖上述 9 组，睡觉、吃白饭和 16 方向鼠标注视未配置。

## 源码地图与验证

| 路径                                | 职责                                   |
| ----------------------------------- | -------------------------------------- |
| `pet-packs/manifest.json`           | 素材清单、动画元数据与 SHA256          |
| `pet-packs/<id>/`                   | 可安装的角色配置、头像与动画           |
| `sources/acheron-hd/`               | 黄泉原画、真实动作帧、提示词及配准清单 |
| `tools/install-codex-pets.mjs`      | 跨平台安装、更新与旧素材备份           |
| `tools/install-codex-pets.test.mjs` | 临时目录安装与更新行为测试             |
| `tools/prepare-hd-pet.py`           | 透明动作帧配准、编码与视频检查         |

```sh
node --test tools/install-codex-pets.test.mjs
```

本分支也同步了本机使用的 `PET_ALPHA_FIX_ENABLED = true`，使浏览器与桌面构建共同去除残留的微量灰色背景；滤镜会增加每帧合成开销。

上游声明与原始素材标识见 [来源记录](pet-packs/ATTRIBUTION.md)。这些宠物包位于仓库扩展目录，沿用独立安装流程；现有 npm 包的发布清单与版本保持原状。
