// Orbit native build (Phase 1): precompile the inline JSX block to app.js and
// rewrite index.html to load vendored React + app.js (no CDN, no runtime Babel
// — required to be store-safe). Adapted from MenuCaptain's build.js; Leaflet/map
// vendoring is dropped because Orbit V1 has no maps.
//
// Run with node:  node build.js
// Prereq: vendor React/ReactDOM and fonts into www/vendor/ (see README).
const fs = require("fs");
const path = require("path");

const SRC = path.join(__dirname, "index.html");
const OUT = path.join(__dirname, "www");        // Capacitor webDir

(async () => {
  if (!fs.existsSync(OUT)) fs.mkdirSync(OUT, { recursive: true });
  let html = fs.readFileSync(SRC, "utf8");

  // 1. extract the text/babel block
  const m = html.match(/<script type="text\/babel"[^>]*>([\s\S]*?)<\/script>/);
  if (!m) { console.error("NO BABEL BLOCK"); process.exit(1); }
  const jsx = m[1];

  // 2. version (for the in-app updater regex on index.html)
  const vm = jsx.match(/APP_VERSION\s*=\s*"([^"]+)"/);
  const ver = vm ? vm[1] : "0.0.0";

  // 3. transform JSX -> plain JS (react preset only, same as runtime today)
  const r = await fetch("https://unpkg.com/@babel/standalone@7.23.6/babel.min.js");
  const src = await r.text();
  const mod = { exports: {} };
  new Function("module", "exports", "window", src)(mod, mod.exports, mod.exports);
  const babel = mod.exports.Babel || mod.exports;
  const out = babel.transform(jsx, { presets: ["react"] }).code;
  fs.writeFileSync(path.join(OUT, "app.js"), out, "utf8");

  // 4. rewrite index.html: vendor libs, drop babel, swap block for app.js
  html = html
    .replace("https://cdnjs.cloudflare.com/ajax/libs/react/18.2.0/umd/react.production.min.js", "./vendor/react.production.min.js")
    .replace("https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.2.0/umd/react-dom.production.min.js", "./vendor/react-dom.production.min.js")
    // fonts: drop Google Fonts CDN (preconnects + css2) for vendored local fonts.css
    .replace(/\s*<link rel="preconnect" href="https:\/\/fonts\.googleapis\.com"[^>]*>/, "")
    .replace(/\s*<link rel="preconnect" href="https:\/\/fonts\.gstatic\.com"[^>]*>/, "")
    .replace(/<link href="https:\/\/fonts\.googleapis\.com\/css2[^"]*" rel="stylesheet"\s*\/>/, '<link rel="stylesheet" href="./vendor/fonts.css" />')
    .replace(/<script src="https:\/\/cdnjs\.cloudflare\.com\/ajax\/libs\/babel-standalone\/7\.23\.6\/babel\.min\.js"><\/script>\s*/, "")
    .replace(/<script type="text\/babel"[^>]*>[\s\S]*?<\/script>/, '<script src="./app.js"></script>');

  // keep APP_VERSION discoverable in index.html for the updater
  html = html.replace("</head>", '  <script>/* APP_VERSION = "' + ver + '" (native build marker) */</script>\n</head>');

  fs.writeFileSync(path.join(OUT, "index.html"), html, "utf8");
  console.log("OK ver=" + ver + " app.js=" + out.length + " chars, index.html written to www/");
})();
