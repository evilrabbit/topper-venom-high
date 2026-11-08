// Topper colorway editor.
// The shoe's colour is rebuilt every frame from UV-space maps baked in Blender
// (tools/shoe/pipeline/bake_editor_maps.py):
//   id.png      R = part index + 1            shade.png  R = scan shading / 1.6, G = ink mask
//   posHi/Lo    16-bit object-space position  normal.png object-space normal
// final = mix( partColor * mix(1, shade, detail)  ->  ink ,  paint.rgb , paint.a )
// The brush stamps in real 3D distance (posHi/Lo) so it never stretches or tears at UV seams.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
import { RoomEnvironment } from 'three/addons/RoomEnvironment.js';

const MAPS = './maps/';
// material presets, same numbers as tools/shoe/pipeline/materials.py (grain: 0 = none, 1 = coarse nap)
const PRESETS = {
  nubuck:  { rough: 0.96, sheen: 0.55, grain: 0.9 },
  leather: { rough: 0.48, sheen: 0.05, grain: 0.45 },
  patent:  { rough: 0.10, sheen: 0.00, grain: 0.05 },
  rubber:  { rough: 0.62, sheen: 0.00, grain: 0.35 },
  eva:     { rough: 0.74, sheen: 0.05, grain: 0.15 },
  mesh:    { rough: 0.72, sheen: 0.35, grain: 0.6 },
  nylon:   { rough: 0.58, sheen: 0.25, grain: 0.5 },
  print:   { rough: 0.50, sheen: 0.00, grain: 0.05 },
};
const DEFAULT_MATERIAL = (name) => /^(outsole|toe_bumper|heel_ribs)/.test(name) ? 'rubber' : /^(midsole|heel_plate|window_frame)/.test(name) ? 'eva'
  : /^(laces|tongue$|collar)/.test(name) ? 'nylon' : /^lining/.test(name) ? 'mesh' : /badge|logo/.test(name) ? 'print' : /^side_triangle|^triangle|vamp/.test(name) ? 'nubuck' : 'leather';
const STATE = './state/';
const $ = (id) => document.getElementById(id);
const statusEl = $('status');
const setStatus = (t) => { statusEl.textContent = t; };

/* ------------------------------------------------------------------ renderer + scene */
const canvas = $('view');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.toneMapping = THREE.NeutralToneMapping;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.setClearColor(0xf4f2ec, 1);

const scene = new THREE.Scene();
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = 0.9;
scene.add(new THREE.HemisphereLight(0xffffff, 0xd8d2c4, 0.55));
const key = new THREE.DirectionalLight(0xfffaf2, 2.1); key.position.set(2.2, 5.5, 3.2);
const fill = new THREE.DirectionalLight(0xe8eeff, 0.45); fill.position.set(-4, 1.5, 2);
const rim = new THREE.DirectionalLight(0xfff1dc, 0.9); rim.position.set(-3, 3, -4);
scene.add(key, fill, rim);

const camera = new THREE.PerspectiveCamera(30, 1, 0.01, 100);

/* ------------------------------------------------------------------ orbit camera (right drag / space+drag) */
const orbit = { target: new THREE.Vector3(), r: 6, theta: -0.9, phi: 1.2 };
function placeCamera() {
  const { r, theta, phi, target } = orbit;
  camera.position.set(target.x + r * Math.sin(phi) * Math.sin(theta), target.y + r * Math.cos(phi), target.z + r * Math.sin(phi) * Math.cos(theta));
  camera.lookAt(target);
  // keep the key light over the viewer's shoulder so painted areas are always readable
  key.position.copy(camera.position).add(new THREE.Vector3(1.5, 4, 0));
}

/* ------------------------------------------------------------------ helpers */
async function loadRaw(url) {
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  const bmp = await createImageBitmap(await res.blob(), { colorSpaceConversion: 'none', premultiplyAlpha: 'none' });
  const c = new OffscreenCanvas(bmp.width, bmp.height);
  const x = c.getContext('2d', { willReadFrequently: true });
  x.drawImage(bmp, 0, 0);
  return x.getImageData(0, 0, bmp.width, bmp.height);
}
function dataTex(img) {
  const t = new THREE.DataTexture(new Uint8Array(img.data.buffer), img.width, img.height, THREE.RGBAFormat, THREE.UnsignedByteType);
  t.flipY = false; t.minFilter = t.magFilter = THREE.NearestFilter; t.generateMipmaps = false; t.needsUpdate = true;
  return t;
}
const hexToLinear = (hex) => new THREE.Color(hex);                // THREE.Color stores linear values (ColorManagement on)
const linearToHex = (c) => '#' + c.getHexString();
const srgbVec = (hex) => { const c = new THREE.Color(); c.setStyle(hex, THREE.NoColorSpace); return new THREE.Vector3(c.r, c.g, c.b); };

/* ------------------------------------------------------------------ fullscreen UV-space passes */
const passCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2));
quad.frustumCulled = false;
const passScene = new THREE.Scene(); passScene.add(quad);
function runPass(material, target) {
  quad.material = material;
  renderer.setRenderTarget(target);
  renderer.render(passScene, passCam);
  renderer.setRenderTarget(null);
}
const VERT = /* glsl */`
  precision highp float;
  in vec3 position; out vec2 vUv;
  void main() { vUv = position.xy * 0.5 + 0.5; gl_Position = vec4(position.xy, 0.0, 1.0); }`;
const raw = (fragmentShader, uniforms) => new THREE.RawShaderMaterial({ glslVersion: THREE.GLSL3, vertexShader: VERT, fragmentShader, uniforms, depthTest: false, depthWrite: false });

const copyMat = raw(/* glsl */`
  precision highp float; in vec2 vUv; out vec4 o; uniform sampler2D src;
  void main() { o = texture(src, vUv); }`, { src: { value: null } });

/* ------------------------------------------------------------------ boot */
const [meta, idImg, shadeImg, hiImg, loImg, nImg] = await Promise.all([
  fetch(MAPS + 'parts.json', { cache: 'no-store' }).then((r) => r.json()),
  loadRaw(MAPS + 'id.png'), loadRaw(MAPS + 'shade.png'), loadRaw(MAPS + 'posHi.png'), loadRaw(MAPS + 'posLo.png'), loadRaw(MAPS + 'normal.png'),
]);
const RES = meta.res;
const NP = meta.parts.length;
const bsize = new THREE.Vector3(...meta.bboxSize);
const bmin = new THREE.Vector3(...meta.bboxMin);
const unitsPerMm = 1 / meta.mmPerUnit;

let saved = null;
try { const r = await fetch(STATE + 'parts.json', { cache: 'no-store' }); if (r.ok) saved = await r.json(); } catch {}
const parts = meta.parts.map((p, i) => ({ ...p, material: DEFAULT_MATERIAL(p.name), ...(saved?.parts?.find((s) => s.name === p.name) ?? {}) }));
let paintImg;
try { paintImg = await loadRaw(STATE + 'paint.png'); } catch { paintImg = await loadRaw(MAPS + 'paint-seed.png'); }

const idTex = dataTex(idImg), shadeTex = dataTex(shadeImg), hiTex = dataTex(hiImg), loTex = dataTex(loImg), nTex = dataTex(nImg);
const seedTex = dataTex(paintImg);

const mkRT = (o = {}) => new THREE.WebGLRenderTarget(RES, RES, { depthBuffer: false, minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter, generateMipmaps: false, ...o });
let paintRT = [mkRT(), mkRT()];
let cur = 0;
copyMat.uniforms.src.value = seedTex; runPass(copyMat, paintRT[0]);
const compRT = mkRT({ minFilter: THREE.LinearMipmapLinearFilter, magFilter: THREE.LinearFilter, generateMipmaps: true, colorSpace: THREE.SRGBColorSpace, anisotropy: 8 });

/* ------------------------------------------------------------------ composite */
const compMat = raw(/* glsl */`
  precision highp float; precision highp int;
  in vec2 vUv; out vec4 o;
  uniform sampler2D idTex, shadeTex, paintTex, scanTex;
  uniform vec3 uColors[${NP}]; uniform float uDetail[${NP}]; uniform float uForce[${NP}];
  uniform vec3 uLightColor; uniform float uEdgeMode;        // scan-edge mode: light scan texels take the upper's colour
  uniform vec3 uInk; uniform float uPaintDetail; uniform int uHover; uniform float uOutlines; uniform vec2 uTexel;
  vec3 toLin(vec3 c) { return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(0.04045, c)); }
  int partAt(vec2 uv) { return int(texture(idTex, uv).r * 255.0 + 0.5) - 1; }
  uniform float uSmooth;                                   // edge smoothing radius in texels (0 = off)
  // Parts are made of whole scan triangles, so their borders are stair-stepped. Majority vote over a disc:
  // each texel takes the colour most of its neighbourhood belongs to, which rounds the steps into a smooth
  // contour; the vote fraction also gives a soft anti-aliased edge.
  const int TAPS = 32;
  void main() {
    int id = partAt(vUv); int k = clamp(id, 0, ${NP - 1});
    vec2 sh = texture(shadeTex, vUv).rg; float shade = sh.r * 1.6;
    vec3 own = uColors[k] * mix(1.0, shade, uDetail[k]);
    vec3 base = own; float forceSm = uForce[k];
    if (uSmooth > 0.0) {
      float same = 0.0, total = 0.0; vec3 other = vec3(0.0); float otherW = 0.0, otherF = 0.0;
      for (int i = 0; i < TAPS; i++) {
        float a = float(i) * 2.39996323;                      // golden-angle spiral covers the disc evenly
        float r = sqrt((float(i) + 0.5) / float(TAPS)) * uSmooth;
        vec2 o = vec2(cos(a), sin(a)) * r * uTexel / 1.5;
        int j = partAt(vUv + o); int kj = clamp(j, 0, ${NP - 1});
        float w = 1.0;
        total += w;
        if (j == id) same += w; else { other += uColors[kj] * mix(1.0, shade, uDetail[kj]) * w; otherW += w; otherF += uForce[kj] * w; }
      }
      float f = same / total;                                 // share of the neighbourhood that is this part
      if (otherW > 0.0) base = mix(other / otherW, own, smoothstep(0.42, 0.58, f));
      forceSm = mix(otherF / max(total - same, 1e-4), uForce[k], smoothstep(0.42, 0.58, f));
    }
    base = mix(base, uInk, sh.g);
    // scan-edge: part borders are stair-stepped triangles; the scan's own black/white edge is smooth.
    // Where the scan is light and this part is a dark panel (not forced), use the light (upper) colour instead.
    if (uEdgeMode > 0.5 && uForce[k] < 0.5) {
      float lsum = 0.0; vec2 tx = uTexel / 1.5;
      for (int dy = -1; dy <= 1; dy++) for (int dx = -1; dx <= 1; dx++) {
        vec3 sc = texture(scanTex, vUv + vec2(float(dx), float(dy)) * tx * 1.6).rgb;
        lsum += pow(dot(sc, vec3(0.2126, 0.7152, 0.0722)), 1.0 / 2.2) * ((dx == 0 ? 2.0 : 1.0) * (dy == 0 ? 2.0 : 1.0));
      }
      float lb = lsum / 16.0;
      float toLight = smoothstep(0.30, 0.40, lb);
      // near a border with a *different* part the scan groove is a seam, not panel: let the light colour (shaded) win there
      float nearOther = 0.0;
      for (int dy = -2; dy <= 2; dy++) for (int dx = -2; dx <= 2; dx++) { if (partAt(vUv + vec2(float(dx), float(dy)) * tx) != id) nearOther = 1.0; }
      vec3 lightBase = uLightColor * mix(1.0, shade, 0.6);
      float isDark = 1.0 - smoothstep(0.25, 0.45, dot(uColors[k], vec3(0.2126, 0.7152, 0.0722)));
      base = mix(base, lightBase, max(toLight, nearOther * (1.0 - smoothstep(0.08, 0.2, lb)) * 0.0 + nearOther * step(lb, 0.3)) * isDark);
    }
    vec4 p = texture(paintTex, vUv);
    vec3 col = mix(base, toLin(p.rgb) * mix(1.0, shade, uPaintDetail), p.a);
    if (uOutlines > 0.0) {
      // part borders baked from the 3D mesh (id.png B), so UV-island edges never draw false lines
      float edge = texture(idTex, vUv).b;
      col = mix(col, vec3(1.0, 0.18, 0.05), 0.85 * uOutlines * smoothstep(0.62, 0.86, edge));
    }
    if (id == uHover) col = mix(col, vec3(1.0, 0.75, 0.1), 0.16);
    // alpha channel = part class for the site shader: 1.0 panel (dark side allowed), 0.75 light part (never dark), 0.5 forced colour
    float partLum = dot(uColors[k], vec3(0.2126, 0.7152, 0.0722));
    float isLightPart = step(0.3, partLum);
    float a = forceSm > 0.5 ? 0.5 : (isLightPart > 0.5 ? 0.75 : 1.0);
    o = vec4(col, a);
  }`, {
  idTex: { value: idTex }, shadeTex: { value: shadeTex }, paintTex: { value: null },
  uColors: { value: parts.map((p) => new THREE.Vector3()) }, uDetail: { value: parts.map(() => 0.6) }, uForce: { value: parts.map(() => 0) },
  uInk: { value: new THREE.Vector3() }, uPaintDetail: { value: 0.6 }, uHover: { value: -1 },
  uOutlines: { value: 1 }, uTexel: { value: new THREE.Vector2(1.5 / RES, 1.5 / RES) }, uSmooth: { value: 2 },
  scanTex: { value: null }, uLightColor: { value: new THREE.Vector3(0.9, 0.9, 0.9) }, uEdgeMode: { value: 1 },
});
const ink = hexToLinear('#0b0b0b');
compMat.uniforms.uInk.value.set(ink.r, ink.g, ink.b);
let compDirty = true;
function syncPartUniforms() {
  const up = parts.find((p) => p.name === 'upper' || p.name === 'side_frame.L') || parts[0];
  const uc = hexToLinear(up.color); compMat.uniforms.uLightColor.value.set(uc.r, uc.g, uc.b);
  parts.forEach((p, i) => {
    const c = hexToLinear(p.color);
    compMat.uniforms.uColors.value[i].set(c.r, c.g, c.b);
    compMat.uniforms.uDetail.value[i] = p.detail;
    compMat.uniforms.uForce.value[i] = p.force ? 1 : 0;
  });
  compDirty = true;
}
function composite(exporting = false) {
  compMat.uniforms.paintTex.value = paintRT[cur].texture;
  compMat.uniforms.uOutlines.value = exporting ? 0 : ui.outlines.checked ? 1 : 0;
  compMat.uniforms.uHover.value = exporting ? -1 : hoverId;
  runPass(compMat, compRT);
}

/* ------------------------------------------------------------------ edge padding (dilate island colours into empty texels) */
const dilateMat = raw(/* glsl */`
  precision highp float; in vec2 vUv; out vec4 o;
  uniform sampler2D src, covTex; uniform vec2 uTx;
  void main() {
    vec4 c = texture(src, vUv);
    if (c.a > 0.5) { o = c; return; }                        // already filled (alpha marks filled texels during dilation)
    vec4 acc = vec4(0.0); float n = 0.0;
    for (int dy = -1; dy <= 1; dy++) for (int dx = -1; dx <= 1; dx++) {
      if (dx == 0 && dy == 0) continue;
      vec4 s = texture(src, vUv + vec2(float(dx), float(dy)) * uTx);
      if (s.a > 0.5) { acc += vec4(s.rgb, 1.0); n += 1.0; }
    }
    o = n > 0.0 ? vec4(acc.rgb / n, 1.0) : vec4(c.rgb, 0.0);
  }`, { src: { value: null }, covTex: { value: idTex }, uTx: { value: new THREE.Vector2(1 / RES, 1 / RES) } });
// seed: composite colour where covered (alpha 1), alpha 0 elsewhere
const seedMat = raw(/* glsl */`
  precision highp float; in vec2 vUv; out vec4 o; uniform sampler2D src, covTex;
  void main() { o = vec4(texture(src, vUv).rgb, texture(covTex, vUv).g > 0.5 && texture(covTex, vUv).r > 0.0 ? 1.0 : 0.0); }`,
  { src: { value: null }, covTex: { value: idTex } });
let padRT = [mkRT({ colorSpace: THREE.SRGBColorSpace }), mkRT({ colorSpace: THREE.SRGBColorSpace })];
function padComposite(srcTex, steps = 48) {
  seedMat.uniforms.src.value = srcTex; runPass(seedMat, padRT[0]);
  let a = 0;
  for (let i = 0; i < steps; i++) { dilateMat.uniforms.src.value = padRT[a].texture; runPass(dilateMat, padRT[1 - a]); a = 1 - a; }
  return padRT[a];
}

/* ------------------------------------------------------------------ material map pass (R rough, G sheen, B grain) */
const matMat = raw(/* glsl */`
  precision highp float; precision highp int;
  in vec2 vUv; out vec4 o;
  uniform sampler2D idTex; uniform vec3 uMat[${NP}];
  void main() {
    int id = int(texture(idTex, vUv).r * 255.0 + 0.5) - 1; int k = clamp(id, 0, ${NP - 1});
    o = vec4(uMat[k], 1.0);
  }`, { idTex: { value: idTex }, uMat: { value: parts.map(() => new THREE.Vector3(0.9, 0, 0.3)) } });
const matRT = mkRT({ minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter });
function syncMaterialUniforms() {
  parts.forEach((p, i) => { const P = PRESETS[p.material] || PRESETS.leather; matMat.uniforms.uMat.value[i].set(P.rough, P.sheen, P.grain); });
}
syncMaterialUniforms();

/* ------------------------------------------------------------------ brush stamp */
const stampMat = raw(/* glsl */`
  precision highp float; precision highp int;
  in vec2 vUv; out vec4 o;
  uniform sampler2D prevTex, hiTex, loTex, nTex, idTex;
  uniform vec3 uCenter, uN, uBSize, uColor; uniform float uRadius, uHard, uOpacity; uniform int uMask, uErase;
  void main() {
    vec4 prev = texture(prevTex, vUv);
    vec3 hi = floor(texture(hiTex, vUv).rgb * 255.0 + 0.5), lo = floor(texture(loTex, vUv).rgb * 255.0 + 0.5);
    vec3 pw = (hi * 256.0 + lo) / 65535.0 * uBSize;
    float d = distance(pw, uCenter);
    float a = 1.0 - smoothstep(min(uRadius * uHard, uRadius * 0.995), uRadius, d);
    vec3 n = texture(nTex, vUv).rgb * 2.0 - 1.0;
    a *= smoothstep(-0.2, 0.25, dot(n, uN));                  // don't bleed through to the other side of a thin wall
    int id = int(texture(idTex, vUv).r * 255.0 + 0.5) - 1;
    if (uMask >= 0 && id != uMask) a = 0.0;
    a *= uOpacity;
    if (a <= 0.0) { o = prev; return; }
    if (uErase == 1) { o = vec4(prev.rgb, prev.a * (1.0 - a)); return; }
    float oa = a + prev.a * (1.0 - a);
    o = vec4((uColor * a + prev.rgb * prev.a * (1.0 - a)) / max(oa, 1e-4), oa);
  }`, {
  prevTex: { value: null }, hiTex: { value: hiTex }, loTex: { value: loTex }, nTex: { value: nTex }, idTex: { value: idTex },
  uCenter: { value: new THREE.Vector3() }, uN: { value: new THREE.Vector3() }, uBSize: { value: bsize.clone() },
  uColor: { value: new THREE.Vector3() }, uRadius: { value: 0.01 }, uHard: { value: 0.9 }, uOpacity: { value: 1 },
  uMask: { value: -1 }, uErase: { value: 0 },
});
function stamp(center, normal) {
  const u = stampMat.uniforms;
  u.prevTex.value = paintRT[cur].texture;
  u.uCenter.value.copy(center); u.uN.value.copy(normal);
  runPass(stampMat, paintRT[1 - cur]);
  cur = 1 - cur;
  compDirty = true;
}

/* ------------------------------------------------------------------ texel lookups (CPU copies of the maps) */
function texel(uv) {
  const x = Math.min(RES - 1, Math.max(0, Math.floor(uv.x * RES)));
  const y = Math.min(RES - 1, Math.max(0, Math.floor(uv.y * RES)));
  return (y * RES + x) * 4;
}
function sampleAt(uv) {
  const i = texel(uv);
  const id = idImg.data[i] - 1;
  const h = hiImg.data, l = loImg.data, n = nImg.data;
  const pos = new THREE.Vector3((h[i] * 256 + l[i]) / 65535, (h[i + 1] * 256 + l[i + 1]) / 65535, (h[i + 2] * 256 + l[i + 2]) / 65535).multiply(bsize);
  const nrm = new THREE.Vector3(n[i] / 127.5 - 1, n[i + 1] / 127.5 - 1, n[i + 2] / 127.5 - 1).normalize();
  return { id, pos, nrm };
}

/* ------------------------------------------------------------------ model */
const gltf = await new GLTFLoader().setMeshoptDecoder(MeshoptDecoder).loadAsync('../../models/shoe.glb');
const root = new THREE.Group(); root.add(gltf.scene); scene.add(root);
let shoe = null;
gltf.scene.traverse((o) => {
  if (!o.isMesh) return;
  shoe = o;
  const m = o.material;
  m.metalness = 0; m.metalnessMap = null; m.roughness = 1; m.envMapIntensity = 0.85;
  compMat.uniforms.scanTex.value = m.map;                 // the scan's own colour texture (glb base colour)
  m.map = compRT.texture; m.needsUpdate = true;
});
// normalise: centre + longest side = 2 units
gltf.scene.updateMatrixWorld(true);
const box0 = new THREE.Box3().setFromObject(gltf.scene);
const s0 = 2 / Math.max(...box0.getSize(new THREE.Vector3()).toArray());
root.scale.setScalar(s0);
root.position.copy(box0.getCenter(new THREE.Vector3()).multiplyScalar(-s0));
root.updateMatrixWorld(true);
// Blender (Z up) -> glTF (Y up): (x, y, z) -> (x, z, -y); calibrate scale + offset from the two bounding boxes
const toGl = (v) => new THREE.Vector3(v.x, v.z, -v.y);
const glMin = new THREE.Vector3(bmin.x, bmin.z, -(bmin.y + bsize.y));
const glSize = new THREE.Vector3(bsize.x, bsize.z, bsize.y);
const wBox = new THREE.Box3().setFromObject(shoe);
const wSize = wBox.getSize(new THREE.Vector3());
const kScale = wSize.y / glSize.y;
const kOff = wBox.min.clone().sub(glMin.clone().multiplyScalar(kScale));
console.log('blender->world scale per axis', (wSize.x / glSize.x).toFixed(4), kScale.toFixed(4), (wSize.z / glSize.z).toFixed(4));
const toWorld = (pBlender) => toGl(bmin.clone().add(pBlender)).multiplyScalar(kScale).add(kOff);

orbit.target.set(0, 0, 0); orbit.r = 6.5;

/* ------------------------------------------------------------------ GPU picking: mesh UV under the cursor */
const pickRT = new THREE.WebGLRenderTarget(1, 1, { depthBuffer: true });
const pickMat = new THREE.ShaderMaterial({
  vertexShader: /* glsl */`varying vec2 vUv2; void main() { vUv2 = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  fragmentShader: /* glsl */`varying vec2 vUv2; void main() {
    float u = floor(clamp(vUv2.x, 0.0, 1.0) * 4095.0 + 0.5), v = floor(clamp(vUv2.y, 0.0, 1.0) * 4095.0 + 0.5);
    gl_FragColor = vec4(floor(u / 16.0) / 255.0, (mod(u, 16.0) * 16.0 + floor(v / 256.0)) / 255.0, mod(v, 256.0) / 255.0, 1.0); }`,
});
const pickBuf = new Uint8Array(4);
function pickUV(clientX, clientY) {
  const r = canvas.getBoundingClientRect();
  const x = (clientX - r.left) * renderer.getPixelRatio(), y = (clientY - r.top) * renderer.getPixelRatio();
  const w = canvas.width, h = canvas.height;
  camera.setViewOffset(w, h, Math.floor(x), Math.floor(y), 1, 1);
  const prevTM = renderer.toneMapping; renderer.toneMapping = THREE.NoToneMapping;
  scene.overrideMaterial = pickMat; ring.visible = false;
  const prevClear = renderer.getClearAlpha(); renderer.setClearColor(0x000000, 0);
  renderer.setRenderTarget(pickRT); renderer.clear(); renderer.render(scene, camera); renderer.setRenderTarget(null);
  renderer.setClearColor(0xf4f2ec, prevClear); scene.overrideMaterial = null; renderer.toneMapping = prevTM;
  camera.clearViewOffset();
  renderer.readRenderTargetPixels(pickRT, 0, 0, 1, 1, pickBuf);
  if (pickBuf[3] === 0) return null;
  const u = (pickBuf[0] * 16 + (pickBuf[1] >> 4)) / 4095, v = ((pickBuf[1] & 15) * 256 + pickBuf[2]) / 4095;
  return new THREE.Vector2(u, v);
}

/* ------------------------------------------------------------------ brush cursor */
const ring = new THREE.Group();
const ringMat = new THREE.MeshBasicMaterial({ color: 0x0c0c0d, transparent: true, opacity: 0.85, depthTest: false, side: THREE.DoubleSide });
const ringMat2 = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.9, depthTest: false, side: THREE.DoubleSide });
ring.add(new THREE.Mesh(new THREE.RingGeometry(0.96, 1.0, 96), ringMat), new THREE.Mesh(new THREE.RingGeometry(1.0, 1.04, 96), ringMat2));
const dot = new THREE.Mesh(new THREE.CircleGeometry(0.035, 16), ringMat); ring.add(dot);
ring.renderOrder = 10; ring.children.forEach((c) => { c.renderOrder = 10; });
ring.visible = false; scene.add(ring);

/* ------------------------------------------------------------------ UI */
const ui = {
  color: $('color'), colorHex: $('colorHex'), size: $('size'), hard: $('hard'), opacity: $('opacity'),
  maskPart: $('maskPart'), outlines: $('outlines'), parts: $('parts'), hoverName: $('hoverName'),
};
let tool = 'brush';
const SWATCHES = [['Navy', '#1b2045'], ['White', '#f1f1f3'], ['Ink', '#0b0b0b'], ['Silver', '#c4c6cc'], ['Red', '#c8102e'], ['Gum', '#b5793f'], ['Royal', '#24399b']];
$('swatches').innerHTML = SWATCHES.map(([n, c]) => `<button title="${n} ${c}" style="--c:${c}" data-c="${c}"></button>`).join('');
$('swatches').addEventListener('click', (e) => { const c = e.target.dataset.c; if (c) setColor(c); });
function setColor(hex) { ui.color.value = hex; ui.colorHex.value = hex; }
ui.color.addEventListener('input', () => { ui.colorHex.value = ui.color.value; });
ui.colorHex.addEventListener('change', () => { if (/^#[0-9a-f]{6}$/i.test(ui.colorHex.value)) ui.color.value = ui.colorHex.value.toLowerCase(); else ui.colorHex.value = ui.color.value; });
const fmt = { size: (v) => `${v} mm`, hard: (v) => `${Math.round(v * 100)}%`, opacity: (v) => `${Math.round(v * 100)}%` };
for (const k of ['size', 'hard', 'opacity']) {
  const out = $(k + 'Out'); const upd = () => { out.textContent = fmt[k](+ui[k].value); };
  ui[k].addEventListener('input', upd); upd();
}
ui.outlines.addEventListener('change', () => { compDirty = true; });
const smoothEl = $('smooth'), smoothOut = $('smoothOut');
const setSmooth = (v) => { compMat.uniforms.uSmooth.value = +v; smoothEl.value = v; smoothOut.textContent = +v ? `${v} px` : 'off'; compDirty = true; };
smoothEl.addEventListener('input', () => { setSmooth(smoothEl.value); markDirty(); });
setSmooth(saved?.smooth ?? 2);
function setTool(t) {
  tool = t;
  document.querySelectorAll('[data-tool]').forEach((b) => b.classList.toggle('is-on', b.dataset.tool === t));
  document.body.classList.toggle('tool-pen', t === 'pen');
  pointerDirty = true;
}
document.querySelectorAll('[data-tool]').forEach((b) => b.addEventListener('click', () => { setTool(b.dataset.tool); blurControls(); }));

function renderPartList() {
  ui.parts.innerHTML = parts.map((p, i) => `
    <li data-i="${i}">
      <input type="color" value="${p.color}" data-i="${i}" title="${p.name} colour">
      <span title="${p.name}">${p.name.replace(/_/g, ' ')}</span>
      <input type="range" min="0" max="1" step="0.05" value="${p.detail}" data-i="${i}" title="Scan detail (shading) for ${p.name}">
      <input type="checkbox" ${p.force ? 'checked' : ''} data-i="${i}" title="Force: use this colour over light areas of the scan too">
      <select data-i="${i}" title="Material">${Object.keys(PRESETS).map((k) => `<option value="${k}" ${p.material === k ? 'selected' : ''}>${k}</option>`).join('')}</select>
    </li>`).join('');
}
renderPartList();
ui.parts.addEventListener('input', (e) => {
  const i = +e.target.dataset.i; if (Number.isNaN(i)) return;
  if (e.target.type === 'color') parts[i].color = e.target.value;
  else if (e.target.type === 'checkbox') parts[i].force = e.target.checked;
  else if (e.target.tagName === 'SELECT') { parts[i].material = e.target.value; syncMaterialUniforms(); }
  else parts[i].detail = +e.target.value;
  syncPartUniforms(); markDirty();
});
ui.parts.addEventListener('focusin', (e) => { if (e.target.dataset.i !== undefined) pushParts(); });   // one undo step per edit
syncPartUniforms();

/* ------------------------------------------------------------------ history */
const undoStack = [], redoStack = [];
const MAX_HISTORY = RES > 2048 ? 8 : 24;                      // each snapshot is a full RES² render target
function snapPaint() { const rt = mkRT(); copyMat.uniforms.src.value = paintRT[cur].texture; runPass(copyMat, rt); return rt; }
function snapParts() { return parts.map((p) => ({ color: p.color, detail: p.detail, force: !!p.force, material: p.material })); }
function push(entry) {
  undoStack.push(entry); if (undoStack.length > MAX_HISTORY) { const e = undoStack.shift(); e.rt?.dispose(); }
  redoStack.forEach((e) => e.rt?.dispose()); redoStack.length = 0;
  updateHistoryUI();
}
function updateHistoryUI() {
  for (const [id, st] of [['undo', undoStack], ['redo', redoStack], ['tbUndo', undoStack], ['tbRedo', redoStack]]) {
    const b = $(id); if (!b) continue; b.disabled = st.length === 0; const n = b.querySelector('b'); if (n) n.textContent = st.length || '';
  }
}
function pushPaint() { push({ kind: 'paint', rt: snapPaint() }); }
function pushParts() { push({ kind: 'parts', parts: snapParts() }); }
function restore(entry) {
  if (entry.kind === 'paint') {
    const now = { kind: 'paint', rt: snapPaint() };
    copyMat.uniforms.src.value = entry.rt.texture; runPass(copyMat, paintRT[cur]); entry.rt.dispose();
    compDirty = true; return now;
  }
  const now = { kind: 'parts', parts: snapParts() };
  entry.parts.forEach((s, i) => Object.assign(parts[i], s)); renderPartList(); syncPartUniforms(); syncMaterialUniforms();
  return now;
}
function undo() { const e = undoStack.pop(); if (!e) { setStatus('Nothing to undo'); return; } redoStack.push(restore(e)); markDirty(); updateHistoryUI(); setStatus(`Undo · ${undoStack.length} left`); }
function redo() { const e = redoStack.pop(); if (!e) { setStatus('Nothing to redo'); return; } undoStack.push(restore(e)); markDirty(); updateHistoryUI(); setStatus(`Redo · ${redoStack.length} left`); }
for (const id of ['undo', 'tbUndo']) $(id).addEventListener('click', () => { undo(); blurControls(); });
for (const id of ['redo', 'tbRedo']) $(id).addEventListener('click', () => { redo(); blurControls(); });
updateHistoryUI();
$('clearPaint').addEventListener('click', () => {
  pushPaint(); renderer.setRenderTarget(paintRT[cur]); renderer.setClearColor(0, 0); renderer.clear(); renderer.setRenderTarget(null);
  renderer.setClearColor(0xf4f2ec, 1); compDirty = true; markDirty(); setStatus('Paint cleared (⌘Z to undo)');
});

let dirty = false;
function markDirty() { dirty = true; $('save').textContent = 'Save to site •'; }
addEventListener('beforeunload', (e) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });

/* ------------------------------------------------------------------ pointer: paint / fill / pick / orbit */
let hoverId = -1, hoverUV = null, pointer = null, pointerDirty = false;
let stroke = null;           // { last: Vector3 (blender units), mask }
let orbiting = null;         // { x, y, pan }
let spaceDown = false;

function brushRadius() { return +ui.size.value / 2 * unitsPerMm; }
function applyBrushUniforms() {
  const u = stampMat.uniforms;
  u.uRadius.value = brushRadius();
  u.uHard.value = +ui.hard.value;
  u.uOpacity.value = +ui.opacity.value;
  u.uErase.value = tool === 'erase' ? 1 : 0;
  const c = srgbVec(ui.color.value); u.uColor.value.copy(c);
}
function strokeTo(s) {
  const r = brushRadius();
  if (!stroke.last) { stamp(s.pos, s.nrm); stroke.last = s.pos.clone(); stroke.lastN = s.nrm.clone(); return; }
  const d = s.pos.distanceTo(stroke.last);
  if (d > r * 12) { stamp(s.pos, s.nrm); }                        // big jump (other side / fast flick): don't drag a line through the shoe
  else {
    const step = Math.max(r * 0.22, unitsPerMm * 0.15);
    const n = Math.min(64, Math.ceil(d / step));
    for (let k = 1; k <= n; k++) {
      const t = k / n;
      stamp(stroke.last.clone().lerp(s.pos, t), stroke.lastN.clone().lerp(s.nrm, t).normalize());
    }
  }
  stroke.last = s.pos.clone(); stroke.lastN = s.nrm.clone();
}
function pickColorAt(uv) {
  composite(true);
  const px = new Uint8Array(4);
  renderer.readRenderTargetPixels(compRT, Math.floor(uv.x * RES), Math.floor(uv.y * RES), 1, 1, px);
  compDirty = true;
  const hex = '#' + [px[0], px[1], px[2]].map((v) => v.toString(16).padStart(2, '0')).join('');
  setColor(hex); setStatus(`Picked ${hex}`);
}

canvas.addEventListener('contextmenu', (e) => e.preventDefault());
function startOrbit(e, pan) {
  orbiting = { x: e.clientX, y: e.clientY, pan };
  canvas.classList.add('is-grabbing'); ring.visible = false;
  if (hoverId !== -1) { hoverId = -1; compDirty = true; }
}
canvas.addEventListener('pointerdown', (e) => {
  canvas.setPointerCapture(e.pointerId);
  blurControls();
  // right / middle button, Space+drag, the Rotate tool, or a drag that starts off the shoe: move the camera
  if (e.button === 2 || e.button === 1 || (e.button === 0 && (spaceDown || tool === 'rotate'))) { startOrbit(e, e.shiftKey || e.button === 1); return; }
  if (e.button !== 0) return;
  if (tool === 'pen' && !e.altKey) { if (!penAddOrGrab(e)) startOrbit(e, e.shiftKey); return; }
  const uv = pickUV(e.clientX, e.clientY);
  if (!uv) { startOrbit(e, e.shiftKey); return; }
  const s = sampleAt(uv);
  const t = e.altKey ? 'pick' : tool;
  if (t === 'pick') { pickColorAt(uv); return; }
  if (t === 'fill') {
    if (s.id < 0) return;
    pushParts(); parts[s.id].color = ui.color.value; renderPartList(); syncPartUniforms(); markDirty();
    setStatus(`${parts[s.id].name} → ${ui.color.value}`); return;
  }
  pushPaint(); applyBrushUniforms();
  stampMat.uniforms.uMask.value = ui.maskPart.checked ? s.id : -1;
  stroke = { last: null, lastN: null };
  strokeTo(s); markDirty();
});
function orbitBy(dx, dy) {
  orbit.theta -= dx * 0.006;
  orbit.phi = Math.min(Math.PI - 0.05, Math.max(0.05, orbit.phi - dy * 0.006));
  placeCamera(); pointerDirty = true;
}
function panBy(dx, dy) {
  const k = orbit.r * 0.0016;
  const right = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 0), up = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 1);
  orbit.target.addScaledVector(right, -dx * k).addScaledVector(up, dy * k);
  placeCamera(); pointerDirty = true;
}
canvas.addEventListener('pointermove', (e) => {
  pointer = { x: e.clientX, y: e.clientY }; pointerDirty = true;
  if (pen.dragIdx >= 0) { penDragTo(e); return; }
  if (orbiting) {
    const dx = e.clientX - orbiting.x, dy = e.clientY - orbiting.y; orbiting.x = e.clientX; orbiting.y = e.clientY;
    orbiting.pan ? panBy(dx, dy) : orbitBy(dx, dy);
  }
});
const endPointer = () => {
  stroke = null; pen.dragIdx = -1;
  if (orbiting) { orbiting = null; canvas.classList.remove('is-grabbing'); pointerDirty = true; }
};
canvas.addEventListener('pointerup', endPointer);
canvas.addEventListener('pointercancel', endPointer);
canvas.addEventListener('lostpointercapture', endPointer);
canvas.addEventListener('pointerleave', () => { if (orbiting || stroke) return; ring.visible = false; hoverId = -1; compDirty = true; pointer = null; });
// Trackpad: two-finger scroll rotates, pinch (ctrl+wheel) zooms, shift+scroll pans. Mouse wheel (big integer steps) zooms.
canvas.addEventListener('wheel', (e) => {
  e.preventDefault();
  const mouseWheel = e.deltaMode === 1 || (e.deltaX === 0 && Number.isInteger(e.deltaY) && Math.abs(e.deltaY) >= 50);
  if (e.ctrlKey || e.metaKey || mouseWheel) {
    const k = e.ctrlKey ? 0.01 : 0.0012;
    orbit.r = Math.min(20, Math.max(0.6, orbit.r * Math.exp(e.deltaY * k)));
    placeCamera(); pointerDirty = true;
  } else if (e.shiftKey) panBy(-e.deltaX, -e.deltaY);
  else orbitBy(-e.deltaX * 0.8, -e.deltaY * 0.8);
}, { passive: false });

// sliders / colour wells keep focus after use; give the keyboard back to the canvas
function blurControls() { const a = document.activeElement; if (a && a !== document.body && a.type !== 'text') a.blur(); }
const VIEWS = { side: [-Math.PI / 2, 1.45], other: [Math.PI / 2, 1.45], front: [Math.PI, 1.35], back: [0, 1.35], top: [-Math.PI / 2, 0.08], three: [-0.9, 1.2] };
function setView(name) {
  const [theta, phi] = VIEWS[name]; orbit.theta = theta; orbit.phi = phi; orbit.target.set(0, 0, 0); orbit.r = 6.5;
  placeCamera(); pointerDirty = true;
}
document.querySelectorAll('[data-view]').forEach((b) => b.addEventListener('click', () => { setView(b.dataset.view); blurControls(); }));

addEventListener('keydown', (e) => {
  const typing = e.target.tagName === 'INPUT' && e.target.type === 'text';
  const meta = e.metaKey || e.ctrlKey;
  if (meta && e.key.toLowerCase() === 'z' && !typing && !e.shiftKey && tool === 'pen' && pen.pts.length) { e.preventDefault(); pen.pts.pop(); pen.closed = false; updatePenUI(); return; }
  if (meta && e.key.toLowerCase() === 'z' && !typing) { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
  if (!typing && pen.pts.length) {
    if (e.key === 'Enter') { e.preventDefault(); commitPen(); return; }
    if (e.key === 'Escape') { e.preventDefault(); cancelPen(); return; }
    if (e.key === 'Backspace' || e.key === 'Delete') { e.preventDefault(); pen.pts.pop(); pen.closed = false; updatePenUI(); return; }
  }
  if (meta && e.key.toLowerCase() === 'y' && !typing) { e.preventDefault(); redo(); return; }
  if (meta && e.key.toLowerCase() === 's') { e.preventDefault(); save(); return; }
  if (typing || meta) return;
  if (e.code === 'Space') { spaceDown = true; canvas.classList.add('is-grab'); e.preventDefault(); return; }
  const k = e.key.toLowerCase();
  if (k === 'b') setTool('brush'); else if (k === 'e') setTool('erase'); else if (k === 'f') setTool('fill');
  else if (k === 'i') setTool('pick'); else if (k === 'r') setTool('rotate'); else if (k === 'p') setTool('pen');
  else if (k === '1') setView('side'); else if (k === '2') setView('other'); else if (k === '3') setView('front');
  else if (k === '4') setView('back'); else if (k === '5') setView('top'); else if (k === '0') setView('three');
  else if (e.key === 'ArrowLeft') { orbitBy(-26, 0); e.preventDefault(); } else if (e.key === 'ArrowRight') { orbitBy(26, 0); e.preventDefault(); }
  else if (e.key === 'ArrowUp') { orbitBy(0, -26); e.preventDefault(); } else if (e.key === 'ArrowDown') { orbitBy(0, 26); e.preventDefault(); }
  else if (k === '[' || k === ']') {
    const v = +ui.size.value, nv = k === ']' ? v * 1.2 : v / 1.2;
    ui.size.value = Math.min(40, Math.max(0.5, Math.round(nv * 2) / 2)); ui.size.dispatchEvent(new Event('input')); pointerDirty = true;
  }
});
addEventListener('keyup', (e) => { if (e.code === 'Space') { spaceDown = false; canvas.classList.remove('is-grab'); } });

function updateHover() {
  if (!pointer || orbiting) return;
  const uv = pickUV(pointer.x, pointer.y);
  const paintTool = tool === 'brush' || tool === 'erase';
  // the system cursor is always visible: crosshair over the shoe for painting, grab hand where a drag rotates
  canvas.dataset.cursor = !uv || tool === 'rotate' || spaceDown ? 'grab' : tool === 'fill' ? 'fill' : tool === 'pen' ? 'pen' : 'paint';
  if (tool === 'pen') {
    const r = canvasRect(); pen.cursor = [pointer.x - r.left, pointer.y - r.top];
    pen.hoverIdx = penHit(pen.cursor[0], pen.cursor[1]);
    if (pen.hoverIdx >= 0) canvas.dataset.cursor = pen.hoverIdx === 0 && pen.pts.length >= 3 && !pen.closed ? 'close' : 'move';
  }
  if (!uv) { ring.visible = false; if (hoverId !== -1) { hoverId = -1; compDirty = true; } ui.hoverName.textContent = ''; markHoverRow(-1); return; }
  const s = sampleAt(uv);
  hoverUV = uv;
  if (stroke) strokeTo(s);
  const showHover = tool === 'fill' || (paintTool && ui.maskPart.checked);
  const hid = showHover ? s.id : -1;
  if (hid !== hoverId) { hoverId = hid; compDirty = true; }
  ui.hoverName.textContent = s.id >= 0 ? parts[s.id].name.replace(/_/g, ' ') : '';
  markHoverRow(s.id);
  // brush ring on the surface, sized to the brush in real millimetres
  const wp = toWorld(s.pos), wn = toGl(s.nrm).normalize();
  ring.position.copy(wp).addScaledVector(wn, 0.002);
  ring.lookAt(wp.clone().add(wn));
  ring.scale.setScalar(Math.max(brushRadius() * kScale, 0.004));
  ring.visible = paintTool;
}
let lastRow = -1;
function markHoverRow(i) {
  if (i === lastRow) return;
  ui.parts.querySelector(`li[data-i="${lastRow}"]`)?.classList.remove('is-hover');
  ui.parts.querySelector(`li[data-i="${i}"]`)?.classList.add('is-hover');
  lastRow = i;
}


/* ------------------------------------------------------------------ pen tool
 * Points live on the surface (Blender-space position + normal), so the path survives rotating the view.
 * Line: the path is sampled in screen space and every sample is looked up on the surface from a single
 *       full-view UV render, so the committed line lands exactly where the preview was drawn.
 * Fill: the closed outline is rasterised in screen space (4x MSAA); a UV-space pass projects every texel
 *       into the current view and paints it if it is inside the outline AND is the visible surface there.
 */
const overlay = $('overlay');
const octx = overlay.getContext('2d');
const pen = { pts: [], closed: false, mode: 'fill', dragIdx: -1, hoverIdx: -1, cursor: null };
const penUI = { apply: $('penApply'), cancel: $('penCancel'), info: $('penInfo'), curves: $('penCurves') };
document.querySelectorAll('[data-penmode]').forEach((b) => b.addEventListener('click', () => {
  pen.mode = b.dataset.penmode;
  document.querySelectorAll('[data-penmode]').forEach((x) => x.classList.toggle('is-on', x === b));
  updatePenUI(); blurControls();
}));
penUI.curves.addEventListener('change', () => { pen.pts.forEach((p) => { p.smooth = penUI.curves.checked; }); blurControls(); });
penUI.apply.addEventListener('click', () => { commitPen(); blurControls(); });
penUI.cancel.addEventListener('click', () => { cancelPen(); blurControls(); });

function canvasRect() { return canvas.getBoundingClientRect(); }
function toScreen(w) {
  const v = w.clone().project(camera); const r = canvasRect();
  return [(v.x * 0.5 + 0.5) * r.width, (-v.y * 0.5 + 0.5) * r.height, v.z];
}
const anchorScreen = (p) => toScreen(toWorld(p.pos));
// cubic Hermite through the points; corner points get zero tangents, smooth points Catmull-Rom tangents
function hermite(P, smooth, closed, steps = 24) {
  const n = P.length; if (n < 2) return P.map((p) => p.slice());
  const dim = P[0].length, get = (i) => closed ? P[((i % n) + n) % n] : P[Math.max(0, Math.min(n - 1, i))];
  const tan = (i) => {
    const k = ((i % n) + n) % n;
    if (!smooth[k]) return new Array(dim).fill(0);
    const a = get(i - 1), b = get(i + 1);
    return a.map((_, d) => (b[d] - a[d]) * 0.5);
  };
  const out = [], segs = closed ? n : n - 1;
  for (let sgi = 0; sgi < segs; sgi++) {
    const p0 = get(sgi), p1 = get(sgi + 1), m0 = tan(sgi), m1 = tan(sgi + 1);
    for (let k = 0; k < steps; k++) {
      const t = k / steps, t2 = t * t, t3 = t2 * t;
      const h00 = 2 * t3 - 3 * t2 + 1, h10 = t3 - 2 * t2 + t, h01 = -2 * t3 + 3 * t2, h11 = t3 - t2;
      out.push(p0.map((_, d) => h00 * p0[d] + h10 * m0[d] + h01 * p1[d] + h11 * m1[d]));
    }
  }
  if (!closed) out.push(P[n - 1].slice());
  return out;
}
function resample(poly, step, closed) {
  if (poly.length < 2) return poly;
  const pts = closed ? [...poly, poly[0]] : poly, out = [pts[0]];
  let carry = 0;
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1], b = pts[i], L = Math.hypot(b[0] - a[0], b[1] - a[1]);
    let t = step - carry;
    while (t <= L) { out.push([a[0] + (b[0] - a[0]) * t / L, a[1] + (b[1] - a[1]) * t / L]); t += step; }
    carry = L - (t - step);
  }
  return out;
}
function penPath2D(closed = pen.closed) {
  const P = pen.pts.map((p) => anchorScreen(p).slice(0, 2));
  return hermite(P, pen.pts.map((p) => p.smooth), closed);
}

// one full-view UV render, read back once, then CPU lookups for every sample
const pickFullRT = new THREE.WebGLRenderTarget(1, 1, { minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter, depthBuffer: true });
function renderPickFull() {
  const w = canvas.width, h = canvas.height;
  if (pickFullRT.width !== w || pickFullRT.height !== h) pickFullRT.setSize(w, h);
  const prevTM = renderer.toneMapping; renderer.toneMapping = THREE.NoToneMapping;
  scene.overrideMaterial = pickMat; const rv = ring.visible; ring.visible = false;
  renderer.setClearColor(0x000000, 0);
  renderer.setRenderTarget(pickFullRT); renderer.clear(); renderer.render(scene, camera); renderer.setRenderTarget(null);
  renderer.setClearColor(0xf4f2ec, 1); scene.overrideMaterial = null; renderer.toneMapping = prevTM; ring.visible = rv;
}
function readPickRegion(samplesCss) {
  const dpr = renderer.getPixelRatio(), W = canvas.width, H = canvas.height;
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const [x, y] of samplesCss) { x0 = Math.min(x0, x * dpr); y0 = Math.min(y0, y * dpr); x1 = Math.max(x1, x * dpr); y1 = Math.max(y1, y * dpr); }
  x0 = Math.max(0, Math.floor(x0) - 1); y0 = Math.max(0, Math.floor(y0) - 1); x1 = Math.min(W - 1, Math.ceil(x1) + 1); y1 = Math.min(H - 1, Math.ceil(y1) + 1);
  const bw = x1 - x0 + 1, bh = y1 - y0 + 1, buf = new Uint8Array(bw * bh * 4);
  renderer.readRenderTargetPixels(pickFullRT, x0, H - 1 - y1, bw, bh, buf);   // RT rows run bottom-up
  return (x, y) => {
    const px = Math.round(x * dpr) - x0, py = (H - 1 - Math.round(y * dpr)) - (H - 1 - y1);
    if (px < 0 || py < 0 || px >= bw || py >= bh) return null;
    const i = (py * bw + px) * 4;
    if (buf[i + 3] === 0) return null;
    return new THREE.Vector2((buf[i] * 16 + (buf[i + 1] >> 4)) / 4095, ((buf[i + 1] & 15) * 256 + buf[i + 2]) / 4095);
  };
}

const polyRT = new THREE.WebGLRenderTarget(1, 1, { samples: 4, depthBuffer: false });
const polyScene = new THREE.Scene();
const polyMesh = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide }));
polyMesh.frustumCulled = false; polyScene.add(polyMesh);
const fillMat = raw(/* glsl */`
  precision highp float; precision highp int;
  in vec2 vUv; out vec4 o;
  uniform sampler2D prevTex, hiTex, loTex, idTex, pickTex, polyTex;
  uniform mat4 uViewProj; uniform vec3 uBMin, uBSize, uKOff, uColor; uniform float uKScale, uOpacity, uTol; uniform int uMask, uErase;
  vec3 posAt(vec2 uv) {
    vec3 hi = floor(texture(hiTex, uv).rgb * 255.0 + 0.5), lo = floor(texture(loTex, uv).rgb * 255.0 + 0.5);
    return (hi * 256.0 + lo) / 65535.0 * uBSize;
  }
  void main() {
    vec4 prev = texture(prevTex, vUv); o = prev;
    vec3 p = posAt(vUv), b = uBMin + p;
    vec4 c = uViewProj * vec4(vec3(b.x, b.z, -b.y) * uKScale + uKOff, 1.0);
    if (c.w <= 0.0) return;
    vec2 sc = c.xy / c.w * 0.5 + 0.5;
    if (any(lessThan(sc, vec2(0.0))) || any(greaterThan(sc, vec2(1.0)))) return;
    float inside = smoothstep(0.35, 0.65, texture(polyTex, sc).r);
    if (inside <= 0.0) return;
    vec4 pk = texture(pickTex, sc);
    if (pk.a < 0.5) return;
    float r = floor(pk.r * 255.0 + 0.5), g = floor(pk.g * 255.0 + 0.5), bb = floor(pk.b * 255.0 + 0.5);
    vec2 puv = vec2(r * 16.0 + floor(g / 16.0), mod(g, 16.0) * 256.0 + bb) / 4095.0;
    if (distance(posAt(puv), p) > uTol) return;               // texel is hidden behind something in this view
    int id = int(texture(idTex, vUv).r * 255.0 + 0.5) - 1;
    if (uMask >= 0 && id != uMask) return;
    float a = inside * uOpacity;
    if (uErase == 1) { o = vec4(prev.rgb, prev.a * (1.0 - a)); return; }
    float oa = a + prev.a * (1.0 - a);
    o = vec4((uColor * a + prev.rgb * prev.a * (1.0 - a)) / max(oa, 1e-4), oa);
  }`, {
  prevTex: { value: null }, hiTex: { value: hiTex }, loTex: { value: loTex }, idTex: { value: idTex },
  pickTex: { value: pickFullRT.texture }, polyTex: { value: polyRT.texture },
  uViewProj: { value: new THREE.Matrix4() }, uBMin: { value: bmin.clone() }, uBSize: { value: bsize.clone() },
  uKOff: { value: kOff.clone() }, uKScale: { value: kScale }, uColor: { value: new THREE.Vector3() },
  uOpacity: { value: 1 }, uTol: { value: 0.01 }, uMask: { value: -1 }, uErase: { value: 0 },
});

function commitPen() {
  const n = pen.pts.length;
  if (pen.mode === 'fill' ? n < 3 : n < 2) { setStatus(pen.mode === 'fill' ? 'A shape needs at least 3 points' : 'A line needs at least 2 points'); return; }
  pushPaint();
  const erase = tool === 'erase';
  if (pen.mode === 'line') {
    applyBrushUniforms();
    const samples = resample(penPath2D(), 1.5, pen.closed);
    renderPickFull();
    const look = readPickRegion(samples);
    stroke = { last: null, lastN: null };
    let mask = -1, painted = 0;
    for (const [x, y] of samples) {
      const uv = look(x, y); if (!uv) { stroke.last = null; continue; }
      const sm = sampleAt(uv);
      if (mask === -1 && ui.maskPart.checked) { mask = sm.id; stampMat.uniforms.uMask.value = mask; }
      if (!ui.maskPart.checked) stampMat.uniforms.uMask.value = -1;
      strokeTo(sm); painted++;
    }
    stroke = null;
    setStatus(`Line applied (${painted} samples) · ⌘Z to undo`);
  } else {
    const outline = penPath2D(true);
    const r = canvasRect();
    const shape = new THREE.Shape(outline.map(([x, y]) => new THREE.Vector2(x / r.width * 2 - 1, 1 - y / r.height * 2)));
    polyMesh.geometry.dispose(); polyMesh.geometry = new THREE.ShapeGeometry(shape);
    const w = canvas.width, h = canvas.height;
    if (polyRT.width !== w || polyRT.height !== h) polyRT.setSize(w, h);
    renderer.setClearColor(0x000000, 1);
    renderer.setRenderTarget(polyRT); renderer.clear(); renderer.render(polyScene, passCam); renderer.setRenderTarget(null);
    renderer.setClearColor(0xf4f2ec, 1);
    renderPickFull();
    camera.updateMatrixWorld();
    const u = fillMat.uniforms;
    u.uViewProj.value.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
    // depth tolerance: ~3 screen pixels at the target distance, never under 1 mm
    const worldPerPx = 2 * orbit.r * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) / canvas.height;
    u.uTol.value = Math.max(unitsPerMm, 3 * worldPerPx / kScale);
    u.uColor.value.copy(srgbVec(ui.color.value)); u.uOpacity.value = +ui.opacity.value; u.uErase.value = erase ? 1 : 0;
    const first = sampleAt(pen.pts[0].uv);
    u.uMask.value = ui.maskPart.checked ? first.id : -1;
    u.prevTex.value = paintRT[cur].texture;
    runPass(fillMat, paintRT[1 - cur]); cur = 1 - cur; compDirty = true;
    setStatus(`Shape filled${ui.maskPart.checked ? ` inside ${parts[first.id]?.name ?? 'part'}` : ''} · ⌘Z to undo`);
  }
  markDirty();
  pen.pts = []; pen.closed = false; pen.dragIdx = -1; updatePenUI();
}
function cancelPen() { pen.pts = []; pen.closed = false; pen.dragIdx = -1; updatePenUI(); setStatus('Pen path cancelled'); }
function updatePenUI() {
  const n = pen.pts.length, need = pen.mode === 'fill' ? 3 : 2;
  penUI.apply.disabled = n < need; penUI.cancel.disabled = n === 0;
  penUI.info.textContent = n === 0
    ? 'Click on the shoe to place points. Drag a point to adjust it. Click the first point to close.'
    : pen.closed ? `Closed shape · ${n} points · drag points to adjust · ⏎ to ${pen.mode === 'fill' ? 'fill' : 'draw'}`
    : `${n} point${n > 1 ? 's' : ''} · ⌫ removes the last · ${n >= need ? '⏎ applies' : `${need - n} more to apply`}`;
}
function penHit(x, y) {
  for (let i = pen.pts.length - 1; i >= 0; i--) { const [sx, sy] = anchorScreen(pen.pts[i]); if (Math.hypot(sx - x, sy - y) < 9) return i; }
  return -1;
}
function penAddOrGrab(e) {
  const r = canvasRect(), x = e.clientX - r.left, y = e.clientY - r.top;
  const hit = penHit(x, y);
  if (hit === 0 && pen.pts.length >= 3 && !pen.closed) { pen.closed = true; updatePenUI(); setStatus('Shape closed · ⏎ to apply'); return true; }
  if (hit >= 0) { pen.dragIdx = hit; return true; }
  if (pen.closed) return true;                                 // finished outline: only point edits until applied
  const uv = pickUV(e.clientX, e.clientY);
  if (!uv) return false;
  const smp = sampleAt(uv);
  pen.pts.push({ pos: smp.pos, nrm: smp.nrm, uv, smooth: penUI.curves.checked });
  pen.dragIdx = pen.pts.length - 1; updatePenUI();
  return true;
}
function penDragTo(e) {
  const uv = pickUV(e.clientX, e.clientY); if (!uv) return;
  const smp = sampleAt(uv); Object.assign(pen.pts[pen.dragIdx], { pos: smp.pos, nrm: smp.nrm, uv });
}
canvas.addEventListener('dblclick', (e) => {
  if (tool !== 'pen') return;
  const r = canvasRect(), i = penHit(e.clientX - r.left, e.clientY - r.top);
  if (i >= 0) { pen.pts[i].smooth = !pen.pts[i].smooth; setStatus(`Point ${i + 1}: ${pen.pts[i].smooth ? 'smooth' : 'corner'}`); }
});
function drawOverlay() {
  const dpr = renderer.getPixelRatio(), r = canvasRect();
  if (overlay.width !== Math.round(r.width * dpr) || overlay.height !== Math.round(r.height * dpr)) { overlay.width = Math.round(r.width * dpr); overlay.height = Math.round(r.height * dpr); }
  octx.setTransform(dpr, 0, 0, dpr, 0, 0); octx.clearRect(0, 0, r.width, r.height);
  if (!pen.pts.length) return;
  const path = penPath2D();
  const color = ui.color.value;
  octx.lineJoin = 'round'; octx.lineCap = 'round';
  if (pen.mode === 'fill' && pen.pts.length >= 3) {
    const closedPath = penPath2D(true);
    octx.beginPath(); closedPath.forEach(([x, y], i) => (i ? octx.lineTo(x, y) : octx.moveTo(x, y))); octx.closePath();
    octx.globalAlpha = pen.closed ? 0.45 : 0.2; octx.fillStyle = color; octx.fill(); octx.globalAlpha = 1;
  }
  const strokePath = (w, c, dash = []) => {
    octx.setLineDash(dash); octx.lineWidth = w; octx.strokeStyle = c; octx.beginPath();
    path.forEach(([x, y], i) => (i ? octx.lineTo(x, y) : octx.moveTo(x, y)));
    if (pen.closed) octx.closePath();
    octx.stroke(); octx.setLineDash([]);
  };
  strokePath(3.5, 'rgba(255,255,255,0.95)'); strokePath(1.5, '#0c0c0d');
  // rubber band from the last point to the cursor
  if (!pen.closed && pen.cursor && pen.dragIdx < 0) {
    const [lx, ly] = anchorScreen(pen.pts[pen.pts.length - 1]);
    octx.setLineDash([4, 4]); octx.lineWidth = 1.25; octx.strokeStyle = '#0c0c0d';
    octx.beginPath(); octx.moveTo(lx, ly); octx.lineTo(pen.cursor[0], pen.cursor[1]); octx.stroke(); octx.setLineDash([]);
  }
  pen.pts.forEach((p, i) => {
    const [x, y] = anchorScreen(p);
    const big = (i === 0 && pen.pts.length >= 3 && !pen.closed && pen.hoverIdx === 0) || pen.hoverIdx === i || pen.dragIdx === i;
    const s = big ? 6 : 4.5;
    octx.fillStyle = i === 0 ? '#0c0c0d' : '#ffffff'; octx.strokeStyle = i === 0 ? '#ffffff' : '#0c0c0d'; octx.lineWidth = 1.5;
    octx.beginPath();
    if (p.smooth) octx.arc(x, y, s, 0, Math.PI * 2); else octx.rect(x - s, y - s, s * 2, s * 2);
    octx.fill(); octx.stroke();
  });
}

/* ------------------------------------------------------------------ save */
async function save() {
  const btn = $('save'); btn.disabled = true; setStatus('Saving…');
  try {
    composite(true);
    const padded = padComposite(compRT.texture);
    const px = new Uint8Array(RES * RES * 4);
    renderer.readRenderTargetPixels(padded, 0, 0, RES, RES, px);
    // restore the site's alpha channel (force flag) from the unpadded composite
    const apx = new Uint8Array(RES * RES * 4); renderer.readRenderTargetPixels(compRT, 0, 0, RES, RES, apx);
    for (let i = 3; i < px.length; i += 4) px[i] = apx[i];
    const c = new OffscreenCanvas(RES, RES); const x = c.getContext('2d');
    x.putImageData(new ImageData(new Uint8ClampedArray(px.buffer), RES, RES), 0, 0);
    const webp = await c.convertToBlob({ type: 'image/webp', quality: 0.92 });
    const r1 = await fetch('/api/save-texture', { method: 'POST', body: webp }).then((r) => r.ok ? r.json() : Promise.reject(new Error('texture: ' + r.status)));
    // material map (R rough, G sheen, B grain) for the site's PBR shader
    runPass(matMat, matRT);
    const mpx = new Uint8Array(RES * RES * 4); renderer.readRenderTargetPixels(matRT, 0, 0, RES, RES, mpx);
    const mc = new OffscreenCanvas(RES, RES); mc.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(mpx.buffer), RES, RES), 0, 0);
    await fetch('/api/save-material', { method: 'POST', body: await mc.convertToBlob({ type: 'image/webp', quality: 0.9 }) }).then((r) => r.ok ? r.json() : Promise.reject(new Error('material: ' + r.status)));
    // editor state: part colours + brush layer
    renderer.readRenderTargetPixels(paintRT[cur], 0, 0, RES, RES, px);
    const c2 = new OffscreenCanvas(RES, RES); c2.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(px.buffer), RES, RES), 0, 0);
    await fetch('/api/state/paint', { method: 'POST', body: await c2.convertToBlob({ type: 'image/png' }) });
    await fetch('/api/state/parts', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ smooth: +smoothEl.value, parts: parts.map(({ name, color, detail, force, material }) => ({ name, color, detail, force: !!force, material })) }) });
    dirty = false; btn.textContent = 'Save to site';
    setStatus(`Saved ${(r1.bytes / 1024).toFixed(0)} KB → models/navy-color.webp · reload the site`);
  } catch (err) {
    console.error(err); setStatus('Save failed: ' + err.message);
  } finally { btn.disabled = false; compDirty = true; }
}
$('save').addEventListener('click', save);

/* ------------------------------------------------------------------ loop */
function resize() {
  const r = canvas.parentElement.getBoundingClientRect();
  renderer.setSize(r.width, r.height, false);
  camera.aspect = r.width / r.height; camera.updateProjectionMatrix();
}
addEventListener('resize', resize); resize(); placeCamera();
function frame() {
  if (pointerDirty) { pointerDirty = false; updateHover(); }
  if (compDirty) { compDirty = false; composite(false); }
  renderer.render(scene, camera);
  drawOverlay();
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
setStatus(saved ? 'Loaded your saved state' : 'Ready · paint on the shoe');
window.__editor = { compMat, composite, pen, commitPen, undoStack, redoStack, setView, parts, stampAtUV: (u, v) => { const s = sampleAt(new THREE.Vector2(u, v)); applyBrushUniforms(); stamp(s.pos, s.nrm); }, save, orbit, placeCamera, setTool, setColor };
