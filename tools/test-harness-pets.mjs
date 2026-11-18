#!/usr/bin/env node
/** 在运行中的本地 Harness 逐段点播宠物素材，记录渲染端回执，并在收尾释放测试占用。 */
import { readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { parseArgs } from "node:util";

const { values } = parseArgs({
  options: {
    base: { type: "string" },
    pet: { type: "string", multiple: true },
    out: { type: "string" },
    help: { type: "boolean" },
  },
});
if (values.help || !values.base) {
  console.log("Usage: node tools/test-harness-pets.mjs --base http://127.0.0.1:PORT/dsh-pet-7340/ [--pet codex-acheron] [--out report.json]");
  process.exit(values.help ? 0 : 1);
}
const base = new URL(values.base.endsWith("/") ? values.base : `${values.base}/`);
if (!["127.0.0.1", "localhost", "[::1]"].includes(base.hostname)) {
  throw new Error("测试只接受本机 Harness 地址");
}
const manifest = JSON.parse(await readFile(new URL("../pet-packs/manifest.json", import.meta.url), "utf8"));
const requested = values.pet ?? manifest.packs.map((pack) => pack.id);
const packs = requested.map((id) => {
  const pack = manifest.packs.find((candidate) => candidate.id === id);
  if (!pack) throw new Error(`Unknown pet pack: ${id}`);
  return pack;
});

/** 业务失败和 HTTP 失败都必须中止点播，不能把 accepted 当作已播放。 */
async function request(path, query = {}, body) {
  const url = new URL(path, base);
  for (const [key, value] of Object.entries(query)) url.searchParams.set(key, String(value));
  const response = await fetch(url, {
    method: body === undefined ? "GET" : "POST",
    ...(body === undefined ? {} : {
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
    signal: AbortSignal.timeout(20000),
  });
  const result = await response.json();
  if (!response.ok || result.ok === false) {
    throw new Error(`${path}: ${JSON.stringify(result)}`);
  }
  return result;
}

/** 单次长轮询上限是 10 秒；片段总等待预算由清单时长决定。 */
async function waitForPlayback(playbackId, durationSeconds) {
  const deadline = Date.now() + Math.ceil(durationSeconds * 1000 + 5000);
  let receipt;
  do {
    receipt = await request(`playback/${encodeURIComponent(playbackId)}`, {
      wait: "ended,failed,cancelled",
      timeout: Math.min(10000, Math.max(0, deadline - Date.now())),
    });
    if (["ended", "failed", "cancelled"].includes(receipt.status)) return receipt;
  } while (Date.now() < deadline);
  return receipt;
}

const report = { startedAt: new Date().toISOString(), packs: [], errors: [] };
for (const pack of packs) {
  const result = { id: pack.id, animations: [] };
  report.packs.push(result);
  let lockId;
  try {
    const config = await request("config");
    const instance = config[pack.id]?.pets?.find((pet) => pet.id === pack.id);
    if (instance?.display !== "desktop") {
      throw new Error(`${pack.id}: 请先设为仅桌面显示，以免网页端回执混入测试`);
    }
    result.assetHashes = {};
    for (const animation of pack.animations) {
      const url = new URL(`thumb/${encodeURIComponent(pack.id)}/${encodeURIComponent(animation.name)}.webm`, base);
      const response = await fetch(url, { cache: "no-store", signal: AbortSignal.timeout(20000) });
      if (!response.ok) throw new Error(`${pack.id}/${animation.name}: 素材 HTTP ${response.status}`);
      const digest = createHash("sha256").update(Buffer.from(await response.arrayBuffer())).digest("hex");
      if (digest !== animation.sha256) throw new Error(`${pack.id}/${animation.name}: Harness 素材与本地清单不一致`);
      result.assetHashes[animation.name] = digest;
    }
    result.poseBefore = await request("pose", { pet: pack.id });
    ({ lockId } = await request("lock", { pet: pack.id, surface: "desktop" }, { ttl: 120000 }));
    for (const animation of pack.animations) {
      const playback = await request("anim", { pet: pack.id, surface: "desktop", lock: lockId }, { name: animation.name });
      const receipt = await waitForPlayback(playback.playbackId, animation.durationSeconds);
      result.animations.push(receipt);
      console.log(`${pack.id} / ${animation.name}: ${receipt.status}`);
      if (receipt.status !== "ended") throw new Error(`${pack.id}/${animation.name}: ${receipt.status}`);
    }
    result.poseAfter = await request("pose", { pet: pack.id });
  } catch (error) {
    report.errors.push(String(error));
    console.error(String(error));
  } finally {
    if (lockId) {
      try {
        await request("lock/release", { pet: pack.id }, { lockId });
      } catch (error) {
        report.errors.push(`释放 ${pack.id} 占用失败：${error}`);
      }
    }
  }
}
report.finishedAt = new Date().toISOString();
if (values.out) await writeFile(values.out, `${JSON.stringify(report, null, 2)}\n`);
console.log(`${report.packs.flatMap((pack) => pack.animations).filter((animation) => animation.status === "ended").length} animations ended; ${report.errors.length} errors`);
process.exitCode = report.errors.length ? 1 : 0;
