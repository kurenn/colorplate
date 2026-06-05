/* three-preview.jsx — real 3D preview of the layered color plates.

   Renders the *actual* extruded geometry the backend builds (one mesh per
   detected region for the front shell, plus the backing plate) with Three.js.
   Filament colors are applied client-side, so reassigning a filament recolors
   instantly; only size / thickness / color-count changes refetch geometry.

   No bundler: Three.js is loaded as a UMD global (THREE) from a CDN, and a tiny
   built-in orbit controller (drag-rotate, wheel + pinch zoom) avoids the
   OrbitControls module dependency. */
const ThreePreview = (function () {
  const { useRef, useEffect, useState } = React;

  const REDUCED_MOTION =
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const DEF_RX = -0.5, DEF_RY = -0.62;   // hero 3/4 tilt

  // Small LRU of fetched geometry so 2D⇄3D toggles and revisited sizes are
  // instant and don't re-hit the backend.
  const MESH_CACHE = new Map();
  const MESH_CACHE_CAP = 8;

  function webglSupported() {
    try {
      const c = document.createElement("canvas");
      return !!(window.WebGLRenderingContext &&
        (c.getContext("webgl") || c.getContext("experimental-webgl")));
    } catch (e) { return false; }
  }

  async function fetchGeom(key, url, body) {
    if (MESH_CACHE.has(key)) return MESH_CACHE.get(key);
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      let detail = r.statusText;
      try { detail = (await r.json()).detail || detail; } catch (e) {}
      throw new Error(detail);
    }
    const data = await r.json();
    MESH_CACHE.set(key, data);
    if (MESH_CACHE.size > MESH_CACHE_CAP) MESH_CACHE.delete(MESH_CACHE.keys().next().value);
    return data;
  }

  function makeGeometry(geom, center) {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(geom.positions, 3));
    g.setIndex(geom.indices);
    g.translate(-center[0], -center[1], -center[2]);
    g.computeVertexNormals();
    return g;
  }

  function ThreePreview(props) {
    const { uploadId, regions, backing, size, front, back, theme } = props;
    const mode = props.mode || "mmu";              // "mmu" | "stack"
    const stack = props.stackParams || null;       // {order, base, step, layer} when stack
    const mountRef = useRef(null);
    const ctx = useRef(null);          // persistent three.js context
    const [status, setStatus] = useState("idle");   // idle|loading|ready|error|unsupported

    const [err, setErr] = useState(null);

    const assignKey = regions.map((r) => r.filament.hex).join(",");
    const colorKey = assignKey + "|" + (backing || "");
    const geomKey = mode === "stack"
      ? ["stack", uploadId, size, assignKey, (stack.order || []).join(","),
         stack.base, stack.step, stack.layer].join("|")
      : ["mmu", uploadId, regions.length, size, front, back].join("|");

    // request (url + body) for the current geometry mode
    const geomReq = () => mode === "stack"
      ? ["/api/stack3d", {
          uploadId, assignments: regions.map((r) => r.filament.hex),
          order: stack.order, size, base: stack.base, step: stack.step, layer: stack.layer,
        }]
      : ["/api/mesh3d", { uploadId, size, front, back }];

    // ---- one-time scene setup ---------------------------------------------
    useEffect(() => {
      if (!webglSupported()) { setStatus("unsupported"); return; }
      const mount = mountRef.current;
      let renderer;
      try {
        renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      } catch (e) { setStatus("unsupported"); return; }
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.setSize(mount.clientWidth, mount.clientHeight, false);
      renderer.domElement.style.display = "block";
      renderer.domElement.style.touchAction = "none";
      mount.appendChild(renderer.domElement);

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(38, mount.clientWidth / mount.clientHeight, 0.1, 5000);
      camera.position.set(0, 0, 300);

      const pivot = new THREE.Group();
      scene.add(pivot);
      const model = new THREE.Group();
      pivot.add(model);
      // MMU: flip so the colored show-face (z=0) faces the viewer.
      // Stack: don't flip — the colored face is the TOP (z=max).
      model.rotation.x = mode === "stack" ? 0 : Math.PI;

      const hemi = new THREE.HemisphereLight(0xffffff, 0x444450, 1.1);
      const key = new THREE.DirectionalLight(0xffffff, 2.6); key.position.set(0.6, 1.0, 1.2);
      const fill = new THREE.DirectionalLight(0xffffff, 0.9); fill.position.set(-1.0, -0.4, 0.6);
      const rim = new THREE.DirectionalLight(0xffffff, 0.7); rim.position.set(0, 0.3, -1.2);
      scene.add(hemi, key, fill, rim);

      const state = {
        renderer, scene, camera, pivot, model,
        regionMeshes: [], backingMesh: null, edgeLines: [],
        radius: 100, dist: 300, fitDist: 300,
        defRX: mode === "stack" ? -0.95 : DEF_RX,   // stack reads better from above
        rotX: mode === "stack" ? -0.95 : DEF_RX, rotY: DEF_RY,
        velY: 0, dragging: false, interacted: REDUCED_MOTION, // no idle spin if reduced
        pointers: new Map(), pinchDist: 0,
        raf: 0, running: true, disposed: false,
      };
      ctx.current = state;

      // ---- orbit + zoom (mouse + touch, incl. pinch) ----------------------
      const el = renderer.domElement;
      const onDown = (e) => {
        state.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
        state.dragging = true; state.interacted = true; state.velY = 0;
        if (state.pointers.size === 2) state.pinchDist = pointerSpread(state.pointers);
        el.setPointerCapture && el.setPointerCapture(e.pointerId);
      };
      const onMove = (e) => {
        const p = state.pointers.get(e.pointerId);
        if (!p) return;
        const prev = { x: p.x, y: p.y };
        p.x = e.clientX; p.y = e.clientY;
        if (state.pointers.size >= 2) {
          const d = pointerSpread(state.pointers);
          if (state.pinchDist) zoomBy(state, state.pinchDist / d);
          state.pinchDist = d;
          return;
        }
        const dx = p.x - prev.x, dy = p.y - prev.y;
        state.rotY += dx * 0.01;
        state.rotX += dy * 0.01;
        const lim = Math.PI / 2 - 0.05;
        state.rotX = Math.max(-lim, Math.min(lim, state.rotX));
        state.velY = dx * 0.01;
      };
      const onUp = (e) => {
        state.pointers.delete(e.pointerId);
        if (state.pointers.size < 2) state.pinchDist = 0;
        if (state.pointers.size === 0) state.dragging = false;
        try { el.releasePointerCapture(e.pointerId); } catch (_) {}
      };
      const onWheel = (e) => {
        e.preventDefault();
        state.interacted = true;
        zoomBy(state, Math.exp(e.deltaY * 0.0012));
      };
      const onDblClick = () => resetView(state);
      el.addEventListener("pointerdown", onDown);
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      window.addEventListener("pointercancel", onUp);
      el.addEventListener("wheel", onWheel, { passive: false });
      el.addEventListener("dblclick", onDblClick);

      // ---- render loop (paused when the tab is hidden) ---------------------
      const tick = () => {
        if (state.disposed) return;
        state.raf = requestAnimationFrame(tick);
        if (!state.running) return;
        if (!state.dragging) {
          if (!state.interacted) state.rotY += 0.0032;
          else { state.rotY += state.velY; state.velY *= 0.92; }
        }
        pivot.rotation.x = state.rotX;
        pivot.rotation.y = state.rotY;
        camera.position.set(0, 0, state.dist);
        camera.lookAt(0, 0, 0);
        renderer.render(scene, camera);
      };
      tick();

      const onVis = () => { state.running = !document.hidden; };
      document.addEventListener("visibilitychange", onVis);

      const ro = new ResizeObserver(() => {
        const w = mount.clientWidth, h = mount.clientHeight;
        if (!w || !h) return;
        renderer.setSize(w, h, false);
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
      });
      ro.observe(mount);

      return () => {
        state.disposed = true;
        cancelAnimationFrame(state.raf);
        ro.disconnect();
        document.removeEventListener("visibilitychange", onVis);
        el.removeEventListener("pointerdown", onDown);
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        window.removeEventListener("pointercancel", onUp);
        el.removeEventListener("wheel", onWheel);
        el.removeEventListener("dblclick", onDblClick);
        disposeModel(state);
        renderer.dispose();
        if (el.parentNode) el.parentNode.removeChild(el);
        ctx.current = null;
      };
    }, []);

    // ---- (re)build geometry on shape change -------------------------------
    useEffect(() => {
      const state = ctx.current;
      if (!state || !uploadId || status === "unsupported") return;
      let cancelled = false;
      const cached = MESH_CACHE.has(geomKey);
      if (!cached) { setStatus("loading"); setErr(null); }
      const run = async () => {
        try {
          const [url, body] = geomReq();
          const data = await fetchGeom(geomKey, url, body);
          if (cancelled || state.disposed) return;
          buildModel(state, data);
          applyColors(state, props.regions, props.backing, theme);
          setStatus("ready");
        } catch (e) {
          if (!cancelled) { setErr(e.message); setStatus("error"); }
        }
      };
      // instant for cached geometry; debounce live fetches (stepper drags)
      if (cached) { run(); return () => { cancelled = true; }; }
      const t = setTimeout(run, 280);
      return () => { cancelled = true; clearTimeout(t); };
    }, [geomKey]);

    // ---- recolor on filament / backing / theme change ---------------------
    useEffect(() => {
      const state = ctx.current;
      if (state && state.regionMeshes.length) applyColors(state, regions, backing, theme);
    }, [colorKey, theme]);

    // ---- re-orient when the printer mode changes (no remount) -------------
    useEffect(() => {
      const s = ctx.current;
      if (!s) return;
      s.model.rotation.x = mode === "stack" ? 0 : Math.PI;
      s.defRX = mode === "stack" ? -0.95 : DEF_RX;
      s.rotX = s.defRX; s.rotY = DEF_RY; s.velY = 0;
      s.interacted = REDUCED_MOTION;
    }, [mode]);

    const doReset = () => { if (ctx.current) resetView(ctx.current); };

    return (
      <div className="three-wrap" ref={mountRef}>
        {status === "loading" && (
          <div className="three-overlay"><Icons.spinner size={20} className="spin" /><span>building 3D…</span></div>
        )}
        {status === "error" && (
          <div className="three-overlay err">3D preview failed: {err}</div>
        )}
        {status === "unsupported" && (
          <div className="three-overlay err">3D preview needs WebGL, which is unavailable here. Use the 2D view.</div>
        )}
        {status === "ready" && (
          <button className="three-reset" onClick={doReset} title="Reset view (or double-click)">
            <Icons.refresh size={14} /> Reset view
          </button>
        )}
        {status !== "unsupported" && <div className="three-hint">drag to rotate · scroll or pinch to zoom</div>}
      </div>
    );
  }

  // ---- helpers ------------------------------------------------------------
  function pointerSpread(pointers) {
    const pts = [...pointers.values()];
    return Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y) || 1;
  }
  function zoomBy(state, factor) {
    state.dist = Math.max(state.radius * 1.2, Math.min(state.radius * 8, state.dist * factor));
  }

  function disposeModel(state) {
    const kill = (m) => {
      if (!m) return;
      state.model.remove(m);
      if (m.geometry) m.geometry.dispose();
      if (m.material) m.material.dispose();
    };
    state.regionMeshes.forEach(kill);
    state.edgeLines.forEach(kill);
    kill(state.backingMesh);
    state.regionMeshes = []; state.edgeLines = []; state.backingMesh = null;
  }

  function buildModel(state, data) {
    disposeModel(state);
    const bbox = data.bbox;
    if (!bbox) { sizeCamera(state, 100); return; }
    const center = [(bbox[0] + bbox[3]) / 2, (bbox[1] + bbox[4]) / 2, (bbox[2] + bbox[5]) / 2];
    const dims = [bbox[3] - bbox[0], bbox[4] - bbox[1], bbox[5] - bbox[2]];
    const radius = 0.5 * Math.hypot(dims[0], dims[1], dims[2]);

    state.regionMeshes = data.regions.map((r) => {
      if (!r.geometry) return null;
      const geo = makeGeometry(r.geometry, center);
      const mat = new THREE.MeshStandardMaterial({ color: 0xcccccc, roughness: 0.62, metalness: 0.0 });
      const mesh = new THREE.Mesh(geo, mat);
      state.model.add(mesh);
      const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(geo, 30),
        new THREE.LineBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.12 })
      );
      state.model.add(edges);
      state.edgeLines.push(edges);
      return mesh;
    });

    if (data.backing) {
      const geo = makeGeometry(data.backing, center);
      const mat = new THREE.MeshStandardMaterial({ color: 0x999999, roughness: 0.7, metalness: 0.0 });
      const mesh = new THREE.Mesh(geo, mat);
      state.model.add(mesh);
      state.backingMesh = mesh;
    }
    sizeCamera(state, radius);
  }

  function sizeCamera(state, radius) {
    state.radius = radius;
    const fov = (state.camera.fov * Math.PI) / 180;
    state.dist = (radius / Math.sin(fov / 2)) * 1.18;
    state.fitDist = state.dist;
  }

  function resetView(state) {
    state.rotX = state.defRX != null ? state.defRX : DEF_RX;
    state.rotY = DEF_RY;
    state.velY = 0;
    state.dist = state.fitDist;
    state.interacted = true;   // hold the reset pose; no surprise re-spin
  }

  function applyColors(state, regions, backing, theme) {
    state.regionMeshes.forEach((mesh, i) => {
      if (!mesh) return;
      const hex = regions[i] && regions[i].filament ? regions[i].filament.hex : "#cccccc";
      mesh.material.color.set(hex);
    });
    if (state.backingMesh) {
      const show = !!backing;
      state.backingMesh.visible = show;
      if (show) state.backingMesh.material.color.set(backing);
    }
    const edgeColor = theme === "dark" ? 0x000000 : 0x222222;
    const edgeOpacity = theme === "dark" ? 0.18 : 0.1;
    state.edgeLines.forEach((e) => { e.material.color.set(edgeColor); e.material.opacity = edgeOpacity; });
  }

  return ThreePreview;
})();

window.ThreePreview = ThreePreview;
