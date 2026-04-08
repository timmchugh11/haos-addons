import * as THREE from './vendor/three/build/three.module.js';
import { GLTFLoader } from './vendor/three/examples/jsm/loaders/GLTFLoader.js';

const MODEL_CACHE_NAME = 'van-model-cache-v3';
const MODEL_CACHE_TTL_MS = 7 * 24 * 60 * 60 * 1000;

function createCachedResponse(response) {
  const headers = new Headers(response.headers);
  headers.set('x-van-model-cached-at', String(Date.now()));
  return response.blob().then((blob) => new Response(blob, {
    status: response.status,
    statusText: response.statusText,
    headers,
  }));
}

async function resolveModelSource(modelUrl) {
  const resolvedUrl = new URL(modelUrl, window.location.href).toString();
  if (!('caches' in window)) {
    return { url: resolvedUrl, revoke() {} };
  }

  const cache = await caches.open(MODEL_CACHE_NAME);
  const cached = await cache.match(resolvedUrl);
  const cachedAt = Number.parseInt(cached?.headers.get('x-van-model-cached-at') || '0', 10);
  const isFresh = cached && cachedAt && (Date.now() - cachedAt) < MODEL_CACHE_TTL_MS;

  if (isFresh) {
    const blob = await cached.blob();
    const objectUrl = URL.createObjectURL(blob);
    return {
      url: objectUrl,
      revoke() {
        URL.revokeObjectURL(objectUrl);
      },
    };
  }

  try {
    const response = await fetch(resolvedUrl, { cache: 'force-cache' });
    if (!response.ok) {
      throw new Error(`Failed to fetch model: ${response.status}`);
    }

    await cache.put(resolvedUrl, await createCachedResponse(response.clone()));
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    return {
      url: objectUrl,
      revoke() {
        URL.revokeObjectURL(objectUrl);
      },
    };
  } catch (error) {
    if (cached) {
      const blob = await cached.blob();
      const objectUrl = URL.createObjectURL(blob);
      return {
        url: objectUrl,
        revoke() {
          URL.revokeObjectURL(objectUrl);
        },
      };
    }
    throw error;
  }
}

export function createVanScene(container, options = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 100);
  const loader = new GLTFLoader();

  let destroyed = false;
  const rootGroup = new THREE.Group();
  const modelGroup = new THREE.Group();
  const labelGroup = new THREE.Group();
  let rotationY = options.initialRotationY ?? -0.78;
  let targetRotationY = rotationY;
  let targetPitch = options.initialPitch ?? 0.08;
  let pitch = targetPitch;
  let radius = 11;
  let lookAtY = options.lookAtY ?? 0.1;
  let labelsSpinWithModel = Boolean(options.labelsSpinWithModel);
  let frameId = 0;
  let lastFrameTime = performance.now();
  let pointerDown = false;
  let lastX = 0;
  let lastY = 0;
  let modelResource = null;

  const labelEntries = new Map();
  const labelSpecs = options.labelSpecs || {
    solar: { angle: -2.72, radius: 3.55, y: 1.15, scale: 1.95, title: 'SOLAR' },
    grid: { angle: -0.78, radius: 3.45, y: 1.15, scale: 1.95, title: 'HOOKUP' },
    alternator: { angle: 2.45, radius: 3.1, y: 1.15, scale: 1.95, title: 'ALTERNATOR' },
    battery: { angle: 0.62, radius: 2.85, y: 1.15, scale: 2.1, title: 'BATTERY' },
  };

  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  container.innerHTML = '';
  container.appendChild(renderer.domElement);

  scene.add(rootGroup);
  scene.add(labelGroup);
  rootGroup.add(modelGroup);

  scene.add(new THREE.AmbientLight(0xffffff, 1.8));

  const keyLight = new THREE.DirectionalLight(0xffffff, 2.6);
  keyLight.position.set(8, 10, 10);
  scene.add(keyLight);

  const fillLight = new THREE.DirectionalLight(0x7db8ff, 1.2);
  fillLight.position.set(-8, 4, -10);
  scene.add(fillLight);

  const rimLight = new THREE.DirectionalLight(0xffe1be, 1.6);
  rimLight.position.set(0, 7, -12);
  scene.add(rimLight);

  function createLabelEntry(name, spec) {
    const canvas = document.createElement('canvas');
    canvas.width = 512;
    canvas.height = 320;
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;

    const material = new THREE.SpriteMaterial({
      map: texture,
      transparent: true,
      depthTest: true,
      depthWrite: false,
      toneMapped: false,
      sizeAttenuation: true,
    });

    const sprite = new THREE.Sprite(material);
    sprite.scale.set(spec.scale * 1.6, spec.scale, 1);
    labelGroup.add(sprite);

    const entry = {
      name,
      spec,
      canvas,
      texture,
      sprite,
      title: spec.title || name.toUpperCase(),
      lines: ['—', '—', '—'],
    };
    labelEntries.set(name, entry);
    return entry;
  }

  function drawLabel(entry) {
    const ctx = entry.canvas.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, entry.canvas.width, entry.canvas.height);
    ctx.textAlign = 'center';

    ctx.fillStyle = 'rgba(0,0,0,0.32)';
    ctx.font = '900 76px Inter, Arial, sans-serif';
    ctx.fillText(entry.lines[0] || '—', entry.canvas.width / 2 + 8, 94 + 8);
    ctx.font = '800 56px Inter, Arial, sans-serif';
    ctx.fillText(entry.lines[1] || '—', entry.canvas.width / 2 + 6, 168 + 6);
    ctx.fillText(entry.lines[2] || '—', entry.canvas.width / 2 + 6, 232 + 6);

    ctx.fillStyle = 'rgba(255,255,255,0.68)';
    ctx.font = '700 22px Inter, Arial, sans-serif';
    ctx.fillText(entry.title, entry.canvas.width / 2, 278);

    ctx.fillStyle = '#ffffff';
    ctx.font = '900 76px Inter, Arial, sans-serif';
    ctx.fillText(entry.lines[0] || '—', entry.canvas.width / 2, 94);
    ctx.font = '800 56px Inter, Arial, sans-serif';
    ctx.fillText(entry.lines[1] || '—', entry.canvas.width / 2, 168);
    ctx.fillText(entry.lines[2] || '—', entry.canvas.width / 2, 232);

    entry.texture.needsUpdate = true;
  }

  function ensureLabel(name) {
    return labelEntries.get(name) || createLabelEntry(name, labelSpecs[name] || {
      angle: 0,
      radius: 3,
      y: 1.2,
      scale: 1.95,
      title: name.toUpperCase(),
    });
  }

  function setLabel(name, payload = {}) {
    const entry = ensureLabel(name);
    entry.title = payload.title || entry.spec.title || entry.title;
    entry.lines = Array.isArray(payload.lines) && payload.lines.length
      ? payload.lines.slice(0, 3).map((line) => String(line))
      : ['—', '—', '—'];
    drawLabel(entry);
  }

  function setLabels(labels = {}) {
    Object.entries(labels).forEach(([name, payload]) => setLabel(name, payload));
  }

  function updateLabelPositions() {
    labelEntries.forEach((entry) => {
      const orbit = labelsSpinWithModel ? rotationY : 0;
      const angle = entry.spec.angle + orbit;
      entry.sprite.position.set(
        Math.cos(angle) * entry.spec.radius,
        entry.spec.y,
        Math.sin(angle) * entry.spec.radius
      );
    });
  }

  Object.entries(labelSpecs).forEach(([name, spec]) => {
    const entry = createLabelEntry(name, spec);
    drawLabel(entry);
  });

  function updateCamera() {
    camera.position.set(
      Math.sin(rotationY) * radius,
      3.2 + pitch * 6,
      Math.cos(rotationY) * radius
    );
    camera.lookAt(0, lookAtY, 0);
  }

  function fitModel(object) {
    object.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(object);
    const size = new THREE.Vector3();
    const center = new THREE.Vector3();
    box.getSize(size);
    box.getCenter(center);

    const maxDim = Math.max(size.x, size.y, size.z) || 1;
    const scale = 7.4 / maxDim;
    object.scale.setScalar(scale);
    object.updateMatrixWorld(true);

    box.setFromObject(object);
    box.getCenter(center);
    object.position.sub(center);
    object.updateMatrixWorld(true);

    box.setFromObject(object);
    object.position.y -= box.min.y + 1.0;
    object.updateMatrixWorld(true);
  }

  async function loadModel() {
    const source = await resolveModelSource(options.modelUrl || './van.glb');
    if (destroyed) {
      source.revoke();
      return;
    }

    modelResource?.revoke?.();
    modelResource = source;

    loader.load(source.url, (gltf) => {
      if (destroyed) {
        source.revoke();
        if (modelResource === source) modelResource = null;
        return;
      }
      const model = gltf.scene;
      fitModel(model);
      modelGroup.clear();
      modelGroup.add(model);
      source.revoke();
      modelResource = null;
    }, undefined, () => {
      source.revoke();
      if (modelResource === source) modelResource = null;
    });
  }

  loadModel().catch((error) => {
    console.error('Failed to load van model', error);
  });

  function resize() {
    const width = Math.max(1, container.clientWidth);
    const height = Math.max(1, container.clientHeight);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }

  function onPointerDown(event) {
    if (!options.interactive) return;
    pointerDown = true;
    lastX = event.clientX;
    lastY = event.clientY;
    container.classList.add('is-dragging');
  }

  function onPointerMove(event) {
    if (!pointerDown) return;
    const dx = event.clientX - lastX;
    const dy = event.clientY - lastY;
    lastX = event.clientX;
    lastY = event.clientY;
    targetRotationY -= dx * 0.008;
    targetPitch = Math.max(-0.18, Math.min(0.32, targetPitch + dy * 0.003));
  }

  function onPointerUp() {
    pointerDown = false;
    container.classList.remove('is-dragging');
  }

  container.addEventListener('pointerdown', onPointerDown);
  window.addEventListener('pointermove', onPointerMove);
  window.addEventListener('pointerup', onPointerUp);
  window.addEventListener('pointercancel', onPointerUp);

  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(container);
  resize();

  function render() {
    if (destroyed) return;
    frameId = requestAnimationFrame(render);
    const now = performance.now();
    const delta = Math.min((now - lastFrameTime) / 1000, 0.05);
    lastFrameTime = now;

    if (!pointerDown && options.autoRotate !== false) {
      targetRotationY += delta * (options.autoRotateSpeed ?? 0.2);
    }

    rotationY += (targetRotationY - rotationY) * 0.08;
    pitch += (targetPitch - pitch) * 0.08;
    updateLabelPositions();
    updateCamera();
    renderer.render(scene, camera);
  }

  updateLabelPositions();
  render();

  return {
    getRotation() {
      return rotationY;
    },
    setLabels,
    setLabelsSpinWithModel(enabled) {
      labelsSpinWithModel = Boolean(enabled);
      updateLabelPositions();
    },
    resize,
    destroy() {
      destroyed = true;
      cancelAnimationFrame(frameId);
      modelResource?.revoke?.();
      resizeObserver.disconnect();
      container.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
      window.removeEventListener('pointercancel', onPointerUp);
      renderer.dispose();
      container.innerHTML = '';
    },
  };
}
