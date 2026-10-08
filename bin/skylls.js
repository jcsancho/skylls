#!/usr/bin/env node
// npm launcher for skylls, which is a Python 3.11+ program with no dependencies.
// It runs the Python sources shipped in this package: python3 -m skylls <args>.
"use strict";

const { spawnSync } = require("child_process");
const path = require("path");

const root = path.resolve(__dirname, "..");
const candidates = [process.env.SKYLLS_PYTHON, "python3.14", "python3.13", "python3.12", "python3.11", "python3", "python"]
  .filter(Boolean);

function version(cmd) {
  const res = spawnSync(cmd, ["-c", "import sys; print('%d.%d' % sys.version_info[:2])"], { encoding: "utf8" });
  if (res.status !== 0 || !res.stdout) return null;
  const [major, minor] = res.stdout.trim().split(".").map(Number);
  return { major, minor };
}

const python = candidates.find((cmd) => {
  const v = version(cmd);
  return v && (v.major > 3 || (v.major === 3 && v.minor >= 11));
});

if (!python) {
  console.error(
    "skylls needs Python 3.11 or newer, which wasn't found.\n" +
      "  macOS:  brew install python      Linux: use your package manager, or https://www.python.org/downloads/\n" +
      "  (or point SKYLLS_PYTHON at a python3.11+ binary)"
  );
  process.exit(1);
}

const env = { ...process.env, PYTHONPATH: [root, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter) };
const res = spawnSync(python, ["-m", "skylls", ...process.argv.slice(2)], { stdio: "inherit", env });
if (res.error) {
  console.error(`skylls: could not run ${python}: ${res.error.message}`);
  process.exit(1);
}
process.exit(res.status === null ? 1 : res.status);
