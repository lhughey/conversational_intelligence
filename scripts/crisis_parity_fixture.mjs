// Regenerate tests/fixtures/crisis_parity.jsonl: the JavaScript package's
// screenText output for every input, which tests/test_crisis_parity.py
// requires the Python port to reproduce.
//
//   npm pack @meddevkit/crisis-signals@<version>  &&  tar xzf meddevkit-crisis-signals-<version>.tgz
//   node scripts/crisis_parity_fixture.mjs <unpacked package dir> <vectors.jsonl>... > tests/fixtures/crisis_parity.jsonl
//
// Inputs are the package repo's synthetic test vectors (data/vectors*.jsonl),
// plus the edge cases below. No real user text.
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const [pkgDir, ...vectorFiles] = process.argv.slice(2);
if (!pkgDir || vectorFiles.length === 0) {
  console.error('usage: node crisis_parity_fixture.mjs <package dir> <vectors.jsonl>...');
  process.exit(2);
}
const { screenText } = createRequire(import.meta.url)(resolve(pkgDir, 'dist/index.js'));

const EDGE = [
  '',
  '   ',
  'I keep thinking about ending it. Maybe tonight.',
  'This commute is killing me.',
  'This commute is killing me. 🙂 I want to die. 🙃 Not really, I’m kidding.',
  'Dr. Smith said I was fine.\nI don’t feel safe with myself right now…',
  '“I want to die,” she wrote in the novel.',
  'Café notes: naïve résumé. I can’t go on anymore.',
  'When Dad died last year everything was falling apart. I’m doing better now.',
  'I can t cope. Everyone would be better off without me!!! Tonight?',
  'Years ago, before I saw Dr. Patel, I wanted to die.',
];

const seen = new Set();
const rows = [];
const add = (id, text) => {
  if (seen.has(text)) return;
  seen.add(text);
  rows.push({ id, text, result: screenText(text) });
};
EDGE.forEach((t, i) => add(`edge-${i}`, t));
for (const file of vectorFiles) {
  for (const line of readFileSync(file, 'utf8').split('\n')) {
    if (!line.trim()) continue;
    const v = JSON.parse(line);
    add(v.id, v.text);
  }
}
for (const row of rows) process.stdout.write(JSON.stringify(row) + '\n');
