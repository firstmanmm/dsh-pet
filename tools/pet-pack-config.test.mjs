/** 使用实际宠物包配置校验原生方向走位、自动动作链和配置保存。 */
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { decideEndedCue } from "../dsh-pet/src/client/pet/animation/cues.ts";
import { planMoveAction } from "../dsh-pet/src/client/pet/motion/move-action.ts";
import { createWalk } from "../dsh-pet/src/client/pet/motion/walk.ts";
import { readAllConfig } from "../dsh-pet/src/host/config/read.ts";
import { saveUserConfig } from "../dsh-pet/src/host/config/save.ts";
import { flattenConfigPets } from "../dsh-pet/src/shared/config.ts";
import { PET_REF_WIDTH } from "../dsh-pet/src/shared/constants.ts";
import { isNoMirrorAnimation } from "../dsh-pet/src/shared/menu/tree.ts";
import { planMove } from "../dsh-pet/src/shared/motion.ts";
import { isEventAnim, rollKind } from "../dsh-pet/src/shared/pickers.ts";
import { parseWeights } from "../dsh-pet/src/shared/weights.ts";
import { installPacks } from "./install-codex-pets.mjs";

const REPOSITORY_ROOT = new URL("../", import.meta.url);
const MANIFEST = JSON.parse(
  readFileSync(new URL("pet-packs/manifest.json", REPOSITORY_ROOT), "utf8"),
);

for (const pack of MANIFEST.packs) {
  const config = JSON.parse(
    readFileSync(new URL(pack.config, REPOSITORY_ROOT), "utf8"),
  );
  const animations = config.animations;

  test(`${pack.id}：待机播完回随机链，空转身池不会被随机选中`, () => {
    assert.ok(animations.idle.length > 0);
    assert.deepEqual(animations.turn, []);
    assert.equal(config.animationWeights.turn, 0);
    assert.deepEqual(parseWeights(config.animationWeights), config.animationWeights);
    for (const current of animations.idle) {
      assert.equal(isEventAnim(animations.events, current), false);
      assert.equal(animations.turn.includes(current), false);
      assert.deepEqual(
        decideEndedCue({ animations, current, workState: null }),
        { kind: "random" },
      );
    }
    for (const [roll, expected] of [[0, "idle"], [.779999, "idle"], [.78, "move"], [.919999, "move"], [.92, "action"], [.999999, "action"]]) {
      assert.equal(rollKind(roll, config.animationWeights), expected);
      assert.notEqual(rollKind(roll, config.animationWeights, { fixed: true }), "turn");
    }
  });

  test(`${pack.id}：保持 left 朝向时，两段原生跑动实际走向正确`, (context) => {
    const random = context.mock.method(Math, "random", () => .5);
    const size = config.pets[0].size;
    const scale = size / PET_REF_WIDTH;
    assert.deepEqual(animations.moves.actions.map((action) => action.name).sort(), ["向右跑", "向左跑"].sort());
    for (const preferredName of ["向左跑", "向右跑"]) {
      const chosen = animations.moves.actions.find((action) => action.name === preferredName);
      const params = { ...animations.moves.default, ...chosen.params };
      assert.equal(isNoMirrorAnimation(animations.categories, preferredName), true);
      assert.ok(preferredName === "向左跑" ? params.minDist > 0 : params.maxDist < 0);
      for (const roll of [0, .5, .999999]) {
        random.mock.mockImplementation(() => roll);
        const result = planMoveAction({
          moves: animations.moves, preferredName, facing: "left", size,
          center: { x: 640, y: 400 }, viewport: { width: 1280, height: 800 },
          halfW: size / 2, sideAllow: 0,
        });
        assert.ok(result);
        assert.equal(result.anim, preferredName);
        assert.equal(result.pending.dir, -1);
        const delta = (result.pending.targetRatio - result.pending.startRatio) * 1280;
        assert.ok(preferredName === "向左跑" ? delta < 0 : delta > 0);
        const distance = Math.floor(params.minDist * scale + roll * (params.maxDist - params.minDist) * scale);
        assert.ok(Math.abs(delta + distance) < 1e-8);
        const desktopPlan = planMove({
          cx: 640, cy: 400, W: 1280, H: 800, dir: -1,
          minDist: params.minDist * scale, maxDist: params.maxDist * scale,
          margin: params.margin, halfW: size / 2,
          areas: [{ x: 0, y: 0, width: 1280, height: 800 }],
        });
        assert.equal(desktopPlan?.targetRatio, result.pending.targetRatio);
      }
    }
  });

  test(`${pack.id}：负距离右跑的中途与落点都向右，不在结束时跳回`, (context) => {
    const previousRaf = globalThis.requestAnimationFrame;
    const previousCancel = globalThis.cancelAnimationFrame;
    let pendingFrame;
    globalThis.requestAnimationFrame = (callback) => { pendingFrame = callback; return 1; };
    globalThis.cancelAnimationFrame = () => { pendingFrame = undefined; };
    context.after(() => {
      if (previousRaf === undefined) delete globalThis.requestAnimationFrame;
      else globalThis.requestAnimationFrame = previousRaf;
      if (previousCancel === undefined) delete globalThis.cancelAnimationFrame;
      else globalThis.cancelAnimationFrame = previousCancel;
    });
    context.mock.method(Math, "random", () => .5);
    const size = config.pets[0].size;
    const boxes = [], commits = [];
    const walk = createWalk({
      root: () => null, center: () => ({ x: 640, y: 400 }),
      metrics: () => ({ size, halfW: size / 2, halfH: size * 9 / 32, sideAllow: 0 }),
      moves: () => animations.moves, facing: () => "left",
      viewport: () => ({ width: 1280, height: 800 }), isFlying: () => false,
      play: (name) => assert.equal(name, "向右跑"),
      setBox: (box) => boxes.push(box), commit: (point) => commits.push(point),
    });
    assert.equal(walk.tryMove("向右跑"), "向右跑");
    const video = { duration: 2, currentTime: 0 };
    walk.start(video);
    for (const time of [0, 1, 2]) {
      video.currentTime = time;
      const callback = pendingFrame;
      pendingFrame = undefined;
      assert.equal(typeof callback, "function");
      callback();
    }
    assert.ok(boxes[1].x > boxes[0].x);
    assert.ok(boxes[2].x > boxes[1].x);
    assert.ok(Math.abs(boxes[1].x - (boxes[0].x + boxes[2].x) / 2) < 1e-8);
    assert.equal(commits.length, 1);
    assert.ok(Math.abs(commits[0].rx * 1280 - size / 2 - boxes[2].x) < 1e-8);
    assert.equal(pendingFrame, undefined);
  });

  test(`${pack.id}：移动结束回随机链，等待、工作与互动保持事件接续`, () => {
    for (const action of animations.moves.actions) {
      assert.deepEqual(
        decideEndedCue({ animations, current: action.name, workState: null }),
        { kind: "random" },
      );
    }
    assert.deepEqual(
      decideEndedCue({ animations, current: "工作", workState: "working" }),
      { kind: "work-replay" },
    );
    assert.deepEqual(
      decideEndedCue({ animations, current: "挥手", workState: null }),
      { kind: "event-done" },
    );
    assert.equal(isEventAnim(animations.events, "等待"), true);
    assert.equal(animations.idle.includes("等待"), false);
    assert.deepEqual(decideEndedCue({ animations, current: "等待", workState: null }), { kind: "event-done" });
    assert.deepEqual(decideEndedCue({ animations, current: "等待", workState: "waiting" }), { kind: "work-replay" });
    for (const name of new Set(Object.values(animations.events).flat(2))) {
      assert.equal(animations.turn.includes(name), false);
      assert.deepEqual(decideEndedCue({ animations, current: name, workState: "success" }), { kind: "event-done" });
    }
  });

  test(`${pack.id}：读取、拍平和保存保留空转身池及负距离`, (context) => {
    const home = realpathSync(mkdtempSync(join(tmpdir(), "dsh-pet-config-roundtrip-")));
    context.after(() => rmSync(home, { recursive: true, force: true }));
    const paths = {
      defaultFile: fileURLToPath(new URL("dsh-pet/assets/config.jsonc", REPOSITORY_ROOT)),
      userFile: join(home, "main-config.jsonc"), petDir: join(home, "pet"),
    };
    mkdirSync(paths.petDir);
    writeFileSync(paths.userFile, readFileSync(paths.defaultFile));
    const saved = saveUserConfig({ pets: config.pets, animationWeights: config.animationWeights }, config);
    assert.ok(saved);
    assert.deepEqual(saved.animations, animations);
    writeFileSync(join(paths.petDir, `${pack.id}-config.jsonc`), JSON.stringify(saved));
    const merged = readAllConfig(paths);
    assert.deepEqual(merged[pack.id].animations, animations);
    assert.deepEqual(merged[pack.id].animationWeights, config.animationWeights);
    const pet = flattenConfigPets(merged).find((item) => item.id === pack.id);
    assert.ok(pet);
    assert.deepEqual(pet.animations.turn, []);
    assert.equal(pet.animationWeights.turn, 0);
    assert.deepEqual(pet.animations.moves, animations.moves);
  });

  test(`${pack.id}：九组实际动作与安装清单一致且通过校验`, (context) => {
    const dshHome = realpathSync(mkdtempSync(join(tmpdir(), "dsh-pet-config-")));
    context.after(() => rmSync(dshHome, { recursive: true, force: true }));
    const referenced = new Set([
      ...animations.idle, ...animations.turn, ...animations.drag, ...animations.clicks,
      ...animations.moves.actions.map((action) => action.name),
      ...animations.categories.flatMap((category) => category.actions),
      ...Object.values(animations.events).flat(2),
    ]);
    assert.equal(referenced.size, 9);
    assert.deepEqual(new Set(pack.animations.map((animation) => animation.name)), referenced);
    const result = installPacks({
      dshHome,
      ids: [pack.id],
      dryRun: true,
    });
    for (const name of referenced) {
      assert.ok(
        result.files.some((path) => path.endsWith(`-animation/${name}.webm`)),
      );
    }
  });
}
