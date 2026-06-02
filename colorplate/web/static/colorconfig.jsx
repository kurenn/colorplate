/* colorconfig.jsx — region rows + preset/hex picker (popover + inline modes) */

function PickerBody({ current, onPick, inline }) {
  const [hex, setHex] = React.useState((current.hex || "").replace("#", "").toUpperCase());
  React.useEffect(() => { setHex((current.hex || "").replace("#", "").toUpperCase()); }, [current.hex]);
  const valid = /^[0-9A-F]{6}$/.test(hex);
  const liveHex = valid ? "#" + hex : current.hex;
  const commitHex = () => {
    if (!valid) return;
    const h = "#" + hex;
    // if it matches a preset exactly, use that name; else "Custom"
    const exact = PRESETS.find((p) => p.hex.toUpperCase() === h.toUpperCase());
    onPick({ name: exact ? exact.name : "Custom", hex: h });
  };
  return (
    <div className={"picker" + (inline ? " picker--inline" : "")}>
      <div className="ptitle">Filament presets</div>
      <div className="picker__grid">
        {PRESETS.map((p) => (
          <div key={p.name} className="preset" aria-selected={p.hex.toUpperCase() === (current.hex || "").toUpperCase()}
               onClick={() => onPick({ ...p })} title={p.name + " " + p.hex}>
            <span className="psw" style={{ background: p.hex }} />
            <span className="pname">{p.name}</span>
          </div>
        ))}
      </div>
      <div className="hexrow">
        <label className="lbl">Custom hex</label>
        <div className="hexfield">
          <span className="hash">#</span>
          <input className="mono" value={hex} maxLength={6} spellCheck={false}
                 onChange={(e) => setHex(e.target.value.replace(/[^0-9a-fA-F]/g, "").toUpperCase())}
                 onKeyDown={(e) => { if (e.key === "Enter") commitHex(); }}
                 onBlur={commitHex} placeholder="RRGGBB" />
          <span className="live" style={{ background: liveHex }} />
        </div>
      </div>
    </div>
  );
}

function ColorRow({ region, index, mode, openId, setOpenId }) {
  const open = openId === region.id;
  const anchorRef = React.useRef(null);
  const [pos, setPos] = React.useState(null);

  const onPick = (fil) => { region.onAssign(fil); if (mode === "popover") setOpenId(null); };

  const toggle = () => {
    if (mode === "popover" && anchorRef.current) {
      const r = anchorRef.current.getBoundingClientRect();
      const w = 300;
      let left = r.right - w;
      left = Math.max(12, left);
      const below = r.bottom + 8;
      setPos({ left, top: below });
    }
    setOpenId(open ? null : region.id);
  };

  return (
    <div className={"crow" + (open ? " crow--active" : "")}>
      <div className="crow__main">
        <div className="region-sw" style={{ background: region.detected }} title={"Detected region " + (index + 1) + " · " + region.detected}>
          <span className="reglabel">{region.detected.toUpperCase()}</span>
        </div>
        <span className="arrow"><Icons.arrow size={17} /></span>
        <div className="filchip" ref={anchorRef} onClick={toggle} aria-expanded={open}>
          <span className="sw" style={{ background: region.filament.hex }} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="fname">{region.filament.name}</div>
            <div className="fhex">{region.filament.hex.toUpperCase()}</div>
          </div>
          <span className="badge">{region.id}</span>
          <span className="caret"><Icons.chevD size={15} style={{ transform: open ? "rotate(180deg)" : "none", transition: "transform .18s" }} /></span>
        </div>
      </div>

      {/* inline picker */}
      {open && mode === "inline" && (
        <div className="inline-anim">
          <PickerBody current={region.filament} onPick={onPick} inline />
        </div>
      )}

      {/* popover picker — portaled to body so no overflow/stacking context can clip it */}
      {open && mode === "popover" && pos && ReactDOM.createPortal(
        <>
          <div className="backdrop" onClick={() => setOpenId(null)} />
          <div className="pop-anim" style={{ position: "fixed", left: pos.left, top: pos.top, zIndex: 40 }}>
            <PickerBody current={region.filament} onPick={onPick} />
          </div>
        </>,
        document.body
      )}
    </div>
  );
}

function ColorConfig({ regions, mode }) {
  const [openId, setOpenId] = React.useState(null);
  return (
    <div className="crows">
      {regions.map((r, i) => (
        <ColorRow key={r.id} region={r} index={i} mode={mode} openId={openId} setOpenId={setOpenId} />
      ))}
    </div>
  );
}

Object.assign(window, { PickerBody, ColorRow, ColorConfig });
