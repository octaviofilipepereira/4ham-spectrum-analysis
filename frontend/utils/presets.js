export function loadPresetsFromJson(text) {
  const parsed = JSON.parse(text);
  if (!Array.isArray(parsed)) {
    throw new Error("Invalid presets file");
  }
  return parsed;
}
