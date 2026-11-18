# Codex 自定义宠物包

本分支为上游 [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet) 添加三套独立宠物素材，沿用上游的文件宠物机制。

| 种类 ID         | 角色     | 素材                  | 动作数量 |
| --------------- | -------- | --------------------- | -------- |
| `codex-acheron` | 黄泉     | 高清 2D Q 版重绘      | 9        |
| `codex-firefly` | 流萤     | 高清 2D Q 版重绘      | 9        |
| `codex-ayaka`   | 神里绫华 | 高清 2D Q 版重绘      | 9        |

所有动画为 640×360 VP9-alpha WebM，包含待机、左右跑动、挥手、跳跃、失落、等待、工作和检视。待机使用同一中立底图，编码为 30 fps、8 秒的轻微呼吸与局部眨眼；左右跑步各使用 8 个新绘制姿态，以 12 fps 播放三个周期。工作状态映射沿用 dsh-pet 的六档协议。

自动链关闭转身池及其权重，避免站立数秒后整个人突然镜像。左右移动分别播放原生方向素材：初始朝向保持 `left`，右跑通过负的移动距离向右走；两组动作均列为 `noMirror`。普通待机不加入事件池，播完后仍可进入随机链。旧版复制待机的 `转身.webm` 已移出素材包。

本次问题、修改与验证范围见 [修改记录](PET-PACKS-CHANGES.md)。

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

## 从原画重建动画

需要 Python 3、Pillow、ffmpeg 和 ffprobe。图片生成使用内置 imagegen；三个角色的原画、9 张动作网格、完整提示词及配准清单分别保存在 `sources/acheron-hd/`、`sources/firefly-hd/`、`sources/ayaka-hd/`。

```sh
python tools/prepare-hd-pet.py inspect --image sources/acheron-hd/idle-sheet.png --columns 3 --rows 2
python tools/prepare-hd-pet.py build --manifest sources/acheron-hd/animation-manifest.json --out temp/acheron-hd
python tools/prepare-hd-pet.py build --manifest sources/firefly-hd/animation-manifest.json --out temp/firefly-hd
python tools/prepare-hd-pet.py build --manifest sources/ayaka-hd/animation-manifest.json --out temp/ayaka-hd
```

脚本使用清单中的统一缩放、身体轴配准及姿态时长。`standing_scale` 固定角色比例，`standing_anchor` 将中立身体轴对齐画布 x=320，避免发丝范围改变人物位置。`idle_rig` 在现有姿态上组合局部眨眼与连续呼吸：头部仅平移，肩胸渐变位移，腿脚像素锁定，首尾复用同一中立帧；没有把整张重绘图淡入淡出。眼部 ROI 使用最终 640×360 画布坐标，缩放和定位变动后必须重新检查。

输出包括透明视频、联系表与逐帧检查结果；重复构建应使用新的输出目录。生成后将视频同步到对应 `pet-packs/<id>/animations/`，并更新素材清单中的哈希、字节数和动画元数据。源目录保留旧动作图供比对，实际使用哪张图以 `animation-manifest.json` 为准。

为保留跑动时飘开的长发，黄泉绘制范围允许延伸到画框 x=160..480；脸部保留在原点击区内。基础动作覆盖上述 9 组，睡觉、吃白饭和 16 方向鼠标注视未配置。

## 源码地图与验证

| 路径                                | 职责                                   |
| ----------------------------------- | -------------------------------------- |
| `pet-packs/manifest.json`           | 素材清单、动画元数据与 SHA256          |
| `pet-packs/<id>/`                   | 可安装的角色配置、头像与动画           |
| `sources/*-hd/`                     | 三个角色的原画、真实动作帧、提示词及配准清单 |
| `tools/install-codex-pets.mjs`      | 跨平台安装、更新与旧素材备份           |
| `tools/install-codex-pets.test.mjs` | 临时目录安装与更新行为测试             |
| `tools/prepare-hd-pet.py`           | 透明动作帧配准、编码与视频检查         |
| `tools/idle_rig.py`                | 固定底图的呼吸与局部眨眼组合           |
| `tools/test_idle_rig.py`           | 锁脚、闭环、局部眨眼与配准回归检查     |
| `tools/pet-pack-config.test.mjs`    | 真实播放决策与素材别名的配置回归检查   |
| `tools/inspect-pet-motion.py`       | 逐帧透明度、接缝指标及人工审查联系表   |
| `tools/test-harness-pets.mjs`       | 本机 Harness 实际点播与完成回执检查  |

```sh
node --test tools/install-codex-pets.test.mjs tools/pet-pack-config.test.mjs
python -m unittest discover -s tools -p 'test_idle_rig.py'
# 另需 NumPy；输出目录必须不存在
python tools/inspect-pet-motion.py --manifest pet-packs/manifest.json --out temp/motion-qa
# 启动 Harness 并启用角色的桌面显示后，使用本机实际端口
node tools/test-harness-pets.mjs --base http://127.0.0.1:PORT/dsh-pet-7340/ --out temp/harness-qa.json
```

检查工具区分文件完整性与美术判断：首尾差、相邻帧差及位置范围只用于发现可疑跳变，仍需查看联系表和桌面实际播放。Harness 测试要求目标角色设为“仅桌面”，先核验实际提供的视频 SHA256，再逐角色临时取得占用、点播所有动画、等待真实 `ended` 回执，并在结束或失败时释放占用；它不会修改显示偏好或触发模型对话。

升级已有安装时，安装器会保留用户配置。先备份旧配置，再同步素材包的 `animations` 和 `animationWeights` 两段；保留自己的 `pets`（显示、大小、位置等）及其他偏好，然后重载配置。仅覆盖视频不会自动修复旧的转身池和移动方向配置。旧安装目录中未引用的 `转身.webm` 可随备份一并移除。

本分支也同步了本机使用的 `PET_ALPHA_FIX_ENABLED = true`，使浏览器与桌面构建共同去除残留的微量灰色背景；滤镜会增加每帧合成开销。

上游声明与原始素材标识见 [来源记录](pet-packs/ATTRIBUTION.md)。这些宠物包位于仓库扩展目录，沿用独立安装流程；现有 npm 包的发布清单与版本保持原状。
