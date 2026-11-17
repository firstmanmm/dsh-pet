/** 宠物包安装器的临时目录集成测试。 */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { test } from "node:test";
import { installPacks } from "./install-codex-pets.mjs";

function fixture(context) {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "dsh-pet-install-")));
  context.after(() => rmSync(root, { recursive: true, force: true }));
  const sourceRoot = join(root, "source"),
    dshHome = join(root, "home"),
    id = "codex-test";
  const base = `pet-packs/${id}`;
  const payloads = new Map([
    [
      `${base}/config.jsonc`,
      JSON.stringify({ pets: [{ id, display: "none", name: "测试宠物" }] }),
    ],
    [`${base}/avatar.png`, "avatar-bytes"],
    [`${base}/animations/待机.webm`, "animation-bytes"],
  ]);
  const files = [...payloads].map(([path, contents]) => {
    const target = join(sourceRoot, path);
    mkdirSync(resolve(target, ".."), { recursive: true });
    writeFileSync(target, contents);
    return {
      path,
      sha256: createHash("sha256").update(contents).digest("hex"),
    };
  });
  const manifest = {
    schemaVersion: 1,
    packs: [
      {
        id,
        config: `${base}/config.jsonc`,
        avatar: `${base}/avatar.png`,
        animations: [{ file: `${base}/animations/待机.webm` }],
      },
    ],
    files,
  };
  const manifestPath = join(sourceRoot, "manifest.json");
  writeFileSync(manifestPath, JSON.stringify(manifest));
  return {
    sourceRoot,
    dshHome,
    id,
    manifest,
    manifestPath,
    petRoot: join(dshHome, "dsh-pet", "pet"),
  };
}

test("预演：只验证和列出目标，不创建 DSH 目录", (context) => {
  const input = fixture(context);
  const result = installPacks({ ...input, dryRun: true });
  assert.equal(result.files.length, 3);
  assert.equal(result.dryRun, true);
  assert.equal(existsSync(input.dshHome), false);
});

test("安装：使用 DSH 发现约定，并保留默认隐藏状态", (context) => {
  const input = fixture(context);
  installPacks(input);
  assert.equal(
    readFileSync(
      join(input.petRoot, `${input.id}-animation`, "待机.webm"),
      "utf8",
    ),
    "animation-bytes",
  );
  assert.equal(
    readFileSync(join(input.petRoot, `${input.id}-avatar.png`), "utf8"),
    "avatar-bytes",
  );
  const config = JSON.parse(
    readFileSync(join(input.petRoot, `${input.id}-config.jsonc`), "utf8"),
  );
  assert.equal(config.pets[0].display, "none");
  assert.equal(installPacks(input).files.length, 0);
});

test("默认更新：发现不同素材时，整批拒绝写入", (context) => {
  const input = fixture(context);
  installPacks(input);
  const video = join(input.petRoot, `${input.id}-animation`, "待机.webm");
  writeFileSync(video, "user-edited-animation");
  assert.throws(() => installPacks(input), /use --overwrite/);
  assert.equal(readFileSync(video, "utf8"), "user-edited-animation");
  assert.equal(
    existsSync(join(input.dshHome, "dsh-pet", "pet-pack-backups")),
    false,
  );
});

test("显式更新：备份被替换素材，角色配置保持原文", (context) => {
  const input = fixture(context);
  installPacks(input);
  const video = join(input.petRoot, `${input.id}-animation`, "待机.webm");
  const config = join(input.petRoot, `${input.id}-config.jsonc`);
  const userConfig =
    '// user settings\n{"pets":[{"id":"codex-test","display":"desktop"}]}';
  writeFileSync(video, "previous-animation");
  writeFileSync(config, userConfig);
  const result = installPacks({ ...input, overwrite: true });
  assert.equal(result.files.length, 1);
  assert.equal(
    readFileSync(
      join(result.backupDir, `${input.id}-animation`, "待机.webm"),
      "utf8",
    ),
    "previous-animation",
  );
  assert.equal(
    existsSync(join(result.backupDir, `${input.id}-config.jsonc`)),
    false,
  );
  assert.equal(readFileSync(config, "utf8"), userConfig);
  assert.equal(readFileSync(video, "utf8"), "animation-bytes");
});

test("校验：源素材哈希变化时，不创建目标目录", (context) => {
  const input = fixture(context);
  writeFileSync(
    join(input.sourceRoot, "pet-packs", input.id, "avatar.png"),
    "tampered-avatar",
  );
  assert.throws(() => installPacks(input), /checksum mismatch/);
  assert.equal(existsSync(input.dshHome), false);
});

test("路径守卫：清单中的越界路径在读写前被拒绝", (context) => {
  const input = fixture(context);
  input.manifest.files.push({ path: "../escaped", sha256: "a".repeat(64) });
  writeFileSync(input.manifestPath, JSON.stringify(input.manifest));
  assert.throws(() => installPacks(input), /escapes its root/);
  assert.equal(existsSync(input.dshHome), false);
});

test("路径守卫：目标目录链接不能把写入引到其他位置", (context) => {
  const input = fixture(context);
  const elsewhere = join(input.sourceRoot, "elsewhere");
  mkdirSync(elsewhere);
  mkdirSync(join(input.dshHome, "dsh-pet"), { recursive: true });
  try {
    symlinkSync(elsewhere, input.petRoot, "junction");
  } catch (error) {
    if (error.code === "EPERM")
      return context.skip("当前系统未授予创建目录链接的权限");
    throw error;
  }
  assert.throws(() => installPacks(input), /linked installation destination/);
  assert.equal(existsSync(join(elsewhere, `${input.id}-avatar.png`)), false);
});
