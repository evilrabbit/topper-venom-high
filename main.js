import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
import { RoomEnvironment } from 'three/addons/RoomEnvironment.js';

/* ------------------------------------------------------------------ *
 * Config
 * ------------------------------------------------------------------ */
const REAL_LENGTH_CM = 31.0;           // men's US 10 outsole length
const NORM_LENGTH = 2.0;               // model length in scene units
// Orientation of the scanned mesh -> scene (Y up, length along X).
// Tweak these if the scan comes in rotated.
const ORIENT = { x: 0, y: Math.PI / 2, z: 0 };
// Callout anchors as fractions of the source bounding box (x, y, z in 0..1)
// Each target snaps to the nearest scan vertex; `mirror` picks whichever side faces the camera.
const CALLOUTS = [
  { n: '01', label: 'Padded collar', f: [0.5, 0.86, 0.0] },
  { n: '02', label: 'Lacing system', f: [0.5, 0.62, 0.62] },
  { n: '03', label: 'Topper side panel', f: [1, 0.42, 0.38], mirror: true },
  { n: '04', label: 'Toe box', f: [0.5, 0.25, 1.0] },
  { n: '05', label: 'Rubber cupsole', f: [1, 0.08, 0.62], mirror: true },
];

const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
const isMobile = () => innerWidth < 860;

/* ------------------------------------------------------------------ *
 * Renderer / scene
 * ------------------------------------------------------------------ */
const canvas = document.getElementById('stage');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight, false);
renderer.toneMapping = THREE.NeutralToneMapping;
renderer.toneMappingExposure = 1.0;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = 0.9;
// soft studio fill: sky/ground bounce keeps the off-whites from going flat
scene.add(new THREE.HemisphereLight(0xffffff, 0xd8d2c4, 0.55));

// key (casts the ground shadow), cool fill, warm rim
const KEY_OFFSET = new THREE.Vector3(2.2, 5.5, 3.2);
const key = new THREE.DirectionalLight(0xfffaf2, 2.1);
key.castShadow = true;
key.shadow.mapSize.set(2048, 2048);
key.shadow.radius = 6;
key.shadow.blurSamples = 16;
key.shadow.bias = -0.0004;
key.shadow.normalBias = 0.02;
Object.assign(key.shadow.camera, { left: -2.2, right: 2.2, top: 2.2, bottom: -2.2, near: 0.5, far: 14 });
scene.add(key, key.target);
const fill = new THREE.DirectionalLight(0xe8eeff, 0.45);
fill.position.set(-4, 1.5, 3);
scene.add(fill);
const rim = new THREE.DirectionalLight(0xfff1dc, 0.9);
rim.position.set(-3, 3, -4);
scene.add(rim);

const camera = new THREE.PerspectiveCamera(30, innerWidth / innerHeight, 0.1, 100);
camera.position.set(0, 0.25, 6);
camera.lookAt(0, 0, 0);

// Hierarchy: base(pos, scale) -> pitch(rx) -> yaw(ry) -> [shadow, orient -> norm -> model]
const base = new THREE.Group();
const pitch = new THREE.Group();
const yaw = new THREE.Group();
const orient = new THREE.Group();
const norm = new THREE.Group();
orient.rotation.set(ORIENT.x, ORIENT.y, ORIENT.z);
scene.add(base); base.add(pitch); pitch.add(yaw); yaw.add(orient); orient.add(norm);

/* ------------------------------------------------------------------ *
 * Shared reveal uniforms + shader patch
 * ------------------------------------------------------------------ */
const U = {
  uSweep: { value: -10 },               // signed position of the reveal plane in source space
  uDir: { value: new THREE.Vector3(0, 0.3, 1).normalize() },
  uEdge: { value: 0.012 },
  uEdgeColor: { value: new THREE.Color('#ffffff') },
  uWire: { value: 1 },
  uWireColor: { value: new THREE.Color('#ffffff') },
  // colorway remap: dark leather -> uCwDark, light leather -> uCwLight
  uCwMix: { value: 0 },
  uCwDark: { value: new THREE.Color('#0c0c0d') },
  uCwLight: { value: new THREE.Color('#f4f2ec') },
  uCwMask: { value: 0 },                 // 1 = navy: use the painted navy texture
  uNavyTex: { value: null },
  uSoleTop: { value: 0.104 },
  uMapTexel: { value: new THREE.Vector2(1 / 2048, 1 / 2048) },  // texel size of the scan texture (set on load)
  uBoxMin: { value: new THREE.Vector3() },
  uBoxSize: { value: new THREE.Vector3(1, 1, 1) },
};

const COLORWAYS = {
  og: { mask: 0, mix: 0, dark: '#0c0c0d', light: '#f4f2ec', swatches: [['Venom black', '#0c0c0d'], ['Court white', '#f4f2ec']] },
  navy: { mask: 1, mix: 1, dark: '#232849', light: '#f2f2f0', swatches: [['Navy', '#262b4b'], ['White', '#f2f2f0']] },
  blackout: { mask: 0, mix: 1, dark: '#060606', light: '#111111', swatches: [['Triple black', '#0a0a0a'], ['Jet black', '#141414']] },
};
const cwTarget = { mask: 0, mix: 0, dark: new THREE.Color('#0c0c0d'), light: new THREE.Color('#f4f2ec') };

const REVEAL_VERT_HEAD = /* glsl */`
  uniform mat4 uNodeMat;
  varying vec3 vSrc;
  varying vec3 vSrcN;
`;
const REVEAL_FRAG_HEAD = /* glsl */`
  uniform float uSweep; uniform vec3 uDir; uniform float uEdge; uniform vec3 uEdgeColor;
  varying vec3 vSrc;
  varying vec3 vSrcN;
  float sweepDist() { return dot(vSrc, uDir) - uSweep; }
`;
const CW_FRAG_HEAD = /* glsl */`
  uniform float uCwMix; uniform vec3 uCwDark; uniform vec3 uCwLight;
  uniform float uCwMask; uniform vec3 uBoxMin; uniform vec3 uBoxSize; uniform sampler2D uNavyTex; uniform float uSoleTop; uniform vec2 uMapTexel;
`;
const CW_MAP = /* glsl */`
#ifdef USE_MAP
  vec4 texel = texture2D(map, vMapUv);
  float lum = dot(texel.rgb, vec3(0.2126, 0.7152, 0.0722));
  float l = pow(lum, 1.0 / 2.2);                       // perceptual lightness
  float sat = max(texel.r, max(texel.g, texel.b)) - min(texel.r, min(texel.g, texel.b));
  // Navy: recolour the scan itself. models/navy-color.webp says, per part, what the scan's dark leather
  // becomes (navy panels/outsole, black prints, white elsewhere); the scan's own black/white edge decides
  // where, so every contour is exactly as smooth and anti-aliased as the original texture.
  vec4 tg = texture2D(uNavyTex, vMapUv); vec3 tgt = tg.rgb;
  // Edge decision from a slightly blurred lightness (irons out the leather noise along the scan's edges),
  // drawn with screen-space anti-aliasing so the navy/white contour is ~1px wide and smooth at any zoom.
  float lb = 0.0;
  for (int dy = -1; dy <= 1; dy++) for (int dx = -1; dx <= 1; dx++) {
    vec3 s = texture2D(map, vMapUv + vec2(float(dx), float(dy)) * uMapTexel * 1.4).rgb;
    lb += pow(dot(s, vec3(0.2126, 0.7152, 0.0722)), 1.0 / 2.2) * ((dx == 0 ? 2.0 : 1.0) * (dy == 0 ? 2.0 : 1.0));
  }
  lb /= 16.0;
  float aa = max(fwidth(lb) * 0.8, 0.012);
  float tw = smoothstep(0.48 - aa, 0.48 + aa, lb);
  vec3 cN = mix(tgt * mix(0.84, 1.1, smoothstep(0.14, 0.34, l)), uCwLight * mix(0.88, 1.03, l), tw);
  // alpha < 1 marks "forced" parts (light in the scan, coloured on the real shoe): use the colour everywhere
  cN = mix(cN, tgt * mix(0.9, 1.04, l), clamp((1.0 - tg.a) * 2.0, 0.0, 1.0));
  float t = smoothstep(0.12, 0.8, l);
  vec3 recStd = mix(uCwDark, uCwLight, t) * mix(0.85, 1.05, l);
  vec3 rec = mix(recStd, cN, uCwMask);
  float keep = smoothstep(0.12, 0.3, sat);              // saturated details (red ball) stay as scanned
  vec3 col = mix(texel.rgb, rec, uCwMix * (1.0 - keep));
  diffuseColor *= vec4(col, texel.a);
#endif
`;

function patchSolid(material, nodeMat) {
  material.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, U, { uNodeMat: { value: nodeMat } });
    shader.vertexShader = REVEAL_VERT_HEAD + shader.vertexShader.replace(
      '#include <begin_vertex>',
      '#include <begin_vertex>\n vSrc = (uNodeMat * vec4(transformed, 1.0)).xyz;\n vSrcN = normalize(mat3(uNodeMat) * objectNormal);'
    );
    shader.fragmentShader = REVEAL_FRAG_HEAD + CW_FRAG_HEAD + shader.fragmentShader
      .replace('#include <map_fragment>', CW_MAP)
      .replace('#include <clipping_planes_fragment>', '#include <clipping_planes_fragment>\n float sd = sweepDist(); if (sd > 0.0) discard;')
      .replace('#include <emissivemap_fragment>', '#include <emissivemap_fragment>\n totalEmissiveRadiance += uEdgeColor * 3.0 * (1.0 - smoothstep(0.0, uEdge, -sd));');
  };
  material.needsUpdate = true;
}

const identity = new THREE.Matrix4();

// Blueprint line material: shows only ahead of the sweep
const wireMat = new THREE.ShaderMaterial({
  uniforms: { ...U, uNodeMat: { value: identity } },
  transparent: true,
  depthWrite: false,
  vertexShader: REVEAL_VERT_HEAD + /* glsl */`
    void main() {
      vSrc = (uNodeMat * vec4(position, 1.0)).xyz;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }`,
  fragmentShader: REVEAL_FRAG_HEAD + /* glsl */`
    uniform float uWire; uniform vec3 uWireColor;
    void main() {
      float sd = sweepDist();
      if (sd < 0.0) discard;
      float edge = 1.0 - smoothstep(0.0, uEdge * 4.0, sd);
      vec3 c = mix(uWireColor, uEdgeColor, edge);
      gl_FragColor = vec4(c, (0.42 + edge * 0.6) * uWire);
    }`,
});

// Ghost surface: soft blueprint fill with fresnel rim, also writes depth to hide back lines
const ghostMat = new THREE.ShaderMaterial({
  uniforms: { ...U, uNodeMat: { value: identity } },
  transparent: true,
  polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1,
  vertexShader: REVEAL_VERT_HEAD + /* glsl */`
    varying vec3 vN; varying vec3 vV;
    void main() {
      vSrc = (uNodeMat * vec4(position, 1.0)).xyz;
      vec4 mv = modelViewMatrix * vec4(position, 1.0);
      vN = normalize(normalMatrix * normal); vV = normalize(-mv.xyz);
      gl_Position = projectionMatrix * mv;
    }`,
  fragmentShader: REVEAL_FRAG_HEAD + /* glsl */`
    uniform float uWire; uniform vec3 uWireColor;
    varying vec3 vN; varying vec3 vV;
    void main() {
      if (sweepDist() < 0.0) discard;
      float fr = pow(1.0 - abs(dot(normalize(vN), normalize(vV))), 2.2);
      gl_FragColor = vec4(uWireColor, (0.05 + fr * 0.35) * uWire);
    }`,
});

/* ------------------------------------------------------------------ *
 * Loading
 * ------------------------------------------------------------------ */
const loaderEl = document.getElementById('loader');
const loaderBar = document.getElementById('loaderBar');
const loaderPct = document.getElementById('loaderPct');
let pModel = 0, pWire = 0;
const setProgress = () => {
  const p = pModel * 0.88 + pWire * 0.12;
  loaderBar.style.transform = `scaleX(${p})`;
  loaderPct.textContent = `${Math.round(p * 100)}%`;
};

const navyTex = new THREE.TextureLoader().load('models/navy-color.webp');
navyTex.flipY = false;                 // same UV convention as glTF textures
navyTex.colorSpace = THREE.SRGBColorSpace;
navyTex.anisotropy = 8;
U.uNavyTex.value = navyTex;

const gltfLoader = new GLTFLoader().setMeshoptDecoder(MeshoptDecoder);
const modelPromise = gltfLoader.loadAsync('models/shoe.glb', (e) => { if (e.total) { pModel = e.loaded / e.total; setProgress(); } });
const wirePromise = new THREE.FileLoader().setResponseType('arraybuffer')
  .loadAsync('models/shoe-wire.bin', (e) => { if (e.total) { pWire = e.loaded / e.total; setProgress(); } });

let srcBox = null;      // bounding box in source space
let shadow = null;
let ready = false;

Promise.all([modelPromise, wirePromise]).then(([gltf, buf]) => {
  const root = gltf.scene;
  root.updateMatrixWorld(true);
  srcBox = new THREE.Box3().setFromObject(root);
  U.uBoxMin.value.copy(srcBox.min);
  srcBox.getSize(U.uBoxSize.value);

  root.traverse((o) => {
    if (!o.isMesh) return;
    const m = o.material;
    m.side = THREE.FrontSide;
    // leather and rubber are dielectric: the scan's metallic map made the whites look like plastic chrome
    m.metalness = 0;
    m.metalnessMap = null;
    m.roughness = 1;
    m.envMapIntensity = 0.85;
    o.castShadow = true;
    if (m.map?.image?.width) U.uMapTexel.value.set(1 / m.map.image.width, 1 / m.map.image.height);
    patchSolid(m, o.matrixWorld.clone()); // root has identity transform, so matrixWorld == node->source
  });

  // Wire geometry (raw positions + indices, already in source space)
  const [vc, ic] = new Uint32Array(buf, 0, 2);
  const pos = new Float32Array(buf, 8, vc * 3);
  const idx = new Uint32Array(buf, 8 + vc * 12, ic);
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setIndex(new THREE.BufferAttribute(idx, 1));
  g.computeVertexNormals();
  const ghost = new THREE.Mesh(g, ghostMat);
  ghost.renderOrder = 1;
  const lines = new THREE.LineSegments(new THREE.WireframeGeometry(g), wireMat);
  lines.renderOrder = 2;
  root.add(ghost, lines);
  snapCallouts(pos);

  // Normalize: centre the box and scale its longest horizontal extent to NORM_LENGTH
  const size = srcBox.getSize(new THREE.Vector3());
  const center = srcBox.getCenter(new THREE.Vector3());
  const s = NORM_LENGTH / Math.max(size.x, size.z);
  norm.scale.setScalar(s);
  norm.position.copy(center).multiplyScalar(-s);
  norm.add(root);

  // Sweep range along uDir
  const corners = boxCorners(srcBox).map((c) => c.dot(U.uDir.value));
  sweepRange = [Math.min(...corners) - 0.02, Math.max(...corners) + 0.02];

  // Contact shadow
  const tex = radialTexture();
  shadow = new THREE.Mesh(
    new THREE.PlaneGeometry(NORM_LENGTH * 1.12, NORM_LENGTH * 0.42),
    new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false, opacity: 0 })
  );
  shadow.rotation.x = -Math.PI / 2;
  // after orient, length lies along X; keep the shadow under the shoe
  shadow.position.y = -size.y * s * 0.5 - 0.005;
  yaw.add(shadow);
  // real cast shadow from the key light, on an invisible ground plane
  ground = new THREE.Mesh(new THREE.PlaneGeometry(8, 8), new THREE.ShadowMaterial({ opacity: 0, transparent: true }));
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = shadow.position.y - 0.002;
  ground.receiveShadow = true;
  yaw.add(ground);

  fillDimensions(size);
  ready = true;
  requestAnimationFrame(() => loaderEl.classList.add('is-done'));
}).catch((err) => {
  console.error(err);
  loaderPct.textContent = 'Could not load the model';
});

let sweepRange = [-1, 1];
let ground = null;

function nearestVertex(pos, t) {
  let best = 0, bd = Infinity;
  for (let i = 0; i < pos.length; i += 3) {
    const d = (pos[i] - t.x) ** 2 + (pos[i + 1] - t.y) ** 2 + (pos[i + 2] - t.z) ** 2;
    if (d < bd) { bd = d; best = i; }
  }
  return new THREE.Vector3(pos[best], pos[best + 1], pos[best + 2]);
}
function snapCallouts(pos) {
  for (const c of CALLOUTS) {
    c.anchors = [nearestVertex(pos, fromFrac(...c.f))];
    if (c.mirror) c.anchors.push(nearestVertex(pos, fromFrac(1 - c.f[0], c.f[1], c.f[2])));
  }
}

function boxCorners(b) {
  const out = [];
  for (const x of [b.min.x, b.max.x]) for (const y of [b.min.y, b.max.y]) for (const z of [b.min.z, b.max.z]) out.push(new THREE.Vector3(x, y, z));
  return out;
}

function radialTexture() {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const ctx = c.getContext('2d');
  const gr = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
  gr.addColorStop(0, 'rgba(0,0,0,0.6)');
  gr.addColorStop(0.35, 'rgba(0,0,0,0.3)');
  gr.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = gr; ctx.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

/* ------------------------------------------------------------------ *
 * Dimensions from the scan
 * ------------------------------------------------------------------ */
const dims = { length: 0, height: 0, width: 0 };
function fillDimensions(size) {
  const len = Math.max(size.x, size.z);
  const wid = Math.min(size.x, size.z);
  const k = REAL_LENGTH_CM / len;
  dims.length = len * k; dims.height = size.y * k; dims.width = wid * k;
  document.querySelectorAll('[data-dim]').forEach((el) => {
    el.textContent = `${dims[el.dataset.dim].toFixed(1)} cm`;
  });
  document.querySelectorAll('[data-dim-count]').forEach((el) => {
    const v = el.dataset.dimCount === 'ratio' ? dims.length / dims.width : dims[el.dataset.dimCount];
    el.dataset.to = v.toFixed(2);
  });
}

/* ------------------------------------------------------------------ *
 * Scroll choreography
 * ------------------------------------------------------------------ */
const KEYS = ['ry', 'rx', 'x', 'y', 'scale', 'reveal', 'wire', 'dims', 'callouts', 'paper'];
const stops = [...document.querySelectorAll('[data-ry]')];
let anchors = [];
let anatomyCentre = 0;
function measure() {
  const an = document.getElementById('anatomy');
  if (an) anatomyCentre = an.offsetTop + an.offsetHeight / 2;
  const maxScroll = document.documentElement.scrollHeight - innerHeight;
  anchors = stops.map((el, i) => {
    let a = el.offsetTop + el.offsetHeight / 2 - innerHeight / 2;
    if (i === 0) a = 0;
    if (i === stops.length - 1) a = maxScroll;
    return Math.max(0, Math.min(maxScroll, a));
  });
}
const values = stops.map((el) => Object.fromEntries(KEYS.map((k) => [k, parseFloat(el.dataset[k])])));
// Mobile poses: optional data-m-<key> per section (data-m-scale, data-m-y, ...), else the desktop value.
// Desktop `x` pushes the shoe beside the copy; on a phone it stays centred unless data-m-x says otherwise.
const valuesM = stops.map((el, i) => Object.fromEntries(KEYS.map((k) => {
  const m = el.dataset['m' + k[0].toUpperCase() + k.slice(1)];
  return [k, m !== undefined ? parseFloat(m) : k === 'x' ? 0 : values[i][k]];
})));

const target = Object.fromEntries(KEYS.map((k) => [k, values[0][k]]));
const cur = { ...target };
let activeIndex = 0;

const smooth = (t) => t * t * (3 - 2 * t);
function sampleScroll() {
  const y = scrollY;
  let i = 0;
  while (i < anchors.length - 2 && y > anchors[i + 1]) i++;
  const a = anchors[i], b = anchors[i + 1];
  const t = b > a ? smooth(Math.min(1, Math.max(0, (y - a) / (b - a)))) : 0;
  const vals = isMobile() ? valuesM : values;
  for (const k of KEYS) target[k] = vals[i][k] + (vals[i + 1][k] - vals[i][k]) * t;
  activeIndex = t > 0.5 ? i + 1 : i;
  return y / Math.max(1, anchors[anchors.length - 1]);
}

/* ------------------------------------------------------------------ *
 * Drag to rotate (spring back to the choreographed angle)
 * ------------------------------------------------------------------ */
const drag = { active: false, id: null, lastX: 0, lastY: 0, offY: 0, offX: 0, velY: 0, lastMove: 0 };
canvas.addEventListener('pointerdown', (e) => {
  if (drag.active) return; // ignore extra touch points
  drag.active = true; drag.id = e.pointerId; drag.lastX = e.clientX; drag.lastY = e.clientY;
  canvas.setPointerCapture(e.pointerId);
  canvas.classList.add('is-dragging');
});
canvas.addEventListener('pointermove', (e) => {
  if (!drag.active || e.pointerId !== drag.id) return;
  const dx = e.clientX - drag.lastX, dy = e.clientY - drag.lastY;
  drag.lastX = e.clientX; drag.lastY = e.clientY;
  drag.offY += dx * 0.008; drag.velY = dx * 0.008;
  drag.offX = Math.max(-0.5, Math.min(0.5, drag.offX + dy * 0.004));
  drag.lastMove = performance.now();
});
const endDrag = (e) => {
  if (e.pointerId !== drag.id) return;
  drag.active = false; drag.id = null;
  // held still before letting go: no fling from a stale velocity
  if (performance.now() - drag.lastMove > 80) drag.velY = 0;
  canvas.classList.remove('is-dragging');
};
canvas.addEventListener('pointerup', endDrag);
canvas.addEventListener('pointercancel', endDrag);
// capture can be lost without pointerup (alt-tab, scroll gesture taking over); never stay stuck dragging
canvas.addEventListener('lostpointercapture', endDrag);

/* ------------------------------------------------------------------ *
 * SVG overlay: dimension lines + callouts
 * ------------------------------------------------------------------ */
const svg = document.getElementById('overlay');
const NS = 'http://www.w3.org/2000/svg';
const el = (tag, attrs = {}, parent = svg) => {
  const n = document.createElementNS(NS, tag);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  parent.appendChild(n);
  return n;
};

const dimG = el('g', { opacity: 0 });
const dimParts = ['len', 'hgt'].map(() => ({
  ext1: el('line', { class: 'dim-ext' }, dimG),
  ext2: el('line', { class: 'dim-ext' }, dimG),
  line: el('path', { class: 'dim-line', 'marker-start': 'url(#tick)', 'marker-end': 'url(#tick)' }, dimG),
  bg: el('rect', { class: 'dim-label-bg', height: 18 }, dimG),
  text: el('text', { 'text-anchor': 'middle', 'dominant-baseline': 'central' }, dimG),
}));
const defs = el('defs');
const marker = el('marker', { id: 'tick', viewBox: '-6 -6 12 12', markerWidth: 12, markerHeight: 12, orient: 'auto-start-reverse' }, defs);
el('path', { d: 'M -4 4 L 4 -4', stroke: '#fff', 'stroke-width': 1.2 }, marker);
svg.insertBefore(defs, svg.firstChild);

const coG = el('g', { opacity: 0 });
const coParts = CALLOUTS.map((c) => {
  const g = el('g', {}, coG);
  return {
    c, g,
    line: el('path', { class: 'co-line' }, g),
    dot: el('circle', { class: 'co-dot', r: 4 }, g),
    num: el('text', { class: 'co-num' }, g),
    text: el('text', {}, g),
  };
});

const v3 = new THREE.Vector3();
function project(src) {
  v3.copy(src);
  norm.children[0]?.localToWorld(v3);
  v3.project(camera);
  return [(v3.x * 0.5 + 0.5) * innerWidth, (-v3.y * 0.5 + 0.5) * innerHeight, v3.z];
}
function projectNearest(list) {
  let best = null;
  for (const a of list) { const p = project(a); if (!best || p[2] < best[2]) best = p; }
  return best;
}
function fromFrac(fx, fy, fz) {
  const b = srcBox;
  return new THREE.Vector3(b.min.x + (b.max.x - b.min.x) * fx, b.min.y + (b.max.y - b.min.y) * fy, b.min.z + (b.max.z - b.min.z) * fz);
}

function drawDim(p, a, b, offset, label) {
  // offset perpendicular to the a->b direction
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const L = Math.hypot(dx, dy) || 1;
  const nx = -dy / L * offset, ny = dx / L * offset;
  const A = [a[0] + nx, a[1] + ny], B = [b[0] + nx, b[1] + ny];
  p.ext1.setAttribute('x1', a[0]); p.ext1.setAttribute('y1', a[1]); p.ext1.setAttribute('x2', A[0] + nx * 0.25); p.ext1.setAttribute('y2', A[1] + ny * 0.25);
  p.ext2.setAttribute('x1', b[0]); p.ext2.setAttribute('y1', b[1]); p.ext2.setAttribute('x2', B[0] + nx * 0.25); p.ext2.setAttribute('y2', B[1] + ny * 0.25);
  p.line.setAttribute('d', `M${A[0]},${A[1]} L${B[0]},${B[1]}`);
  const mx = (A[0] + B[0]) / 2, my = (A[1] + B[1]) / 2;
  p.text.textContent = label;
  const w = label.length * 7.4 + 16;
  p.bg.setAttribute('x', mx - w / 2); p.bg.setAttribute('y', my - 9); p.bg.setAttribute('width', w);
  p.text.setAttribute('x', mx); p.text.setAttribute('y', my);
}

function updateOverlay() {
  if (!ready) return;
  dimG.setAttribute('opacity', cur.dims.toFixed(3));
  coG.setAttribute('opacity', (isMobile() ? 0 : cur.callouts).toFixed(3));

  if (cur.dims > 0.01) {
    // Length along the longest horizontal axis, measured at the sole
    const lenAxisZ = (srcBox.max.z - srcBox.min.z) >= (srcBox.max.x - srcBox.min.x);
    const a = lenAxisZ ? fromFrac(0.5, 0, 0) : fromFrac(0, 0, 0.5);
    const b = lenAxisZ ? fromFrac(0.5, 0, 1) : fromFrac(1, 0, 0.5);
    let pa = project(a), pb = project(b);
    if (pa[0] > pb[0]) [pa, pb] = [pb, pa];
    drawDim(dimParts[0], pa, pb, 44, `${dims.length.toFixed(1)} CM`);
    // Height at the heel end (leftmost on screen)
    const heelIsA = project(a)[0] <= project(b)[0];
    const base3 = heelIsA ? a : b;
    const top3 = base3.clone(); top3.y = srcBox.max.y;
    const ph = project(base3), pt = project(top3);
    drawDim(dimParts[1], ph, pt, 48, `${dims.height.toFixed(1)} CM`);
  }

  if (cur.callouts > 0.01 && !isMobile()) {
    // Callout labels sit on the bright 120px grid lines: column on x = 120, one row per major line,
    // text baseline and leader tick on the line. Rows are centred on the anatomy section; when the grid
    // scrolls with the page they are anchored to the page (so they ride on the same lines), otherwise
    // they snap to the fixed grid in the window.
    const M = 120, n = coParts.length;
    const scrolling = document.documentElement.classList.contains('grid-scroll');
    const centre = scrolling ? anatomyCentre - scrollY : innerHeight / 2;
    const rowsTop = scrolling
      ? Math.round((anatomyCentre - ((n - 1) / 2) * M) / M) * M - scrollY
      : Math.round((centre - ((n - 1) / 2) * M) / M) * M;
    coParts.forEach((p, i) => {
      const [ax, ay] = projectNearest(p.c.anchors);
      const lx = M, ly = rowsTop + i * M;
      const elbow = lx + 2 * M + 24;
      p.line.setAttribute('d', `M${lx + 2 * M},${ly} L${elbow},${ly} L${ax},${ay}`);
      p.dot.setAttribute('cx', ax); p.dot.setAttribute('cy', ay);
      p.num.setAttribute('x', lx); p.num.setAttribute('y', ly); p.num.textContent = p.c.n;
      p.text.setAttribute('x', lx + 48); p.text.setAttribute('y', ly); p.text.textContent = p.c.label;
      // stagger each callout by its index
      const local = Math.min(1, Math.max(0, cur.callouts * 1.6 - i * 0.12));
      p.g.setAttribute('opacity', local.toFixed(3));
    });
  }
}

/* ------------------------------------------------------------------ *
 * HUD
 * ------------------------------------------------------------------ */
const paperEl = document.querySelector('.backdrop__paper');
const gridEl = document.querySelector('.backdrop__grid');
const railFill = document.getElementById('railFill');
const railLabel = document.getElementById('railLabel');
const sheetNo = document.getElementById('sheetNo');
const buildPct = document.getElementById('buildPct');
let lastIdx = -1, lastPaper = null, lastPct = -1;

function updateHud(progress) {
  railFill.style.transform = `scaleX(${progress.toFixed(4)})`;
  const paper = smooth(Math.min(1, Math.max(0, (cur.paper - 0.45) / 0.45)));
  paperEl.style.opacity = paper.toFixed(3);
  gridEl.style.opacity = (1 - paper).toFixed(3);
  const isPaper = paper > 0.5;
  if (isPaper !== lastPaper) { document.body.classList.toggle('is-paper', isPaper); lastPaper = isPaper; }
  if (activeIndex !== lastIdx) {
    const s = stops[activeIndex];
    railLabel.textContent = s.dataset.label; sheetNo.textContent = s.dataset.sheet; lastIdx = activeIndex;
    document.body.classList.toggle('no-shoe', s.id === 'court');
  }
  const pct = Math.round(cur.reveal * 100);
  if (pct !== lastPct) { buildPct.textContent = pct; lastPct = pct; }
  return paper;
}

/* ------------------------------------------------------------------ *
 * Loop
 * ------------------------------------------------------------------ */
measure();
addEventListener('resize', () => {
  renderer.setSize(innerWidth, innerHeight, false);
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  measure();
});
addEventListener('load', measure);

let lastT = performance.now();
const wireInk = new THREE.Color('#0c0c0d'), wireWhite = new THREE.Color('#ffffff');
let elapsed = 0;
let spinAngle = 0;

function frame(now = performance.now()) {
  const dt = Math.min((now - lastT) / 1000, 0.05);
  lastT = now;
  elapsed += dt;
  const progress = sampleScroll();
  const k = 1 - Math.exp(-dt * 6);
  for (const key of KEYS) cur[key] += (target[key] - cur[key]) * k;

  // drag spring: free while dragging, inertia, then ease back after a pause
  if (!drag.active) {
    drag.offY += drag.velY; drag.velY *= 0.92;
    if (performance.now() - drag.lastMove > 1400) {
      // wrap to (-PI, PI] first so a multi-turn drag eases back the short way instead of unwinding
      const TAU = Math.PI * 2;
      drag.offY -= Math.round(drag.offY / TAU) * TAU;
      drag.offY += (0 - drag.offY) * (1 - Math.exp(-dt * 2));
      drag.offX += (0 - drag.offX) * (1 - Math.exp(-dt * 2));
    }
  }

  const sway = reduceMotion ? 0 : Math.sin(elapsed * 0.5) * 0.12 * Math.max(0, 1 - progress * 6);
  // Outro turntable: integrate a speed (eased in over the last 6% of scroll) instead of scaling
  // `elapsed`, which made tiny scrolls at the bottom jump the shoe by many full turns.
  const spinRate = reduceMotion ? 0 : Math.min(1, Math.max(0, (progress - 0.94) / 0.06));
  if (spinRate > 0) {
    spinAngle += dt * 0.35 * spinRate;
  } else if (spinAngle !== 0) {
    // scrolled back up: settle on the nearest full turn so the shoe returns to its pose
    const home = Math.round(spinAngle / (Math.PI * 2)) * Math.PI * 2;
    spinAngle += (home - spinAngle) * (1 - Math.exp(-dt * 2));
    if (Math.abs(home - spinAngle) < 1e-4) spinAngle = 0;
  }
  const spin = spinAngle;

  const visH = 2 * camera.position.z * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
  const visW = visH * camera.aspect;
  const mobile = isMobile();
  // Mobile: the shoe is the hero. Fit its length to ~96% of the screen width (capped by height for
  // landscape / tablets) and hold it in the upper third, above the copy that sits at the bottom.
  const fit = mobile
    ? Math.min((visW * 0.96) / NORM_LENGTH, (visH * 0.62) / NORM_LENGTH)
    : Math.min(1.25, visW / 5.2);
  base.position.set(cur.x * visW, (mobile ? visH * 0.2 : 0) + cur.y * visH, 0);
  base.scale.setScalar(cur.scale * fit);
  pitch.rotation.x = cur.rx + drag.offX;
  yaw.rotation.y = cur.ry + drag.offY + sway + spin;

  // reveal + palette
  U.uSweep.value = sweepRange[0] + (sweepRange[1] - sweepRange[0]) * cur.reveal;
  const paper = updateHud(progress);
  U.uWireColor.value.copy(wireWhite).lerp(wireInk, paper);
  U.uWire.value = Math.max(cur.wire, 0.0);
  if (shadow) shadow.material.opacity = 0.12 + paper * 0.5;
  if (ground) ground.material.opacity = paper * (document.body.classList.contains('is-dark') ? 0.5 : 0.22);
  // keep the key light (and its shadow frustum) locked to the shoe wherever the layout moves it
  key.target.position.copy(base.position);
  key.position.copy(base.position).add(KEY_OFFSET);
  const sc = 2.2 * base.scale.x;
  if (Math.abs(key.shadow.camera.right - sc) > 0.01) {
    Object.assign(key.shadow.camera, { left: -sc, right: sc, top: sc, bottom: -sc });
    key.shadow.camera.updateProjectionMatrix();
  }
  scene.environmentIntensity = 0.75 + paper * 0.35;
  const kc = 1 - Math.exp(-dt * 7);
  U.uCwMix.value += (cwTarget.mix - U.uCwMix.value) * kc;
  U.uCwMask.value += (cwTarget.mask - U.uCwMask.value) * kc;
  U.uCwDark.value.lerp(cwTarget.dark, kc);
  U.uCwLight.value.lerp(cwTarget.light, kc);

  renderer.render(scene, camera);
  updateOverlay();
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

/* ------------------------------------------------------------------ *
 * In-view: text reveals, counters, bars, gauges
 * ------------------------------------------------------------------ */
document.querySelectorAll('.copy > *, .hero > *, .metrics__head > *, .court__head > *, .outro > *').forEach((n, i) => {
  n.classList.add('reveal');
  n.style.transitionDelay = `${(i % 6) * 60}ms`;
});

const easeOut = (t) => 1 - Math.pow(1 - t, 3);
function countUp(node) {
  const to = parseFloat(node.dataset.to || '0');
  const dec = parseInt(node.dataset.dec || '0', 10);
  if (reduceMotion) { node.textContent = to.toFixed(dec); return; }
  const t0 = performance.now(), dur = 1300;
  const tick = (now) => {
    const t = Math.min(1, (now - t0) / dur);
    node.textContent = (to * easeOut(t)).toFixed(dec);
    if (t < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

const io = new IntersectionObserver((entries) => {
  for (const e of entries) {
    if (!e.isIntersecting) continue;
    const n = e.target;
    n.classList.add('in-view');
    n.querySelectorAll('.count').forEach(countUp);
    n.querySelectorAll('.bars b').forEach((b) => { b.style.transform = `scaleX(${b.dataset.val / 100})`; });
    n.querySelectorAll('.gauge__fill').forEach((g) => { g.style.strokeDashoffset = 100 - g.dataset.val; });
    io.unobserve(n);
  }
}, { rootMargin: '0px 0px -4% 0px' });
document.querySelectorAll('.reveal, .card').forEach((n) => io.observe(n));

/* ------------------------------------------------------------------ *
 * Colorway tabs
 * ------------------------------------------------------------------ */
const tabs = [...document.querySelectorAll('.colorways [role="tab"]')];
const pill = document.querySelector('.colorways__pill');
const swatchBox = document.querySelector('.swatches');
const cwName = document.getElementById('cwName');
function movePill(btn) {
  pill.style.width = `${btn.offsetWidth}px`;
  pill.style.transform = `translateX(${btn.offsetLeft}px)`;
}
function setColorway(id, btn) {
  const cw = COLORWAYS[id];
  // when coming from the original texture, start the remap from its own colors so the fade is smooth
  if (U.uCwMix.value < 0.01) { U.uCwDark.value.set(COLORWAYS.og.dark); U.uCwLight.value.set(COLORWAYS.og.light); }
  cwTarget.mix = cw.mix;
  cwTarget.mask = cw.mask;
  cwTarget.dark.set(cw.dark);
  cwTarget.light.set(cw.light);
  tabs.forEach((t) => t.setAttribute('aria-selected', String(t === btn)));
  movePill(btn);
  swatchBox.innerHTML = cw.swatches.map(([n, c]) => `<span style="--c:${c}"><em class="mono">${n}</em></span>`).join('');
  if (cwName) cwName.textContent = btn.textContent.trim();
  document.body.classList.toggle('is-dark', id === 'blackout');
  dispatchEvent(new Event('themechange'));
}
tabs.forEach((t) => t.addEventListener('click', () => setColorway(t.dataset.cw, t)));
document.querySelector('.colorways').addEventListener('keydown', (e) => {
  if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
  const i = tabs.findIndex((t) => t.getAttribute('aria-selected') === 'true');
  const n = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
  n.focus(); setColorway(n.dataset.cw, n);
});
addEventListener('resize', () => movePill(tabs.find((t) => t.getAttribute('aria-selected') === 'true')));
document.fonts.ready.then(() => movePill(tabs[0]));

// test hook: ?debug exposes the drag state so screenshots can pose the model
if (new URLSearchParams(location.search).has('debug')) {
  window.__drag = drag;
  const rc = new THREE.Raycaster();
  window.__pick = (x, y) => {
    rc.setFromCamera(new THREE.Vector2((x / innerWidth) * 2 - 1, -(y / innerHeight) * 2 + 1), camera);
    const hit = rc.intersectObjects(scene.children, true).find((h) => h.object.isMesh && h.uv && h.object.material.map);
    return hit ? [Math.round(hit.uv.x * 8192), Math.round(hit.uv.y * 8192)] : null;
  };
  window.__pickF = (x, y) => {
    rc.setFromCamera(new THREE.Vector2((x / innerWidth) * 2 - 1, -(y / innerHeight) * 2 + 1), camera);
    const hit = rc.intersectObjects(scene.children, true).find((h) => h.object.isMesh && h.object.material.map);
    if (!hit) return null;
    const p = norm.children[0].worldToLocal(hit.point.clone());
    return [(p.x - srcBox.min.x) / (srcBox.max.x - srcBox.min.x), (p.y - srcBox.min.y) / (srcBox.max.y - srcBox.min.y), (p.z - srcBox.min.z) / (srcBox.max.z - srcBox.min.z)].map((v) => +v.toFixed(4));
  };
}
