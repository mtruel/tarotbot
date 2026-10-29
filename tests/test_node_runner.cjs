const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const path = require("node:path");
const test = require("node:test");

test("le test d'historique fonctionne depuis le répertoire tests", () => {
  const result = spawnSync(process.execPath, ["--test", path.join(__dirname, "test_history_js.cjs")], {
    cwd: __dirname,
    encoding: "utf8",
    timeout: 10000,
  });
  assert.equal(result.error, undefined);
  assert.equal(result.status, 0, result.stdout + result.stderr);
});
