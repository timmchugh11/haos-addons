import * as THREE from './vendor/three/build/three.module.js';
import { GLTFLoader } from './vendor/three/examples/jsm/loaders/GLTFLoader.js';

export function createVanScene(container, options = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 100);
  const clock = new THREE.Clock();
  const loader = new GLTFLoader();

  let destroyed = false;
  let rootGroup = new THREE.Group();
  let modelGroup = new THREE.Group();
  let rotationY = options.initialRotationY ?? -0.78;
  let targetRotationY = rotationY;
  let targetPitch = options.initialPitch ?? 0.08;
  let pitch = targetPitch;
  let radius = 11;
  let lookAtY = options.lookAtY ?? -0.5;
  let frameId = 0;
  let pointerDown = false;
  let lastX = 0;
  let lastY = 0;

  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  container.innerHTML = '';
  container.appendChild(renderer.domElement);

  scene.add(rootGroup);
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

  loader.load(options.modelUrl || './van.glb', (gltf) => {
    if (destroyed) return;
    const model = gltf.scene;
    fitModel(model);
    modelGroup.clear();
    modelGroup.add(model);
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
    targetPitch = Math.max(-0.18, Math.min(0.32, targetPitch - dy * 0.003));
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
    const delta = Math.min(clock.getDelta(), 0.05);

    if (!pointerDown && options.autoRotate !== false) {
      targetRotationY += delta * (options.autoRotateSpeed ?? 0.2);
    }

    rotationY += (targetRotationY - rotationY) * 0.08;
    pitch += (targetPitch - pitch) * 0.08;
    options.onFrame?.({ rotationY, pitch });
    updateCamera();
    renderer.render(scene, camera);
  }

  render();

  return {
    getRotation() {
      return rotationY;
    },
    resize,
    destroy() {
      destroyed = true;
      cancelAnimationFrame(frameId);
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
