"""验证待机组合的局部性、锁脚、刚性头部、循环速度与配准约束。"""

import copy
import importlib.util
from pathlib import Path
import unittest

from PIL import Image, ImageDraw

from idle_rig import IdleRig

loader = importlib.util.spec_from_file_location('prepare_hd_pet', Path(__file__).with_name('prepare-hd-pet.py'))
builder = importlib.util.module_from_spec(loader)
loader.loader.exec_module(builder)


def fixture():
    """创建带可核对细节和半透明边缘的合成姿态。"""
    base = Image.new('RGBA', (64, 96))
    draw = ImageDraw.Draw(base)
    draw.rectangle((18, 10, 45, 80), fill=(150, 100, 50, 255))
    draw.rectangle((17, 10, 17, 80), fill=(183, 77, 52, 173))
    draw.rectangle((24, 17, 39, 27), fill=(80, 140, 230, 255))
    draw.rectangle((24, 84, 39, 88), fill=(110, 50, 190, 255))
    half, closed = base.copy(), base.copy()
    ImageDraw.Draw(half).rectangle((24, 17, 39, 27), fill=(80, 140, 90, 255))
    ImageDraw.Draw(closed).rectangle((24, 17, 39, 27), fill=(80, 30, 90, 255))
    spec = {'duration_seconds': 8, 'base_frame': 0,
            'breath': {'cycles': 2, 'lift_px': 1.2, 'head_bottom_y': 36, 'lock_y': 70},
            'blink': {'frames': [1, 2], 'roi': [22, 15, 42, 30], 'centers_seconds': [2, 6],
                      'duration_seconds': .2, 'feather_px': 2}}
    return [base, half, closed], spec


class IdleRigTest(unittest.TestCase):
    def test_loop_preserves_neutral_and_feet_for_every_frame(self):
        poses, spec = fixture()
        before = [p.tobytes() for p in poses]
        rig = IdleRig(poses, spec, 30)
        self.assertEqual(rig.count, 240)
        self.assertEqual(rig.frame(0).tobytes(), before[0])
        self.assertEqual(rig.frame(239).tobytes(), before[0])
        feet = poses[0].crop((0, 70, 64, 96)).tobytes()
        longest_hold = hold = 0
        previous = None
        for index in range(rig.count):
            frame = rig.frame(index)
            self.assertEqual(frame.crop((0, 70, 64, 96)).tobytes(), feet)
            self.assertEqual(frame.getpixel((0, 0))[3], 0)
            pixels = frame.tobytes()
            hold = hold + 1 if pixels == previous else 1
            longest_hold = max(hold, longest_hold)
            previous = pixels
        self.assertLessEqual(longest_hold / rig.fps, .3)
        self.assertEqual([p.tobytes() for p in poses], before)

    def test_blink_only_changes_roi_and_uses_closed_pose(self):
        poses, spec = fixture()
        spec['breath']['lift_px'] = 0
        rig = IdleRig(poses, spec, 30)
        closed = rig.frame(60)
        self.assertEqual(closed.getpixel((31, 22)), poses[2].getpixel((31, 22)))
        self.assertEqual(closed.getpixel((22, 15)), poses[0].getpixel((22, 15)))
        restored = closed.copy()
        restored.paste(poses[0].crop(rig.roi), rig.roi[:2])
        self.assertEqual(restored.tobytes(), poses[0].tobytes())
        self.assertEqual(rig.frame(56).tobytes(), poses[0].tobytes())
        self.assertEqual(rig.frame(64).tobytes(), poses[0].tobytes())

    def test_head_translates_without_scaling_and_feet_stay_exact(self):
        poses, spec = fixture()
        rig = IdleRig(poses, spec, 30)
        moved = rig._breathe(poses[0], 1)
        self.assertEqual(moved.crop((18, 9, 46, 34)).tobytes(), poses[0].crop((18, 10, 46, 35)).tobytes())
        self.assertEqual(moved.crop((0, 70, 64, 96)).tobytes(), poses[0].crop((0, 70, 64, 96)).tobytes())

    def test_breath_is_small_and_starts_and_ends_at_rest(self):
        poses, spec = fixture()
        rig = IdleRig(poses, spec, 30)
        lifts = [rig.breath_lift(i) for i in range(rig.count)]
        changes = [abs(b - a) for a, b in zip(lifts, lifts[1:])]
        self.assertEqual(lifts[0], lifts[-1])
        self.assertLess(changes[0], .001)
        self.assertLess(changes[-1], .001)
        self.assertLess(max(changes), .04)
        self.assertLessEqual(max(lifts), 1.2)
        self.assertGreater(max(lifts), 1.19)

    def test_invalid_rigs_fail_before_rendering(self):
        poses, spec = fixture()
        cases = [('breath', 'cycles', 1.5), ('breath', 'head_bottom_y', 25),
                 ('blink', 'roi', [22, 15, 42, 37]), ('blink', 'frames', [1, 99]),
                 ('blink', 'centers_seconds', [0, 6]), ('blink', 'centers_seconds', [2, 2.1])]
        for section, key, value in cases:
            with self.subTest(key=key, value=value):
                invalid = copy.deepcopy(spec)
                invalid[section][key] = value
                with self.assertRaises(ValueError):
                    IdleRig(poses, invalid, 30)


class PlacementTest(unittest.TestCase):
    def test_anchor_accounts_for_source_scale_and_offset(self):
        actions = [{'name': '待机', 'cells': [Image.new('RGBA', (512, 512))],
                    'scale_origin': [256, 450], 'frame_offsets': [[-10, 0]],
                    'action_scale': .9, 'source_factor': 1}]
        spec = {'standing_scale': .6, 'standing_anchor': {'animation': '待机', 'source_x': 266, 'target_x': 320}}
        scale, x, y = builder.placement(spec, actions, [80, 30, 430, 470], [160, 54, 480, 330])
        self.assertEqual(scale, .6)
        self.assertAlmostEqual(256 * scale + x, 320)
        self.assertAlmostEqual(470 * scale + y, 330)

    def test_explicit_scale_does_not_silently_shrink(self):
        with self.assertRaisesRegex(ValueError, 'widen target_box'):
            builder.placement({'standing_scale': 1}, [], [0, 0, 500, 500], [160, 54, 480, 330])


if __name__ == '__main__':
    unittest.main()
