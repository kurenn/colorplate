/* app.jsx — ColorPlate main application, wired to the real pipeline backend. */
const { useState, useEffect, useMemo, useRef } = React;

const PICKER_MODE = "popover";   // product default (Tweaks panel is dev-only)

// ---- tiny API client -------------------------------------------------------
async function apiErr(r) {
  try { const j = await r.json(); return new Error(j.detail || r.statusText); }
  catch (e) { return new Error(r.statusText || "Request failed"); }
}
const api = {
  async detect(file, maxColors) {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("maxColors", String(maxColors));
    const r = await fetch("/api/detect", { method: "POST", body: fd });
    if (!r.ok) throw await apiErr(r);
    return r.json();
  },
  async redetect(uploadId, maxColors) {
    const r = await fetch("/api/redetect", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ uploadId, maxColors }),
    });
    if (!r.ok) throw await apiErr(r);
    return r.json();
  },
  async preview(uploadId, assignments) {
    const r = await fetch("/api/preview", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ uploadId, assignments }),
    });
    if (!r.ok) throw await apiErr(r);
    return r.json();
  },
  async generate(payload) {
    const r = await fetch("/api/generate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!r.ok) throw await apiErr(r);
    return r.json();
  },
  async generateStack(payload) {
    const r = await fetch("/api/generate-stack", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!r.ok) throw await apiErr(r);
    return r.json();
  },
};

function App() {
  const [theme, setTheme] = useState(() => document.documentElement.getAttribute("data-theme") || "light");
  useEffect(() => {
    const el = document.documentElement;
    el.setAttribute("data-theme", theme);
    el.setAttribute("data-font", "geist");
    el.style.setProperty("--radius", "10px");
    try { localStorage.setItem("colorplate-theme", theme); } catch (e) {}
  }, [theme]);

  const [uploadId, setUploadId] = useState(null);
  const [file, setFile] = useState(null);            // filename or null
  const [preview, setPreview] = useState(null);      // data URL of recolored art
  const [phase, setPhase] = useState("empty");        // empty | loaded | generating | results
  const [busy, setBusy] = useState(false);            // detecting / re-detecting
  const [error, setError] = useState(null);

  const [view, setView] = useState("2d");             // 2d recolor | 3d geometry
  const [maxColors, setMaxColors] = useState(4);
  const [size, setSize] = useState(180);
  const [front, setFront] = useState(1.0);
  const [backThick, setBackThick] = useState(2.0);
  const [regions, setRegions] = useState([]);
  const [backing, setBacking] = useState(null);       // filament hex | null
  const [result, setResult] = useState(null);

  // single-extruder ("filament swap") mode
  const [printer, setPrinter] = useState("mmu");      // mmu | single
  const [order, setOrder] = useState([]);             // distinct hexes, base -> top
  const [baseH, setBaseH] = useState(0.8);
  const [stepH, setStepH] = useState(0.6);
  const [layerH, setLayerH] = useState(0.2);

  const loaded = phase === "loaded" || phase === "generating" || phase === "results";
  const previewToken = useRef(0);

  const distinct = useMemo(() => {
    const seen = new Set(), out = [];
    regions.forEach((r) => { const k = r.filament.hex; if (!seen.has(k)) { seen.add(k); out.push(r.filament); } });
    return out;
  }, [regions]);

  // Keep the stack order reconciled with the colors actually in use:
  // preserve existing positions, append new colors on top, drop removed ones.
  useEffect(() => {
    const live = distinct.map((f) => f.hex);
    setOrder((prev) => {
      const kept = prev.filter((h) => live.includes(h));
      const added = live.filter((h) => !kept.includes(h));
      const next = [...kept, ...added];
      return next.length === prev.length && next.every((h, i) => h === prev[i]) ? prev : next;
    });
  }, [distinct]);

  const filamentByHex = (hex) => distinct.find((f) => f.hex === hex) || { name: hex, hex };

  // client-side swap schedule (mirrors the server's layer snapping)
  const schedule = useMemo(() => {
    const snap = (v, l) => Math.max(l, Math.round(v / l) * l);
    const b = snap(baseH, layerH), s = snap(stepH, layerH);
    const bands = order.map((hex, i) => {
      const z0 = i === 0 ? 0 : +(b + (i - 1) * s).toFixed(2);
      const z1 = i === 0 ? +b.toFixed(2) : +(b + i * s).toFixed(2);
      return { hex, action: i === 0 ? "start" : "swap", z0, z1,
               layer: Math.round(z0 / layerH) + 1, fil: filamentByHex(hex) };
    });
    const total = +(b + (order.length - 1) * s).toFixed(2);
    return { bands, total };
  }, [order, baseH, stepH, layerH, distinct]);

  const moveColor = (hex, dir) => {
    setOrder((prev) => {
      const i = prev.indexOf(hex), j = i + dir;
      if (i < 0 || j < 0 || j >= prev.length) return prev;
      const next = [...prev];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  };

  const applyDetection = (resp) => {
    setUploadId(resp.uploadId);
    setFile(resp.filename);
    setRegions(resp.regions);
    setPreview(resp.preview);
    setBacking(resp.regions.length ? resp.regions[0].filament.hex : null);
  };

  const loadFile = async (f) => {
    setBusy(true); setError(null);
    try {
      const resp = await api.detect(f, maxColors);
      applyDetection(resp);
      setResult(null);
      setPhase("loaded");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const clearFile = () => {
    setUploadId(null); setFile(null); setPreview(null);
    setRegions([]); setBacking(null); setResult(null);
    setError(null); setPhase("empty");
  };

  const changeMax = async (n) => {
    setMaxColors(n);
    if (!loaded || !uploadId) return;
    setBusy(true); setError(null);
    try {
      const resp = await api.redetect(uploadId, n);
      applyDetection(resp);
      if (phase === "results") { setResult(null); setPhase("loaded"); }
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const refreshPreview = async (regs) => {
    if (!uploadId) return;
    const token = ++previewToken.current;
    try {
      const resp = await api.preview(uploadId, regs.map((r) => r.filament.hex));
      if (token === previewToken.current) setPreview(resp.preview);
    } catch (e) { /* keep stale preview on transient error */ }
  };

  const assign = (i, fil) => {
    const next = regions.map((r, idx) => (idx === i ? { ...r, filament: fil } : r));
    setRegions(next);
    // keep backing valid: if its color is gone, fall back to the dominant filament
    const hexes = new Set(next.map((r) => r.filament.hex));
    if (backing && !hexes.has(backing)) setBacking(next[0].filament.hex);
    refreshPreview(next);
    if (phase === "results") { setResult(null); setPhase("loaded"); }
  };

  const regionViews = regions.map((r, i) => ({ ...r, onAssign: (fil) => assign(i, fil) }));

  const generate = async () => {
    setPhase("generating"); setError(null);
    try {
      const resp = await api.generate({
        uploadId,
        assignments: regions.map((r) => ({ name: r.filament.name, hex: r.filament.hex })),
        size, front, back: backThick, backing,
      });
      setResult(resp);
      setPhase("results");
    } catch (e) {
      setError(e.message);
      setPhase("loaded");
    }
  };

  const generateSingle = async () => {
    setPhase("generating"); setError(null);
    try {
      const resp = await api.generateStack({
        uploadId,
        assignments: regions.map((r) => ({ name: r.filament.name, hex: r.filament.hex })),
        order, size, base: baseH, step: stepH, layer: layerH,
      });
      setResult(resp);
      setPhase("results");
    } catch (e) {
      setError(e.message);
      setPhase("loaded");
    }
  };

  const fileUrl = (name) => `/api/file/${uploadId}/${encodeURIComponent(name)}`;
  const zipUrl = result ? `/api/zip/${uploadId}/${encodeURIComponent(result.zip)}` : "#";

  return (
    <>
      {/* TOP BAR */}
      <div className="topbar">
        <div className="brand">
          <span className="logomark" style={{ display: "inline-flex" }}>
            <Emblem regions={regions} size={22} />
          </span>
          ColorPlate <small>/ color-plate generator</small>
        </div>
        <div className="spacer" />
        <div className="pill"><span className="dot" />{loaded ? "ready" : "awaiting file"}</div>
        <button className="icon-btn" title="Toggle theme"
                onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
          {theme === "dark" ? <Icons.moon size={16} /> : <Icons.sun size={16} />}
        </button>
      </div>

      {/* LAYOUT */}
      <div className="layout">
        {/* LEFT — controls */}
        <div className="col-left">
          <div className="pad">
            {/* upload */}
            <div className="group">
              <div className="section-label">Source file</div>
              {file
                ? <FileCard name={file} regionCount={regions.length} preview={preview} onClear={clearFile} />
                : <UploadZone onLoad={loadFile} busy={busy} error={error} />}
            </div>

            {/* printer type */}
            <div className={"group" + (loaded ? "" : " is-disabled")}>
              <div className="section-label">Printer</div>
              <div className="seg" role="group" aria-label="Printer type">
                <button aria-pressed={printer === "mmu"} onClick={() => setPrinter("mmu")}>Multi-material</button>
                <button aria-pressed={printer === "single"}
                        onClick={() => { setPrinter("single"); setView("3d"); }}>Single extruder</button>
              </div>
              <div className="hint">{printer === "mmu"
                ? "MMU / toolchanger — one STL per color, printed face-down."
                : "One nozzle — colors stacked by height with filament swaps (a relief)."}</div>
            </div>

            {/* max colors */}
            <div className={"group" + (loaded ? "" : " is-disabled")}>
              <div className="section-label">Max colors</div>
              <Segmented value={maxColors} options={[2, 3, 4, 5, 6]} onChange={changeMax} />
              <div className="hint">Most printers handle 4 at once.</div>
            </div>

            {/* color config */}
            <div className={"group" + (loaded ? "" : " is-disabled")}>
              <div className="section-label">Filament assignments <span className="n">{regions.length}</span></div>
              <ColorConfig regions={regionViews} mode={PICKER_MODE} />
            </div>

            {/* size */}
            <div className={"group" + (loaded ? "" : " is-disabled")}>
              <div className="section-label">Size</div>
              <NumberField value={size} onChange={setSize} unit="mm" step={5} min={20} />
              <div className="hint">Longest dimension of the finished plate.</div>
            </div>

            {printer === "mmu" ? (
              <>
                {/* thickness */}
                <div className={"group" + (loaded ? "" : " is-disabled")}>
                  <div className="section-label">Thickness</div>
                  <div className="twocol">
                    <div>
                      <label className="lbl">Front</label>
                      <NumberField value={front} onChange={setFront} unit="mm" step={0.1} min={0.2} decimals={1} />
                    </div>
                    <div>
                      <label className="lbl">Backing</label>
                      <NumberField value={backThick} onChange={setBackThick} unit="mm" step={0.1} min={0.2} decimals={1} />
                    </div>
                  </div>
                  <div className="hint">Front layers carry the color art; the backing is the solid base plate everything prints onto.</div>
                </div>

                {/* backing color */}
                <div className={"group" + (loaded ? "" : " is-disabled")}>
                  <div className="section-label">Backing color</div>
                  <BackingSelect regions={regions} value={backing} onChange={setBacking} />
                </div>
              </>
            ) : (
              <>
                {/* stack order */}
                <div className={"group" + (loaded ? "" : " is-disabled")}>
                  <div className="section-label">Stack order <span className="n" style={{ color: "var(--text-3)" }}>top → base</span></div>
                  <div className="stack-list">
                    {[...order].map((hex, i) => ({ hex, i })).reverse().map(({ hex, i }) => {
                      const fil = filamentByHex(hex);
                      const isTop = i === order.length - 1, isBase = i === 0;
                      return (
                        <div className="stack-row" key={hex}>
                          <span className="sw" style={{ background: hex }} />
                          <span className="snm">{fil.name}</span>
                          {isBase && <span className="badge">base</span>}
                          <div className="stack-btns">
                            <button disabled={isTop} onClick={() => moveColor(hex, +1)} aria-label="Raise">↑</button>
                            <button disabled={isBase} onClick={() => moveColor(hex, -1)} aria-label="Lower">↓</button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  <div className="hint">Background color sits at the base; accents stack on top.</div>
                </div>

                {/* layering */}
                <div className={"group" + (loaded ? "" : " is-disabled")}>
                  <div className="section-label">Layering</div>
                  <div className="twocol">
                    <div>
                      <label className="lbl">Base</label>
                      <NumberField value={baseH} onChange={setBaseH} unit="mm" step={0.2} min={0.2} decimals={1} />
                    </div>
                    <div>
                      <label className="lbl">Step / color</label>
                      <NumberField value={stepH} onChange={setStepH} unit="mm" step={0.2} min={0.2} decimals={1} />
                    </div>
                  </div>
                  <div style={{ marginTop: 10 }}>
                    <label className="lbl">Layer height</label>
                    <NumberField value={layerH} onChange={setLayerH} unit="mm" step={0.04} min={0.04} decimals={2} />
                  </div>
                  <div className="hint">Swaps snap to a layer boundary · total height ≈ {schedule.total} mm.</div>
                </div>

                {/* swap schedule */}
                <div className={"group" + (loaded ? "" : " is-disabled")}>
                  <div className="section-label">Filament swaps <span className="n">{Math.max(0, order.length - 1)}</span></div>
                  <div className="swap-list">
                    {schedule.bands.map((b) => (
                      <div className="swap-row" key={b.hex}>
                        <span className="sw" style={{ background: b.hex }} />
                        <span className="snm">{b.fil.name}</span>
                        <span className="swap-z mono">{b.action === "start" ? "start" : "swap @ " + b.z0 + "mm"}</span>
                        <span className="swap-layer mono">L{b.layer}</span>
                      </div>
                    ))}
                  </div>
                  <div className="hint">Insert an <code>M600</code> at each swap layer (single nozzle).</div>
                </div>
              </>
            )}
          </div>

          {/* sticky footer: Generate button (hidden once results show) */}
          {phase !== "results" && (
            <div className="sticky-foot">
              {error && loaded ? <div className="dz-err" style={{ marginBottom: 8, textAlign: "center" }}>{error}</div> : null}
              {printer === "single" ? (
                <button className="btn-primary" disabled={!loaded || phase === "generating"} onClick={generateSingle}>
                  {phase === "generating"
                    ? <><Icons.spinner size={17} className="spin" /> Building terraced STL…</>
                    : <><Icons.cube size={17} /> Export STL + swap schedule</>}
                </button>
              ) : (
                <button className="btn-primary" disabled={!loaded || phase === "generating"} onClick={generate}>
                  {phase === "generating"
                    ? <><Icons.spinner size={17} className="spin" /> Slicing color plates…</>
                    : <><Icons.cube size={17} /> Generate STLs</>}
                </button>
              )}
            </div>
          )}

          {/* results overlay sheet */}
          {phase === "results" && result && (
            <div className="results-sheet">
              <div className="rs-head">
                <div className="rhead">
                  <span className="ok"><Icons.check size={13} /></span>
                  <h4>{result.files.length} files ready</h4>
                  <span className="mono" style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-3)" }}>{result.totalMB.toFixed(1)} MB total</span>
                </div>
                <div className="hint" style={{ marginTop: 6 }}>{printer === "single"
                  ? <>One terraced STL ({result.totalHeight}mm tall) plus a swap schedule. Print as one object on a single nozzle, inserting an <code>M600</code> at each swap layer.</>
                  : "One STL per filament color, plus the backing plate. Load them into your slicer as a single multi-color object."}</div>
              </div>
              <div className="rs-list">
                {result.files.map((f, i) => (
                  <div className="file-row" key={f.name} style={{ animationDelay: i * 45 + "ms" }}>
                    <span className="fi" style={{ background: f.hex }} />
                    <span className="fn">{f.name}</span>
                    <span className="fsz">{f.sizeMB.toFixed(1)} MB</span>
                    <a className="dl" title="Download" href={fileUrl(f.name)} download><Icons.download size={15} /></a>
                  </div>
                ))}
              </div>
              <div className="rs-foot">
                <a className="btn-primary" href={zipUrl} download><Icons.pkg size={17} /> Download all (.zip)</a>
                <button className="btn-ghost" onClick={() => setPhase("loaded")}><Icons.pencil size={15} /> Back to editing</button>
              </div>
            </div>
          )}
        </div>

        {/* RIGHT — preview */}
        <div className="col-right">
          <div className="preview-wrap">
            <div className="preview-top">
              <Icons.image size={16} />
              <span style={{ fontSize: 13, fontWeight: 600 }}>Print preview</span>
              {loaded && (
                <div className="view-toggle" style={{ marginLeft: "auto" }} role="group" aria-label="Preview mode">
                  <button aria-pressed={view === "2d"} onClick={() => setView("2d")}>2D</button>
                  <button aria-pressed={view === "3d"} onClick={() => setView("3d")}>3D</button>
                </div>
              )}
              <span className="ptab" style={loaded ? null : { marginLeft: "auto" }}>
                {!loaded ? "no file"
                  : view === "2d" ? "painted with assigned filaments"
                  : printer === "single" ? "single-extruder relief"
                  : "real layered geometry"}
              </span>
            </div>

            <div className="preview-stage">
              {loaded && view === "3d" ? (
                <div style={{ position: "absolute", inset: 0 }}>
                  <ThreePreview
                    uploadId={uploadId}
                    regions={regions}
                    backing={printer === "single" ? (order[0] || null) : backing}
                    size={size}
                    front={front}
                    back={backThick}
                    theme={theme}
                    mode={printer === "single" ? "stack" : "mmu"}
                    stackParams={printer === "single"
                      ? { order, base: baseH, step: stepH, layer: layerH } : null}
                  />
                </div>
              ) : loaded && preview ? (
                <div className="stage-card">
                  <img className="emblem-box art-preview" src={preview} alt="recolored logo preview" />
                  <div className="stage-legend">
                    {distinct.map((f) => (
                      <div className="legchip" key={f.hex}>
                        <span className="ls" style={{ background: f.hex }} />
                        <span className="lt">{f.name} {f.hex.toUpperCase()}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="empty-ill">
                  <div className="empty-ring">
                    <Icons.layers size={40} />
                  </div>
                  <div style={{ textAlign: "center" }}>
                    <h3>Drop an SVG or PNG to start</h3>
                    <p>Your logo, separated into printable color layers.</p>
                  </div>
                </div>
              )}
            </div>

            <div className="status">
              {loaded ? (
                <>
                  <span className="k">{result && result.coverageGap ? result.coverageGap + "px gap" : "100% coverage"}</span>
                  <span className="sep">·</span>
                  <span className="k">{regions.length} colors</span>
                  <span className="sep">·</span>
                  <span className="k">~{size}mm</span>
                  <span className="sep">·</span>
                  <span className="k">{printer === "single"
                    ? schedule.total + "mm tall · " + Math.max(0, order.length - 1) + " swaps"
                    : (front + backThick).toFixed(1) + "mm thick"}</span>
                  <span className="swrow">
                    {distinct.map((f) => <span key={f.hex} className="mini" style={{ background: f.hex }} title={f.name} />)}
                  </span>
                </>
              ) : (
                <span className="k" style={{ color: "var(--text-3)" }}>Awaiting a file — drop one on the left to begin.</span>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
