"""只读检查宠物视频，输出透明度验证、动作差异指标与人工审查联系表。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ALPHA_THRESHOLD = 16
TILE = (160, 90)


def premultiplied_rgba(pixels):
    values = pixels.astype(np.float32) / 255
    values[:, :, :3] *= values[:, :, 3:4]
    return values


def difference(left, right):
    return round(float(np.abs(left - right).mean()), 8)


def span(values):
    return [round(float(min(values)), 3), round(float(max(values)), 3)] if values else None


def thumbnail(pixels):
    return Image.fromarray(pixels).convert('RGBa').resize(TILE, Image.Resampling.LANCZOS).convert('RGBA')


def inspect_frames(raw, size):
    width, height = size
    frame_bytes = width * height * 4
    if not raw or len(raw) % frame_bytes:
        raise ValueError('解码结果为空或 RGBA 帧长度不完整')
    frames = np.frombuffer(raw, np.uint8).reshape(-1, height, width, 4)
    samples, changes, centers_x, centers_y, bottoms = [], [], [], [], []
    sample_indices = {round(float(v)) for v in np.linspace(0, len(frames) - 1, min(6, len(frames)))}
    bad_corners, empty, weak_alpha = [], [], []
    first = previous = previous_pixels = None
    run_start = 0
    longest_static_run = {'from': 0, 'to': 0, 'frames': 1}
    for index, pixels in enumerate(frames):
        alpha = pixels[:, :, 3]
        if any(alpha[y, x] != 0 for x, y in [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)]):
            bad_corners.append(index)
        rows, columns = np.nonzero(alpha > ALPHA_THRESHOLD)
        if not rows.size:
            empty.append(index)
        else:
            centers_x.append((int(columns.min()) + int(columns.max()) + 1) / 2)
            centers_y.append((int(rows.min()) + int(rows.max()) + 1) / 2)
        opaque_rows = np.nonzero(alpha >= 200)[0]
        if opaque_rows.size:
            bottoms.append(int(opaque_rows.max()) + 1)
        else:
            weak_alpha.append(index)
        current = premultiplied_rgba(pixels)
        changed = previous_pixels is None or not np.array_equal(pixels, previous_pixels)
        if index in sample_indices:
            samples.append((index, thumbnail(pixels)))
        if changed:
            run_start = index
        run_length = index - run_start + 1
        if run_length > longest_static_run['frames']:
            longest_static_run = {'from': run_start, 'to': index, 'frames': run_length}
        if previous is not None and changed:
            encoded_loop_seam = np.array_equal(previous_pixels, frames[-1]) and np.array_equal(pixels, frames[0])
            changes.append({'from': index - 1, 'to': index, 'difference': difference(previous, current),
                            'encoded_loop_seam': encoded_loop_seam})
        if first is None:
            first = current
        previous, previous_pixels = current, pixels
    seam = difference(previous, first)
    maximum = max((change['difference'] for change in changes), default=0)
    nonseam_maximum = max((change['difference'] for change in changes if not change['encoded_loop_seam']), default=0)
    ratio = round(seam / maximum, 4) if maximum else None
    nonseam_ratio = round(seam / nonseam_maximum, 4) if nonseam_maximum else None
    findings = []
    if nonseam_ratio is not None and nonseam_ratio > 1.25:
        findings.append('首尾差大于片内最大非接缝相邻变化的 1.25 倍，请人工查看循环接缝')
    if not nonseam_maximum and seam > 0:
        findings.append('没有非零的非接缝相邻变化可作比较，比例记为 null，请人工查看循环接缝')
    if not changes:
        findings.append('全部解码帧相同，请确认该动作是否有意保持静止')
    errors = [f'{label}: {indices}' for label, indices in [
        ('非透明角落帧', bad_corners), ('空帧', empty), ('缺少不透明主体的帧', weak_alpha),
    ] if indices]
    return {
        'decoded_frames': len(frames),
        'longest_static_run': longest_static_run,
        'contact_sample_indices': sorted(sample_indices),
        'adjacent_nonduplicate_changes': changes,
        'max_adjacent_difference': maximum,
        'max_nonseam_adjacent_difference': nonseam_maximum,
        'first_last_difference': seam,
        'seam_to_max_adjacent_ratio': ratio,
        'seam_to_max_nonseam_ratio': nonseam_ratio,
        'bbox_center_x_range_px': span(centers_x),
        'bbox_center_y_range_px': span(centers_y),
        'opaque_bottom_range_px': span(bottoms),
        'all_frames_alpha_valid': not errors,
        'potential_findings': findings,
        'errors': errors,
    }, samples + [(len(frames) - 1, thumbnail(frames[-1])), (0, thumbnail(frames[0]))]


def inspect_video(path, entry, record, canvas):
    with path.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    errors = []
    if digest != entry.get('sha256') or digest != record.get('sha256'):
        errors.append('视频 SHA256 与动作或文件清单不一致')
    if path.stat().st_size != record.get('bytes'):
        errors.append('文件字节数与清单不一致')
    probe = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames',
        '-show_entries', 'stream=codec_name,width,height,nb_read_frames:stream_tags=alpha_mode:format=duration',
        '-of', 'json', str(path),
    ], timeout=30))
    stream = probe['streams'][0]
    size = [stream['width'], stream['height']]
    alpha_mode = {key.lower(): value for key, value in stream.get('tags', {}).items()}.get('alpha_mode')
    if stream['codec_name'] != 'vp9' or alpha_mode != '1':
        errors.append('视频必须为 VP9 且声明 alpha_mode=1')
    if size != canvas or size != [entry.get('width'), entry.get('height')]:
        errors.append('视频尺寸与画布或动作清单不一致')
    duration = float(probe['format']['duration'])
    if abs(duration - entry.get('durationSeconds', duration)) > .02:
        errors.append('视频时长与动作清单差异超过 0.02 秒')
    # 默认 VP9 解码器可能丢弃 alpha，必须显式使用 libvpx-vp9。
    raw = subprocess.check_output([
        'ffmpeg', '-v', 'error', '-c:v', 'libvpx-vp9', '-i', str(path),
        '-map', '0:v:0', '-an', '-f', 'rawvideo', '-pix_fmt', 'rgba', 'pipe:1',
    ], timeout=60)
    metrics, samples = inspect_frames(raw, size)
    metrics['longest_static_seconds'] = round(duration * metrics['longest_static_run']['frames'] / metrics['decoded_frames'], 6)
    if entry['name'] == '待机' and metrics['longest_static_seconds'] > .5:
        metrics['potential_findings'].append(
            f"待机连续完全相同帧持续 {metrics['longest_static_seconds']:.3f} 秒，超过 0.5 秒；请检查是否长时间停住后突然切姿态")
    if metrics['decoded_frames'] != entry.get('frames') or metrics['decoded_frames'] != int(stream['nb_read_frames']):
        errors.append('解码帧数与动作清单或 ffprobe 不一致')
    metrics['errors'] = errors + metrics['errors']
    return {
        'name': entry['name'], 'file': entry['file'], 'sha256': digest,
        'codec': stream['codec_name'], 'dimensions': size, 'alpha_mode': alpha_mode,
        'duration_seconds': duration, **metrics,
    }, samples


def contact_sheet(rows, title, output):
    sheet = Image.new('RGB', (8 * TILE[0], 42 + len(rows) * 132), '#202433')
    drawing = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for candidate in ['/System/Library/Fonts/STHeiti Medium.ttc', '/Library/Fonts/Arial Unicode.ttf',
                      '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']:
        if Path(candidate).is_file():
            font = ImageFont.truetype(candidate, 14)
            break
    drawing.text((8, 10), f'{title} | 全时段均匀取样（最多 6 帧）| 末帧 → 首帧（索引从 0 开始）', font=font, fill='white')
    checker = Image.new('RGBA', TILE, '#cbd0da')
    squares = ImageDraw.Draw(checker)
    for top in range(0, TILE[1], 10):
        for left in range(0, TILE[0], 10):
            if (top // 10 + left // 10) % 2:
                squares.rectangle((left, top, left + 9, top + 9), fill='#edf0f5')
    for row_index, (name, samples) in enumerate(rows):
        top = 42 + row_index * 132
        drawing.text((8, top), name, font=font, fill='white')
        for column, sample in enumerate(samples[:-2] + [None] * (8 - len(samples)) + samples[-2:]):
            if sample is None:
                continue
            frame_index, picture = sample
            left = column * TILE[0]
            sheet.paste(Image.alpha_composite(checker, picture).convert('RGB'), (left, top + 20))
            label = ('末帧' if column == 6 else '首帧' if column == 7 else '帧') + f' {frame_index}'
            drawing.text((left + 6, top + 112), label, font=font, fill='white')
    sheet.save(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        parser.error('请把 ffmpeg 和 ffprobe 加入 PATH')
    manifest_path = args.manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    root = manifest_path.parent.parent
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    records = {record['path']: record for record in manifest['files']}
    report = {
        'manifest': str(manifest_path),
        'metric_notes': {
            'difference': '全画布预乘 RGB 与 alpha 的平均绝对差，归一化到 0..1；只跳过连续完全相同的解码帧',
            'bbox': f'alpha > {ALPHA_THRESHOLD} 的主体包围盒中心；自然姿态变化也会改变范围',
            'opaque_bottom': 'alpha >= 200 的最下边缘，作为脚底位置代理；衣服、道具或阴影也可能成为最下边缘',
            'encoded_loop_seam': '相邻帧与整段末帧→首帧在原始 RGBA 像素上分别完全相同，标记为已编码循环接缝',
            'seam_ratio': '保留首尾差 / 最大相邻非重复帧差；人工检查提示使用新增的首尾差 / 最大非接缝相邻帧差',
            'nonseam_ratio': '排除已编码循环接缝后，比例大于 1.25 仅提示人工检查；分母为 0 时比例为 null，首尾仍有变化则提示缺少比较基准',
            'seam_limits': '只识别像素完全相同的循环接缝；有损编码误差或相似但不同的重复接缝仍可能留在分母中',
            'static_run': '原始 RGBA 完全相同的最长连续帧段，from/to 为含端点的索引，frames 为帧数；并列取最早一段，不跨首尾拼接',
            'static_seconds': '最长帧段帧数 × 视频时长 / 解码帧数，按恒定帧率估算；待机超过 0.5 秒仅提示人工检查，不判失败',
            'contact_samples': '按帧索引在全时段均匀取最多 6 帧，另列末帧与首帧；抽样可能遗漏短暂动作，不能代替播放审查',
            'limits': '不评估角色一致性、肢体合理性或不同动作之间的姿态衔接；单次动作首尾不同可能完全合理',
        },
        'packs': [],
    }
    for pack in manifest['packs']:
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', pack['id']):
            raise ValueError('宠物 ID 不能用作安全的输出文件名')
        result = {'id': pack['id'], 'name': pack['name'], 'animations': []}
        rows = []
        for entry in pack['animations']:
            try:
                path = (root / entry['file']).resolve()
                if not path.is_relative_to(root):
                    raise ValueError('素材路径越过仓库根目录')
                metrics, samples = inspect_video(path, entry, records[entry['file']], manifest['canvas'])
                rows.append((entry['name'], samples))
            except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError) as error:
                metrics = {'name': entry['name'], 'file': entry['file'], 'errors': [str(error)]}
            result['animations'].append(metrics)
            print(f"{pack['id']} / {entry['name']}: {'FAIL' if metrics['errors'] else 'OK'}", flush=True)
        result['contact_sheet'] = f"{pack['id']}-contact-sheet.png"
        contact_sheet(rows, pack['name'], output / result['contact_sheet'])
        (output / f"{pack['id']}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        report['packs'].append(result)
    report['errors'] = sum(bool(animation['errors']) for pack in report['packs'] for animation in pack['animations'])
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"报告：{output / 'report.json'}；失败视频：{report['errors']}")
    raise SystemExit(1 if report['errors'] else 0)


if __name__ == '__main__':
    main()
