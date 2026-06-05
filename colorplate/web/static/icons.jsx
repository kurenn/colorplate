/* icons.jsx — minimal stroke icon set, shared on window */
const Ic = ({ d, size = 18, fill = "none", sw = 1.6, children, ...p }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={fill} stroke="currentColor"
       strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" {...p}>
    {d ? <path d={d} /> : children}
  </svg>
);

const Icons = {
  upload: (p) => <Ic {...p}><path d="M12 16V4" /><path d="m7 9 5-5 5 5" /><path d="M5 16v3a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-3" /></Ic>,
  image:  (p) => <Ic {...p}><rect x="3" y="3" width="18" height="18" rx="2.5" /><circle cx="8.5" cy="8.5" r="1.6" /><path d="m21 15-5-5L5 21" /></Ic>,
  x:      (p) => <Ic {...p} d="M18 6 6 18M6 6l12 12" />,
  chevR:  (p) => <Ic {...p} d="m9 6 6 6-6 6" />,
  chevD:  (p) => <Ic {...p} d="m6 9 6 6 6-6" />,
  arrow:  (p) => <Ic {...p}><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></Ic>,
  check:  (p) => <Ic {...p} d="M20 6 9 17l-5-5" />,
  download:(p)=> <Ic {...p}><path d="M12 3v12" /><path d="m7 10 5 5 5-5" /><path d="M5 21h14" /></Ic>,
  sun:    (p) => <Ic {...p}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></Ic>,
  moon:   (p) => <Ic {...p} d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />,
  layers: (p) => <Ic {...p}><path d="m12 2 9 5-9 5-9-5 9-5Z" /><path d="m3 12 9 5 9-5" /><path d="m3 17 9 5 9-5" /></Ic>,
  cube:   (p) => <Ic {...p}><path d="M21 7.5 12 3 3 7.5v9L12 21l9-4.5v-9Z" /><path d="M3 7.5 12 12l9-4.5M12 12v9" /></Ic>,
  spinner:(p) => <Ic {...p}><path d="M12 3a9 9 0 1 0 9 9" /></Ic>,
  pkg:    (p) => <Ic {...p}><path d="M21 8 12 3 3 8v8l9 5 9-5V8Z" /><path d="m3 8 9 5 9-5M12 13v8" /></Ic>,
  pencil: (p) => <Ic {...p} d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5Z" />,
  refresh:(p) => <Ic {...p}><path d="M21 12a9 9 0 1 1-2.64-6.36" /><path d="M21 4v4h-4" /></Ic>,
  mail:   (p) => <Ic {...p}><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m4 7 8 6 8-6" /></Ic>,
  help:   (p) => <Ic {...p}><circle cx="12" cy="12" r="9" /><path d="M9.2 9.2a2.8 2.8 0 0 1 5.4 1c0 1.8-2.6 2-2.6 3.4" /><path d="M12 17h.01" /></Ic>,
  warn:   (p) => <Ic {...p}><path d="M10.3 3.4 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.4a2 2 0 0 0-3.4 0Z" /><path d="M12 9v4" /><path d="M12 17h.01" /></Ic>,
  github: (p) => (
    <Ic {...p} fill="currentColor" sw={0}>
      <path d="M12 1.5a10.5 10.5 0 0 0-3.32 20.47c.53.1.72-.23.72-.5v-1.75c-2.92.63-3.54-1.4-3.54-1.4-.48-1.22-1.17-1.55-1.17-1.55-.96-.65.07-.64.07-.64 1.06.08 1.62 1.09 1.62 1.09.94 1.61 2.47 1.14 3.07.87.1-.68.37-1.14.67-1.4-2.33-.27-4.78-1.17-4.78-5.2 0-1.15.41-2.09 1.09-2.83-.11-.27-.47-1.34.1-2.8 0 0 .88-.28 2.9 1.08a10 10 0 0 1 5.28 0c2-1.36 2.89-1.08 2.89-1.08.57 1.46.21 2.53.1 2.8.68.74 1.09 1.68 1.09 2.83 0 4.04-2.46 4.93-4.8 5.19.38.33.71.97.71 1.96v2.9c0 .28.19.61.73.5A10.5 10.5 0 0 0 12 1.5Z" />
    </Ic>
  ),
};

window.Icons = Icons;
