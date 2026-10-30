// Decode a DSH session log (session.v4.jsonl.zstd: concatenated zstd frames) to JSONL on stdout.
// Python's stdlib has no zstd decoder, Node 22's zlib does.
import { readFileSync } from 'node:fs';
import { zstdDecompressSync } from 'node:zlib';

const MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd]);

export function decodeFrames(buf) {
  const starts = [];
  for (let i = buf.indexOf(MAGIC); i !== -1; i = buf.indexOf(MAGIC, i + 4)) starts.push(i);
  // A magic sequence can in principle occur inside compressed data, so a frame that fails to
  // decode is merged with the following one instead of being dropped.
  let out = '';
  let from = starts[0] ?? 0;
  for (let k = 1; k <= starts.length; k++) {
    const to = k < starts.length ? starts[k] : buf.length;
    try {
      out += zstdDecompressSync(buf.subarray(from, to)).toString('utf8');
      from = to;
    } catch (err) {
      if (to === buf.length) throw err;
    }
  }
  return out;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  process.stdout.write(decodeFrames(readFileSync(process.argv[2])));
}
