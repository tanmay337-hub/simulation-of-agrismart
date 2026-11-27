import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

/**
 * Crisp 16-bit Pixel-Art Canvas Texture Factory (NearestFilter, zero blur)
 */
function makePixelTexture(w, h, painter, repeatX = 1, repeatY = 1) {
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  painter(ctx, w, h);

  const tex = new THREE.CanvasTexture(canvas);
  tex.magFilter = THREE.NearestFilter;
  tex.minFilter = THREE.NearestFilter;
  tex.generateMipmaps = false;
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(repeatX, repeatY);
  return tex;
}

function makeSpriteTexture(w, h, painter) {
  const tex = makePixelTexture(w, h, painter, 1, 1);
  tex.wrapS = THREE.ClampToEdgeWrapping;
  tex.wrapT = THREE.ClampToEdgeWrapping;
  return tex;
}

/** Draw filled integer-pixel circle/blob for crisp 16-bit canopies & clouds */
function pxBlob(ctx, cx, cy, r, color) {
  ctx.fillStyle = color;
  const r2 = r * r;
  for (let y = -r; y <= r; y++) {
    for (let x = -r; x <= r; x++) {
      if (x * x + y * y <= r2) {
        ctx.fillRect(Math.round(cx + x), Math.round(cy + y), 1, 1);
      }
    }
  }
}

function createTextures() {
  // Lush sunlit green pixel meadow matching reference grass terraces
  const grass = makePixelTexture(
    16,
    16,
    (ctx, w, h) => {
      ctx.fillStyle = "#8bc344";
      ctx.fillRect(0, 0, w, h);
      const blade = [
        [1, 2, "#9ed152"], [5, 1, "#72aa36"], [10, 4, "#a8db5c"],
        [13, 8, "#60962e"], [3, 10, "#9ed152"], [8, 12, "#72aa36"],
        [14, 14, "#60962e"], [2, 6, "#72aa36"], [11, 11, "#9ed152"],
      ];
      for (const [x, y, c] of blade) {
        ctx.fillStyle = c;
        ctx.fillRect(x, y, 2, 1);
      }
      ctx.fillStyle = "#ffe57f";
      ctx.fillRect(13, 2, 1, 1);
      ctx.fillStyle = "#f48fb1";
      ctx.fillRect(6, 14, 1, 1);
    },
    14,
    6
  );

  // Grass overhang + earthy shaded hill terrace cliff wall
  const terraceCliff = makePixelTexture(
    16,
    16,
    (ctx, w, h) => {
      ctx.fillStyle = "#4d7832";
      ctx.fillRect(0, 0, w, 5);
      ctx.fillStyle = "#6ca83b";
      for (let x = 0; x < w; x += 3) {
        ctx.fillRect(x, 0, 2, 4);
      }
      ctx.fillStyle = "#2b1b12";
      ctx.fillRect(0, 5, w, 1);
      ctx.fillStyle = "#6b482e";
      ctx.fillRect(0, 6, w, h - 6);
      ctx.fillStyle = "#523520";
      ctx.fillRect(2, 8, 3, 2);
      ctx.fillRect(10, 11, 4, 2);
      ctx.fillStyle = "#80593c";
      ctx.fillRect(6, 7, 3, 2);
    },
    14,
    1
  );

  // Warm dirt footpath with darker borders
  const path = makePixelTexture(
    16,
    16,
    (ctx, w, h) => {
      ctx.fillStyle = "#aa6f42";
      ctx.fillRect(0, 0, w, h);
      const stones = [
        [2, 3, "#8b5630"], [7, 2, "#c28655"], [12, 9, "#7d4a26"],
        [4, 12, "#8b5630"], [10, 5, "#c28655"], [1, 7, "#7d4a26"],
      ];
      for (const [x, y, c] of stones) {
        ctx.fillStyle = c;
        ctx.fillRect(x, y, 2, 2);
      }
    },
    4,
    4
  );

  // Tilled crop soil bed
  const soil = makePixelTexture(
    16,
    16,
    (ctx, w, h) => {
      ctx.fillStyle = "#6b4228";
      ctx.fillRect(0, 0, w, h);
      ctx.fillStyle = "#4e2e1a";
      for (let y = 0; y < h; y += 4) ctx.fillRect(0, y, w, 1);
      ctx.fillStyle = "#825437";
      ctx.fillRect(3, 2, 2, 1);
      ctx.fillRect(10, 6, 3, 1);
      ctx.fillRect(5, 10, 2, 1);
      ctx.fillRect(12, 14, 2, 1);
    },
    3,
    2
  );

  // Detailed pixel-art building facades
  const houseFront = makeSpriteTexture(48, 28, (ctx, w, h) => {
    // Timber wall planks + outline
    ctx.fillStyle = "#7a4a31";
    ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = "#5f3722";
    for (let y = 0; y < h; y += 4) ctx.fillRect(0, y, w, 1);
    ctx.fillStyle = "#26160e";
    ctx.strokeRect(0.5, 0.5, w - 1, h - 1);
    // Stone base
    ctx.fillStyle = "#786e65";
    ctx.fillRect(1, h - 4, w - 2, 3);
    // Door
    ctx.fillStyle = "#26160e";
    ctx.fillRect(20, 12, 8, 13);
    ctx.fillStyle = "#539ec4";
    ctx.fillRect(21, 13, 6, 11);
    ctx.fillStyle = "#98dcf7";
    ctx.fillRect(22, 14, 4, 4);
    // Left & Right Glowing Cyan Windows
    for (const wx of [6, 34]) {
      ctx.fillStyle = "#26160e";
      ctx.fillRect(wx, 8, 8, 8);
      ctx.fillStyle = "#6ac5ea";
      ctx.fillRect(wx + 1, 9, 6, 6);
      ctx.fillStyle = "#c8f0ff";
      ctx.fillRect(wx + 2, 10, 2, 2);
      ctx.fillStyle = "#26160e";
      ctx.fillRect(wx + 3, 9, 1, 6);
      ctx.fillRect(wx + 1, 12, 6, 1);
    }
  });

  const cottageFront = makeSpriteTexture(44, 24, (ctx, w, h) => {
    ctx.fillStyle = "#7c4c33";
    ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = "#5f3823";
    for (let y = 0; y < h; y += 4) ctx.fillRect(0, y, w, 1);
    ctx.fillStyle = "#26160e";
    ctx.fillRect(0, 0, w, 1);
    ctx.fillRect(0, h - 1, w, 1);
    // Double blue-framed cottage windows + wooden door
    for (const wx of [4, 15, 32]) {
      ctx.fillStyle = "#26160e";
      ctx.fillRect(wx, 7, 7, 8);
      ctx.fillStyle = "#6fcaf0";
      ctx.fillRect(wx + 1, 8, 5, 6);
      ctx.fillStyle = "#26160e";
      ctx.fillRect(wx + 3, 8, 1, 6);
      ctx.fillRect(wx + 1, 11, 5, 1);
    }
    ctx.fillStyle = "#26160e";
    ctx.fillRect(24, 9, 6, 14);
    ctx.fillStyle = "#59331f";
    ctx.fillRect(25, 10, 4, 12);
  });

  const barnFront = makeSpriteTexture(40, 24, (ctx, w, h) => {
    ctx.fillStyle = "#8a4b34";
    ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = "#633220";
    for (let x = 0; x < w; x += 4) ctx.fillRect(x, 0, 1, h);
    // Double barn door
    ctx.fillStyle = "#26160e";
    ctx.fillRect(13, 8, 14, 15);
    ctx.fillStyle = "#5f3923";
    ctx.fillRect(14, 9, 12, 13);
    ctx.fillStyle = "#f2d6a6";
    ctx.fillRect(19, 9, 1, 13);
    // Loft cyan window
    ctx.fillStyle = "#26160e";
    ctx.fillRect(17, 2, 6, 4);
    ctx.fillStyle = "#76d1f5";
    ctx.fillRect(18, 3, 4, 2);
  });

  const terracottaRoof = makePixelTexture(
    16,
    16,
    (ctx, w, h) => {
      ctx.fillStyle = "#e3683b";
      ctx.fillRect(0, 0, w, h);
      ctx.fillStyle = "#bd4822";
      for (let y = 0; y < h; y += 4) {
        ctx.fillRect(0, y, w, 1);
        for (let x = y % 8 === 0 ? 0 : 2; x < w; x += 4) ctx.fillRect(x, y, 1, 3);
      }
      ctx.fillStyle = "#f48f60";
      ctx.fillRect(1, 1, 2, 1);
      ctx.fillRect(9, 5, 2, 1);
    },
    3,
    2
  );

  const slateRoof = makePixelTexture(
    16,
    16,
    (ctx, w, h) => {
      ctx.fillStyle = "#584847";
      ctx.fillRect(0, 0, w, h);
      ctx.fillStyle = "#403332";
      for (let y = 0; y < h; y += 4) ctx.fillRect(0, y, w, 1);
      ctx.fillStyle = "#726160";
      ctx.fillRect(2, 2, 3, 1);
      ctx.fillRect(10, 6, 3, 1);
    },
    3,
    2
  );

  // Sky Panorama matching warm sunset + white pixel clouds + sky-blue peaks + teal treeline
  const skyBackdrop = makeSpriteTexture(320, 144, (ctx, w, h) => {
    const sky = ctx.createLinearGradient(0, 0, 0, 108);
    sky.addColorStop(0.0, "#e27f36");
    sky.addColorStop(0.28, "#ee9f4b");
    sky.addColorStop(0.55, "#f7c46f");
    sky.addColorStop(0.84, "#fce3a5");
    sky.addColorStop(1.0, "#d7ece2");
    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, w, h);

    // Subtle horizontal pixel sky scan-streaks like reference art
    ctx.fillStyle = "rgba(255, 248, 224, 0.35)";
    ctx.fillRect(16, 12, 84, 2);
    ctx.fillRect(190, 9, 96, 2);
    ctx.fillRect(62, 24, 110, 2);

    // Crisp Pixel Clouds
    const cloud = (cx, cy, sc) => {
      pxBlob(ctx, cx, cy, Math.round(9 * sc), "#f2d6a6");
      pxBlob(ctx, cx - 10 * sc, cy + 2 * sc, Math.round(7 * sc), "#f2d6a6");
      pxBlob(ctx, cx + 10 * sc, cy + 2 * sc, Math.round(7 * sc), "#f2d6a6");
      pxBlob(ctx, cx, cy - 2 * sc, Math.round(9 * sc), "#fff9ea");
      pxBlob(ctx, cx - 9 * sc, cy, Math.round(6.5 * sc), "#fff9ea");
      pxBlob(ctx, cx + 9 * sc, cy + 1 * sc, Math.round(6 * sc), "#fff9ea");
      ctx.fillStyle = "#fff9ea";
      ctx.fillRect(Math.round(cx - 16 * sc), Math.round(cy + 2 * sc), Math.round(32 * sc), Math.round(6 * sc));
    };
    cloud(44, 34, 1.3);
    cloud(148, 28, 1.0);
    cloud(266, 36, 1.45);

    // Pixelated sky-blue mountains (stair-stepped pixel raster!)
    const drawPixelMtn = (ridgeFn, color) => {
      ctx.fillStyle = color;
      for (let x = 0; x < w; x += 2) {
        const y = Math.floor(ridgeFn(x) / 2) * 2;
        ctx.fillRect(x, y, 2, h - y);
      }
    };
    drawPixelMtn(
      (x) =>
        88 -
        Math.max(0, 22 - Math.abs(x - 36) * 0.7) -
        Math.max(0, 28 - Math.abs(x - 105) * 0.65) -
        Math.max(0, 25 - Math.abs(x - 188) * 0.6) -
        Math.max(0, 26 - Math.abs(x - 275) * 0.65),
      "#a0cbe0"
    );
    drawPixelMtn(
      (x) =>
        104 -
        Math.max(0, 16 - Math.abs(x - 68) * 0.55) -
        Math.max(0, 20 - Math.abs(x - 152) * 0.5) -
        Math.max(0, 18 - Math.abs(x - 240) * 0.55),
      "#6f9fbc"
    );
    // Dark green-teal treeline horizon
    drawPixelMtn((x) => 118 - ((Math.sin(x * 0.11) * 4 + Math.cos(x * 0.27) * 3 + 4)), "#467550");
  });

  // 16-bit Pixel-Art Trees & Shrubs
  const treeOak = makeSpriteTexture(36, 44, (ctx) => {
    // Trunk
    ctx.fillStyle = "#24140c";
    ctx.fillRect(15, 27, 6, 16);
    ctx.fillStyle = "#694127";
    ctx.fillRect(16, 27, 4, 15);
    ctx.fillStyle = "#8a5939";
    ctx.fillRect(17, 28, 2, 13);
    // Dark outline blobs
    for (const [cx, cy, r] of [[18, 17, 12], [11, 20, 8], [25, 20, 8], [18, 9, 9]]) pxBlob(ctx, cx, cy, r, "#1b3019");
    // Deep forest fill
    for (const [cx, cy, r] of [[18, 17, 11], [11, 20, 7], [25, 20, 7], [18, 9, 8]]) pxBlob(ctx, cx, cy, r, "#2f6b31");
    // Mid leaf clumps
    for (const [cx, cy, r] of [[17, 15, 8], [12, 18, 5], [23, 18, 5], [18, 8, 6]]) pxBlob(ctx, cx, cy, r, "#4c963c");
    // Sunlit top pixel clusters
    for (const [cx, cy, r] of [[16, 11, 4], [21, 14, 3], [11, 16, 3], [18, 6, 4]]) pxBlob(ctx, cx, cy, r, "#88c448");
  });

  const treeAutumn = makeSpriteTexture(36, 44, (ctx) => {
    ctx.fillStyle = "#24140c";
    ctx.fillRect(15, 27, 6, 16);
    ctx.fillStyle = "#694127";
    ctx.fillRect(16, 27, 4, 15);
    for (const [cx, cy, r] of [[18, 17, 11], [11, 20, 7], [25, 20, 7], [18, 9, 8]]) pxBlob(ctx, cx, cy, r, "#2d2a12");
    for (const [cx, cy, r] of [[18, 17, 10], [11, 20, 6], [25, 20, 6], [18, 9, 7]]) pxBlob(ctx, cx, cy, r, "#6e6a29");
    for (const [cx, cy, r] of [[17, 14, 7], [12, 18, 4], [23, 18, 4], [18, 8, 5]]) pxBlob(ctx, cx, cy, r, "#9c9436");
    for (const [cx, cy, r] of [[16, 10, 4], [21, 13, 3], [18, 6, 3]]) pxBlob(ctx, cx, cy, r, "#caba4d");
  });

  const flowerBush = makeSpriteTexture(24, 18, (ctx) => {
    for (const [cx, cy, r] of [[12, 11, 7], [7, 12, 5], [17, 12, 5]]) pxBlob(ctx, cx, cy, r, "#1d381b");
    for (const [cx, cy, r] of [[12, 11, 6], [7, 12, 4], [17, 12, 4]]) pxBlob(ctx, cx, cy, r, "#3c7e34");
    for (const [cx, cy, r] of [[11, 9, 4], [15, 10, 3]]) pxBlob(ctx, cx, cy, r, "#6ab344");
    // Pink & cream pixel blossoms
    for (const [fx, fy, fc] of [[7, 10, "#f48fb1"], [12, 8, "#fce4ec"], [16, 11, "#f48fb1"], [10, 12, "#ffd54f"]]) {
      ctx.fillStyle = fc;
      ctx.fillRect(fx, fy, 2, 2);
    }
  });

  // 4 Crop Pixel Sprites (white-tinted material can shift them slightly for drought/frost)
  const cropTomato = makeSpriteTexture(24, 24, (ctx) => {
    for (const [cx, cy, r] of [[12, 14, 8], [7, 16, 5], [17, 16, 5], [12, 9, 6]]) pxBlob(ctx, cx, cy, r, "#1e3a1a");
    for (const [cx, cy, r] of [[12, 14, 7], [7, 16, 4], [17, 16, 4], [12, 9, 5]]) pxBlob(ctx, cx, cy, r, "#3f8735");
    for (const [cx, cy, r] of [[11, 11, 4], [15, 13, 3]]) pxBlob(ctx, cx, cy, r, "#6cc04a");
    // Plump red pixel tomatoes
    for (const [tx, ty] of [[8, 12], [14, 15], [12, 8]]) {
      ctx.fillStyle = "#26160e";
      ctx.fillRect(tx - 1, ty - 1, 4, 4);
      ctx.fillStyle = "#df3c2c";
      ctx.fillRect(tx, ty, 3, 3);
      ctx.fillStyle = "#ff8a65";
      ctx.fillRect(tx, ty, 1, 1);
    }
  });

  const cropWheat = makeSpriteTexture(24, 24, (ctx) => {
    // Rich golden-orange harvest stalks echoing reference bottom crop field
    ctx.fillStyle = "#2c1b0e";
    for (const sx of [5, 10, 15, 19]) {
      ctx.fillRect(sx - 1, 6, 4, 17);
      ctx.fillStyle = "#a35b1f";
      ctx.fillRect(sx, 14, 2, 9);
      ctx.fillStyle = "#d97828";
      ctx.fillRect(sx, 8, 2, 7);
      ctx.fillStyle = "#f2b644";
      ctx.fillRect(sx - 1, 7, 3, 4);
      ctx.fillStyle = "#ffe082";
      ctx.fillRect(sx, 6, 1, 2);
      ctx.fillStyle = "#2c1b0e";
    }
  });

  const cropCorn = makeSpriteTexture(24, 28, (ctx) => {
    ctx.fillStyle = "#1c3618";
    ctx.fillRect(10, 4, 4, 23);
    ctx.fillRect(4, 12, 6, 3);
    ctx.fillRect(14, 10, 6, 3);
    ctx.fillStyle = "#4d9436";
    ctx.fillRect(11, 5, 2, 21);
    ctx.fillRect(5, 13, 6, 2);
    ctx.fillRect(13, 11, 6, 2);
    // Yellow cobs
    ctx.fillStyle = "#f4c43f";
    ctx.fillRect(8, 14, 3, 5);
    ctx.fillRect(13, 15, 3, 5);
    ctx.fillStyle = "#d89c2e";
    ctx.fillRect(11, 2, 2, 3);
  });

  const cropSoy = makeSpriteTexture(24, 22, (ctx) => {
    for (const [cx, cy, r] of [[12, 13, 7], [7, 15, 5], [17, 15, 5]]) pxBlob(ctx, cx, cy, r, "#1d3d19");
    for (const [cx, cy, r] of [[12, 13, 6], [7, 15, 4], [17, 15, 4]]) pxBlob(ctx, cx, cy, r, "#47993c");
    for (const [cx, cy, r] of [[11, 10, 4], [15, 11, 3]]) pxBlob(ctx, cx, cy, r, "#7fd053");
    ctx.fillStyle = "#d8eb75";
    ctx.fillRect(9, 13, 2, 3);
    ctx.fillRect(14, 12, 2, 3);
  });

  return {
    grass,
    terraceCliff,
    path,
    soil,
    houseFront,
    cottageFront,
    barnFront,
    terracottaRoof,
    slateRoof,
    skyBackdrop,
    treeOak,
    treeAutumn,
    flowerBush,
    cropTomato,
    cropWheat,
    cropCorn,
    cropSoy,
  };
}

// 3 Terraced Diorama Elevations:
//   Terrace 3 (Back Hill, y=1.65): Farmhouse, Cistern Tank, MQTT Relay Mast
//   Terrace 2 (Mid Terrace, y=0.82): Barn + Cottage + Shed in back, Sectors 3 & 4 in front
//   Terrace 1 (Front Terrace, y=0.0): Sectors 1 & 2, Lantern, Front Fence & Trees
const SECTOR_META = {
  1: { x: -5.4, y: 0.0,  z: 4.8,  crop: "tomato", label: "Sector 1 (Tomatoes)" },
  2: { x: 5.4,  y: 0.0,  z: 4.8,  crop: "wheat",  label: "Sector 2 (Wheat)" },
  3: { x: -5.4, y: 0.82, z: -0.6, crop: "corn",   label: "Sector 3 (Corn)" },
  4: { x: 5.4,  y: 0.82, z: -0.6, crop: "soy",    label: "Sector 4 (Soybeans)" },
};

// Narrow 20-deg telephoto camera for crisp 2.5D orthogonal-like depth without distortion
const CAMERA_PRESETS = {
  overview: { pos: [0, 21.5, 42.5], target: [0, 1.3, -1.2] },
  1:        { pos: [-5.4, 9.5, 22.0], target: [-5.4, 0.7, 4.8] },
  2:        { pos: [5.4, 9.5, 22.0],  target: [5.4, 0.7, 4.8] },
  3:        { pos: [-5.4, 10.5, 17.5], target: [-5.4, 1.5, -0.6] },
  4:        { pos: [5.4, 10.5, 17.5],  target: [5.4, 1.5, -0.6] },
  top:      { pos: [0, 48.0, 6.0],    target: [0, 0.8, -1.2] },
};

export class Farm3DScene {
  constructor(canvas, onSelectSector, onHover) {
    this.canvas = canvas;
    this.onSelectSector = onSelectSector;
    this.onHover = onHover;
    this.selectedSector = 1;
    this.hoveredSector = null;
    this.crisis = "normal";
    this.sectorVisuals = {};
    this.smokePuffs = [];
    this.mqttPackets = [];
    this.rainParticles = null;
    this.frostParticles = null;
    this.swaySprites = [];
    this.latestState = null;

    this._initScene();
    this._buildTerracedEnvironment();
    this._buildBuildingsAndTank();
    this._buildSectors();
    this._buildWeatherParticles();
    this._bindEvents();
    this._animate();
  }

  _initScene() {
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color("#f3b659");

    const w = this.canvas.clientWidth || 800;
    const h = this.canvas.clientHeight || 500;
    this.camera = new THREE.PerspectiveCamera(20, w / h, 0.5, 180);
    this.camera.position.set(...CAMERA_PRESETS.overview.pos);

    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas,
      antialias: false,
      powerPreference: "high-performance",
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setSize(w, h, false);
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.BasicShadowMap;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;

    // Restricted 2.5D OrbitControls: smooth pan, zoom, and subtle tilt while locking front diorama framing
    this.controls = new OrbitControls(this.camera, this.canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.09;
    this.controls.minAzimuthAngle = -0.62;
    this.controls.maxAzimuthAngle = 0.62;
    this.controls.minPolarAngle = 0.35;
    this.controls.maxPolarAngle = 1.18;
    this.controls.minDistance = 15;
    this.controls.maxDistance = 62;
    this.controls.target.set(...CAMERA_PRESETS.overview.target);

    // Golden-Hour Illumination
    this.hemiLight = new THREE.HemisphereLight("#ffefc8", "#4e7636", 1.1);
    this.scene.add(this.hemiLight);

    this.sunLight = new THREE.DirectionalLight("#fff2cc", 1.65);
    this.sunLight.position.set(16, 26, 16);
    this.sunLight.castShadow = true;
    this.sunLight.shadow.mapSize.set(1024, 1024);
    this.sunLight.shadow.camera.near = 2;
    this.sunLight.shadow.camera.far = 75;
    this.sunLight.shadow.camera.left = -20;
    this.sunLight.shadow.camera.right = 20;
    this.sunLight.shadow.camera.top = 20;
    this.sunLight.shadow.camera.bottom = -20;
    this.scene.add(this.sunLight);

    this.tex = createTextures();
    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    this.hardwareHitMeshes = [];
    this.sectorHitMeshes = [];
  }

  _box(w, h, d, colorOrMat, x = 0, y = 0, z = 0) {
    const mat =
      colorOrMat instanceof THREE.Material
        ? colorOrMat
        : new THREE.MeshLambertMaterial({ color: colorOrMat });
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
    mesh.position.set(x, y, z);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    return mesh;
  }

  _spriteCard(tex, w, h, x, y, z, tilt = -0.22) {
    const mat = new THREE.MeshLambertMaterial({
      map: tex,
      transparent: true,
      alphaTest: 0.45,
      side: THREE.DoubleSide,
    });
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, h), mat);
    mesh.position.set(x, y + h / 2, z);
    mesh.rotation.x = tilt;
    mesh.castShadow = true;
    return mesh;
  }

  _buildTerracedEnvironment() {
    // Wide sunset sky + blue mountains backdrop across the northern horizon
    const skyMat = new THREE.MeshBasicMaterial({ map: this.tex.skyBackdrop });
    const skyPlane = new THREE.Mesh(new THREE.PlaneGeometry(66, 27), skyMat);
    skyPlane.position.set(0, 9.2, -16.5);
    this.scene.add(skyPlane);

    const grassMat = new THREE.MeshLambertMaterial({ map: this.tex.grass });
    const cliffMat = new THREE.MeshLambertMaterial({ map: this.tex.terraceCliff });
    const dirtSide = new THREE.MeshLambertMaterial({ color: "#523523" });

    // Tier 1: Foreground Terrace (top at y = 0.0)
    const t1 = this._box(30, 1.2, 23, [dirtSide, dirtSide, grassMat, dirtSide, cliffMat, dirtSide], 0, -0.6, -0.5);
    t1.castShadow = false;
    this.scene.add(t1);

    // Tier 2: Middle Terrace (top at y = 0.82, z from -6.8 to +1.8)
    const t2 = this._box(30, 0.82, 8.8, [dirtSide, dirtSide, grassMat, dirtSide, cliffMat, dirtSide], 0, 0.41, -2.5);
    t2.castShadow = false;
    this.scene.add(t2);

    // Tier 3: Upper Hill Terrace (top at y = 1.65, z from -12.0 to -6.8)
    const t3 = this._box(30, 0.83, 5.4, [dirtSide, dirtSide, grassMat, dirtSide, cliffMat, dirtSide], 0, 1.235, -9.4);
    t3.castShadow = false;
    this.scene.add(t3);

    // Meandering Dirt Trails descending across the terraces (with dark timber-brown border trim)
    const pathMat = new THREE.MeshLambertMaterial({ map: this.tex.path });
    const addPathSeg = (w, d, x, y, z, rotY = 0) => {
      const m = this._box(w, 0.04, d, pathMat, x, y + 0.02, z);
      m.rotation.y = rotY;
      m.castShadow = false;
      this.scene.add(m);
    };
    addPathSeg(2.2, 3.6, -0.6, 1.65, -7.8, -0.18); // from Farmhouse hill
    addPathSeg(10.5, 1.5, -3.5, 0.82, -3.4, 0.05); // across Barn / Cottage / Shed front
    addPathSeg(2.2, 5.2, -0.2, 0.82, -0.6, 0.14); // center ramp down to Sector 3/4 corridor
    addPathSeg(2.3, 8.2, 0.0, 0.0, 5.6, -0.05);   // down between Sectors 1 & 2 to gate
    addPathSeg(22.0, 1.5, 0.0, 0.0, 2.0, 0.0);    // front cross trail

    // Warm Garden Lantern Post along right dirt path (from reference artwork)
    const lantern = new THREE.Group();
    lantern.position.set(1.5, 0.0, 2.8);
    lantern.add(this._box(0.14, 1.85, 0.14, "#3b5e36", 0, 0.92, 0));
    lantern.add(this._box(0.45, 0.12, 0.12, "#3b5e36", 0.18, 1.82, 0));
    lantern.add(new THREE.Mesh(new THREE.BoxGeometry(0.24, 0.28, 0.24), new THREE.MeshBasicMaterial({ color: "#ffe082" })));
    lantern.children[2].position.set(0.35, 1.66, 0);
    this.scene.add(lantern);

    // Split-Rail Wooden Fences lining terrace edges like reference farm
    this._addFenceRow(-13.8, 1.65, -1.6, 1.65, -7.1, 6);
    this._addFenceRow(4.2, 0.82, 13.8, 0.82, -3.3, 5);
    this._addFenceRow(-13.5, 0.0, -1.8, 0.0, 8.6, 6);
    this._addFenceRow(1.8, 0.0, 13.5, 0.0, 8.6, 6);

    // 2.5D Pixel-Art Trees (Oak & Autumn Olive pairs matching the reference hills & foreground)
    const treePlacements = [
      // Back upper hill left & right clusters
      [-12.6, 1.65, -9.6, "oak", 3.6, 4.4],
      [-9.5,  1.65, -9.3, "autumn", 3.4, 4.1],
      [-13.4, 1.65, -7.7, "oak", 3.2, 3.9],
      [13.4,  1.65, -9.4, "oak", 3.5, 4.3],
      // Middle terrace flanking trees
      [-13.4, 0.82, -4.6, "oak", 3.1, 3.8],
      [13.4,  0.82, -4.4, "oak", 3.2, 3.9],
      [-12.2, 0.82, -0.5, "autumn", 2.9, 3.5],
      [12.3,  0.82, -0.4, "oak", 3.0, 3.6],
      // Foreground framing grove along bottom edge
      [-12.6, 0.0, 8.2, "oak", 3.7, 4.5],
      [-10.2, 0.0, 9.0, "oak", 3.1, 3.8],
      [-2.2,  0.0, 9.2, "oak", 2.7, 3.3],
      [10.8,  0.0, 8.9, "oak", 3.3, 4.0],
      [13.0,  0.0, 8.0, "oak", 3.6, 4.4],
    ];
    for (const [x, y, z, kind, w, h] of treePlacements) {
      const tex = kind === "autumn" ? this.tex.treeAutumn : this.tex.treeOak;
      const sp = this._spriteCard(tex, w, h, x, y, z, -0.22);
      sp.userData.baseX = x;
      sp.userData.swayPhase = x * 0.4 + z * 0.2;
      this.swaySprites.push(sp);
      this.scene.add(sp);
    }

    // Cozy Flower Shrubs beside paths & buildings
    const bushSpots = [
      [-1.5, 1.65, -8.3], [-4.1, 0.82, -3.5], [-10.0, 0.82, -3.4],
      [9.4, 0.82, -3.4], [2.4, 0.0, 7.6], [-2.5, 0.0, 2.2],
    ];
    for (const [bx, by, bz] of bushSpots) {
      this.scene.add(this._spriteCard(this.tex.flowerBush, 1.5, 1.15, bx, by, bz, -0.22));
    }
  }

  _addFenceRow(x1, y, x2, _unusedY, z, segments) {
    const g = new THREE.Group();
    const dx = x2 - x1;
    const len = Math.abs(dx);
    for (let i = 0; i <= segments; i++) {
      const t = i / segments;
      g.add(this._box(0.16, 0.65, 0.16, "#5c3923", x1 + dx * t, y + 0.32, z));
    }
    for (const ry of [y + 0.24, y + 0.48]) {
      g.add(this._box(len, 0.09, 0.08, "#8c5c3e", (x1 + x2) / 2, ry, z));
    }
    this.scene.add(g);
  }

  _buildBuildingsAndTank() {
    const roofOrange = new THREE.MeshLambertMaterial({ map: this.tex.terracottaRoof });
    const roofSlate = new THREE.MeshLambertMaterial({ map: this.tex.slateRoof });
    const woodSide = new THREE.MeshLambertMaterial({ color: "#693e28" });
    const houseFace = new THREE.MeshLambertMaterial({ map: this.tex.houseFront });
    const cottageFace = new THREE.MeshLambertMaterial({ map: this.tex.cottageFront });
    const barnFace = new THREE.MeshLambertMaterial({ map: this.tex.barnFront });

    // 1) Upper Hilltop Main Farmhouse (x=1.8, y=1.65, z=-9.5) — cozy visual centerpiece
    const fh = new THREE.Group();
    fh.position.set(1.8, 1.65, -9.5);
    fh.add(this._box(4.2, 2.2, 2.8, [woodSide, woodSide, woodSide, woodSide, houseFace, woodSide], 0, 1.1, 0));
    // Terracotta stepped pixel gable roof + pale cream eaves trim
    fh.add(this._box(4.6, 0.22, 3.2, "#f3e2c4", 0, 2.25, 0));
    fh.add(this._box(4.5, 0.45, 3.1, roofOrange, 0, 2.52, 0));
    fh.add(this._box(3.5, 0.45, 2.3, roofOrange, 0, 2.95, 0));
    fh.add(this._box(2.3, 0.42, 1.4, roofOrange, 0, 3.38, 0));
    // Side woodshed lean-to
    fh.add(this._box(1.1, 1.35, 2.1, "#5c3b2c", -2.6, 0.68, -0.2));
    // Two Brick Chimneys like reference farmhouse
    fh.add(this._box(0.45, 1.1, 0.45, "#7d5444", 0.55, 3.55, -0.25));
    fh.add(this._box(0.45, 1.1, 0.45, "#7d5444", 1.25, 3.55, -0.25));
    this.scene.add(fh);

    // Rising pixel chimney smoke
    for (let i = 0; i < 5; i++) {
      const puff = this._box(0.32, 0.28, 0.32, "#f9dfc1", 2.35, 5.7 + i * 0.5, -9.75);
      puff.material = new THREE.MeshBasicMaterial({ color: "#f9dfc1", transparent: true, opacity: 0.8 });
      puff.userData.phase = i * 0.2;
      puff.castShadow = false;
      this.smokePuffs.push(puff);
      this.scene.add(puff);
    }

    // Cozy covered wagon beside the farmhouse (from reference image!)
    const wagon = new THREE.Group();
    wagon.position.set(5.1, 1.65, -9.3);
    wagon.add(this._box(1.4, 0.55, 0.9, "#73462c", 0, 0.45, 0));
    wagon.add(this._box(1.5, 0.6, 1.0, "#ead9ba", 0, 0.98, 0));
    this.scene.add(wagon);

    // 2) Middle-Left Rustic Barn (x=-10.2, y=0.82, z=-4.9)
    const barn = new THREE.Group();
    barn.position.set(-10.2, 0.82, -4.9);
    barn.add(this._box(3.2, 2.0, 2.5, [woodSide, woodSide, woodSide, woodSide, barnFace, woodSide], 0, 1.0, 0));
    barn.add(this._box(3.5, 0.2, 2.8, "#5d778a", 0, 2.08, 0)); // blue fascia trim
    barn.add(this._box(3.4, 0.45, 2.7, roofSlate, 0, 2.34, 0));
    barn.add(this._box(2.3, 0.45, 1.8, roofSlate, 0, 2.78, 0));
    this.scene.add(barn);

    // 3) Middle-Center Cozy Cottage Farmhouse (x=-5.6, y=0.82, z=-4.9)
    const cottage = new THREE.Group();
    cottage.position.set(-5.6, 0.82, -4.9);
    cottage.add(this._box(3.8, 1.9, 2.5, [woodSide, woodSide, woodSide, woodSide, cottageFace, woodSide], 0, 0.95, 0));
    cottage.add(this._box(4.1, 0.2, 2.8, "#f7e8ca", 0, 1.98, 0));
    cottage.add(this._box(4.0, 0.45, 2.7, roofOrange, 0, 2.24, 0));
    cottage.add(this._box(2.9, 0.45, 1.9, roofOrange, 0, 2.68, 0));
    cottage.add(this._box(0.45, 0.9, 0.45, "#7d5444", 0.9, 2.95, 0));
    this.scene.add(cottage);

    // 4) Middle-Right Tool & Pump Control Shed (x=10.4, y=0.82, z=-4.9) — Blue siding + Coral roof
    const shed = new THREE.Group();
    shed.position.set(10.4, 0.82, -4.9);
    shed.add(this._box(2.8, 1.9, 2.3, ["#4d6988", "#4d6988", "#4d6988", "#4d6988", houseFace, "#4d6988"], 0, 0.95, 0));
    shed.add(this._box(3.1, 0.2, 2.6, "#f7e8ca", 0, 1.98, 0));
    shed.add(this._box(3.0, 0.45, 2.5, "#d84c35", 0, 2.24, 0));
    shed.add(this._box(2.0, 0.42, 1.6, "#d84c35", 0, 2.66, 0));
    this.scene.add(shed);

    // 5) Water Cistern Tank & Pump Station on Upper Hill (feeds blue PVC pipes down to sectors)
    const tank = new THREE.Group();
    tank.position.set(7.9, 1.65, -9.2);
    for (const [lx, lz] of [[-0.75, -0.75], [0.75, -0.75], [-0.75, 0.75], [0.75, 0.75]]) {
      tank.add(this._box(0.22, 1.5, 0.22, "#593b28", lx, 0.75, lz));
    }
    tank.add(this._box(2.1, 1.6, 2.1, "#4689b8", 0, 2.25, 0));
    tank.add(this._box(2.3, 0.28, 2.3, "#2c5f85", 0, 3.15, 0));
    this.pumpBeacon = new THREE.Mesh(
      new THREE.BoxGeometry(0.38, 0.38, 0.38),
      new THREE.MeshBasicMaterial({ color: "#43a047" })
    );
    this.pumpBeacon.position.set(0, 3.55, 0);
    tank.add(this.pumpBeacon);
    this.scene.add(tank);

    // 6) Field Wireless MQTT Relay Tower (forwards sensor packets OFF-SITE to safe RPi 5 Control Room!)
    const relay = new THREE.Group();
    relay.position.set(11.4, 1.65, -9.1);
    relay.add(this._box(0.32, 3.4, 0.32, "#495461", 0, 1.7, 0));
    relay.add(this._box(1.3, 0.18, 0.18, "#8795a6", 0, 3.15, 0));
    this.relayTip = new THREE.Mesh(
      new THREE.BoxGeometry(0.36, 0.36, 0.36),
      new THREE.MeshBasicMaterial({ color: "#38bdf8" })
    );
    this.relayTip.position.set(0, 3.65, 0);
    relay.add(this.relayTip);
    this.scene.add(relay);
    this.relayWorldPos = new THREE.Vector3(11.4, 5.3, -9.1);

    // Main PVC Trunk Pipe stepping cleanly from Tank -> Terrace 2 -> Terrace 1
    const pipeMat = new THREE.MeshLambertMaterial({ color: "#2d83bc" });
    this.scene.add(this._box(6.4, 0.2, 0.2, pipeMat, 4.6, 1.8, -8.3));
    this.scene.add(this._box(0.22, 0.2, 7.6, pipeMat, 1.45, 0.96, -4.5));
    this.scene.add(this._box(0.22, 0.95, 0.22, pipeMat, 1.45, 1.38, -8.3));
    this.scene.add(this._box(0.22, 0.95, 0.22, pipeMat, 1.45, 0.48, 1.7));
    this.scene.add(this._box(0.22, 0.2, 4.2, pipeMat, 1.45, 0.14, 3.7));
  }

  _buildSectors() {
    const soilMatBase = new THREE.MeshLambertMaterial({ map: this.tex.soil });
    const pipeMat = new THREE.MeshLambertMaterial({ color: "#2d83bc" });

    for (const sid of [1, 2, 3, 4]) {
      const meta = SECTOR_META[sid];
      const group = new THREE.Group();
      group.position.set(meta.x, meta.y, meta.z);

      // Raised soil plot bed (7.4 x 4.4)
      const soilMat = soilMatBase.clone();
      const bed = this._box(7.4, 0.24, 4.4, soilMat, 0, 0.12, 0);
      bed.userData.sectorId = sid;
      bed.userData.label = meta.label;
      this.sectorHitMeshes.push(bed);
      group.add(bed);

      // Timber bed border
      group.add(this._box(7.7, 0.3, 0.18, "#5e3b25", 0, 0.15, 2.25));
      group.add(this._box(7.7, 0.3, 0.18, "#5e3b25", 0, 0.15, -2.25));
      group.add(this._box(0.18, 0.3, 4.5, "#5e3b25", -3.76, 0.15, 0));
      group.add(this._box(0.18, 0.3, 4.5, "#5e3b25", 3.76, 0.15, 0));

      // Selection Highlight Ring + Subtle Hover Border
      const selMat = new THREE.MeshBasicMaterial({
        color: "#ffd54f",
        transparent: true,
        opacity: sid === 1 ? 0.92 : 0.0,
      });
      const selRing = new THREE.Mesh(new THREE.BoxGeometry(7.95, 0.06, 4.85), selMat);
      selRing.position.set(0, 0.04, 0);
      group.add(selRing);

      const hoverMat = new THREE.MeshBasicMaterial({
        color: "#ffffff",
        transparent: true,
        opacity: 0.0,
      });
      const hoverRing = new THREE.Mesh(new THREE.BoxGeometry(8.15, 0.04, 5.05), hoverMat);
      hoverRing.position.set(0, 0.02, 0);
      group.add(hoverRing);

      // Full-sector invisible hover/click catch box so hovering ANY gap over crops reads moisture smoothly
      const catchMat = new THREE.MeshBasicMaterial({
        transparent: true,
        opacity: 0.0,
        depthWrite: false,
      });
      const catchBox = new THREE.Mesh(new THREE.BoxGeometry(7.9, 1.8, 4.8), catchMat);
      catchBox.position.set(0, 0.9, 0);
      catchBox.userData.sectorId = sid;
      catchBox.userData.label = meta.label;
      this.sectorHitMeshes.push(catchBox);
      group.add(catchBox);

      // Dense 2.5D Pixel-Art Crop Sprites in neat agricultural rows
      const cropTex =
        meta.crop === "tomato"
          ? this.tex.cropTomato
          : meta.crop === "wheat"
          ? this.tex.cropWheat
          : meta.crop === "corn"
          ? this.tex.cropCorn
          : this.tex.cropSoy;
      const cropW = meta.crop === "corn" ? 0.9 : 0.85;
      const cropH = meta.crop === "corn" ? 1.15 : 0.88;
      const cropMeshes = [];

      for (let row = -1.35; row <= 1.36; row += 0.9) {
        for (let col = -2.6; col <= 2.61; col += 0.86) {
          if (Math.abs(col) < 0.55 && Math.abs(row) < 0.55) continue;
          const sp = this._spriteCard(cropTex, cropW, cropH, col, 0.24, row, -0.2);
          sp.userData.baseX = col;
          sp.userData.baseH = cropH;
          sp.userData.swayPhase = sid + col * 0.7 + row * 1.1;
          this.swaySprites.push(sp);
          cropMeshes.push(sp);
          group.add(sp);
        }
      }

      // PVC Branch Pipe + Solenoid Valve + Flow Sensor on inner corridor side
      const pipeSide = meta.x < 0 ? 1 : -1;
      const inletX = pipeSide * 3.4;
      group.add(this._box(2.2, 0.16, 0.16, pipeMat, pipeSide * 4.5, 0.2, 0));
      group.add(this._box(3.4, 0.14, 0.14, pipeMat, pipeSide * 1.7, 0.2, 0));

      const valveBody = this._box(0.45, 0.42, 0.45, "#455a64", inletX, 0.36, 0);
      valveBody.userData.sectorId = sid;
      valveBody.userData.label = `Solenoid Valve`;
      this.hardwareHitMeshes.push(valveBody);
      group.add(valveBody);

      const valveHandle = this._box(0.54, 0.12, 0.16, "#d32f2f", inletX, 0.64, 0);
      group.add(valveHandle);

      const flowBody = this._box(0.32, 0.28, 0.32, "#1976d2", inletX - pipeSide * 0.7, 0.26, 0);
      flowBody.userData.sectorId = sid;
      flowBody.userData.label = `YF-S201 Flow Meter`;
      this.hardwareHitMeshes.push(flowBody);
      const flowLed = new THREE.Mesh(
        new THREE.BoxGeometry(0.18, 0.18, 0.18),
        new THREE.MeshBasicMaterial({ color: "#43a047" })
      );
      flowLed.position.set(inletX - pipeSide * 0.7, 0.46, 0);
      group.add(flowBody, flowLed);

      // Center Overhead Sprinkler + Animated Water Spray Droplets
      group.add(this._box(0.15, 0.8, 0.15, "#546e7a", 0, 0.52, 0));
      group.add(this._box(0.42, 0.1, 0.12, "#90a4ae", 0, 0.94, 0));
      const sprayDrops = [];
      for (let i = 0; i < 24; i++) {
        const drop = new THREE.Mesh(
          new THREE.BoxGeometry(0.12, 0.12, 0.12),
          new THREE.MeshBasicMaterial({ color: "#5ec8f2" })
        );
        drop.visible = false;
        drop.userData.angle = (i / 24) * Math.PI * 2;
        drop.userData.phase = (i % 6) / 6;
        group.add(drop);
        sprayDrops.push(drop);
      }

      // ESP32 Field Node + Sensor Trio (Soil Probe, DHT22, BH1750 Lux Dome)
      const espX = pipeSide * 3.0;
      const espZ = 1.7;
      group.add(this._box(0.18, 1.4, 0.18, "#593b28", espX, 0.7, espZ));
      const espBox = this._box(0.75, 0.62, 0.42, "#cfd8dc", espX, 1.15, espZ);
      espBox.userData.sectorId = sid;
      espBox.userData.label = `ESP32 Sector ${sid} Node`;
      this.hardwareHitMeshes.push(espBox);
      group.add(espBox);

      // Antenna + Health Beacon
      group.add(this._box(0.08, 0.52, 0.08, "#263238", espX + 0.22, 1.7, espZ));
      const espLed = new THREE.Mesh(
        new THREE.BoxGeometry(0.24, 0.24, 0.24),
        new THREE.MeshBasicMaterial({ color: "#43a047" })
      );
      espLed.position.set(espX, 1.6, espZ);
      group.add(espLed);

      // Soil Moisture Probe stuck in soil
      const moistProbe = this._box(0.14, 0.52, 0.14, "#263238", espX - pipeSide * 0.85, 0.36, espZ - 0.4);
      moistProbe.userData.sectorId = sid;
      moistProbe.userData.label = `Soil Moisture Probe`;
      this.hardwareHitMeshes.push(moistProbe);
      const moistLed = new THREE.Mesh(
        new THREE.BoxGeometry(0.17, 0.17, 0.17),
        new THREE.MeshBasicMaterial({ color: "#43a047" })
      );
      moistLed.position.set(espX - pipeSide * 0.85, 0.68, espZ - 0.4);
      group.add(moistProbe, moistLed);

      // DHT22 White Louvered Shield
      const dhtShield = this._box(0.32, 0.34, 0.32, "#ffffff", espX - 0.52, 1.38, espZ);
      dhtShield.userData.sectorId = sid;
      dhtShield.userData.label = `DHT22 Temp/Humidity`;
      this.hardwareHitMeshes.push(dhtShield);
      const dhtLed = new THREE.Mesh(
        new THREE.BoxGeometry(0.15, 0.15, 0.15),
        new THREE.MeshBasicMaterial({ color: "#43a047" })
      );
      dhtLed.position.set(espX - 0.52, 1.65, espZ);
      group.add(dhtShield, dhtLed);

      // BH1750 Lux Dome
      const luxDome = this._box(0.22, 0.16, 0.22, "#ffeb3b", espX - 0.14, 1.54, espZ);
      luxDome.userData.sectorId = sid;
      luxDome.userData.label = `BH1750 Light Sensor`;
      this.hardwareHitMeshes.push(luxDome);
      group.add(luxDome);

      // On-plot crisp Signboard Sprite showing "S1 · 22%" + status color
      const signCanvas = document.createElement("canvas");
      signCanvas.width = 128;
      signCanvas.height = 48;
      const signTex = new THREE.CanvasTexture(signCanvas);
      signTex.magFilter = THREE.NearestFilter;
      signTex.minFilter = THREE.NearestFilter;
      signTex.colorSpace = THREE.SRGBColorSpace;
      const signSprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: signTex, transparent: true }));
      signSprite.position.set(-pipeSide * 2.55, 1.25, 1.85);
      signSprite.scale.set(2.3, 0.86, 1);
      group.add(signSprite);

      this.scene.add(group);
      this.sectorVisuals[sid] = {
        group,
        soilMat,
        selRing,
        hoverRing,
        cropMeshes,
        valveHandle,
        espLed,
        moistLed,
        dhtLed,
        luxDome,
        flowLed,
        sprayDrops,
        signCanvas,
        signTex,
        signKey: "",
        antennaPos: new THREE.Vector3(meta.x + espX + 0.22, meta.y + 1.96, meta.z + espZ),
      };
      this._drawSectorSign(sid, "--", "OK", "#4f8a36");
    }
  }

  _drawSectorSign(sid, moistureStr, badgeText, badgeColor) {
    const vis = this.sectorVisuals[sid];
    if (!vis) return;
    const key = `${moistureStr}|${badgeText}|${badgeColor}`;
    if (vis.signKey === key) return;
    vis.signKey = key;

    const ctx = vis.signCanvas.getContext("2d");
    ctx.clearRect(0, 0, 128, 48);
    // Wooden signboard card
    ctx.fillStyle = "#362319";
    ctx.fillRect(0, 0, 128, 44);
    ctx.fillStyle = "#fcf3de";
    ctx.fillRect(3, 3, 122, 38);
    // Colored status bar
    ctx.fillStyle = badgeColor;
    ctx.fillRect(5, 5, 118, 16);
    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 12px monospace";
    ctx.fillText(`S${sid} ${badgeText}`, 9, 17);
    ctx.fillStyle = "#281911";
    ctx.font = "bold 13px monospace";
    ctx.fillText(`M: ${moistureStr}`, 9, 36);
    vis.signTex.needsUpdate = true;
  }

  _buildWeatherParticles() {
    const rainGroup = new THREE.Group();
    const dropMat = new THREE.MeshBasicMaterial({ color: "#7ad7f7" });
    const dropGeo = new THREE.BoxGeometry(0.06, 0.5, 0.06);
    for (let i = 0; i < 200; i++) {
      const m = new THREE.Mesh(dropGeo, dropMat);
      m.position.set((Math.random() - 0.5) * 30, Math.random() * 14 + 1, (Math.random() - 0.5) * 22);
      rainGroup.add(m);
    }
    rainGroup.visible = false;
    this.rainParticles = rainGroup;
    this.scene.add(rainGroup);

    const frostGroup = new THREE.Group();
    const flakeMat = new THREE.MeshBasicMaterial({ color: "#e6f7ff" });
    const flakeGeo = new THREE.BoxGeometry(0.11, 0.11, 0.11);
    for (let i = 0; i < 120; i++) {
      const f = new THREE.Mesh(flakeGeo, flakeMat);
      f.position.set((Math.random() - 0.5) * 30, Math.random() * 12 + 0.5, (Math.random() - 0.5) * 22);
      frostGroup.add(f);
    }
    frostGroup.visible = false;
    this.frostParticles = frostGroup;
    this.scene.add(frostGroup);
  }

  _pickSector(clientX, clientY) {
    const rect = this.canvas.getBoundingClientRect();
    this.pointer.x = ((clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((clientY - rect.top) / rect.height) * 2 + 1;
    this.raycaster.setFromCamera(this.pointer, this.camera);

    const hwHits = this.raycaster.intersectObjects(this.hardwareHitMeshes, false);
    if (hwHits.length > 0) return hwHits[0].object.userData;
    const secHits = this.raycaster.intersectObjects(this.sectorHitMeshes, false);
    if (secHits.length > 0) return secHits[0].object.userData;
    return null;
  }

  _bindEvents() {
    const onPointerMove = (e) => {
      const hit = this._pickSector(e.clientX, e.clientY);
      const nextSid = hit?.sectorId ?? null;
      if (this.hoveredSector !== nextSid) {
        this.hoveredSector = nextSid;
        for (const id of [1, 2, 3, 4]) {
          this.sectorVisuals[id].hoverRing.material.opacity = id === nextSid ? 0.55 : 0.0;
        }
      }
      this.canvas.style.cursor = nextSid ? "pointer" : "grab";
      if (this.onHover) {
        this.onHover(nextSid, hit?.label || null, e.clientX, e.clientY);
      }
    };

    const onPointerLeave = () => {
      this.hoveredSector = null;
      for (const id of [1, 2, 3, 4]) {
        this.sectorVisuals[id].hoverRing.material.opacity = 0.0;
      }
      if (this.onHover) this.onHover(null, null, 0, 0);
    };

    const onPointerDown = (e) => {
      const hit = this._pickSector(e.clientX, e.clientY);
      if (hit?.sectorId && this.onSelectSector) {
        this.onSelectSector(hit.sectorId);
      }
    };

    this.canvas.addEventListener("pointermove", onPointerMove);
    this.canvas.addEventListener("pointerleave", onPointerLeave);
    this.canvas.addEventListener("pointerdown", onPointerDown);

    const resize = () => {
      const w = this.canvas.parentElement.clientWidth;
      const h = this.canvas.parentElement.clientHeight;
      if (w > 0 && h > 0) {
        this.camera.aspect = w / h;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(w, h, false);
      }
    };
    window.addEventListener("resize", resize);
  }

  focusCamera(presetKey) {
    const p = CAMERA_PRESETS[presetKey] || CAMERA_PRESETS.overview;
    if (window.anime) {
      window.anime({
        targets: this.camera.position,
        x: p.pos[0],
        y: p.pos[1],
        z: p.pos[2],
        duration: 650,
        easing: "easeOutQuad",
      });
      window.anime({
        targets: this.controls.target,
        x: p.target[0],
        y: p.target[1],
        z: p.target[2],
        duration: 650,
        easing: "easeOutQuad",
      });
    } else {
      this.camera.position.set(...p.pos);
      this.controls.target.set(...p.target);
    }
  }

  setSelectedSector(sid) {
    this.selectedSector = Number(sid);
    for (const id of [1, 2, 3, 4]) {
      this.sectorVisuals[id].selRing.material.opacity = id === this.selectedSector ? 0.92 : 0.0;
    }
  }

  spawnMqttPacket(sectorId, kind = "telemetry") {
    if (this.crisis === "broker_outage") return;
    const vis = this.sectorVisuals[sectorId];
    if (!vis) return;
    const color = kind === "command" ? "#f59e0b" : kind === "alert" ? "#ef4444" : "#38bdf8";
    const mesh = new THREE.Mesh(
      new THREE.BoxGeometry(0.28, 0.28, 0.28),
      new THREE.MeshBasicMaterial({ color })
    );
    const start = kind === "command" ? this.relayWorldPos : vis.antennaPos;
    const end = kind === "command" ? vis.antennaPos : this.relayWorldPos;
    mesh.position.copy(start);
    this.scene.add(mesh);
    this.mqttPackets.push({ mesh, start: start.clone(), end: end.clone(), t: 0 });
  }

  updateFromState(state) {
    if (!state) return;
    this.latestState = state;
    this.crisis = state.crisis || "normal";
    const th = state.thresholds || { moisture_start: 30, moisture_stop: 55 };

    // Weather lighting, sky & particles
    if (this.crisis === "heatwave") {
      this.scene.background.set("#dc5e2a");
      this.sunLight.color.set("#ff9852");
      this.sunLight.intensity = 2.15;
      this.rainParticles.visible = false;
      this.frostParticles.visible = false;
    } else if (this.crisis === "rainstorm") {
      this.scene.background.set("#637d91");
      this.sunLight.color.set("#b6cbe0");
      this.sunLight.intensity = 0.95;
      this.rainParticles.visible = true;
      this.frostParticles.visible = false;
    } else if (this.crisis === "frost") {
      this.scene.background.set("#b6d7ea");
      this.sunLight.color.set("#e6f6ff");
      this.sunLight.intensity = 1.25;
      this.rainParticles.visible = false;
      this.frostParticles.visible = true;
    } else {
      this.scene.background.set("#f3b659");
      this.sunLight.color.set("#fff2cc");
      this.sunLight.intensity = 1.65;
      this.rainParticles.visible = false;
      this.frostParticles.visible = false;
    }

    this.pumpBeacon.material.color.set(this.crisis === "water_supply_failure" ? "#ef4444" : "#43a047");
    this.relayTip.material.color.set(this.crisis === "broker_outage" ? "#ef4444" : "#38bdf8");

    for (const sid of [1, 2, 3, 4]) {
      const s = state.sectors?.[String(sid)];
      const vis = this.sectorVisuals[sid];
      if (!s || !vis) continue;

      const nodeStatus = s.node?.status || "offline";
      const valveState = s.valve?.state || "CLOSED";
      const valveFault = s.valve?.fault_mode || "normal";
      const flow = Number(s.valve?.flow_rate_lpm ?? 0);
      const rawMoist = s.sensor?.moisture;
      const sh = s.sensor_health || {};
      const chErr = s.channel_errors || {};
      const moistBad = (sh.moisture && sh.moisture !== "ok") || Boolean(chErr.moisture) || rawMoist === null || rawMoist === undefined;
      const moisture = moistBad ? 30 : Number(rawMoist);

      // Soil darkens with moisture
      const wetFactor = Math.min(Math.max(moisture / 100, 0), 1);
      vis.soilMat.color.setRGB(1 - wetFactor * 0.28, 1 - wetFactor * 0.24, 1 - wetFactor * 0.18);

      // Crop tint & droop during crises
      for (const cm of vis.cropMeshes) {
        if (this.crisis === "frost") {
          cm.material.color.set("#9cd3ea");
          cm.scale.y = 0.92;
        } else if (this.crisis === "heatwave" && moisture < 25) {
          cm.material.color.set("#d9a95c");
          cm.scale.y = 0.82;
        } else {
          cm.material.color.set("#ffffff");
          cm.scale.y = 1.0;
        }
      }

      // LEDs
      const anySensorFault = Object.values(sh).some((m) => m && m !== "ok") || Object.keys(chErr).length > 0;
      if (nodeStatus === "offline") vis.espLed.material.color.set("#ef4444");
      else if (anySensorFault || nodeStatus === "stale") vis.espLed.material.color.set("#f59e0b");
      else vis.espLed.material.color.set("#43a047");

      vis.moistLed.material.color.set(moistBad ? "#ef4444" : "#43a047");
      const dhtFault = (sh.temperature && sh.temperature !== "ok") || (sh.humidity && sh.humidity !== "ok");
      vis.dhtLed.material.color.set(dhtFault ? "#ef4444" : "#43a047");
      vis.luxDome.material.color.set(sh.light_lux && sh.light_lux !== "ok" ? "#ef4444" : "#ffeb3b");
      vis.flowLed.material.color.set(sh.flow && sh.flow !== "ok" ? "#ef4444" : "#43a047");

      // Valve handle angle & color
      const targetRot = valveState === "OPEN" ? Math.PI / 2 : 0;
      vis.valveHandle.rotation.y += (targetRot - vis.valveHandle.rotation.y) * 0.35;
      if (valveFault !== "normal") vis.valveHandle.material.color.set("#f59e0b");
      else vis.valveHandle.material.color.set(valveState === "OPEN" ? "#43a047" : "#d32f2f");

      // Sprinkler spray active only with OPEN valve & actual water flow
      const isSpraying = valveState === "OPEN" && this.crisis !== "water_supply_failure" && flow > 0.05;
      vis.sprayDrops.forEach((d) => {
        d.visible = isSpraying;
      });

      // On-map signboard status update
      let sBadge = "OK";
      let sColor = "#4f8a36";
      if (nodeStatus === "offline") {
        sBadge = "OFFLINE";
        sColor = "#b92b27";
      } else if (moistBad) {
        sBadge = "FAULT";
        sColor = "#c94a36";
      } else if (isSpraying) {
        sBadge = "WATERING";
        sColor = "#2f86bf";
      } else if (this.crisis === "frost") {
        sBadge = "FROST";
        sColor = "#5a89b3";
      } else if (this.crisis === "rainstorm") {
        sBadge = "RAINING";
        sColor = "#3d6d8f";
      } else if (moisture < Number(th.moisture_start || 30)) {
        sBadge = "NEEDS H2O";
        sColor = "#d97706";
      }
      this._drawSectorSign(sid, moistBad ? "ERR" : `${moisture.toFixed(0)}%`, sBadge, sColor);
    }
  }

  _animate() {
    requestAnimationFrame(() => this._animate());
    const t = performance.now() * 0.001;

    // Gentle breeze sway on pixel trees & crops
    for (const sp of this.swaySprites) {
      sp.position.x = sp.userData.baseX + Math.sin(t * 1.4 + sp.userData.swayPhase) * 0.035;
    }

    // Chimney smoke rise
    for (const puff of this.smokePuffs) {
      const p = (t * 0.36 + puff.userData.phase) % 1;
      puff.position.y = 5.65 + p * 2.5;
      puff.position.x = 2.35 + Math.sin(t * 2.1 + p * 4) * 0.2;
      puff.material.opacity = (1 - p) * 0.78;
    }

    // Sprinkler water arc droplets
    for (const sid of [1, 2, 3, 4]) {
      const vis = this.sectorVisuals[sid];
      if (!vis) continue;
      for (const d of vis.sprayDrops) {
        if (!d.visible) continue;
        const p = (t * 1.9 + d.userData.phase) % 1;
        const ang = d.userData.angle + t * 1.5;
        const r = p * 2.4;
        d.position.set(Math.cos(ang) * r, 0.94 + Math.sin(p * Math.PI) * 1.05 - p * 0.65, Math.sin(ang) * r);
      }
    }

    // Rainstorm / Frost weather particles
    if (this.rainParticles && this.rainParticles.visible) {
      for (const drop of this.rainParticles.children) {
        drop.position.y -= 0.42;
        if (drop.position.y < 0.1) drop.position.y = 14.5;
      }
    }
    if (this.frostParticles && this.frostParticles.visible) {
      for (const f of this.frostParticles.children) {
        f.position.y -= 0.05;
        f.position.x += Math.sin(t * 2 + f.position.z) * 0.015;
        if (f.position.y < 0.1) f.position.y = 12.5;
      }
    }

    // Flying MQTT packet blips
    for (let i = this.mqttPackets.length - 1; i >= 0; i--) {
      const pkt = this.mqttPackets[i];
      pkt.t += 0.045;
      if (pkt.t >= 1) {
        this.scene.remove(pkt.mesh);
        this.mqttPackets.splice(i, 1);
      } else {
        pkt.mesh.position.lerpVectors(pkt.start, pkt.end, pkt.t);
        pkt.mesh.position.y += Math.sin(pkt.t * Math.PI) * 2.2;
      }
    }

    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }
}
