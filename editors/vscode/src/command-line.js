'use strict';

const fs = require('node:fs');

function resolveConfiguredCommand(command, args, platform = process.platform) {
  if (args.length > 0 || !/\s/.test(command) || fs.existsSync(command)) {
    return {
      description: [command, ...args].join(' '),
      command,
      args,
    };
  }

  const parsedCommandLine = parseCommandLine(command, platform);
  if (parsedCommandLine.length === 0) {
    return {
      description: command,
      command,
      args,
    };
  }

  const [resolvedCommand, ...resolvedArgs] = parsedCommandLine;
  return {
    description: parsedCommandLine.join(' '),
    command: resolvedCommand,
    args: resolvedArgs,
  };
}

function parseCommandLine(commandLine, platform = process.platform) {
  const parts = [];
  let current = '';
  let quote = null;
  let escaping = false;
  const escapeBackslashes = platform !== 'win32';

  for (const character of commandLine) {
    if (escaping) {
      current += character;
      escaping = false;
      continue;
    }

    if (escapeBackslashes && character === '\\' && quote !== '\'') {
      escaping = true;
      continue;
    }

    if (character === '\'' || character === '"') {
      if (quote === character) {
        quote = null;
        continue;
      }
      if (quote === null) {
        quote = character;
        continue;
      }
    }

    if (quote === null && /\s/.test(character)) {
      if (current) {
        parts.push(current);
        current = '';
      }
      continue;
    }

    current += character;
  }

  if (escaping) {
    current += '\\';
  }
  if (current) {
    parts.push(current);
  }
  return parts;
}

module.exports = {
  parseCommandLine,
  resolveConfiguredCommand,
};
