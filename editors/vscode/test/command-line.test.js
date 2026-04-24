'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const { parseCommandLine, resolveConfiguredCommand } = require('../src/command-line');

test('parseCommandLine preserves Windows paths with backslashes', () => {
  assert.deepStrictEqual(
    parseCommandLine('C:\\Users\\me\\.venv\\Scripts\\make-ls.exe --flag', 'win32'),
    ['C:\\Users\\me\\.venv\\Scripts\\make-ls.exe', '--flag'],
  );
});

test('resolveConfiguredCommand preserves quoted Windows paths with spaces', () => {
  assert.deepStrictEqual(
    resolveConfiguredCommand(
      '"C:\\Users\\me\\My Repo\\.venv\\Scripts\\make-ls.exe" --flag',
      [],
      'win32',
    ),
    {
      description: 'C:\\Users\\me\\My Repo\\.venv\\Scripts\\make-ls.exe --flag',
      command: 'C:\\Users\\me\\My Repo\\.venv\\Scripts\\make-ls.exe',
      args: ['--flag'],
    },
  );
});

test('parseCommandLine keeps escaped spaces on POSIX', () => {
  assert.deepStrictEqual(
    parseCommandLine('/opt/homebrew/bin/uv run --directory=/tmp/my\\ repo make-ls', 'darwin'),
    ['/opt/homebrew/bin/uv', 'run', '--directory=/tmp/my repo', 'make-ls'],
  );
});

test('package-lock omits resolved URLs', () => {
  const packageLockPath = path.join(__dirname, '..', 'package-lock.json');
  const packageLock = JSON.parse(fs.readFileSync(packageLockPath, 'utf8'));
  const resolvedUrls = [];
  collectResolvedUrls(packageLock, resolvedUrls);
  assert.deepStrictEqual(resolvedUrls, []);
});

function collectResolvedUrls(value, resolvedUrls) {
  if (Array.isArray(value)) {
    for (const entry of value) {
      collectResolvedUrls(entry, resolvedUrls);
    }
    return;
  }
  if (!value || typeof value !== 'object') {
    return;
  }

  for (const [key, entry] of Object.entries(value)) {
    if (key === 'resolved' && typeof entry === 'string') {
      resolvedUrls.push(entry);
      continue;
    }
    collectResolvedUrls(entry, resolvedUrls);
  }
}
