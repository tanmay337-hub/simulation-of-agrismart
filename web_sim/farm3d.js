import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

/**
 * Crisp 16-bit Pixel-Art Texture Generator (NearestFilter, zero blur)
 */
function makePixelTexture(size, painter, repeatX = 1, repeatY = 1) {
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  painter(ctx, size);

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

function createTextures() {
  const grass = makePixelTexture(
    16,
    (ctx, s) => {
      ctx.fillStyle = "#7cb342";
      ctx.fillRect(0, 0, s, s);
      const dots = [
        [2, 3, "#8bc34a"], [6, 1, "#689f38"], [11, 5, "#9ccc65"],
        [14, 10, "#558b2f"], [4, 12, "#8bc34a"], [9, 14, "#689f38"],
        [1, 9, "#9ccc65"], [12, 2, "#689f38"], [7, 8, "#8bc34a"],
      ];
      for (const [x, y, c] of dots) {
        ctx.fillStyle = c;
        ctx.fillRect(x, y, 2, 1);
      }
      // Subtle pixel wildflower
      ctx.fillStyle = "#ffe082";
      ctx.fillRect(13, 13, 1, 1);
    },
    14,
    11
  );

  const path = makePixelTexture(
    16,
    (ctx, s) => {
      ctx.fillStyle = "#a56d43";
      ctx.fillRect(0, 0, s, s);
      const pebbles = [
        [2, 2, "#8c5731"], [8, 4, "#b87f52"], [12, 11, "#7b4926"],
        [5, 9, "#8c5731"], [10, 1, "#b87f52"], [1, 13, "#7b4926"],
      ];
      for (const [x, y, c] of pebbles) {
        ctx.fillStyle = c;
        ctx.fillRect(x, y, 2, 2);
      }
    },
    6,
    6
  );

  const soilDry = makePixelTexture(
    16,
    (ctx, s) => {
      ctx.fillStyle = "#6d452c";
      ctx.fillRect(0, 0, s, s);
      ctx.fillStyle = "#54331e";
      for (let y = 0; y < s; y += 4) ctx.fillRect(0, y, s, 1);
      ctx.fillStyle = "#85583a";
      ctx.fillRect(3, 2, 2, 1);
      ctx.fillRect(11, 6, 2, 1);
      ctx.fillRect(6, 10, 2, 1);
    },
    3,
    2
  );

  const wood = makePixelTexture(
    16,
    (ctx, s) => {
      ctx.fillStyle = "#7a4e33";
      ctx.fillRect(0, 0, s, s);
      ctx.fillStyle = "#5c3822";
      for (let x = 0; x < s; x += 4) ctx.fillRect(x, 0, 1, s);
      ctx.fillStyle = "#8f5f42";
      ctx.fillRect(1, 2, 2, 12);
      ctx.fillRect(9, 1, 2, 13);
    },
    2,
    1
  );

  const roof = makePixelTexture(
    16,
    (ctx, s) => {
      ctx.fillStyle = "#d4633b";
      ctx.fillRect(0, 0, s, s);
      ctx.fillStyle = "#b04622";
      for (let y = 0; y < s; y += 4) {
        ctx.fillRect(0, y, s, 1);
        for (let x = (y % 8 === 0 ? 0 : 2); x < s; x += 4) {
          ctx.fillRect(x, y, 1, 3);
        }
      }
      ctx.fillStyle = "#e6825c";
      ctx.fillRect(1, 1, 2, 1);
      ctx.fillRect(9, 5, 2, 1);
    },
    3,
    2
  );

  const skyBackdrop = makePixelTexture(256, (ctx, s) => {
    // Sunset gradient matching uploaded pixel farm artwork
    const grad = ctx.createLinearGradient(0, 0, 0, s);
    grad.addColorStop(0.0, "#eb8e41");
    grad.addColorStop(0.32, "#f5be6b");
    grad.addColorStop(0.58, "#fce4a6");
    grad.addColorStop(1.0, "#d7e8d8");
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, s, s);

    // Crisp pixel clouds
    const drawCloud = (cx, cy, w) => {
      ctx.fillStyle = "#fff9e8";
      ctx.fillRect(cx, cy, w, 10);
      ctx.fillRect(cx + 6, cy - 6, w - 12, 8);
      ctx.fillRect(cx + 12, cy - 10, w - 24, 6);
      ctx.fillStyle = "#f2d6a7";
      ctx.fillRect(cx + 2, cy + 8, w - 4, 2);
    };
    drawCloud(18, 42, 46);
    drawCloud(112, 30, 56);
    drawCloud(190, 48, 48);

    // Layered sky-blue mountains matching reference image
    const drawMtn = (peaks, color) => {
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.moveTo(0, s);
      for (const [px, py] of peaks) ctx.lineTo(px, py);
      ctx.lineTo(s, s);
      ctx.closePath();
      ctx.fill();
    };
    drawMtn([[0, 170], [28, 128], [58, 154], [95, 114], [134, 148], [176, 118], [218, 145], [256, 126]], "#96c0d6");
    drawMtn([[0, 190], [42, 154], [80, 178], [122, 144], [162, 174], [202, 148], [256, 172]], "#6e9cb8");
    // Distant tree silhouette ridge
    ctx.fillStyle = "#487447";
    for (let x = 0; x < s; x += 8) {
      const h = 18 + ((x * 17) % 14);
      ctx.fillRect(x, s - h, 8, h);
    }
  });

  return { grass, path, soilDry, wood, roof, skyBackdrop };
}

const SECTOR_META = {
  1: { x: -6.0, z: 4.5, crop: "tomato", label: "Sector 1 (Tomatoes)" },
  2: { x: 6.0, z: 4.5, crop: "wheat", label: "Sector 2 (Wheat)" },
  3: { x: -6.0, z: -3.5, crop: "corn", label: "Sector 3 (Corn)" },
  4: { x: 6.0, z: -3.5, crop: "soy", label: "Sector 4 (Soybeans)" },
};

const CAMERA_PRESETS = {
  overview: { pos: [0, 17.5, 21.5], target: [0, 0.5, 0.2] },
  1: { pos: [-6.0, 7.5, 11.8], target: [-6.0, 0.7, 4.5] },
  2: { pos: [6.0, 7.5, 11.8], target: [6.0, 0.7, 4.5] },
  3: { pos: [-6.0, 7.5, 3.8], target: [-6.0, 0.7, -3.5] },
  4: { pos: [6.0, 7.5, 3.8], target: [6.0, 0.7, -3.5] },
  top: { pos: [0, 26.5, 0.5], target: [0, 0, 0] },
};

export class Farm3DScene {
  constructor(canvas, onSelectSector, onHover) {
    this.canvas = canvas;
    this.onSelectSector = onSelectSector;
    this.onHover = onHover;
    this.selectedSector = 1;
    this.crisis = "normal";
    this.sectorVisuals = {};
    this.smokePuffs = [];
    this.mqttPackets = [];
    this.rainParticles = null;
    this.latestState = null;

    this._initScene();
    this._buildEnvironment();
    this._buildBuildingsAndTank();
    this._buildSectors();
    this._buildWeatherParticles();
    this._bindEvents();
    this._animate();
  }

  _initScene() {
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color("#f5be6b");

    const w = this.canvas.clientWidth || 800;
    const h = this.canvas.clientHeight || 455;
    this.camera = new THREE.PerspectiveCamera(36, w / h, 0.1, 160);
    this.camera.position.set(...CAMERA_PRESETS.overview.pos);

    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas,
      antialias: false,
      powerPreference: "high-performance",
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setSize(w, h, false);
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.BasicShadowMap; // crisp pixel shadows
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;

    this.controls = new OrbitControls(this.camera, this.canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.maxPolarAngle = Math.PI / 2.15;
    this.controls.minDistance = 6;
    this.controls.maxDistance = 38;
    this.controls.target.set(...CAMERA_PRESETS.overview.target);

    // Warm Golden-Hour Sunlight + Sky Fill
    this.hemiLight = new THREE.HemisphereLight("#ffecc2", "#476a32", 0.95);
    this.scene.add(this.hemiLight);

    this.sunLight = new THREE.DirectionalLight("#fff1cc", 1.75);
    this.sunLight.position.set(16, 22, 12);
    this.sunLight.castShadow = true;
    this.sunLight.shadow.mapSize.set(1024, 1024);
    this.sunLight.shadow.camera.near = 2;
    this.sunLight.shadow.camera.far = 60;
    this.sunLight.shadow.camera.left = -18;
    this.sunLight.shadow.camera.right = 18;
    this.sunLight.shadow.camera.top = 18;
    this.sunLight.shadow.camera.bottom = -18;
    this.scene.add(this.sunLight);

    this.tex = createTextures();
    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    this.clickableMeshes = [];
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

  _buildEnvironment() {
    // Sky Backdrop Wall (north & gentle side wings matching uploaded sunset artwork)
    const skyMat = new THREE.MeshBasicMaterial({ map: this.tex.skyBackdrop });
    const backSky = new THREE.Mesh(new THREE.PlaneGeometry(54, 22), skyMat);
    backSky.position.set(0, 7.5, -18);
    this.scene.add(backSky);

    // Crisp Farm Island Base (grass top + earthy cliff sides)
    const grassMat = new THREE.MeshLambertMaterial({ map: this.tex.grass });
    const cliffMat = new THREE.MeshLambertMaterial({ color: "#523523" });
    const ground = this._box(29, 1.2, 22, [cliffMat, cliffMat, grassMat, cliffMat, cliffMat, cliffMat], 0, -0.6, 0);
    ground.castShadow = false;
    this.scene.add(ground);

    // Winding Dirt Paths dividing the 4 sectors (matches artwork paths)
    const pathMat = new THREE.MeshLambertMaterial({ map: this.tex.path });
    const nsPath = this._box(2.0, 0.04, 17.5, pathMat, 0, 0.02, 0.8);
    const ewPath = this._box(23.5, 0.04, 1.8, pathMat, 0, 0.02, 0.5);
    nsPath.castShadow = false;
    ewPath.castShadow = false;
    this.scene.add(nsPath, ewPath);

    // Perimeter Pixel Trees
    const treeSpots = [
      [-12.5, -8.5, 1.15], [-9.2, -9.2, 0.95], [9.5, -9.0, 1.1], [12.6, -8.2, 1.2],
      [-13.0, -1.5, 1.0], [-12.8, 6.2, 1.1], [12.9, 5.8, 1.05], [12.8, -1.2, 0.95],
      [-11.8, 9.2, 0.9], [11.5, 9.1, 1.0],
    ];
    for (const [tx, tz, sc] of treeSpots) {
      this._addPixelTree(tx, tz, sc);
    }

    // Perimeter Split-Rail Fences
    this._addFenceRow(-11.8, 9.5, 11.8, 9.5, 8);
    this._addFenceRow(-13.2, -7.2, -13.2, 9.2, 6);
    this._addFenceRow(13.2, -7.2, 13.2, 9.2, 6);
  }

  _addPixelTree(x, z, scale = 1) {
    const g = new THREE.Group();
    g.position.set(x, 0, z);
    g.scale.setScalar(scale);
    g.add(this._box(0.55, 1.4, 0.55, "#5b3924", 0, 0.7, 0));
    g.add(this._box(2.0, 1.2, 2.0, "#2f6b2d", 0, 1.75, 0));
    g.add(this._box(1.5, 0.9, 1.5, "#4c8f3d", 0, 2.55, 0));
    g.add(this._box(0.9, 0.5, 0.9, "#7cb342", 0, 3.05, 0));
    this.scene.add(g);
  }

  _addFenceRow(x1, z1, x2, z2, segments) {
    const g = new THREE.Group();
    const dx = x2 - x1;
    const dz = z2 - z1;
    const len = Math.hypot(dx, dz);
    const angle = Math.atan2(dx, dz);
    for (let i = 0; i <= segments; i++) {
      const t = i / segments;
      g.add(this._box(0.16, 0.65, 0.16, "#69432b", x1 + dx * t, 0.32, z1 + dz * t));
    }
    const railMat = new THREE.MeshLambertMaterial({ color: "#8c5c3e" });
    for (const ry of [0.24, 0.48]) {
      const rail = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.09, len), railMat);
      rail.position.set((x1 + x2) / 2, ry, (z1 + z2) / 2);
      rail.rotation.y = angle;
      rail.castShadow = true;
      g.add(rail);
    }
    this.scene.add(g);
  }

  _buildBuildingsAndTank() {
    const woodMat = new THREE.MeshLambertMaterial({ map: this.tex.wood });
    const roofMat = new THREE.MeshLambertMaterial({ map: this.tex.roof });

    // Background Rustic Farmhouse (north-center — cozy visual anchor like reference image)
    const house = new THREE.Group();
    house.position.set(-3.2, 0, -9.2);
    house.add(this._box(3.8, 2.1, 2.8, woodMat, 0, 1.05, 0));
    // Terracotta gable roof layers (stepped crisp pixel roof)
    house.add(this._box(4.2, 0.45, 3.2, roofMat, 0, 2.3, 0));
    house.add(this._box(3.4, 0.45, 2.4, roofMat, 0, 2.75, 0));
    house.add(this._box(2.2, 0.45, 1.4, roofMat, 0, 3.2, 0));
    // Door & glowing blue pixel windows
    house.add(this._box(0.65, 1.15, 0.1, "#4a2c1b", 0, 0.58, 1.42));
    house.add(this._box(0.6, 0.6, 0.1, "#80d0eb", -1.1, 1.15, 1.42));
    house.add(this._box(0.6, 0.6, 0.1, "#80d0eb", 1.1, 1.15, 1.42));
    // Chimney
    house.add(this._box(0.55, 1.2, 0.55, "#7d5444", 1.1, 3.4, -0.4));
    this.scene.add(house);

    // Chimney smoke puffs
    for (let i = 0; i < 4; i++) {
      const puff = this._box(0.32, 0.28, 0.32, "#f8e2c4", -2.1, 4.2 + i * 0.55, -9.6);
      puff.material = new THREE.MeshBasicMaterial({ color: "#f7dec0", transparent: true, opacity: 0.75 });
      puff.userData.phase = i * 0.25;
      this.smokePuffs.push(puff);
      this.scene.add(puff);
    }

    // Timber Barn on the left background
    const barn = new THREE.Group();
    barn.position.set(-8.6, 0, -8.8);
    barn.add(this._box(3.2, 2.0, 2.6, "#8c4332", 0, 1.0, 0));
    barn.add(this._box(3.5, 0.45, 2.9, "#5b4844", 0, 2.2, 0));
    barn.add(this._box(2.4, 0.45, 2.0, "#5b4844", 0, 2.65, 0));
    barn.add(this._box(1.1, 1.3, 0.1, "#5c3822", 0, 0.65, 1.32));
    barn.add(this._box(0.55, 0.55, 0.1, "#80d0eb", 0, 1.55, 1.32));
    this.scene.add(barn);

    // Main Water Supply Tank & Pump Station (feeds PVC pipes into the 4 sectors)
    const tankGroup = new THREE.Group();
    tankGroup.position.set(4.5, 0, -8.8);
    for (const [lx, lz] of [[-0.8, -0.8], [0.8, -0.8], [-0.8, 0.8], [0.8, 0.8]]) {
      tankGroup.add(this._box(0.24, 1.6, 0.24, "#593b28", lx, 0.8, lz));
    }
    tankGroup.add(this._box(2.2, 1.7, 2.2, "#4689b8", 0, 2.4, 0));
    tankGroup.add(this._box(2.4, 0.3, 2.4, "#2c5f85", 0, 3.35, 0));
    this.pumpBeacon = new THREE.Mesh(
      new THREE.BoxGeometry(0.35, 0.35, 0.35),
      new THREE.MeshBasicMaterial({ color: "#43a047" })
    );
    this.pumpBeacon.position.set(0, 3.7, 0);
    tankGroup.add(this.pumpBeacon);
    this.scene.add(tankGroup);

    // Wireless MQTT Field Relay Antenna (sends telemetry OFF-SITE to safe RPi 5!)
    const relay = new THREE.Group();
    relay.position.set(8.6, 0, -8.6);
    relay.add(this._box(0.35, 3.6, 0.35, "#55606e", 0, 1.8, 0));
    relay.add(this._box(1.2, 0.2, 0.2, "#8795a6", 0, 3.4, 0));
    this.relayTip = new THREE.Mesh(
      new THREE.BoxGeometry(0.32, 0.32, 0.32),
      new THREE.MeshBasicMaterial({ color: "#38bdf8" })
    );
    this.relayTip.position.set(0, 3.85, 0);
    relay.add(this.relayTip);
    this.scene.add(relay);
    this.relayWorldPos = new THREE.Vector3(8.6, 3.85, -8.6);

    // Main PVC distribution trunk pipe from Water Tank down the center path
    const pipeMat = new THREE.MeshLambertMaterial({ color: "#3889bd" });
    this.scene.add(this._box(0.22, 0.22, 13.8, pipeMat, 0.65, 0.15, -1.6));
    this.scene.add(this._box(4.0, 0.22, 0.22, pipeMat, 2.6, 0.15, -8.4));
  }

  _buildSectors() {
    const soilMatBase = new THREE.MeshLambertMaterial({ map: this.tex.soilDry });
    const pipeMat = new THREE.MeshLambertMaterial({ color: "#3889bd" });

    for (const sid of [1, 2, 3, 4]) {
      const meta = SECTOR_META[sid];
      const group = new THREE.Group();
      group.position.set(meta.x, 0, meta.z);

      // Raised soil plot bed
      const soilMat = soilMatBase.clone();
      const bed = this._box(8.4, 0.26, 5.8, soilMat, 0, 0.13, 0);
      bed.userData.sectorId = sid;
      bed.userData.label = meta.label;
      this.clickableMeshes.push(bed);
      group.add(bed);

      // Wood border frame around plot
      group.add(this._box(8.7, 0.32, 0.18, "#6e462d", 0, 0.16, 2.95));
      group.add(this._box(8.7, 0.32, 0.18, "#6e462d", 0, 0.16, -2.95));
      group.add(this._box(0.18, 0.32, 5.8, "#6e462d", -4.28, 0.16, 0));
      group.add(this._box(0.18, 0.32, 5.8, "#6e462d", 4.28, 0.16, 0));

      // Selection Highlight Ring
      const selMat = new THREE.MeshBasicMaterial({
        color: "#ffd54f",
        transparent: true,
        opacity: sid === 1 ? 0.9 : 0.0,
      });
      const selRing = new THREE.Mesh(new THREE.BoxGeometry(8.95, 0.06, 6.15), selMat);
      selRing.position.set(0, 0.04, 0);
      group.add(selRing);

      // Sector-specific crisp pixel crops
      const cropMeshes = [];
      for (let row = -1.6; row <= 1.61; row += 1.06) {
        for (let col = -3.0; col <= 3.01; col += 1.0) {
          if (Math.abs(col) < 0.6 && Math.abs(row) < 0.6) continue; // leave center for sprinkler
          const cGroup = new THREE.Group();
          cGroup.position.set(col, 0.26, row);
          if (meta.crop === "tomato") {
            const bush = this._box(0.55, 0.55, 0.55, "#3f8735", 0, 0.28, 0);
            const fruit = this._box(0.18, 0.18, 0.18, "#d93b2b", 0.16, 0.42, 0.22);
            cGroup.add(bush, fruit);
            cropMeshes.push(bush);
          } else if (meta.crop === "wheat") {
            const stalk = this._box(0.45, 0.72, 0.45, "#dfb040", 0, 0.36, 0);
            cGroup.add(stalk);
            cropMeshes.push(stalk);
          } else if (meta.crop === "corn") {
            const stalk = this._box(0.32, 1.05, 0.32, "#599b38", 0, 0.52, 0);
            const cob = this._box(0.16, 0.28, 0.16, "#f2c144", 0.15, 0.58, 0);
            cGroup.add(stalk, cob);
            cropMeshes.push(stalk);
          } else {
            const bush = this._box(0.58, 0.44, 0.58, "#569c41", 0, 0.22, 0);
            cGroup.add(bush);
            cropMeshes.push(bush);
          }
          group.add(cGroup);
        }
      }

      // Branch Pipe + Solenoid Valve + Flow Sensor on sector inner edge
      const pipeSide = meta.x < 0 ? 1 : -1;
      const inletX = pipeSide * 3.8;
      group.add(this._box(1.9, 0.18, 0.18, pipeMat, pipeSide * 4.5, 0.2, 0));
      group.add(this._box(3.8, 0.16, 0.16, pipeMat, pipeSide * 1.9, 0.2, 0));

      // Valve body + rotating wheel
      const valveBody = this._box(0.46, 0.42, 0.46, "#455a64", inletX, 0.36, 0);
      valveBody.userData.sectorId = sid;
      valveBody.userData.label = `Sector ${sid} Solenoid Valve`;
      this.clickableMeshes.push(valveBody);
      group.add(valveBody);

      const valveHandle = this._box(0.55, 0.12, 0.16, "#d32f2f", inletX, 0.64, 0);
      group.add(valveHandle);

      // Flow sensor inline block
      const flowLed = new THREE.Mesh(
        new THREE.BoxGeometry(0.18, 0.18, 0.18),
        new THREE.MeshBasicMaterial({ color: "#43a047" })
      );
      flowLed.position.set(inletX - pipeSide * 0.75, 0.42, 0);
      group.add(this._box(0.32, 0.28, 0.32, "#1976d2", inletX - pipeSide * 0.75, 0.25, 0));
      group.add(flowLed);

      // Center Overhead Sprinkler + Water Spray Droplets
      group.add(this._box(0.16, 0.85, 0.16, "#546e7a", 0, 0.55, 0));
      group.add(this._box(0.45, 0.1, 0.12, "#90a4ae", 0, 0.98, 0));
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

      // ESP32 Field Enclosure + Sensor Mast (soil moisture probe, DHT22 shield, BH1750 light dome)
      const espX = pipeSide * 3.4;
      const espZ = 2.2;
      group.add(this._box(0.2, 1.5, 0.2, "#593b28", espX, 0.75, espZ)); // wooden post
      const espBox = this._box(0.75, 0.65, 0.45, "#cfd8dc", espX, 1.2, espZ);
      espBox.userData.sectorId = sid;
      espBox.userData.label = `ESP32 Sector ${sid} Node`;
      this.clickableMeshes.push(espBox);
      group.add(espBox);

      // Antenna
      group.add(this._box(0.08, 0.55, 0.08, "#263238", espX + 0.22, 1.75, espZ));
      const espLed = new THREE.Mesh(
        new THREE.BoxGeometry(0.24, 0.24, 0.24),
        new THREE.MeshBasicMaterial({ color: "#43a047" })
      );
      espLed.position.set(espX, 1.65, espZ);
      group.add(espLed);

      // Soil Moisture Probe stuck into bed + Temp/Hum louver shield + Light dome
      group.add(this._box(0.12, 0.5, 0.12, "#263238", espX - pipeSide * 0.9, 0.35, espZ - 0.5));
      const moistLed = new THREE.Mesh(
        new THREE.BoxGeometry(0.16, 0.16, 0.16),
        new THREE.MeshBasicMaterial({ color: "#43a047" })
      );
      moistLed.position.set(espX - pipeSide * 0.9, 0.65, espZ - 0.5);
      group.add(moistLed);

      const dhtShield = this._box(0.32, 0.36, 0.32, "#ffffff", espX - 0.55, 1.45, espZ);
      const dhtLed = new THREE.Mesh(
        new THREE.BoxGeometry(0.14, 0.14, 0.14),
        new THREE.MeshBasicMaterial({ color: "#43a047" })
      );
      dhtLed.position.set(espX - 0.55, 1.7, espZ);
      group.add(dhtShield, dhtLed);

      const luxDome = this._box(0.22, 0.16, 0.22, "#ffeb3b", espX - 0.15, 1.6, espZ);
      group.add(luxDome);

      this.scene.add(group);
      this.sectorVisuals[sid] = {
        group,
        soilMat,
        selRing,
        cropMeshes,
        valveHandle,
        espLed,
        moistLed,
        dhtLed,
        luxDome,
        flowLed,
        sprayDrops,
        antennaPos: new THREE.Vector3(meta.x + espX + 0.22, 2.0, meta.z + espZ),
      };
    }
  }

  _buildWeatherParticles() {
    // 180 Raindrop pixel streaks (shown during rainstorm crisis)
    const rainGroup = new THREE.Group();
    const dropMat = new THREE.MeshBasicMaterial({ color: "#7ad7f7" });
    const dropGeo = new THREE.BoxGeometry(0.06, 0.45, 0.06);
    for (let i = 0; i < 180; i++) {
      const m = new THREE.Mesh(dropGeo, dropMat);
      m.position.set((Math.random() - 0.5) * 28, Math.random() * 14 + 1, (Math.random() - 0.5) * 20);
      rainGroup.add(m);
    }
    rainGroup.visible = false;
    this.rainParticles = rainGroup;
    this.scene.add(rainGroup);
  }

  _bindEvents() {
    const onPointerMove = (e) => {
      const rect = this.canvas.getBoundingClientRect();
      this.pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      this.pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      this.raycaster.setFromCamera(this.pointer, this.camera);
      const hits = this.raycaster.intersectObjects(this.clickableMeshes, false);
      this.canvas.style.cursor = hits.length > 0 ? "pointer" : "grab";
      if (hits.length > 0 && this.onHover) {
        const hit = hits[0].object;
        this.onHover(hit.userData.sectorId, hit.userData.label);
      }
    };

    const onPointerDown = (e) => {
      const rect = this.canvas.getBoundingClientRect();
      this.pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      this.pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      this.raycaster.setFromCamera(this.pointer, this.camera);
      const hits = this.raycaster.intersectObjects(this.clickableMeshes, false);
      if (hits.length > 0) {
        const sid = hits[0].object.userData.sectorId;
        if (sid && this.onSelectSector) this.onSelectSector(sid);
      }
    };

    this.canvas.addEventListener("pointermove", onPointerMove);
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
      this.sectorVisuals[id].selRing.material.opacity = id === this.selectedSector ? 0.9 : 0.0;
    }
  }

  spawnMqttPacket(sectorId, kind = "telemetry") {
    if (this.crisis === "broker_outage") return;
    const vis = this.sectorVisuals[sectorId];
    if (!vis) return;
    const color = kind === "command" ? "#f59e0b" : kind === "alert" ? "#ef4444" : "#38bdf8";
    const mesh = new THREE.Mesh(
      new THREE.BoxGeometry(0.24, 0.24, 0.24),
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

    // Weather lighting & rain
    if (this.crisis === "heatwave") {
      this.scene.background.set("#e0682f");
      this.sunLight.color.set("#ff9f59");
      this.sunLight.intensity = 2.2;
      this.rainParticles.visible = false;
    } else if (this.crisis === "rainstorm") {
      this.scene.background.set("#637d91");
      this.sunLight.color.set("#b6cbe0");
      this.sunLight.intensity = 1.0;
      this.rainParticles.visible = true;
    } else if (this.crisis === "frost") {
      this.scene.background.set("#b8d7e8");
      this.sunLight.color.set("#e6f6ff");
      this.sunLight.intensity = 1.3;
      this.rainParticles.visible = false;
    } else {
      this.scene.background.set("#f5be6b");
      this.sunLight.color.set("#fff1cc");
      this.sunLight.intensity = 1.75;
      this.rainParticles.visible = false;
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
      const flow = Number(s.valve?.flow_rate_lpm || 0);
      const moisture = Number(s.sensor?.moisture ?? 30);
      const sh = s.sensor_health || {};

      // Soil darkens slightly as moisture rises
      const wetFactor = Math.min(Math.max(moisture / 100, 0), 1);
      vis.soilMat.color.setRGB(1 - wetFactor * 0.28, 1 - wetFactor * 0.25, 1 - wetFactor * 0.2);

      // Crop tint in drought/heatwave vs healthy
      for (const cm of vis.cropMeshes) {
        if (this.crisis === "heatwave" && moisture < 25) cm.material.color.set("#b89535");
        else if (this.crisis === "frost") cm.material.color.set("#8bbcd1");
        else {
          const meta = SECTOR_META[sid];
          cm.material.color.set(
            meta.crop === "wheat" ? "#dfb040" : meta.crop === "corn" ? "#599b38" : "#488f39"
          );
        }
      }

      // LEDs
      const anySensorFault = Object.values(sh).some((m) => m && m !== "ok");
      if (nodeStatus === "offline") vis.espLed.material.color.set("#ef4444");
      else if (anySensorFault || nodeStatus === "stale") vis.espLed.material.color.set("#f59e0b");
      else vis.espLed.material.color.set("#43a047");

      vis.moistLed.material.color.set(sh.moisture && sh.moisture !== "ok" ? "#ef4444" : "#43a047");
      const dhtFault = (sh.temperature && sh.temperature !== "ok") || (sh.humidity && sh.humidity !== "ok");
      vis.dhtLed.material.color.set(dhtFault ? "#ef4444" : "#43a047");
      vis.luxDome.material.color.set(sh.light_lux && sh.light_lux !== "ok" ? "#ef4444" : "#ffeb3b");
      vis.flowLed.material.color.set(sh.flow && sh.flow !== "ok" ? "#ef4444" : "#43a047");

      // Valve handle angle & color
      const targetRot = valveState === "OPEN" ? Math.PI / 2 : 0;
      vis.valveHandle.rotation.y += (targetRot - vis.valveHandle.rotation.y) * 0.3;
      if (valveFault !== "normal") vis.valveHandle.material.color.set("#f59e0b");
      else vis.valveHandle.material.color.set(valveState === "OPEN" ? "#43a047" : "#d32f2f");

      // Sprinkler water spray only if OPEN and flow > 0 (not pump failure)
      const isSpraying = valveState === "OPEN" && this.crisis !== "water_supply_failure" && flow > 0.05;
      vis.sprayDrops.forEach((d) => {
        d.visible = isSpraying;
      });
    }
  }

  _animate() {
    requestAnimationFrame(() => this._animate());
    const t = performance.now() * 0.001;

    // Chimney smoke rise
    for (const puff of this.smokePuffs) {
      const p = (t * 0.35 + puff.userData.phase) % 1;
      puff.position.y = 4.1 + p * 2.4;
      puff.position.x = -2.1 + Math.sin(t * 2 + p * 4) * 0.18;
      puff.material.opacity = (1 - p) * 0.75;
    }

    // Sprinkler water arc droplets
    for (const sid of [1, 2, 3, 4]) {
      const vis = this.sectorVisuals[sid];
      if (!vis) continue;
      for (const d of vis.sprayDrops) {
        if (!d.visible) continue;
        const p = (t * 1.9 + d.userData.phase) % 1;
        const ang = d.userData.angle + t * 1.4;
        const r = p * 2.7;
        d.position.set(Math.cos(ang) * r, 0.98 + Math.sin(p * Math.PI) * 1.15 - p * 0.7, Math.sin(ang) * r);
      }
    }

    // Rainstorm droplets
    if (this.rainParticles && this.rainParticles.visible) {
      for (const drop of this.rainParticles.children) {
        drop.position.y -= 0.38;
        if (drop.position.y < 0.1) drop.position.y = 14.5;
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
