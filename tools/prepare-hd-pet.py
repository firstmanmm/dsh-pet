"""将已生成的透明动作帧裁切、配准并编码为 dsh-pet 素材。

用法与清单格式见仓库根目录 PET-PACKS.md。需要 Pillow、ffmpeg 和 ffprobe。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from idle_rig import IdleRig, finite_number

CANVAS = (640, 360)
TARGET = (204, 54, 436, 330)
ALPHA_THRESHOLD = 16
CLEAN_ALPHA_THRESHOLD = 3


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean_alpha_noise(image: Image.Image) -> Image.Image:
    """仅清除微量 alpha 噪声，保留可见的抗锯齿边缘。"""
    image = image.copy()
    image.putalpha(image.getchannel('A').point(lambda a: 0 if a <= CLEAN_ALPHA_THRESHOLD else a))
    return image


def rgba_info(image: Image.Image, label: str) -> dict:
    alpha = image.getchannel('A')
    mask = alpha.point(lambda a: 255 if a > ALPHA_THRESHOLD else 0)
    box = mask.getbbox()
    if not box:
        raise ValueError(f'{label}: missing artwork (empty alpha)')
    edges = (alpha.crop((0, 0, image.width, 1)),
             alpha.crop((0, image.height - 1, image.width, image.height)),
             alpha.crop((0, 0, 1, image.height)),
             alpha.crop((image.width - 1, 0, image.width, image.height)))
    if any(edge.getextrema()[1] > ALPHA_THRESHOLD for edge in edges):
        raise ValueError(f'{label}: artwork/background touches a cell edge; repair source artwork')
    hist = alpha.histogram()
    transparent_fraction = hist[0] / (image.width * image.height)
    if transparent_fraction < .15:
        raise ValueError(f'{label}: insufficient true transparency ({transparent_fraction:.1%})')
    if alpha.getextrema()[1] < 200:
        raise ValueError(f'{label}: artwork is almost entirely translucent')
    # 分开记录主体外的半透明内容，避免把可见光效误当成微量噪声清除。
    core = alpha.point(lambda a: 255 if a >= 200 else 0)
    core_bbox = core.getbbox()
    feet_band_height = min(20, core_bbox[3] - core_bbox[1])
    feet_band_bbox = core.crop((0, core_bbox[3] - feet_band_height, image.width, core_bbox[3])).getbbox()
    feet_anchor = [(feet_band_bbox[0] + feet_band_bbox[2]) / 2, core_bbox[3]]
    outside = ImageChops.multiply(alpha, ImageChops.invert(core.filter(ImageFilter.MaxFilter(31))))
    outside_hist = outside.histogram()
    return {
        'dimensions': list(image.size), 'bbox': list(box),
        'artwork_dimensions': [box[2] - box[0], box[3] - box[1]],
        'opaque_core_bbox': list(core_bbox),
        'feet_anchor_heuristic_bottom20px': feet_anchor,
        'transparent_fraction': round(transparent_fraction, 6),
        'outside_core_15px_alpha_max': outside.getextrema()[1],
        'outside_core_15px_pixels_alpha_gt3': sum(outside_hist[4:]),
        'outside_core_15px_attention': outside.getextrema()[1] > 3,
        'low_alpha_noise_pixels': sum(hist[1:CLEAN_ALPHA_THRESHOLD + 1]),
        'rgba_sha256': hashlib.sha256(image.tobytes()).hexdigest(),
    }


def load_cells(path: Path, columns: int, rows: int, frames: int | None = None):
    source = Image.open(path)
    if 'A' not in source.getbands() and 'transparency' not in source.info:
        raise ValueError(f'{path}: image has no alpha channel')
    source = source.convert('RGBA')
    if columns < 1 or rows < 1 or source.width % columns or source.height % rows:
        raise ValueError(f'{path}: dimensions {source.size} do not divide into {columns} x {rows} cells')
    count = columns * rows if frames is None else frames
    if count < 1 or count > columns * rows:
        raise ValueError(f'{path}: invalid frame count {count}')
    width, height = source.width // columns, source.height // rows
    cells, info = [], []
    for index in range(count):
        col, row = index % columns, index // columns
        cell = source.crop((col * width, row * height, (col + 1) * width, (row + 1) * height))
        info.append(rgba_info(cell, f'{path.name}, frame {index}'))
        cells.append(clean_alpha_noise(cell))
    return cells, info


def transparent_resize(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    # 使用预乘 alpha 缩放，避免透明边缘出现黑白色边。
    return image.convert('RGBa').resize(size, Image.Resampling.LANCZOS).convert('RGBA')


def verify_video(path: Path, expected_count: int, expected_duration: float, target_box=TARGET) -> dict:
    result = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-count_frames', '-show_entries',
        'stream=codec_name,width,height,nb_read_frames:stream_tags=alpha_mode:format=duration',
        '-of', 'json', str(path),
    ]))
    stream = result['streams'][0]
    assert stream['codec_name'] == 'vp9', path
    assert (stream['width'], stream['height']) == CANVAS, path
    assert stream.get('tags', {}).get('alpha_mode') == '1', path
    assert int(stream['nb_read_frames']) == expected_count, path
    assert abs(float(result['format']['duration']) - expected_duration) < .015, path
    decoded = subprocess.check_output([
        'ffmpeg', '-v', 'error', '-c:v', 'libvpx-vp9', '-i', str(path),
        '-f', 'rawvideo', '-pix_fmt', 'rgba', 'pipe:1',
    ])
    frame_bytes = CANVAS[0] * CANVAS[1] * 4
    assert len(decoded) == frame_bytes * expected_count, path
    union = None
    for index in range(expected_count):
        rgba = Image.frombytes('RGBA', CANVAS, decoded[index * frame_bytes:(index + 1) * frame_bytes])
        alpha = rgba.getchannel('A')
        bbox = alpha.point(lambda a: 255 if a > ALPHA_THRESHOLD else 0).getbbox()
        assert bbox, (path, index, 'missing decoded artwork')
        assert alpha.getextrema()[0] == 0 and alpha.getextrema()[1] >= 200, (path, index)
        for xy in [(0, 0), (639, 0), (0, 359), (639, 359)]:
            assert alpha.getpixel(xy) == 0, (path, index, 'background not transparent')
        # 为 LANCZOS 抗锯齿边缘保留4像素余量。
        assert bbox[0] >= target_box[0] - 4 and bbox[1] >= target_box[1] - 4, (path, index, bbox)
        assert bbox[2] <= target_box[2] + 4 and bbox[3] <= target_box[3] + 4, (path, index, bbox)
        union = bbox if union is None else (min(union[0], bbox[0]), min(union[1], bbox[1]),
                                           max(union[2], bbox[2]), max(union[3], bbox[3]))
    return {'frames': expected_count, 'duration': float(result['format']['duration']),
            'codec': 'vp9', 'alpha': True, 'all_frame_alpha_verified': True,
            'decoded_union_bbox': list(union), 'sha256': sha(path)}


def contact_sheet(actions, output: Path):
    rows = sum(math.ceil(len(action['rendered']) / 6) for action in actions)
    sheet = Image.new('RGB', (960, rows * 120), '#202433')
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 12)
    except OSError:
        font = ImageFont.load_default()
    row = 0
    for action in actions:
        for index, frame in enumerate(action['rendered']):
            x, y = (index % 6) * 160, (row + index // 6) * 120
            small = transparent_resize(frame, (160, 90))
            sheet.paste(small, (x, y + 22), small)
            draw.text((x + 5, y + 4), f"{action['name']} {index + 1}", font=font, fill='white')
        row += math.ceil(len(action['rendered']) / 6)
    sheet.save(output)


def placement(spec, actions, union, target_box):
    """计算共享比例和身体轴位置；显式比例越界时要求扩大目标框。"""
    scale = min((target_box[2] - target_box[0]) / (union[2] - union[0]),
                (target_box[3] - target_box[1]) / (union[3] - union[1]))
    if 'standing_scale' in spec:
        scale = finite_number(spec['standing_scale'], 'standing_scale', .05, 4)
    offset_x = (target_box[0] + target_box[2]) / 2 - ((union[0] + union[2]) / 2) * scale
    anchor = spec.get('standing_anchor')
    if anchor is not None:
        if not isinstance(anchor, dict):
            raise ValueError('standing_anchor must be a mapping')
        action = next((a for a in actions if a['name'] == anchor.get('animation')), None)
        if action is None:
            raise ValueError('standing_anchor animation must name an existing action')
        index = anchor.get('frame', 0)
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(action['cells']):
            raise ValueError('standing_anchor frame must name an existing source frame')
        source_x = finite_number(anchor.get('source_x'), 'standing_anchor source_x', 0, action['cells'][index].width)
        target_x = finite_number(anchor.get('target_x', CANVAS[0] / 2), 'standing_anchor target_x', 0, CANVAS[0])
        origin_x = action['scale_origin'][0]
        axis = ((source_x + action['frame_offsets'][index][0] - origin_x) * action['action_scale'] + origin_x)
        offset_x = target_x - axis * action['source_factor'] * scale
    offset_y = target_box[3] - union[3] * scale
    projected = [union[0] * scale + offset_x, union[1] * scale + offset_y,
                 union[2] * scale + offset_x, union[3] * scale + offset_y]
    if any(projected[i] < target_box[i] - 4 for i in (0, 1)) or any(projected[i] > target_box[i] + 4 for i in (2, 3)):
        raise ValueError('standing_scale/standing_anchor places artwork outside target_box; widen target_box explicitly')
    return scale, offset_x, offset_y


def build(args):
    if shutil.which('ffmpeg') is None or shutil.which('ffprobe') is None:
        raise ValueError('ffmpeg and ffprobe must be on PATH')
    manifest_path = args.manifest.resolve()
    spec = json.loads(manifest_path.read_text(encoding='utf-8'))
    source_root = manifest_path.parent
    out = args.out.resolve()
    target_box = spec.get('target_box', list(TARGET))
    if (not isinstance(target_box, list) or len(target_box) != 4 or
        not all(isinstance(v, (int, float)) and math.isfinite(v) for v in target_box) or
        not 0 <= target_box[0] < target_box[2] <= CANVAS[0] or
        not 0 <= target_box[1] < target_box[3] <= CANVAS[1]):
        raise ValueError('target_box must be a finite [x0,y0,x1,y1] inside640x360')
    canonical_path = source_root / spec['canonical']
    canonical = Image.open(canonical_path).convert('RGBA')
    canonical_info = rgba_info(canonical, canonical_path.name)
    canonical = clean_alpha_noise(canonical)
    actions, names = [], set()
    union = None
    reference_size = None
    quality_warnings = []
    for entry in spec['animations']:
        name = entry['name']
        if not name or any(c in name for c in '/\\:') or name in names:
            raise ValueError(f'Unsafe or duplicate animation name: {name}')
        names.add(name)
        path = source_root / entry['image']
        cells, info = load_cells(path, int(entry['columns']), int(entry['rows']), entry.get('frames'))
        if len(cells) < 2 or len({i['rgba_sha256'] for i in info}) < 2:
            raise ValueError(f'{name}: supply at least two genuinely distinct generated poses')
        width, height = cells[0].size
        if reference_size is None:
            reference_size = (width, height)
        action_scale = float(entry.get('action_scale', 1))
        origin = entry.get('scale_origin', [width / 2, height / 2])
        offsets = entry.get('frame_offsets', [[0, 0] for _ in cells])
        if not .25 <= action_scale <= 4 or not math.isfinite(action_scale):
            raise ValueError(f'{name}: action_scale must be finite, 0.25..4')
        if not isinstance(origin, list) or len(origin) != 2 or not all(math.isfinite(float(v)) for v in origin):
            raise ValueError(f'{name}: scale_origin must be a finite [x,y] pair')
        origin = [float(v) for v in origin]
        if len(offsets) != len(cells) or any(not isinstance(v, list) or len(v) != 2 or
                                            not all(math.isfinite(float(n)) for n in v) for v in offsets):
            raise ValueError(f'{name}: frame_offsets must contain one finite [dx,dy] pair per source frame')
        offsets = [[float(n) for n in pair] for pair in offsets]
        # 不同分辨率的帧统一到同一坐标系，仅应用清单明确给出的配准参数。
        factor = reference_size[0] / width
        for frame_info, offset in zip(info, offsets):
            box = [((v + offset[i % 2] - origin[i % 2]) * action_scale + origin[i % 2]) * factor
                   for i, v in enumerate(frame_info['bbox'])]
            union = box if union is None else [min(union[0], box[0]), min(union[1], box[1]),
                                               max(union[2], box[2]), max(union[3], box[3])]
        if min(i['artwork_dimensions'][1] for i in info) < 280:
            quality_warnings.append(f'{name}: at least one source pose has fewer than 280 artwork pixels in height')
        if any(i['outside_core_15px_attention'] for i in info):
            quality_warnings.append(f'{name}: alpha>3 content exists more than15px outside the opaque core; inspect source')
        fps, loops = float(entry.get('fps', 30 if 'idle_rig' in entry else 6)), int(entry.get('loops', 3))
        if not 1 <= fps <= 60 or not 1 <= loops <= 20:
            raise ValueError(f'{name}: fps must be 1..60 and loops 1..20')
        holds = entry.get('frame_holds', [1] * len(cells))
        if len(holds) != len(cells) or any(not isinstance(v, int) or not 1 <= v <= 600 for v in holds):
            raise ValueError(f'{name}: frame_holds must contain one integer (1..600) per source frame')
        actions.append({'name': name, 'path': path, 'cells': cells, 'info': info,
                        'fps': fps, 'loops': loops, 'source_factor': factor,
                        'action_scale': action_scale, 'scale_origin': origin, 'frame_offsets': offsets,
                        'frame_holds': holds, 'idle_rig': entry.get('idle_rig')})
    if not actions:
        raise ValueError('No animations')
    scale, offset_x, offset_y = placement(spec, actions, union, target_box)
    out.mkdir(parents=True, exist_ok=True)
    video_dir = out / 'animations'
    video_dir.mkdir(exist_ok=True)
    frames_root = out / 'frames'
    report = {'canonical': {'file': str(canonical_path), 'sha256': sha(canonical_path), **canonical_info},
              'canvas': list(CANVAS), 'target': list(target_box), 'scale': scale,
              'alpha_noise_cutoff': CLEAN_ALPHA_THRESHOLD, 'geometry_alpha_threshold': ALPHA_THRESHOLD,
              'normalized_source_union': union, 'offset': [offset_x, offset_y],
              'standing_anchor': spec.get('standing_anchor'), 'standing_scale': spec.get('standing_scale'),
              'quality_warnings': quality_warnings, 'animations': []}
    canonical.save(out / 'canonical.png')
    for action in actions:
        frame_dir = frames_root / action['name']
        frame_dir.mkdir(parents=True, exist_ok=True)
        # 拒绝混入旧帧，重建时应使用新的输出目录。
        if list(frame_dir.glob('*.png')):
            raise ValueError(f'{frame_dir}: already contains PNG frames; use a new output folder')
        factor = action['source_factor'] * scale * action['action_scale']
        rendered = []
        for cell, correction in zip(action['cells'], action['frame_offsets']):
            size = (round(cell.width * factor), round(cell.height * factor))
            resized = transparent_resize(cell, size)
            canvas = Image.new('RGBA', CANVAS, (0, 0, 0, 0))
            translation = [(action['scale_origin'][i] * (1 - action['action_scale']) + correction[i] * action['action_scale']) *
                           action['source_factor'] * scale for i in range(2)]
            canvas.paste(resized, (round(offset_x + translation[0]), round(offset_y + translation[1])))
            rendered.append(canvas)
        rig = IdleRig(rendered, action['idle_rig'], action['fps']) if action['idle_rig'] is not None else None
        if rig:
            count = rig.count
            samples = sorted({0, count // 8, count // 2, count * 3 // 4, count - 1,
                              round(rig.centers[0] * action['fps']) if rig.centers else count // 4})
            rendered = []
            for index in range(count):
                frame = rig.frame(index)
                frame.save(frame_dir / f'{index:04d}.png')
                if index in samples:
                    rendered.append(frame)
        else:
            held_sequence = [index for index, hold in enumerate(action['frame_holds']) for _ in range(hold)]
            count = len(held_sequence) * action['loops']
            samples = [sum(action['frame_holds'][:index]) for index in range(len(rendered))]
            for index in range(count):
                rendered[held_sequence[index % len(held_sequence)]].save(frame_dir / f'{index:04d}.png')
        target = video_dir / f"{action['name']}.webm"
        subprocess.run([
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
            '-framerate', str(action['fps']), '-i', str(frame_dir / '%04d.png'),
            '-an', '-c:v', 'libvpx-vp9', '-lossless', '1', '-pix_fmt', 'yuva420p',
            '-auto-alt-ref', '0', '-row-mt', '1', '-threads', '2', str(target),
        ], check=True, capture_output=True)
        video_info = verify_video(target, count, count / action['fps'], target_box)
        action['rendered'] = rendered
        report['animations'].append({'name': action['name'], 'source': str(action['path']),
                                     'source_sha256': sha(action['path']), 'source_frames': action['info'],
                                     'source_frame_count': len(action['cells']), 'rendered_frame_count': count,
                                     'preview_frame_indices': samples,
                                     'action_scale': action['action_scale'], 'scale_origin': action['scale_origin'],
                                     'frame_offsets': action['frame_offsets'],
                                     'frame_holds': None if rig else action['frame_holds'],
                                     'loops': 1 if rig else action['loops'],
                                     'idle_rig': rig.report() if rig else None,
                                     'video': str(target), 'fps': action['fps'], **video_info})
        print(f"{action['name']}: {count} frames, transparency verified", flush=True)
    contact_sheet(actions, out / 'contact-sheet.png')
    (out / 'qa.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'PASS: {out}', flush=True)


def inspect(args):
    cells, frames = load_cells(args.image, args.columns, args.rows, args.frames)
    result = {'file': str(args.image.resolve()), 'frames': frames,
              'distinct_frames': len({frame['rgba_sha256'] for frame in frames})}
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    cmd = commands.add_parser('inspect')
    cmd.add_argument('--image', type=Path, required=True)
    cmd.add_argument('--columns', type=int, default=1)
    cmd.add_argument('--rows', type=int, default=1)
    cmd.add_argument('--frames', type=int)
    cmd.set_defaults(func=inspect)
    cmd = commands.add_parser('build')
    cmd.add_argument('--manifest', type=Path, required=True)
    cmd.add_argument('--out', type=Path, required=True)
    cmd.set_defaults(func=build)
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
