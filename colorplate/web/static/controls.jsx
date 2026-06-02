/* controls.jsx — upload zone, segmented selector, number field, backing select */

function UploadZone({ onLoad, busy, error }) {
  const [over, setOver] = React.useState(false);
  const inputRef = React.useRef(null);
  const pick = (f) => { if (f) onLoad(f); };
  return (
    <div
      className={"dropzone" + (over ? " dropzone--over" : "") + (busy ? " dropzone--busy" : "")}
      onClick={() => !busy && inputRef.current && inputRef.current.click()}
      onDragOver={(e) => { e.preventDefault(); if (!busy) setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault(); setOver(false);
        if (busy) return;
        const f = e.dataTransfer.files && e.dataTransfer.files[0];
        pick(f);
      }}
    >
      <div className="dz-accent" />
      <div className="dz-ico">
        {busy ? <Icons.spinner size={26} className="spin" /> : <Icons.upload size={26} />}
      </div>
      <h4>{busy ? "Detecting colors…" : over ? "Drop to upload" : "Drop your logo here"}</h4>
      <div className="hint">
        {busy ? "Reading the artwork and separating its colors." : "or click to browse — we’ll detect the colors"}
      </div>
      <div className="formats">SVG · PNG · up to 20 MB</div>
      {error ? <div className="dz-err">{error}</div> : null}
      <input ref={inputRef} type="file" accept=".svg,.png,.jpg,.jpeg,.webp,image/*"
             style={{ display: "none" }}
             onChange={(e) => { pick(e.target.files[0]); e.target.value = ""; }} />
    </div>
  );
}

function FileCard({ name, regionCount, preview, onClear }) {
  return (
    <div className="filecard">
      <div className="thumb">
        {preview ? <img src={preview} alt="" /> : null}
      </div>
      <div className="meta">
        <div className="name">{name}</div>
        <div className="sub">{(name.split(".").pop() || "svg").toUpperCase()} · {regionCount} regions detected</div>
      </div>
      <div className="x" title="Remove" onClick={onClear}><Icons.x size={16} /></div>
    </div>
  );
}

function Segmented({ value, options, onChange }) {
  return (
    <div className="seg" role="group">
      {options.map((o) => (
        <button key={o} aria-pressed={value === o} onClick={() => onChange(o)}>{o}</button>
      ))}
    </div>
  );
}

function NumberField({ value, onChange, unit, step = 1, min = 0, decimals = 0 }) {
  const fmt = (v) => decimals ? v.toFixed(decimals) : String(v);
  const set = (v) => onChange(Math.max(min, Math.round(v / step) * step));
  return (
    <div className="field">
      <input
        className="mono"
        value={fmt(value)}
        inputMode="decimal"
        onChange={(e) => { const n = parseFloat(e.target.value); if (!isNaN(n)) onChange(Math.max(min, n)); }}
      />
      {unit ? <span className="unit">{unit}</span> : null}
      <div className="stepper">
        <button tabIndex={-1} onClick={() => set(value + step)} aria-label="increase"><Icons.chevR size={12} style={{ transform: "rotate(-90deg)" }} /></button>
        <button tabIndex={-1} onClick={() => set(value - step)} aria-label="decrease"><Icons.chevR size={12} style={{ transform: "rotate(90deg)" }} /></button>
      </div>
    </div>
  );
}

function BackingSelect({ regions, value, onChange }) {
  const [open, setOpen] = React.useState(false);
  const [dropUp, setDropUp] = React.useState(false);
  const btnRef = React.useRef(null);
  const menuRef = React.useRef(null);
  // options: None + one per distinct assigned filament
  const seen = new Set();
  const filaments = [];
  regions.forEach((r) => { const k = r.filament.hex; if (!seen.has(k)) { seen.add(k); filaments.push(r.filament); } });
  const options = [{ name: "None", hex: null }, ...filaments];
  const current = options.find((o) => (o.hex || "none") === (value || "none")) || options[0];

  // Once the menu is rendered, measure it and flip it above the button when it
  // wouldn't fit below — this control sits just above the sticky Generate footer,
  // so a plain drop-down gets clipped and hidden behind it.
  React.useLayoutEffect(() => {
    if (!open) { setDropUp(false); return; }
    const btn = btnRef.current, menu = menuRef.current;
    if (!btn || !menu) return;
    const r = btn.getBoundingClientRect();
    const menuH = menu.offsetHeight;
    const below = window.innerHeight - r.bottom;
    setDropUp(below < menuH + 12 && r.top > below);
  }, [open]);

  return (
    <div className="select">
      <button ref={btnRef} className="select__btn" onClick={() => setOpen((o) => !o)}>
        {current.hex
          ? <span className="dotcol" style={{ background: current.hex }} />
          : <span className="dotcol" style={{ background: "transparent", boxShadow: "inset 0 0 0 1px var(--border-2)" }} />}
        <span>{current.name}{current.hex ? "" : " — no base plate"}</span>
        {current.hex ? <span className="mono" style={{ fontSize: 11, color: "var(--text-3)" }}>{current.hex}</span> : null}
        <Icons.chevD className="chev" size={15} />
      </button>
      {open && (
        <>
          <div className="backdrop" onClick={() => setOpen(false)} />
          <div ref={menuRef}
               className={"select__menu pop-anim" + (dropUp ? " select__menu--up" : "")}>
            {options.map((o) => {
              const sel = (o.hex || "none") === (value || "none");
              return (
                <div key={o.name + (o.hex || "")} className="opt" aria-selected={sel}
                     onClick={() => { onChange(o.hex); setOpen(false); }}>
                  {o.hex
                    ? <span className="dotcol" style={{ background: o.hex }} />
                    : <span className="dotcol" style={{ background: "transparent", boxShadow: "inset 0 0 0 1px var(--border-2)" }} />}
                  <span>{o.name}</span>
                  {o.hex ? <span className="mono" style={{ fontSize: 11, color: "var(--text-3)", marginLeft: "auto" }}>{o.hex}</span> : null}
                  {sel ? <span className="check" style={{ marginLeft: o.hex ? 10 : "auto" }}><Icons.check size={15} /></span> : null}
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

Object.assign(window, { UploadZone, FileCard, Segmented, NumberField, BackingSelect });
