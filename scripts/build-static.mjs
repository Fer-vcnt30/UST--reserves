import {mkdir, copyFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve, dirname} from 'node:path';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
await mkdir(resolve(root, 'dist', 'static'), {recursive: true});
for (const file of ['index.html', 'static/app.js', 'static/style.css']) {
  await copyFile(resolve(root, file), resolve(root, 'dist', file));
}
console.log('Frontend listo en dist/. La API se conecta a Render mediante netlify.toml.');
