#!/usr/bin/env node
/**
 * 将仓库宠物包安装到 DSH 用户目录，并在更新素材前保留被替换文件。
 * 清单中的哈希和路径在写入前一次性校验；已有角色配置始终保留。
 * @module dsh-pet/tools/install-codex-pets
 */
import { createHash, randomUUID } from "node:crypto";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

const REPOSITORY_ROOT = fileURLToPath(new URL("..", import.meta.url));
const hash = (contents) => createHash("sha256").update(contents).digest("hex");

function containedPath(root, filename) {
  if (
    typeof filename !== "string" ||
    !filename ||
    isAbsolute(filename) ||
    /[\\:\0]/.test(filename)
  ) {
    throw new Error(`Invalid package path: ${filename}`);
  }
  const target = resolve(root, filename);
  const suffix = relative(root, target);
  if (
    !suffix ||
    isAbsolute(suffix) ||
    suffix === ".." ||
    suffix.startsWith(`..${sep}`)
  ) {
    throw new Error(`Package path escapes its root: ${filename}`);
  }
  return target;
}

function rejectLinkedDestination(root, target) {
  for (let cursor = target; ; cursor = dirname(cursor)) {
    try {
      if (lstatSync(cursor).isSymbolicLink())
        throw new Error(`Refusing linked installation destination: ${cursor}`);
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
    if (cursor === root) return;
    if (dirname(cursor) === cursor)
      throw new Error("Installation destination escaped its root");
  }
}

function readManifest(sourceRoot) {
  const nested = join(sourceRoot, "pet-packs", "manifest.json");
  const manifest = JSON.parse(
    readFileSync(
      existsSync(nested) ? nested : join(sourceRoot, "manifest.json"),
      "utf8",
    ),
  );
  if (
    manifest.schemaVersion !== 1 ||
    !Array.isArray(manifest.packs) ||
    !Array.isArray(manifest.files)
  ) {
    throw new Error("Expected pet-pack manifest schemaVersion 1");
  }
  const files = new Map();
  for (const file of manifest.files) {
    containedPath(sourceRoot, file.path);
    if (files.has(file.path) || !/^[a-f0-9]{64}$/.test(file.sha256))
      throw new Error("Invalid manifest file hash");
    files.set(file.path, file.sha256);
  }
  return { packs: manifest.packs, files };
}

function verifiedContents(sourceRoot, filename, files) {
  const source = containedPath(sourceRoot, filename);
  containedPath(
    realpathSync(sourceRoot),
    relative(realpathSync(sourceRoot), realpathSync(source))
      .split(sep)
      .join("/"),
  );
  const contents = readFileSync(source);
  if (!files.has(filename) || hash(contents) !== files.get(filename)) {
    throw new Error(`Package checksum mismatch: ${filename}`);
  }
  return contents;
}

function packSources(pack) {
  if (!/^[a-z0-9][a-z0-9-]{0,63}$/.test(pack.id))
    throw new Error("Invalid pet-pack identifier");
  const prefix = `pet-packs/${pack.id}/`;
  if (
    pack.config !== `${prefix}config.jsonc` ||
    pack.avatar !== `${prefix}avatar.png`
  ) {
    throw new Error(`Unexpected configuration/avatar path: ${pack.id}`);
  }
  if (!Array.isArray(pack.animations) || !pack.animations.length)
    throw new Error(`Missing animations: ${pack.id}`);
  const animations = pack.animations.map((animation) => {
    const filename = animation.file.slice(`${prefix}animations/`.length);
    if (
      animation.file !== `${prefix}animations/${filename}` ||
      !filename.endsWith(".webm") ||
      /[/\\:]/.test(filename)
    ) {
      throw new Error(`Unexpected animation path: ${animation.file}`);
    }
    return {
      source: animation.file,
      target: `${pack.id}-animation/${filename}`,
    };
  });
  return [
    ...animations,
    { source: pack.avatar, target: `${pack.id}-avatar.png` },
    { source: pack.config, target: `${pack.id}-config.jsonc`, config: true },
  ];
}

function prepareOperations({
  sourceRoot,
  petRoot,
  dshHome,
  selected,
  files,
  overwrite,
}) {
  const operations = [],
    preserved = [],
    destinations = new Set();
  for (const pack of selected) {
    for (const source of packSources(pack)) {
      const target = containedPath(petRoot, source.target);
      if (destinations.has(target))
        throw new Error(`Duplicate installation target: ${source.target}`);
      destinations.add(target);
      rejectLinkedDestination(dshHome, target);
      const contents = verifiedContents(sourceRoot, source.source, files);
      const previous = existsSync(target) ? readFileSync(target) : undefined;
      if (previous && (source.config || hash(previous) === hash(contents))) {
        preserved.push(target);
        continue;
      }
      if (previous && !overwrite)
        throw new Error(`Existing asset differs; use --overwrite: ${target}`);
      operations.push({ ...source, target, contents, previous });
    }
  }
  return { operations, preserved };
}

function applyOperations({ operations, petRoot, dshHome }) {
  const replacements = operations.filter((operation) => operation.previous);
  const backupRoot = replacements.length
    ? join(
        dshHome,
        "dsh-pet",
        "pet-pack-backups",
        `${new Date().toISOString().replaceAll(":", "-")}-${randomUUID().slice(0, 8)}`,
      )
    : undefined;
  // 先完成全部旧素材备份，再写新素材，避免中途失败时缺少可恢复副本。
  for (const operation of replacements) {
    const backup = containedPath(
      backupRoot,
      relative(petRoot, operation.target).split(sep).join("/"),
    );
    rejectLinkedDestination(dshHome, backup);
    mkdirSync(dirname(backup), { recursive: true });
    writeFileSync(backup, operation.previous, { flag: "wx" });
  }
  for (const operation of operations) {
    rejectLinkedDestination(dshHome, operation.target);
    const current = existsSync(operation.target)
      ? readFileSync(operation.target)
      : undefined;
    if (
      current &&
      (!operation.previous || hash(current) !== hash(operation.previous))
    ) {
      throw new Error(
        `Destination changed during installation: ${operation.target}`,
      );
    }
    mkdirSync(dirname(operation.target), { recursive: true });
    writeFileSync(operation.target, operation.contents, {
      flag: operation.previous ? "w" : "wx",
    });
  }
  return backupRoot;
}

/** 校验并安装选中的宠物包；dryRun 只返回计划，已有配置不会被覆盖。 */
export function installPacks({
  sourceRoot = REPOSITORY_ROOT,
  dshHome,
  ids = [],
  dryRun = false,
  overwrite = false,
}) {
  sourceRoot = resolve(sourceRoot);
  dshHome = resolve(dshHome || process.env.DSH_HOME || join(homedir(), ".dsh"));
  const petRoot = join(dshHome, "dsh-pet", "pet");
  const { packs, files } = readManifest(sourceRoot);
  const requested = [
    ...new Set(ids.length ? ids : packs.map((pack) => pack.id)),
  ];
  const selected = requested.map((id) => {
    const matching = packs.filter((pack) => pack.id === id);
    if (matching.length !== 1)
      throw new Error(`Unknown or duplicate pet pack: ${id}`);
    return matching[0];
  });
  const { operations, preserved } = prepareOperations({
    sourceRoot,
    petRoot,
    dshHome,
    selected,
    files,
    overwrite,
  });
  const backupDir = dryRun
    ? undefined
    : applyOperations({ operations, petRoot, dshHome });
  return {
    dryRun,
    packs: requested,
    files: operations.map((operation) => operation.target),
    preserved,
    backupDir,
  };
}

function main() {
  const { values, positionals } = parseArgs({
    allowPositionals: true,
    options: {
      "dsh-home": { type: "string" },
      "dry-run": { type: "boolean" },
      overwrite: { type: "boolean" },
      help: { type: "boolean" },
    },
  });
  if (values.help) {
    console.log(
      "Usage: node tools/install-codex-pets.mjs [pack-id ...] [--dsh-home PATH] [--dry-run] [--overwrite]",
    );
    return;
  }
  const result = installPacks({
    dshHome: values["dsh-home"],
    ids: positionals,
    dryRun: values["dry-run"],
    overwrite: values.overwrite,
  });
  console.log(JSON.stringify(result, null, 2));
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  try {
    main();
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
