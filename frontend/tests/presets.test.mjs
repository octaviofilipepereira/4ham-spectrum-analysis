import assert from "node:assert/strict";
import { loadPresetsFromJson } from "../utils/presets.js";

const valid = JSON.stringify([
  { name: "Test", band: "20m", gain: 10, sample_rate: 48000, record_path: null }
]);
const invalid = JSON.stringify({ name: "Bad" });

const result = loadPresetsFromJson(valid);
assert.equal(Array.isArray(result), true);
assert.equal(result[0].name, "Test");

let failed = false;
try {
  loadPresetsFromJson(invalid);
} catch (err) {
  failed = true;
}
assert.equal(failed, true);

console.log("presets tests ok");
