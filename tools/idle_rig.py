"""将已配准姿态组合为局部眨眼、头部平移和脚底锁定的连续待机帧。"""

from __future__ import annotations

import math

from PIL import Image


def finite_number(value, label, low, high):
    """读取有界有限数值；清单错误统一抛出 ValueError。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{label}: expected a finite number in {low}..{high}')
    return float(value)


def smoothstep(value):
    """返回两端斜率为零的单位区间插值。"""
    return value * value * (3 - 2 * value)


class IdleRig:
    """按最终画布坐标组合帧；源姿态不变，首尾复用基准帧。"""

    def __init__(self, poses, spec, fps):
        if not isinstance(spec, dict) or not poses or any(p.size != poses[0].size for p in poses):
            raise ValueError('idle_rig: expected a mapping and equal-sized source poses')
        self.fps = finite_number(fps, 'idle_rig fps', 12, 60)
        duration = finite_number(spec.get('duration_seconds', 8), 'idle_rig duration_seconds', .5, 30)
        self.count = round(duration * self.fps)
        if abs(self.count - duration * self.fps) > 1e-6:
            raise ValueError('idle_rig: duration_seconds * fps must be an integer')
        self.duration = self.count / self.fps
        self.base_index = self._index(spec.get('base_frame', 0), len(poses))
        self.neutral = poses[self.base_index].convert('RGBA')
        self.base = self.neutral.convert('RGBa')
        self.size = self.base.size
        width, height = self.size
        breath, blink = spec.get('breath', {}), spec.get('blink', {})
        if not isinstance(breath, dict) or not isinstance(blink, dict):
            raise ValueError('idle_rig: breath and blink must be mappings')
        self.cycles = int(finite_number(breath.get('cycles', 2), 'breath cycles', 1, 10))
        if self.cycles != breath.get('cycles', 2):
            raise ValueError('breath cycles must be an integer for a closed loop')
        self.lift = finite_number(breath.get('lift_px', 1.2), 'breath lift_px', 0, 3)
        self.head_y = finite_number(breath.get('head_bottom_y'), 'breath head_bottom_y', 1, height - 2)
        self.lock_y = finite_number(breath.get('lock_y'), 'breath lock_y', self.head_y + 1, height - 1)
        if int(self.head_y) != self.head_y or int(self.lock_y) != self.lock_y:
            raise ValueError('breath head_bottom_y and lock_y must be integer canvas rows')
        self.head_y, self.lock_y = int(self.head_y), int(self.lock_y)
        frames = blink.get('frames', [1, 2])
        if not isinstance(frames, list) or len(frames) != 2:
            raise ValueError('blink frames must contain half-closed and closed source indices')
        self.blink_indices = [self._index(i, len(poses)) for i in frames]
        roi = blink.get('roi')
        if (not isinstance(roi, list) or len(roi) != 4 or
                any(isinstance(v, bool) or not isinstance(v, int) for v in roi) or
                not 0 <= roi[0] < roi[2] <= width or not 0 <= roi[1] < roi[3] <= self.head_y):
            raise ValueError('blink roi must be an integer [x0,y0,x1,y1] within the rigid head region')
        self.roi = tuple(roi)
        patch_size = (roi[2] - roi[0], roi[3] - roi[1])
        self.feather = finite_number(blink.get('feather_px', 2), 'blink feather_px', 0, min(patch_size) / 2)
        self.mask = Image.new('L', patch_size)
        self.mask.putdata([
            round(255 * smoothstep(min(1, min(x, y, patch_size[0] - 1 - x, patch_size[1] - 1 - y) / self.feather)))
            if self.feather else 255
            for y in range(patch_size[1]) for x in range(patch_size[0])
        ])
        half, closed = [poses[i].convert('RGBa').crop(self.roi) for i in self.blink_indices]
        opened = self.base.crop(self.roi)
        self.patches = [opened, half, closed, half, opened]
        self.blink_duration = finite_number(blink.get('duration_seconds', .2), 'blink duration_seconds', 4 / self.fps, .6)
        self.centers = blink.get('centers_seconds', [duration / 4, duration * 3 / 4])
        if not isinstance(self.centers, list):
            raise ValueError('blink centers_seconds must be a list')
        end_time = (self.count - 1) / self.fps
        self.centers = [finite_number(v, 'blink center', self.blink_duration / 2,
                                     end_time - self.blink_duration / 2) for v in self.centers]
        if any(b - a < self.blink_duration for a, b in zip(sorted(self.centers), sorted(self.centers)[1:])):
            raise ValueError('blink intervals must not overlap')

    @staticmethod
    def _index(value, count):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < count:
            raise ValueError(f'idle_rig source frame must be an integer in 0..{count - 1}')
        return value

    def breath_lift(self, index):
        """返回头部上移量；完整周期与相同端点保证循环处速度归零。"""
        if index == 0 or index == self.count - 1:
            return 0.0
        return self.lift * (1 - math.cos(2 * math.pi * self.cycles * index / (self.count - 1))) / 2

    def _breathe(self, frame, lift):
        if lift < 1e-10:
            return frame
        width, height = self.size

        def source_y(y):
            weight = 1 - smoothstep((y - self.head_y) / (self.lock_y - self.head_y))
            return y + lift * weight

        mesh = [((0, 0, width, self.head_y), (0, lift, 0, self.head_y + lift,
                                                       width, self.head_y + lift, width, lift))]
        for top in range(self.head_y, self.lock_y, 4):
            bottom = min(top + 4, self.lock_y)
            mesh.append(((0, top, width, bottom), (0, source_y(top), 0, source_y(bottom),
                                                  width, source_y(bottom), width, source_y(top))))
        moved = frame.convert('RGBa').transform(self.size, Image.Transform.MESH, mesh,
                                               Image.Resampling.BICUBIC).convert('RGBA')
        # 锁定区域直接复用像素，避免采样器在脚底产生亚像素抖动。
        moved.paste(frame.crop((0, self.lock_y, width, height)), (0, self.lock_y))
        return moved

    def frame(self, index):
        """惰性生成一帧；每帧仅从源姿态读取，避免逐帧变形累积。"""
        if not 0 <= index < self.count:
            raise ValueError('idle_rig output frame index is out of range')
        frame = self.neutral.copy()
        if index == 0 or index == self.count - 1:
            return frame
        t = index / self.fps
        for center in self.centers:
            phase = (t - center) / self.blink_duration + .5
            if 0 < phase < 1:
                position = phase * 4
                step = min(3, int(position))
                patch = Image.blend(self.patches[step], self.patches[step + 1], smoothstep(position - step))
                patch = Image.composite(patch, self.patches[0], self.mask).convert('RGBA')
                frame.paste(patch, self.roi[:2])
                break
        return self._breathe(frame, self.breath_lift(index))

    def report(self):
        """提供实际编码参数；标明眨眼使用的源帧和局部变形范围。"""
        return {'method': 'local-blink-and-anchored-breath', 'base_frame': self.base_index,
                'duration_seconds': self.duration, 'rendered_frame_count': self.count,
                'breath': {'cycles': self.cycles, 'lift_px': self.lift,
                           'head_bottom_y': self.head_y, 'lock_y': self.lock_y},
                'blink': {'frames': self.blink_indices, 'roi': list(self.roi), 'feather_px': self.feather,
                          'duration_seconds': self.blink_duration, 'centers_seconds': self.centers}}
