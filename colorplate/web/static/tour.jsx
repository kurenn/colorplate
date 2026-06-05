/* tour.jsx — a tiny, self-contained spotlight tour so first-time visitors aren't
   overwhelmed. No dependencies: it dims the page, highlights one element at a
   time (via a big box-shadow "spotlight"), and shows a captioned popover with
   Back / Next. Targets are matched by `[data-tour="..."]`; a step with no target
   is centered. Replays from the "?" button; auto-shows once per browser. */
const Tour = (function () {
  const { useState, useEffect, useLayoutEffect, useRef } = React;

  const PAD = 8;        // spotlight padding around the target
  const POP_W = 320;    // popover width (keep in sync with CSS)

  function rectOf(sel) {
    if (!sel) return null;
    const el = document.querySelector(sel);
    if (!el) return null;
    el.scrollIntoView({ block: "center", inline: "nearest" });
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return null;
    return r;
  }

  function Tour(props) {
    const { open, steps, onClose } = props;
    const [i, setI] = useState(0);
    const [rect, setRect] = useState(null);
    const popRef = useRef(null);

    useEffect(() => { if (open) setI(0); }, [open]);

    // track the target rect (re-measure on step change, resize, scroll, anim)
    useLayoutEffect(() => {
      if (!open) return;
      const sel = steps[i] && steps[i].selector;
      const measure = () => setRect(rectOf(sel));
      measure();
      const t = setInterval(measure, 200);
      window.addEventListener("resize", measure, true);
      window.addEventListener("scroll", measure, true);
      return () => {
        clearInterval(t);
        window.removeEventListener("resize", measure, true);
        window.removeEventListener("scroll", measure, true);
      };
    }, [open, i, steps]);

    // keyboard: Esc to close, arrows to navigate
    useEffect(() => {
      if (!open) return;
      const onKey = (e) => {
        if (e.key === "Escape") finish();
        else if (e.key === "ArrowRight" || e.key === "Enter") next();
        else if (e.key === "ArrowLeft") setI((v) => Math.max(0, v - 1));
      };
      window.addEventListener("keydown", onKey);
      return () => window.removeEventListener("keydown", onKey);
    }, [open, i]);

    if (!open) return null;
    const step = steps[i] || {};
    const last = i === steps.length - 1;
    const next = () => (last ? finish() : setI((v) => v + 1));
    const finish = () => onClose && onClose();

    // popover position: below the target if it fits, else above, else clamped
    // inside the viewport (handles targets taller than the screen). No target → centered.
    let popStyle;
    if (rect) {
      const vh = window.innerHeight, vw = window.innerWidth, POP_H = 190;
      const left = Math.max(12, Math.min(rect.left, vw - POP_W - 12));
      let top;
      if (rect.bottom + 12 + POP_H <= vh) top = rect.bottom + 12;
      else if (rect.top - 12 - POP_H >= 0) top = rect.top - 12 - POP_H;
      else top = rect.top + 12;
      top = Math.max(12, Math.min(top, vh - POP_H - 12));
      popStyle = { top, left };
    } else {
      popStyle = { top: "50%", left: "50%", transform: "translate(-50%,-50%)" };
    }

    const spot = rect && {
      top: rect.top - PAD, left: rect.left - PAD,
      width: rect.width + PAD * 2, height: rect.height + PAD * 2,
    };

    return (
      <div className="tour-root" role="dialog" aria-modal="true" aria-label="App tour">
        {/* click-blocker; dim is provided by the spotlight's shadow (or this when centered) */}
        <div className="tour-block" style={rect ? null : { background: "rgba(0,0,0,.55)" }}
             onClick={(e) => e.stopPropagation()} />
        {spot && <div className="tour-spot" style={spot} />}
        <div className="tour-pop" ref={popRef} style={popStyle}>
          <button className="tour-x" title="Skip tour" onClick={finish}><Icons.x size={14} /></button>
          {step.title && <div className="tour-title">{step.title}</div>}
          <div className="tour-body">{step.body}</div>
          <div className="tour-foot">
            <span className="tour-dots">
              {steps.map((_, k) => <span key={k} className={"tour-dot" + (k === i ? " on" : "")} />)}
            </span>
            <div className="tour-btns">
              {i > 0 && <button className="tour-back" onClick={() => setI((v) => v - 1)}>Back</button>}
              <button className="tour-next" onClick={next}>{last ? "Done" : "Next"}</button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return Tour;
})();

window.Tour = Tour;
